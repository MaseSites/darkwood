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

**Which one, though?** For a long time the answer was nowhere. `plan_entry`
returned a bare `None` for all five, the caller incremented a counter, and after
a thousand refusals there was a number and not one recoverable signal. That cost
more than it looks: the five rules below are themselves untested hypotheses.
`scripts/study_cost_floor.py` varied the *threshold* of one of them across four
markets, which is a different question from whether the rule should exist -- and
the only way to ask the second is to keep the signals it threw away.

So `assess` is the real function and returns the verdict: which rule refused,
the sentence saying why, and the figures that were computed on the way,
including the cost estimate that used to be discarded one line after it was
calculated. `plan_entry` is now a thin wrapper over it, unchanged for callers
that only want the order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from traidingbrain.config.settings import AppConfig
from traidingbrain.domain.enums import OrderType, Rule, Side
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.risk.leverage import choose_leverage
from traidingbrain.risk.sizing import (
    PositionSize,
    costs_are_affordable,
    position_size,
    risk_budget,
)
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
    #: Which chart the signal was read off, as a plain string.
    #:
    #: A strategy that reads one chart leaves it empty. The guide pool fills
    #: it, because it searches several and the setup name does not say which
    #: one fired. Carried through to the `Fill` so that grouping trades by
    #: their entry minute can control for it -- an H1 signal enters on :00
    #: and an M15 signal on any quarter, so without this field that grouping
    #: measures the timeframe and calls it the clock.
    timeframe: str = ""

    @property
    def reward_risk(self) -> float:
        distance = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / distance if distance > 0 else 0.0

    @property
    def is_coherent(self) -> bool:
        if self.side is Side.LONG:
            return self.stop < self.entry < self.target
        return self.target < self.entry < self.stop


def setup_label(intent: TradeIntent) -> str:
    """The rule's own name, taken from the head of its reason text.

    The setups write "A: Zone", "V11: Block" and so on, so the part before the
    colon is the label and the rest is the argument. Shared because a refused
    signal has no `PendingEntry` to read it off, and the signal ledger groups
    by exactly this string.
    """
    return intent.reason.split(":")[0].strip()


@dataclass(frozen=True)
class Assessment:
    """What the risk layer decided about one signal, and everything it computed.

    The figures are kept whether the signal was taken or refused. A refused
    signal's cost estimate is the interesting one -- it is the number the rule
    refused *on* -- and a taken signal's is what section 6 of the masterplan
    asks for under "geschätzte Kosten", knowable before the entry and therefore
    usable as a feature without the circularity that realised fees carry.
    """

    entry: PendingEntry | None
    refused_by: Rule | None
    detail: str
    reward_risk: float
    cost_fraction: float
    """Round-trip cost as a share of the amount risked, as estimated at the
    decision. Zero when a rule refused before it could be computed."""

    risk_amount: float
    qty: float
    leverage: float

    @property
    def accepted(self) -> bool:
        return self.entry is not None


#: Eine andere Art, die Groesse zu bestimmen: Absicht, Instrumentregeln und
#: Konto hinein, fertige Position heraus.
#:
#: Der Vertrag ist absichtlich eng. Ein Sizer darf NICHT entscheiden, OB ein
#: Trade stattfindet -- jede Ablehnungsregel laeuft vor und nach ihm weiter,
#: und `is_viable` ist das einzige Nein, das er aussprechen darf. Eine
#: Groessenregel, die auch filtern duerfte, waere eine zweite Strategie an
#: einer Stelle, an der niemand sie sucht.
Sizer = Callable[["TradeIntent", SymbolSpec, float], PositionSize]

