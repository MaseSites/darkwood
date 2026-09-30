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
    news_blackout: int = 0
    wrong_session: int = 0

    @property
    def fire_rate(self) -> float:
        return self.fired / self.seen if self.seen else 0.0

    def summary(self) -> str:
        return (
            f"{self.fired:,} of {self.seen:,} bars passed the gate ({self.fire_rate:.1%})\n"
            f"    skipped: {self.no_structure_event:,} no break, {self.no_sweep:,} no sweep, "
            f"{self.too_little_confluence:,} thin confluence, {self.too_soon:,} too soon, "
            f"{self.unknown_regime:,} regime unknown"
            # Only mentioned when switched on. A line of permanent zeroes reads
            # as a filter that never fires rather than one nobody enabled.
            + (f", {self.news_blackout:,} news blackout" if self.news_blackout else "")
            + (f", {self.wrong_session:,} wrong session" if self.wrong_session else "")
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

        A list rather than a chain, because the order is the design and a chain
        hides it. Cheapest first: spacing leads because it is a subtraction, and
        because it is what stops one developing setup from being priced again on
        every bar of its formation.

        Every entry names its counter, so a skipped bar is always attributable.
        A gate nobody can explain is a gate nobody trusts.
        """
        signal = _view(snapshot, snapshot.signal_timeframe)

        checks: list[tuple[str, bool]] = [
            (
                "too_soon",
                self._last_fired_index is not None
                and bar_index - self._last_fired_index < self.config.min_bars_between_calls,
            ),
            # Not warmed up. There is nothing to judge, and the model would be
            # reasoning about absence rather than about the market.
            ("unknown_regime", signal is None or signal.regime is RegimeKind.UNKNOWN),
        ]
        if signal is not None:
            checks += [
                (
                    "no_structure_event",
                    self.config.require_bos_or_choch
                    and not (signal.structure.bos or signal.structure.choch),
                ),
                (
                    "no_sweep",
                    self.config.require_sweep
                    and not (signal.liquidity.sweep_up or signal.liquidity.sweep_down),
                ),
                (
                    "too_little_confluence",
                    _confluence(signal) < self.config.min_indicator_confluence,
                ),
                ("news_blackout", self._inside_news_blackout(snapshot)),
                ("wrong_session", self._wrong_session(snapshot)),
            ]

        return next((reason for reason, failed in checks if failed), None)

    def _inside_news_blackout(self, snapshot: MarketSnapshot) -> bool:
        """Is a high-impact release close enough to make structure meaningless?

        Symmetric, because both halves are the same problem. Before a release
        the book thins as market makers step back; after it the first move is
        frequently reversed. A stop placed on a swing low means nothing to
        either, and a setup that needs hours is a setup that runs into it.

        Only high impact counts. Treating every scheduled item as a blackout
        would close most of the week and the restriction would never be tested
        against anything.
        """
        window = self.config.news_blackout_minutes
        if window <= 0:
            return False
        return any(
            item.impact == "high"
            and item.minutes_until is not None
            and abs(item.minutes_until) <= window
            for item in snapshot.news
        )

    def _wrong_session(self, snapshot: MarketSnapshot) -> bool:
        """Is this hour outside the desks the configuration allows?

        Both checks are off by default. A restriction nobody measured only
        narrows the sample, and a smaller sample of the same edge looks like a
        better edge without being one.
        """
        session = snapshot.session
        if self.config.require_active_session and session.is_quiet:
            return True
        allowed = self.config.allowed_sessions
        if not allowed:
            return False
        return not any(name in allowed for name in session.active)

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
