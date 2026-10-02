"""Turning a price plan into an order, with every risk rule applied.

This was a private method on `BacktestEngine`. It is here because the forward
paper trader needs the same answer, and the alternative -- a second sizing path
for live trades -- is the exact mistake the simulator's own docstring warns
about: two answers to one question, differing by a few hundredths of an R,
which is the size of the effects being measured.

`TradeIntent` moved with it. It has to live below the planner rather than above
it, or `engine` and `plan` import each other. `engine` re-exports both, so every
existing caller is unchanged -- the same arrangement `grid.py` and `frames.py`
already use here.

**Every `None` returned is a risk rule refusing.** Not an error, not a missing
feature: too little confidence for any budget, a reward-to-risk that does not
pay for the losses, a position too small for the venue, costs too large a share
of what is at stake, or a stop so wide that liquidation arrives before it.
"""

from __future__ import annotations

from dataclasses import dataclass

from traidingbrain.config.settings import AppConfig
from traidingbrain.domain.enums import OrderType, Side
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.risk.leverage import choose_leverage
from traidingbrain.risk.sizing import costs_are_affordable, position_size, risk_budget
from traidingbrain.sim.broker import PendingEntry


@dataclass(frozen=True)
class TradeIntent:
    """What a strategy wants to do, in prices.

    Sizing, leverage and the liquidation check are the engine's job, not the
    strategy's -- so a strategy cannot accidentally propose a position larger than
    the risk budget allows, and every strategy is measured under the same money
    management.
    """

    side: Side
    entry: float
    stop: float
    target: float
    confidence: float
    reason: str = ""

    @property
    def reward_risk(self) -> float:
        distance = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / distance if distance > 0 else 0.0

    @property
    def is_coherent(self) -> bool:
        if self.side is Side.LONG:
            return self.stop < self.entry < self.target
        return self.target < self.entry < self.stop


def plan_entry(
    intent: TradeIntent,
    snapshot: MarketSnapshot | None,
    *,
    symbol: str,
    spec: SymbolSpec,
    config: AppConfig,
    equity: float,
    created_ts: int,
    expires_ts: int,
) -> PendingEntry | None:
    """The order this intent becomes, or None if a risk rule refuses it."""
    risk_config = config.risk
    if intent.reward_risk < risk_config.limits.min_reward_risk:
        return None

    # No snapshot means no history lookup, so no evidence that confidence
    # is calibrated -- and the sizing ladder stays capped. That is the right
    # answer rather than a missing feature: a rule-based strategy states a
    # fixed confidence, and a fixed number is not evidence about itself.
    samples = snapshot.history.similar_situations_found if snapshot is not None else 0
    budget = risk_budget(
        intent.confidence,
        equity,
        risk_config.sizing,
        history_samples=samples,
    )
    if budget is None:
        return None

    size = position_size(intent.side, intent.entry, intent.stop, budget.risk_amount, spec)
    if not size.is_viable:
        return None

    # Costs scale with the position, risk does not. A stop tight enough to
    # make the round trip cost a large share of what is at stake is a trade
    # that cannot win, whatever happens next.
    affordable, _fraction = costs_are_affordable(
        size.notional,
        size.risk_amount,
        spec,
        config.engine.simulation.slippage_bps,
        risk_config.limits.max_cost_fraction_of_risk,
    )
    if not affordable:
        return None

    leverage = choose_leverage(
        intent.side,
        intent.entry,
        intent.stop,
        qty=size.qty,
        spec=spec,
        config=risk_config.leverage,
    )
    if leverage is None:
        return None

    return PendingEntry(
        proposal_id=f"{symbol}-{created_ts}",
        side=intent.side,
        order_type=OrderType.LIMIT,
        limit_price=intent.entry,
        stop=intent.stop,
        target=intent.target,
        qty=size.qty,
        leverage=leverage.leverage,
        created_ts=created_ts,
        expires_ts=expires_ts,
        risk_amount=size.risk_amount,
        # Empty for a bar-reading strategy, which has no normalised view
        # to hash. The field identifies the situation a model was shown, and
        # inventing one here would make two different things look alike in
        # the record.
        snapshot_hash=(snapshot.to_brain_input().content_hash() if snapshot is not None else ""),
    )