def assess(
    intent: TradeIntent,
    snapshot: MarketSnapshot | None,
    *,
    symbol: str,
    spec: SymbolSpec,
    config: AppConfig,
    equity: float,
    created_ts: int,
    expires_ts: int,
    sizer: Sizer | None = None,
) -> Assessment:
    """Run every risk rule and say what happened, in order.

    The order is the one the rules have always run in and it is load-bearing for
    the record: a signal that fails two rules is attributed to the first, so the
    counts stay a partition rather than overlapping sets.

    **`sizer` ist additiv und greift nur, wenn er übergeben wird.** Ohne ihn
    läuft exakt die bisherige Rechnung: Risikobudget hinein, Menge heraus
    (rückwärts). Mit ihm läuft eine andere -- und der Grund, dass dieser Hebel
    existiert, ist ein ausdrücklicher Auftrag: ein zweites Papierkonto, das
    VORWÄRTS bemisst (ein Anteil des Kontos als Margin, mal Hebel).

    Die beiden Richtungen sind nicht symmetrisch. Rückwärts ist das Risiko eine
    Eingabe und damit bekannt; vorwärts ist es ein Ergebnis. Gemessen über die
    7.335 Replay-Trades riskiert „30 % Margin bei 7x" im Median 4,38 % des
    Kontos, im 99. Perzentil **30,62 %** -- bei einem Konfigurationsdeckel von
    3 %. Ein Konto, das so bemisst, braucht darum seine EIGENE
    Risikokonfiguration; den produktiven Deckel rührt dieser Parameter nicht an.
    """
    risk_config = config.risk
    reward_risk = intent.reward_risk

    def refused(
        rule: Rule,
        detail: str,
        *,
        cost_fraction: float = 0.0,
        risk_amount: float = 0.0,
        qty: float = 0.0,
        leverage: float = 0.0,
    ) -> Assessment:
        return Assessment(
            entry=None,
            refused_by=rule,
            detail=detail,
            reward_risk=reward_risk,
            cost_fraction=cost_fraction,
            risk_amount=risk_amount,
            qty=qty,
            leverage=leverage,
        )

    if reward_risk < risk_config.limits.min_reward_risk:
        return refused(
            Rule.REWARD_RISK,
            f"Chance-Risiko {reward_risk:.2f} unter dem Minimum "
            f"{risk_config.limits.min_reward_risk:.2f}",
        )

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
        return refused(
            Rule.CONFIDENCE,
            f"Zuversicht {intent.confidence:.0f} unter der Schwelle "
            f"{risk_config.sizing.min_confidence:.0f}, also kein Budget",
        )

    size = (
        sizer(intent, spec, equity)
        if sizer is not None
        else position_size(
            intent.side, intent.entry, intent.stop, budget.risk_amount, spec
        )
    )
    if not size.is_viable:
        return refused(
            Rule.SIZE,
            f"Position zu klein fuer die Boerse: {budget.risk_amount:.2f} Risiko ueber "
            f"{abs(intent.entry - intent.stop):.6f} Stopweite ergibt weniger als "
            f"{spec.min_qty} Einheiten oder {spec.min_notional:.0f} Nominal",
            risk_amount=budget.risk_amount,
        )

    # Costs scale with the position, risk does not. A stop tight enough to
    # make the round trip cost a large share of what is at stake is a trade
    # that cannot win, whatever happens next.
    #
    # The fraction is kept either way now. It used to be discarded on the line
    # it was computed on -- `affordable, _fraction = ...` -- which made the one
    # number this rule decides on unrecoverable for every signal it refused.
    affordable, cost_fraction = costs_are_affordable(
        size.notional,
        size.risk_amount,
        spec,
        config.engine.simulation.slippage_bps,
        risk_config.limits.max_cost_fraction_of_risk,
    )
    if not affordable:
        return refused(
            Rule.COSTS,
            f"Kosten {cost_fraction:.1%} des Risikos, erlaubt sind "
            f"{risk_config.limits.max_cost_fraction_of_risk:.1%} -- meist ein Stop, "
            f"der fuer die Gebuehren zu eng ist",
            cost_fraction=cost_fraction,
            risk_amount=size.risk_amount,
            qty=size.qty,
        )

    leverage = choose_leverage(
        intent.side,
        intent.entry,
        intent.stop,
        qty=size.qty,
        spec=spec,
        config=risk_config.leverage,
    )
    if leverage is None:
        return refused(
            Rule.LIQUIDATION,
            f"Keine Hebelstufe bis {risk_config.leverage.max:.0f}x laesst die Liquidation "
            f"{risk_config.leverage.min_liquidation_buffer_r:.1f} Stopweiten hinter dem Stop",
            cost_fraction=cost_fraction,
            risk_amount=size.risk_amount,
            qty=size.qty,
        )

    return Assessment(
        entry=_order(
            intent,
            snapshot,
            symbol=symbol,
            qty=size.qty,
            leverage=leverage.leverage,
            risk_amount=size.risk_amount,
            created_ts=created_ts,
            expires_ts=expires_ts,
        ),
        refused_by=None,
        detail=budget.reason,
        reward_risk=reward_risk,
        cost_fraction=cost_fraction,
        risk_amount=size.risk_amount,
        qty=size.qty,
        leverage=leverage.leverage,
    )


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
    """The order this intent becomes, or None if a risk rule refuses it.

    Kept as it was for callers that only need the order. It is `assess(...).entry`
    and nothing else, so the two cannot drift apart.
    """
    return assess(
        intent,
        snapshot,
        symbol=symbol,
        spec=spec,
        config=config,
        equity=equity,
        created_ts=created_ts,
        expires_ts=expires_ts,
    ).entry


def _order(
    intent: TradeIntent,
    snapshot: MarketSnapshot | None,
    *,
    symbol: str,
    qty: float,
    leverage: float,
    risk_amount: float,
    created_ts: int,
    expires_ts: int,
) -> PendingEntry:
    return PendingEntry(
        proposal_id=f"{symbol}-{created_ts}",
        setup=setup_label(intent),
        timeframe=intent.timeframe,
        side=intent.side,
        order_type=OrderType.LIMIT,
        limit_price=intent.entry,
        stop=intent.stop,
        target=intent.target,
        qty=qty,
        leverage=leverage,
        created_ts=created_ts,
        expires_ts=expires_ts,
        risk_amount=risk_amount,
        # Empty for a bar-reading strategy, which has no normalised view
        # to hash. The field identifies the situation a model was shown, and
        # inventing one here would make two different things look alike in
        # the record.
        snapshot_hash=(snapshot.to_brain_input().content_hash() if snapshot is not None else ""),
    )
