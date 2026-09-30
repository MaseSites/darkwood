"""The market as it stands, chartable without a trade attached.

The proposal chart answers "was this a good trade". This answers a different
question -- "what is happening right now" -- and it is the one someone actually
spends time with. A screen that only has something to show when the system
happens to find a setup is a screen nobody learns the market on, and most hours
have no setup.

Everything drawn here is drawn by the same code as the proposal chart. Two
implementations of "which ten of these forty levels are worth the screen" would
disagree eventually, and the disagreement would be invisible: both would look
plausible, and the market view would quietly teach a different reading of the
chart than the one the trades are made on.

**Why the gate is on this screen.** Most hours have no setup, and a screen that
says nothing during them is a screen that cannot be trusted when it does speak --
silence is indistinguishable from a broken pipeline. So every poll shows which of
the named conditions the bar meets and which it does not. That is the same list
the backtest applies, read out in full rather than stopped at the first
objection.

**Why this is cached.** Building a multi-timeframe analysis takes about twenty
seconds -- five timeframes, indicators, structure, liquidity and regime over four
years of bars. Per request that is unusable. The cache is keyed on the newest
stored bar, so it rebuilds exactly when new data arrives and not otherwise.

**And why one build at a time.** The dashboard polls every four seconds. On a
cold cache that is six overlapping twenty-second builds before the first one
finishes, each one slowing the rest, and the screen never arrives -- a failure
that reports nothing at all, because every request is still legitimately working.
So the first caller builds and the others wait for its result.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from traidingbrain.analysis.context import load_context
from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.api.chart import (
    CONTEXT_BARS,
    Candle,
    EventLine,
    LevelLine,
    choose_levels,
)
from traidingbrain.brain.trigger import GateReading, evaluate
from traidingbrain.config.settings import EngineConfig, TriggerConfig
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.snapshot import MarketSnapshot

#: How long a built analysis may be reused before the store is checked again.
#: The check itself is cheap -- one parquet footer read -- so this only exists to
#: keep a burst of requests from doing it dozens of times a second.
FRESHNESS_SECONDS = 20


class FrameRead(BaseModel):
    """What one timeframe says, in the words the analysis already uses."""

    timeframe: str
    regime: str
    trend: str
    volatility: str
    sequence: str
    bos: bool
    choch: bool
    sweep_up: bool
    sweep_down: bool


class GateCheckRead(BaseModel):
    """One of the gate's conditions, as the screen shows it."""

    name: str
    passed: bool
    detail: str
    label: str
    #: The one refusal that decided the bar. Several conditions can read as
    #: unmet while only the first is the reason -- the gate stops there, and a
    #: panel that gave them equal weight would suggest a distance from a setup
    #: that nothing measures.
    blocking: bool = False


class GateRead(BaseModel):
    """Whether this bar would be put to the model, and what decided that.

    `would_ask` is deliberately not called "would trade". The gate only decides
    whether the bar is worth the model's attention; the model still answers WAIT
    on most of what reaches it, and conflating the two would put a number on the
    screen that promises more than it measures.
    """

    would_ask: bool
    blocking: str | None = None
    checks: list[GateCheckRead] = Field(default_factory=list)
    headline: str = ""


class MarketView(BaseModel):
    """The chart plus the reading, for a symbol at this moment."""

    symbol: str
    timeframe: str
    available_timeframes: list[str] = Field(default_factory=list)
    bar_ms: int
    as_of_ts: int
    price: float
    atr: float
    atr_pct: float
    candles: list[Candle]
    levels: list[LevelLine]
    events: list[EventLine] = Field(default_factory=list)
    levels_hidden: int = 0
    frames: list[FrameRead] = Field(default_factory=list)
    positioning: str = ""
    sentiment: str = ""
    session: str = ""
    upcoming: list[str] = Field(default_factory=list)
    gate: GateRead | None = None
    note: str = ""


@dataclass
class _Cached:
    analysis: MultiFrameAnalysis
    builder: SnapshotBuilder
    newest_ts: int
    checked_at: float


