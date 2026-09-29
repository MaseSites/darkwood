"""Turning a decision into a trade you can look at and confirm.

This is where the system's answer becomes a concrete offer: enter here, stop
there, target there, this many contracts, this much leverage, this much at risk in
francs, liquidation at this price. Every number computed, none of them typed by a
model.

The order of construction is the safety argument, and it only works in this
direction:

1. **Confidence** decides the risk budget -- what may be lost if the stop is hit.
2. **The stop distance** decides the position size: `risk / stop distance`. A
   tighter stop buys a larger position for the same loss.
3. **The cost check** refuses the trade if the round trip would eat too much of
   that budget. Tight stops are expensive twice over, and this is the rule that
   caught it.
4. **The liquidation requirement** decides the leverage: the highest that still
   leaves the exchange's own exit well beyond the stop.

Reversing any step breaks it. Choosing leverage first and sizing to it is how a
5x position with a 1% stop becomes a 100% loss.

What the user sees and may change: the leverage and the risk percentage, both
downward only. Lowering either widens the liquidation buffer, so it is always
safe. Raising is a different trade and has to be proposed as one.
"""

from __future__ import annotations

from dataclasses import dataclass

from traidingbrain.brain.scoring import NEUTRAL_CONFIDENCE, ScoreBreakdown, score
from traidingbrain.config.settings import AppConfig, WeightsConfig
from traidingbrain.domain.enums import Bias, ProposalStatus, RiskLevel, Side, Timeframe
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.proposal import (
    EventMark,
    FactorView,
    LevelMark,
    ProposalAdjustment,
    TradeProposal,
)
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.domain.verdict import BrainDecision
from traidingbrain.risk.leverage import choose_leverage, validate_user_leverage
from traidingbrain.risk.limits import AccountState, RiskLimits
from traidingbrain.risk.sizing import costs_are_affordable, position_size, risk_budget


@dataclass(frozen=True)
class Rationale:
    """The narrative half of a proposal: why, rather than what.

    Separated from the numbers because a re-price carries it forward unchanged
    while every number is recomputed. Threading it through as seven conditional
    expressions was how this started, and it was unreadable.
    """

    bias: Bias
    confidence: float
    risk_level: RiskLevel
    reasoning: list[str]
    invalidation_note: str
    snapshot_hash: str
    decision_id: str | None
    # The evidence, captured at the decision rather than re-derived on demand.
    # Re-deriving would draw today's analysis over yesterday's trade, which is a
    # different claim wearing the same chart.
    snapshot_ts: int = 0
    signal_timeframe: Timeframe | None = None
    price_at_build: float = 0.0
    atr_at_build: float = 0.0
    factors: tuple[FactorView, ...] = ()
    levels: tuple[LevelMark, ...] = ()
    events: tuple[EventMark, ...] = ()
    confidence_raw: float = 0.0
    confidence_cap_reason: str = ""

    @classmethod
    def from_decision(
        cls,
        decision: BrainDecision,
        snapshot: MarketSnapshot,
        weights: WeightsConfig,
    ) -> Rationale:
        breakdown = score(decision.verdict, weights, snapshot.history)
        return cls(
            bias=decision.verdict.bias,
            confidence=decision.confidence,
            risk_level=decision.verdict.risk,
            reasoning=list(decision.verdict.reasoning),
            invalidation_note=decision.verdict.scenarios.invalidation_note,
            snapshot_hash=decision.snapshot_hash,
            decision_id=decision.request_id,
            snapshot_ts=snapshot.ts,
            signal_timeframe=snapshot.signal_timeframe,
            price_at_build=snapshot.price,
            atr_at_build=snapshot.atr,
            factors=_factor_views(decision, breakdown),
            events=_event_marks(snapshot),
            confidence_raw=NEUTRAL_CONFIDENCE
            + NEUTRAL_CONFIDENCE * breakdown.directional_score * _sign(breakdown.bias),
            confidence_cap_reason=(
                "the history index holds too few comparable cases to support a higher number"
                if breakdown.capped_by_history
                else ""
            ),
            levels=tuple(
                LevelMark(
                    id=level.id,
                    kind=level.kind,
                    timeframe=level.timeframe,
                    price=level.price,
                    distance_atr=level.distance_atr,
                    age_bars=level.age_bars,
                    touches=level.touches,
                )
                for level in snapshot.levels
            ),
        )

    @classmethod
    def from_proposal(cls, proposal: TradeProposal) -> Rationale:
        return cls(
            bias=proposal.bias,
            confidence=proposal.confidence,
            risk_level=proposal.risk_level,
            reasoning=list(proposal.reasoning),
            invalidation_note=proposal.invalidation_note,
            snapshot_hash=proposal.snapshot_hash,
            decision_id=proposal.decision_id,
            confidence_raw=proposal.confidence_raw,
            confidence_cap_reason=proposal.confidence_cap_reason,
            events=tuple(proposal.events),
            snapshot_ts=proposal.snapshot_ts,
            signal_timeframe=proposal.signal_timeframe,
            price_at_build=proposal.price_at_build,
            atr_at_build=proposal.atr_at_build,
            factors=tuple(proposal.factors),
            levels=tuple(proposal.levels),
        )


