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

**Why this is cached.** Building a multi-timeframe analysis takes about twenty
seconds -- five timeframes, indicators, structure, liquidity and regime over four
years of bars. Per request that is unusable. The cache is keyed on the newest
stored bar, so it rebuilds exactly when new data arrives and not otherwise.
"""

from __future__ import annotations

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
from traidingbrain.config.settings import EngineConfig
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
    upcoming: list[str] = Field(default_factory=list)
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

    def _newest_ts(self, symbol: str) -> int:
        stamp = self.store.last_ts(symbol, self.config.timeframes.signal)
        return int(stamp or 0)

    def for_symbol(self, symbol: str) -> _Cached | None:
        """The analysis for a symbol, rebuilt if the data has moved on."""
        cached = self._cache.get(symbol)
        now = time.monotonic()
        if cached is not None and now - cached.checked_at < FRESHNESS_SECONDS:
            return cached

        newest = self._newest_ts(symbol)
        if cached is not None and cached.newest_ts == newest:
            cached.checked_at = now
            return cached

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
        built = _Cached(analysis, builder, newest, now)
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
        note="No trade is proposed here. This is the market, drawn the way the analysis reads it.",
    )


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