class MarketAnalysisCache:
    """Built analyses, rebuilt only when the underlying bars move.

    Keyed on the newest stored bar rather than on a timer: a timer either
    rebuilds work that is still current or serves a chart that is quietly behind,
    and which of the two you get depends on when the request landed.
    """

    def __init__(self, store: Any, config: EngineConfig) -> None:
        self.store = store
        self.config = config
        self._cache: dict[str, _Cached] = {}
        self._builds: dict[str, threading.Lock] = {}
        self._builds_guard = threading.Lock()

    def _newest_ts(self, symbol: str) -> int:
        stamp = self.store.last_ts(symbol, self.config.timeframes.signal)
        return int(stamp or 0)

    def for_symbol(self, symbol: str) -> _Cached | None:
        """The analysis for a symbol, rebuilt if the data has moved on.

        Only one build per symbol runs at a time. Everything else about this is
        a plain cache; that one rule is what makes it usable from a screen that
        polls faster than the work takes.
        """
        reusable = self._reusable(symbol)
        if reusable is not None:
            return reusable

        with self._build_lock(symbol):
            # Whoever held the lock has just finished a build. Checking again is
            # the whole point of waiting -- without it, every queued caller
            # would rebuild what it was waiting for.
            reusable = self._reusable(symbol)
            return reusable if reusable is not None else self._build(symbol)

    def _reusable(self, symbol: str) -> _Cached | None:
        """A cached analysis still worth serving, or None to rebuild."""
        cached = self._cache.get(symbol)
        if cached is None:
            return None
        now = time.monotonic()
        if now - cached.checked_at < FRESHNESS_SECONDS:
            return cached
        if cached.newest_ts == self._newest_ts(symbol):
            cached.checked_at = now
            return cached
        return None

    def _build_lock(self, symbol: str) -> threading.Lock:
        """One lock per symbol, so BTC waiting does not hold ETH up."""
        with self._builds_guard:
            return self._builds.setdefault(symbol, threading.Lock())

    def _build(self, symbol: str) -> _Cached | None:
        newest = self._newest_ts(symbol)
        frames = {tf: self.store.read(symbol, tf) for tf in self.config.timeframes.context}
        if any(frame.empty for frame in frames.values()):
            return None

        analysis = MultiFrameAnalysis(frames, self.config)
        context = load_context(symbol, analysis.signal.frame, self.config)
        builder = SnapshotBuilder(
            symbol,
            analysis,
            self.config,
            positioning=context.positioning,
            calendar=context.calendar,
            sentiment=context.sentiment,
        )
        built = _Cached(analysis, builder, newest, time.monotonic())
        self._cache[symbol] = built
        return built

    def latest_snapshot(self, symbol: str) -> tuple[MarketSnapshot, MultiFrameAnalysis] | None:
        """The newest bar a complete snapshot can be built for.

        Walks back rather than insisting on the last bar: the newest few can be
        mid-warm-up on a higher timeframe, and that is a normal answer during the
        first hours of a week rather than a fault.
        """
        cached = self.for_symbol(symbol)
        if cached is None:
            return None
        last = len(cached.analysis.signal) - 1
        for index in range(last, max(last - 200, -1), -1):
            snapshot = cached.builder.build(index)
            if snapshot is not None:
                return snapshot, cached.analysis
        return None


def build_market_view(
    snapshot: MarketSnapshot,
    frame: pd.DataFrame,
    *,
    timeframe: Timeframe,
    available: list[Timeframe],
    trigger: TriggerConfig | None = None,
    context_bars: int = CONTEXT_BARS,
) -> MarketView:
    """Assemble the market view for one symbol on one timeframe.

    Bars end at the snapshot, which here is simply the newest complete one --
    there is no decision to hide the future from. The trim still matters: a bar
    the analysis has not read yet would be drawn without any of the lines that
    belong to it.
    """
    bar_ms = timeframe_ms(timeframe)
    visible = frame.loc[frame["ts"] <= snapshot.ts].tail(context_bars)

    ts = visible["ts"].to_numpy(dtype="int64")
    opens = visible["open"].to_numpy(dtype="float64")
    highs = visible["high"].to_numpy(dtype="float64")
    lows = visible["low"].to_numpy(dtype="float64")
    closes = visible["close"].to_numpy(dtype="float64")
    volumes = visible["volume"].to_numpy(dtype="float64")
    candles = [
        Candle(
            ts=int(ts[i]),
            open=float(opens[i]),
            high=float(highs[i]),
            low=float(lows[i]),
            close=float(closes[i]),
            volume=float(volumes[i]),
        )
        for i in range(len(ts))
    ]

    levels, hidden = choose_levels(snapshot.levels, snapshot.atr)

    return MarketView(
        symbol=snapshot.symbol,
        timeframe=timeframe.value,
        available_timeframes=[tf.value for tf in available],
        bar_ms=bar_ms,
        as_of_ts=snapshot.ts,
        price=snapshot.price,
        atr=snapshot.atr,
        atr_pct=snapshot.atr_pct,
        candles=candles,
        levels=levels,
        events=_events(snapshot, timeframe, bar_ms, len(candles)),
        levels_hidden=hidden,
        frames=[
            FrameRead(
                timeframe=view.timeframe.value,
                regime=view.regime.value,
                trend=view.trend.value,
                volatility=view.volatility.value,
                sequence=view.structure.sequence,
                bos=view.structure.bos,
                choch=view.structure.choch,
                sweep_up=view.liquidity.sweep_up,
                sweep_down=view.liquidity.sweep_down,
            )
            for view in snapshot.frames
        ],
        session=_session_line(snapshot),
        positioning=snapshot.positioning.reading if snapshot.positioning.known else "",
        sentiment=(
            f"{snapshot.sentiment.value}/100 {snapshot.sentiment.label}"
            if snapshot.sentiment.known
            else ""
        ),
        upcoming=[
            f"{item.event} in {item.minutes_until // 60}h"
            for item in snapshot.news
            if item.minutes_until is not None and item.minutes_until >= 0
        ][:3],
        gate=(
            # No spacing state here: the dashboard is not the thing that spends
            # money on calls, and reporting "too soon" against a live loop the
            # screen cannot see would be an objection nobody could act on.
            _gate_read(evaluate(snapshot, trigger))
            if trigger is not None
            else None
        ),
        note="No trade is proposed here. This is the market, drawn the way the analysis reads it.",
    )