def _event_marks(snapshot: MarketSnapshot) -> tuple[EventMark, ...]:
    """The structural events behind the read, as distances from the decision.

    Only what the analysis actually confirmed, and only where it recorded how
    long ago. A frame reporting `bos: true` with no distance is a frame that
    knows a break happened and not when, and guessing a position for it would put
    a mark on the chart that nothing supports.
    """
    marks: list[EventMark] = []
    for frame in snapshot.frames:
        structure = frame.structure
        if structure.bos and structure.bars_since_bos is not None:
            marks.append(
                EventMark(
                    kind="bos",
                    timeframe=frame.timeframe,
                    bars_ago=structure.bars_since_bos,
                    label="break of structure",
                )
            )
        if structure.choch and structure.bars_since_choch is not None:
            marks.append(
                EventMark(
                    kind="choch",
                    timeframe=frame.timeframe,
                    bars_ago=structure.bars_since_choch,
                    label="change of character",
                )
            )
        liquidity = frame.liquidity
        if liquidity.bars_since_sweep is not None and (
            liquidity.sweep_up or liquidity.sweep_down
        ):
            marks.append(
                EventMark(
                    kind="sweep_up" if liquidity.sweep_up else "sweep_down",
                    timeframe=frame.timeframe,
                    bars_ago=liquidity.bars_since_sweep,
                    label="buy-side swept" if liquidity.sweep_up else "sell-side swept",
                )
            )
    return tuple(marks)


def _sign(bias: Bias) -> float:
    return {Bias.BULLISH: 1.0, Bias.BEARISH: -1.0, Bias.NEUTRAL: 0.0}[bias]


def _factor_views(decision: BrainDecision, breakdown: ScoreBreakdown) -> tuple[FactorView, ...]:
    """Pair each factor the model scored with the arithmetic it fed.

    `contribution` is in confidence points rather than raw score, because points
    are the unit the reader sees. A factor scoring +0.8 under a 10% weight moves
    the number by four points, and quoting the 0.8 alone makes it look decisive
    when it is nearly noise.
    """
    views = []
    sign = _sign(breakdown.bias)
    for factor, value in breakdown.contributions.items():
        reading = decision.verdict.score_for(factor)
        weight = breakdown.weights_used.get(factor, 0.0)
        views.append(
            FactorView(
                factor=factor,
                score=reading.score if reading else 0.0,
                certainty=reading.confidence if reading else 0.0,
                weight=weight,
                contribution=NEUTRAL_CONFIDENCE * weight * value * sign,
                reasoning=reading.reasoning if reading else "",
            )
        )
    return tuple(sorted(views, key=lambda view: -abs(view.contribution)))


