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

#: What each indicator is called on screen.
#:
#: A lookup rather than a rename: the names are what the snapshot carries, the
#: history index keys on and the tests assert against. A missing entry falls
#: through to the raw name, which is visible rather than silent.
INDICATOR_WORDS = {
    "CLOSE_IN_RANGE": "Lage in der Range",
    "RSI": "RSI",
    "MACD": "MACD",
    "EMA_STACK": "EMA-Reihenfolge",
    "BOLLINGER": "Bollinger",
    "VOLUME": "Volumen",
}


@dataclass(frozen=True)
class GateCheck:
    """One condition, its verdict, and the numbers behind it.

    `detail` carries the measurement rather than a restatement of the rule --
    "1 of 2 indicators taking a side" instead of "too little confluence". A
    screen that only says which rule refused teaches nothing about how close the
    market is to qualifying.
    """

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateReading:
    """Every condition at one bar, in the order the gate applies them."""

    checks: tuple[GateCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def blocking(self) -> str | None:
        """The counter the gate would increment, or None if the bar qualifies."""
        return next((check.name for check in self.checks if not check.passed), None)


def evaluate(
    snapshot: MarketSnapshot,
    config: TriggerConfig,
    *,
    bars_since_last_call: int | None = None,
) -> GateReading:
    """Read every condition at this bar.

    Ordered cheapest first, and the order is the design: spacing leads because it
    is a subtraction, and because it is what stops one developing setup from
    being priced again on every bar of its formation.

    When the signal timeframe has not warmed up there is nothing for the later
    checks to measure, so they are left out rather than reported as passing. A
    condition that reads "satisfied" because it could not be evaluated is the
    kind of reassurance that is worse than silence.
    """
    signal = _view(snapshot, snapshot.signal_timeframe)

    checks: list[GateCheck] = [
        _spacing(config, bars_since_last_call),
        _warmed_up(signal),
    ]
    if signal is not None:
        checks += [
            _structure_event(config, signal),
            _sweep(config, signal),
            _confluence_check(config, signal),
            _news(config, snapshot),
            _session(config, snapshot),
        ]
    return GateReading(tuple(checks))


def _bars(count: int) -> str:
    """"1 bar", not "1 bars". Small, and the kind of small that makes a screen
    look like nobody read it."""
    return f"{count} Kerze{'' if count == 1 else 'n'}"


def _spacing(config: TriggerConfig, bars_since: int | None) -> GateCheck:
    minimum = config.min_bars_between_calls
    if bars_since is None:
        return GateCheck("too_soon", True, "noch kein Aufruf")
    return GateCheck(
        "too_soon",
        bars_since >= minimum,
        f"{bars_since} von {_bars(minimum)} seit dem letzten Aufruf",
    )


def _warmed_up(signal: TimeframeView | None) -> GateCheck:
    if signal is None:
        return GateCheck("unknown_regime", False, "Signal-Zeitebene fehlt")
    known = signal.regime is not RegimeKind.UNKNOWN
    return GateCheck(
        "unknown_regime",
        known,
        signal.regime.value if known else "zu wenige Kerzen für ein Regime",
    )


def _structure_event(config: TriggerConfig, signal: TimeframeView) -> GateCheck:
    structure = signal.structure
    present = structure.bos or structure.choch
    if present:
        which = "Strukturbruch" if structure.bos else "Charakterwechsel"
        bars = structure.bars_since_bos if structure.bos else structure.bars_since_choch
        detail = f"{which} vor {_bars(bars)}" if bars is not None else which
    else:
        detail = f"kein Bruch, Folge {structure.sequence or 'ungelesen'}"
    return GateCheck(
        "no_structure_event", present or not config.require_bos_or_choch, detail
    )


def _sweep(config: TriggerConfig, signal: TimeframeView) -> GateCheck:
    liquidity = signal.liquidity
    present = liquidity.sweep_up or liquidity.sweep_down
    if present:
        side = "Kaufseite" if liquidity.sweep_up else "Verkaufsseite"
        bars = liquidity.bars_since_sweep
        detail = f"{side} geholt{f' vor {_bars(bars)}' if bars is not None else ''}"
    else:
        detail = "kein Sweep" + ("" if config.require_sweep else " (nicht verlangt)")
    return GateCheck("no_sweep", present or not config.require_sweep, detail)


def _confluence_check(config: TriggerConfig, signal: TimeframeView) -> GateCheck:
    count = _confluence(signal)
    minimum = config.min_indicator_confluence
    taking = [
        INDICATOR_WORDS.get(reading.name, reading.name.lower().replace("_", " "))
        for reading in signal.indicators
        if reading.bias is not Bias.NEUTRAL and reading.strength >= MIN_INDICATOR_STRENGTH
    ]
    detail = f"{count} von {minimum} Indikatoren beziehen Stellung"
    if taking:
        detail += f" ({', '.join(taking)})"
    return GateCheck("too_little_confluence", count >= minimum, detail)


def _news(config: TriggerConfig, snapshot: MarketSnapshot) -> GateCheck:
    window = config.news_blackout_minutes
    if window <= 0:
        return GateCheck("news_blackout", True, "Sperre aus")
    close = [
        item
        for item in snapshot.news
        if item.impact == "high"
        and item.minutes_until is not None
        and abs(item.minutes_until) <= window
    ]
    if not close:
        return GateCheck("news_blackout", True, f"nichts Wichtiges in {window} min")
    nearest = min(close, key=lambda item: abs(item.minutes_until or 0))
    return GateCheck("news_blackout", False, f"{nearest.event} in {window} min")


def _session(config: TriggerConfig, snapshot: MarketSnapshot) -> GateCheck:
    session = snapshot.session
    staffed = " + ".join(session.active) if session.active else "none staffed"
    if config.require_active_session and session.is_quiet:
        return GateCheck("wrong_session", False, "kein Desk besetzt")
    allowed = config.allowed_sessions
    if not allowed:
        return GateCheck("wrong_session", True, staffed)
    permitted = any(name in allowed for name in session.active)
    return GateCheck(
        "wrong_session", permitted, f"{staffed}; erlaubt {', '.join(allowed)}"
    )


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
    """The cheap filter in front of the expensive one.

    State is only the spacing rule and the counters; the conditions themselves
    live in `evaluate`, so what the dashboard explains and what the backtest
    applies cannot drift apart.
    """

    def __init__(self, config: TriggerConfig) -> None:
        self.config = config
        self.stats = TriggerStats()
        self._last_fired_index: int | None = None

    def read(self, snapshot: MarketSnapshot, bar_index: int) -> GateReading:
        """Every condition at this bar, without touching the counters.

        Separate from `should_ask` because the dashboard asks on every poll and
        must not move the gate's own state by looking at it.
        """
        return evaluate(
            snapshot,
            self.config,
            bars_since_last_call=self._bars_since(bar_index),
        )

    def should_ask(self, snapshot: MarketSnapshot, bar_index: int) -> bool:
        self.stats.seen += 1
        reason = self.read(snapshot, bar_index).blocking
        if reason is not None:
            setattr(self.stats, reason, getattr(self.stats, reason) + 1)
            return False

        self.stats.fired += 1
        self._last_fired_index = bar_index
        return True

    def _bars_since(self, bar_index: int) -> int | None:
        if self._last_fired_index is None:
            return None
        return bar_index - self._last_fired_index

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
