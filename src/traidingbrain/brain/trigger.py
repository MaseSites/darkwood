"""When to ask the model at all.

Asking on every bar is not an option. Twenty-three thousand hourly bars at Opus
prices is a four-figure backtest, and the overwhelming majority of those calls
would return WAIT -- paying full price for the model to confirm that nothing is
happening.

So a deterministic gate runs first. It is deliberately loose: its job is to
discard the bars where nothing has changed, not to pick the trades. Every
condition here is cheap, explainable, and checked in Python, and anything that
survives goes to the model for the judgement that rules cannot make.

The gate is also a confounder, and it is worth being honest about that. Any edge
the system shows is the edge of the gate *and* the model together. That is why
`StructureBaseline` exists and why the comparison is run: the baseline sees the
same bars.
"""

from __future__ import annotations

from dataclasses import dataclass

from traidingbrain.config.settings import TriggerConfig
from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe
from traidingbrain.domain.snapshot import MarketSnapshot, TimeframeView

#: Strength at which an indicator counts as taking a side.
MIN_INDICATOR_STRENGTH = 0.3


@dataclass
class TriggerStats:
    """Why bars were skipped. A gate nobody measures is a gate nobody trusts."""

    seen: int = 0
    fired: int = 0
    no_structure_event: int = 0
    no_sweep: int = 0
    too_little_confluence: int = 0
    too_soon: int = 0
    unknown_regime: int = 0

    @property
    def fire_rate(self) -> float:
        return self.fired / self.seen if self.seen else 0.0

    def summary(self) -> str:
        return (
            f"{self.fired:,} of {self.seen:,} bars passed the gate ({self.fire_rate:.1%})\n"
            f"    skipped: {self.no_structure_event:,} no break, {self.no_sweep:,} no sweep, "
            f"{self.too_little_confluence:,} thin confluence, {self.too_soon:,} too soon, "
            f"{self.unknown_regime:,} regime unknown"
        )


class Trigger:
    """The cheap filter in front of the expensive one."""

    def __init__(self, config: TriggerConfig) -> None:
        self.config = config
        self.stats = TriggerStats()
        self._last_fired_index: int | None = None

    def should_ask(self, snapshot: MarketSnapshot, bar_index: int) -> bool:
        self.stats.seen += 1
        reason = self._first_objection(snapshot, bar_index)
        if reason is not None:
            setattr(self.stats, reason, getattr(self.stats, reason) + 1)
            return False

        self.stats.fired += 1
        self._last_fired_index = bar_index
        return True

    def _first_objection(self, snapshot: MarketSnapshot, bar_index: int) -> str | None:
        """The first reason not to ask, as the counter name to increment.

        Ordered by cost, cheapest first. Spacing leads because it is a subtraction
        and because it is what stops a single developing setup from being priced
        again on every bar of its formation.
        """
        if (
            self._last_fired_index is not None
            and bar_index - self._last_fired_index < self.config.min_bars_between_calls
        ):
            return "too_soon"

        signal = _view(snapshot, snapshot.signal_timeframe)
        if signal is None or signal.regime is RegimeKind.UNKNOWN:
            # Not warmed up. There is nothing to judge, and the model would be
            # reasoning about absence rather than about the market.
            return "unknown_regime"

        if self.config.require_bos_or_choch and not (
            signal.structure.bos or signal.structure.choch
        ):
            return "no_structure_event"

        if self.config.require_sweep and not (
            signal.liquidity.sweep_up or signal.liquidity.sweep_down
        ):
            return "no_sweep"

        if _confluence(signal) < self.config.min_indicator_confluence:
            return "too_little_confluence"

        return None

    def reset(self) -> None:
        self.stats = TriggerStats()
        self._last_fired_index = None


def _view(snapshot: MarketSnapshot, timeframe: Timeframe) -> TimeframeView | None:
    return next((view for view in snapshot.frames if view.timeframe is timeframe), None)


def _confluence(view: TimeframeView) -> int:
    """How many indicators are taking a side, in either direction.

    Direction-agnostic on purpose. The gate is not trying to pick longs; it is
    trying to find bars where the readings are saying something rather than
    sitting in the middle.
    """
    return sum(
        1
        for reading in view.indicators
        if reading.bias is not Bias.NEUTRAL and reading.strength >= MIN_INDICATOR_STRENGTH
    )