@dataclass(frozen=True)
class BuildFailure:
    """Why no proposal was offered. Always specific enough to act on."""

    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.reason}{f' -- {self.detail}' if self.detail else ''}"


def round_price(value: float, tick: float) -> float:
    """Snap to the venue's price increment.

    Sending more precision than the exchange accepts is a rejected order, and it
    is the kind of bug that only shows up against the real API.
    """
    if tick <= 0:
        return value
    return round(round(value / tick) * tick, 10)


class ProposalBuilder:
    """Builds a complete, confirmable trade -- or explains why it cannot."""

    def __init__(self, config: AppConfig, limits: RiskLimits) -> None:
        self.config = config
        self.limits = limits

    def build(
        self,
        decision: BrainDecision,
        snapshot: MarketSnapshot,
        spec: SymbolSpec,
        account: AccountState,
    ) -> TradeProposal | BuildFailure:
        if not decision.is_tradeable or decision.plan is None:
            return BuildFailure(
                "the analysis did not produce a trade",
                "; ".join(decision.guard.violations) or decision.verdict.decision.value,
            )

        verdict = self.limits.check(account, symbol=snapshot.symbol)
        if not verdict.allowed:
            return BuildFailure("blocked by a risk limit", verdict.reason)

        plan = decision.plan
        budget = risk_budget(
            decision.confidence,
            account.equity,
            self.config.risk.sizing,
            history_samples=snapshot.history.similar_situations_found,
        )
        if budget is None:
            return BuildFailure(
                "confidence below the threshold to trade at all",
                f"{decision.confidence:.0f} < {self.config.risk.sizing.min_confidence:.0f}",
            )

        entry = round_price(plan.entry, spec.price_tick)
        stop = round_price(plan.stop, spec.price_tick)
        target = round_price(plan.target, spec.price_tick)

        return self._assemble(
            symbol=snapshot.symbol,
            side=plan.side,
            entry=entry,
            stop=stop,
            target=target,
            risk_amount=budget.risk_amount,
            risk_pct=budget.risk_pct,
            spec=spec,
            account=account,
            rationale=Rationale.from_decision(decision, snapshot, self.config.weights),
        )

    def adjust(
        self,
        proposal: TradeProposal,
        change: ProposalAdjustment,
        spec: SymbolSpec,
        account: AccountState,
    ) -> TradeProposal | BuildFailure:
        """Re-price a proposal after the user changes something.

        Rebuilt from scratch rather than patched. Changing the leverage moves the
        liquidation price; changing the risk moves the size, which moves the cost
        ratio. Editing one field in place would leave the others describing a trade
        that no longer exists.
        """
        entry = round_price(change.entry or proposal.entry, spec.price_tick)
        stop = round_price(change.stop or proposal.stop, spec.price_tick)
        target = round_price(change.target or proposal.target, spec.price_tick)
        risk_pct = change.risk_pct or proposal.risk_pct

        if risk_pct > proposal.risk_pct:
            return BuildFailure(
                "risk may only be lowered",
                f"{risk_pct:.2%} exceeds the proposed {proposal.risk_pct:.2%}",
            )

        return self._assemble(
            symbol=proposal.symbol,
            side=proposal.side,
            entry=entry,
            stop=stop,
            target=target,
            risk_amount=account.equity * risk_pct,
            risk_pct=risk_pct,
            spec=spec,
            account=account,
            rationale=Rationale.from_proposal(proposal),
            requested_leverage=change.leverage,
        )

    # -- the shared path ---------------------------------------------------- #

    def _assemble(
        self,
        *,
        symbol: str,
        side: Side,
        entry: float,
        stop: float,
        target: float,
        risk_amount: float,
        risk_pct: float,
        spec: SymbolSpec,
        account: AccountState,
        rationale: Rationale,
        requested_leverage: float | None = None,
    ) -> TradeProposal | BuildFailure:
        size = position_size(side, entry, stop, risk_amount, spec)
        if not size.is_viable:
            return BuildFailure(
                "position too small to place",
                f"a {abs(entry - stop):,.2f} stop and {risk_amount:,.0f} of risk "
                f"rounds to nothing at this venue",
            )

        affordable, fraction = costs_are_affordable(
            size.notional,
            size.risk_amount,
            spec,
            self.config.engine.simulation.slippage_bps,
            self.config.risk.limits.max_cost_fraction_of_risk,
        )
        if not affordable:
            return BuildFailure(
                "transaction costs would eat too much of the risk",
                f"a round trip costs {fraction:.0%} of what is at stake "
                f"(limit {self.config.risk.limits.max_cost_fraction_of_risk:.0%}); "
                f"the stop is too tight for the position it implies",
            )

        derived = choose_leverage(
            side, entry, stop, qty=size.qty, spec=spec, config=self.config.risk.leverage
        )
        if derived is None:
            return BuildFailure(
                "no safe leverage exists for this stop",
                "the position would be liquidated before the stop is reached at any leverage",
            )

        leverage = derived
        if requested_leverage is not None:
            checked = validate_user_leverage(
                requested_leverage,
                derived,
                side=side,
                entry=entry,
                stop=stop,
                qty=size.qty,
                spec=spec,
                config=self.config.risk.leverage,
            )
            if checked is None:
                return BuildFailure(
                    "that leverage is not allowed",
                    f"{requested_leverage:g}x is above the {derived.leverage:g}x the stop "
                    f"supports; lowering is always fine, raising is a different trade",
                )
            leverage = checked

        return TradeProposal(
            symbol=symbol,
            side=side,
            entry=entry,
            stop=stop,
            target=target,
            qty=size.qty,
            leverage=leverage.leverage,
            notional=size.notional,
            margin=leverage.margin,
            liquidation_price=round_price(leverage.liquidation_price, spec.price_tick),
            risk_amount=size.risk_amount,
            risk_pct=risk_pct,
            equity_at_build=account.equity,
            bias=rationale.bias,
            confidence=rationale.confidence,
            risk_level=rationale.risk_level,
            reasoning=rationale.reasoning,
            invalidation_note=rationale.invalidation_note,
            snapshot_hash=rationale.snapshot_hash,
            decision_id=rationale.decision_id,
            status=ProposalStatus.PENDING,
            snapshot_ts=rationale.snapshot_ts,
            signal_timeframe=rationale.signal_timeframe,
            price_at_build=rationale.price_at_build,
            atr_at_build=rationale.atr_at_build,
            factors=list(rationale.factors),
            levels=list(rationale.levels),
            events=list(rationale.events),
            confidence_raw=rationale.confidence_raw or rationale.confidence,
            confidence_cap_reason=rationale.confidence_cap_reason,
        )


def describe(proposal: TradeProposal) -> str:
    """The proposal in words, for a terminal or a notification."""
    direction = "LONG" if proposal.side is Side.LONG else "SHORT"
    return "\n".join(
        [
            f"{direction} {proposal.symbol}  confidence {proposal.confidence:.0f}  "
            f"risk {proposal.risk_level.value}",
            f"  entry        {proposal.entry:,.2f}",
            f"  stop         {proposal.stop:,.2f}   "
            f"({abs(proposal.entry - proposal.stop) / proposal.entry:.2%} away)",
            f"  target       {proposal.target:,.2f}   R:R {proposal.reward_risk:.2f}",
            f"  size         {proposal.qty:g} @ {proposal.leverage:g}x "
            f"= {proposal.notional:,.0f} notional",
            f"  margin       {proposal.margin:,.0f}",
            f"  at risk      {proposal.risk_amount:,.0f} "
            f"({proposal.risk_pct:.2%} of {proposal.equity_at_build:,.0f})",
            f"  liquidation  {proposal.liquidation_price:,.2f}   "
            f"{proposal.liquidation_buffer_r:.1f} stop-distances beyond the stop",
            f"  invalidated  {proposal.invalidation_note}",
        ]
    )