#: What each condition is called on screen. The counter names are the engine's
#: vocabulary and they are kept as the identifier, because a label that drifted
#: from the counter would make the statistics unreadable next to the screen.
GATE_LABELS = {
    "too_soon": "Spacing",
    "unknown_regime": "Regime",
    "no_structure_event": "Structure",
    "no_sweep": "Liquidity",
    "too_little_confluence": "Confluence",
    "news_blackout": "News",
    "wrong_session": "Session",
}


def _gate_read(reading: GateReading) -> GateRead:
    """The gate as a panel: every condition, and one sentence for the top.

    The headline names the first objection rather than counting failures. A bar
    that misses on three conditions is not three times further from a setup than
    one that misses on one -- the gate stops at the first, and saying otherwise
    would invent a distance the engine never measures.
    """
    checks = [
        GateCheckRead(
            name=check.name,
            passed=check.passed,
            detail=check.detail,
            label=GATE_LABELS.get(check.name, check.name),
            blocking=check.name == reading.blocking,
        )
        for check in reading.checks
    ]
    if reading.passed:
        headline = "This bar would be put to the model."
    else:
        blocking = next(check for check in checks if check.blocking)
        headline = f"No setup: {blocking.label.lower()} — {blocking.detail}."
    return GateRead(
        would_ask=reading.passed,
        blocking=reading.blocking,
        checks=checks,
        headline=headline,
    )


def _session_line(snapshot: MarketSnapshot) -> str:
    """Which desks are staffed, in a phrase rather than a list.

    Worth showing even though nothing acts on it: it is the difference between a
    break somebody made and a break that happened while nobody was watching, and
    that is not visible in the candles.
    """
    session = snapshot.session
    if not session.active:
        return "no desk staffed"
    names = " + ".join(session.active)
    return f"{names}{' overlap' if session.is_overlap else ''}"


def _events(
    snapshot: MarketSnapshot, timeframe: Timeframe, bar_ms: int, candle_count: int
) -> list[EventLine]:
    """Structural events from the snapshot, placed on this chart's own axis.

    An event confirmed on a higher timeframe still belongs here -- a daily break
    of structure is most of why an hourly chart looks the way it does. Its
    distance converts through real durations rather than bar counts, because the
    two only agree when the chart is on the timeframe the event came from.
    """
    lines: list[EventLine] = []
    for view in snapshot.frames:
        structure = view.structure
        liquidity = view.liquidity
        candidates = [
            ("bos", structure.bos, structure.bars_since_bos, "break of structure"),
            ("choch", structure.choch, structure.bars_since_choch, "change of character"),
            (
                "sweep_up" if liquidity.sweep_up else "sweep_down",
                liquidity.sweep_up or liquidity.sweep_down,
                liquidity.bars_since_sweep,
                "buy-side swept" if liquidity.sweep_up else "sell-side swept",
            ),
        ]
        for kind, present, bars_ago, label in candidates:
            if not present or bars_ago is None:
                continue
            back = round(bars_ago * timeframe_ms(view.timeframe) / bar_ms)
            index = candle_count - 1 - back
            if index < 0 or index >= candle_count:
                continue
            lines.append(
                EventLine(
                    kind=kind,
                    label=f"{label} ({view.timeframe.value})",
                    timeframe=view.timeframe.value,
                    bar_index=index,
                    bars_ago=bars_ago,
                )
            )
    return sorted(lines, key=lambda line: line.bar_index)
