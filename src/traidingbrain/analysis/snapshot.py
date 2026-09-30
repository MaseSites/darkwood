"""Building the snapshot: everything the engine knows at one bar, in one object.

Every indicator reading that leaves this module is scale-free. RSI is already a
percentage; the moving-average spread and the MACD histogram are divided by ATR;
%B and the volume ratio are dimensionless by construction. Nothing here carries a
price, and that is not tidiness -- a single raw number would be enough for the
model to work out which symbol and roughly which month it is looking at, and then
its answer is partly memory rather than analysis.

Values are also quantised. Two snapshots that differ in the ninth decimal place of
an EMA describe the same market, and if they hash differently the decision cache
misses and the run is billed twice for the same question.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from traidingbrain.analysis.levels import build_levels
from traidingbrain.analysis.pipeline import FrameAnalysis, MultiFrameAnalysis
from traidingbrain.analysis.positioning import PositioningTimeline
from traidingbrain.analysis.sessions import SessionTimeline
from traidingbrain.config.settings import EngineConfig
from traidingbrain.data.calendar import MacroCalendar
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.data.sentiment import SentimentTimeline
from traidingbrain.domain.enums import Bias, Timeframe
from traidingbrain.domain.snapshot import (
    NORM_PRECISION,
    HistoryStats,
    IndicatorReading,
    LiquidityView,
    MarketSnapshot,
    NewsItem,
    PositioningStats,
    SentimentStats,
    SessionStats,
    StructureView,
    TimeframeView,
)

#: RSI boundaries. Conventional, and left conventional on purpose: these are the
#: levels the market itself watches, which is most of why they work at all.
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0

#: Spread between the moving averages, in ATR, at which the reading counts as
#: fully committed rather than merely leaning.
EMA_SPREAD_FULL_STRENGTH = 1.5

#: MACD histogram, in ATR, at the same point.
MACD_FULL_STRENGTH = 0.5

#: Volume multiple of its own average that counts as a full-strength signal.
VOLUME_FULL_STRENGTH = 2.5

#: Where a bar has to close within its own range before the close itself says
#: something. A close in the middle of the range is a bar nobody won.
CLOSE_STRONG_HIGH = 0.6
CLOSE_STRONG_LOW = 0.4


def _q(value: float) -> float:
    return round(float(value), NORM_PRECISION)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _reading(name: str, value: float, bias: Bias, strength: float) -> IndicatorReading:
    return IndicatorReading(name=name, value=_q(value), bias=bias, strength=_q(_clamp01(strength)))


def _sign_bias(value: float) -> Bias:
    if value > 0:
        return Bias.BULLISH
    if value < 0:
        return Bias.BEARISH
    return Bias.NEUTRAL


def read_indicators(analysis: FrameAnalysis, index: int) -> list[IndicatorReading]:
    """Turn raw indicator series into scale-free readings with a stance.

    `bias` is what the reading argues for, not what the number is. An RSI of 78 is
    a high number; what it argues is that buyers have already paid up, which is
    bearish for the next move -- and the strength says how emphatically.
    """
    indicators = analysis.indicators
    unit = indicators.at("atr", index)
    frame = analysis.frame
    close = float(frame["close"].to_numpy()[index])
    readings: list[IndicatorReading] = []

    rsi_value = indicators.at("rsi", index)
    if rsi_value >= RSI_OVERBOUGHT:
        rsi_bias = Bias.BEARISH
        rsi_strength = (rsi_value - RSI_OVERBOUGHT) / (100.0 - RSI_OVERBOUGHT)
    elif rsi_value <= RSI_OVERSOLD:
        rsi_bias = Bias.BULLISH
        rsi_strength = (RSI_OVERSOLD - rsi_value) / RSI_OVERSOLD
    else:
        rsi_bias = Bias.NEUTRAL
        rsi_strength = abs(rsi_value - 50.0) / 20.0
    readings.append(_reading("RSI", rsi_value, rsi_bias, rsi_strength))

    spread = (indicators.at("ema_fast", index) - indicators.at("ema_slow", index)) / unit
    readings.append(
        _reading(
            "EMA_SPREAD_ATR",
            spread,
            _sign_bias(spread),
            abs(spread) / EMA_SPREAD_FULL_STRENGTH,
        )
    )

    histogram = (indicators.at("macd_line", index) - indicators.at("macd_signal", index)) / unit
    readings.append(
        _reading(
            "MACD_HIST_ATR",
            histogram,
            _sign_bias(histogram),
            abs(histogram) / MACD_FULL_STRENGTH,
        )
    )

    # The scalar form. Building the whole %B series to read one element was a
    # third of the entire backtest runtime.
    percent_b = indicators.bollinger.percent_b_at(close, index)
    if np.isnan(percent_b):
        bb_bias, bb_strength = Bias.NEUTRAL, 0.0
    elif percent_b > 1.0:
        bb_bias, bb_strength = Bias.BEARISH, percent_b - 1.0
    elif percent_b < 0.0:
        bb_bias, bb_strength = Bias.BULLISH, -percent_b
    else:
        bb_bias, bb_strength = Bias.NEUTRAL, abs(percent_b - 0.5) * 2.0
    readings.append(
        _reading(
            "BB_PERCENT_B",
            0.0 if np.isnan(percent_b) else percent_b,
            bb_bias,
            bb_strength,
        )
    )

    average_volume = indicators.at("volume_ma", index)
    bar_volume = float(frame["volume"].to_numpy()[index])
    volume_ratio = bar_volume / average_volume if average_volume > 0 else 1.0
    # Volume confirms whoever is already in control; on its own it points nowhere.
    readings.append(
        _reading(
            "VOLUME_RATIO",
            volume_ratio,
            Bias.NEUTRAL,
            (volume_ratio - 1.0) / (VOLUME_FULL_STRENGTH - 1.0),
        )
    )

    # Where the bar closed inside its own range: conviction without a price.
    bar_high = float(frame["high"].to_numpy()[index])
    bar_low = float(frame["low"].to_numpy()[index])
    span = bar_high - bar_low
    position = (close - bar_low) / span if span > 0 else 0.5
    readings.append(
        _reading(
            "CLOSE_IN_RANGE",
            position,
            _close_bias(position),
            abs(position - 0.5) * 2.0,
        )
    )
    return readings


def _close_bias(position: float) -> Bias:
    if position > CLOSE_STRONG_HIGH:
        return Bias.BULLISH
    if position < CLOSE_STRONG_LOW:
        return Bias.BEARISH
    return Bias.NEUTRAL


def build_timeframe_view(analysis: FrameAnalysis, index: int) -> TimeframeView:
    structure_state = analysis.structure.state_at(index)
    liquidity_state = analysis.liquidity.state_at(index)
    regime_state = analysis.regime.state_at(index)

    return TimeframeView(
        timeframe=analysis.timeframe,
        regime=regime_state.kind,
        volatility=regime_state.volatility,
        trend=structure_state.trend,
        structure=StructureView(
            sequence=structure_state.sequence_text(),
            bos=structure_state.bos,
            choch=structure_state.choch,
            bars_since_bos=structure_state.bars_since_bos,
            bars_since_choch=structure_state.bars_since_choch,
        ),
        liquidity=LiquidityView(
            sweep_up=liquidity_state.sweep_up,
            sweep_down=liquidity_state.sweep_down,
            bars_since_sweep=liquidity_state.bars_since_sweep,
            zone_level_ids=[],
        ),
        indicators=read_indicators(analysis, index),
    )


EMPTY_HISTORY = HistoryStats(similar_situations_found=0, sample_is_sufficient=False)


class SnapshotBuilder:
    """Builds snapshots for one symbol from a pre-computed multi-frame analysis."""

    def __init__(
        self,
        symbol: str,
        analysis: MultiFrameAnalysis,
        config: EngineConfig,
        *,
        positioning: PositioningTimeline | None = None,
        calendar: MacroCalendar | None = None,
        sentiment: SentimentTimeline | None = None,
    ) -> None:
        self.symbol = symbol
        self.analysis = analysis
        self.config = config
        # Both optional, and absent is a supported state rather than a degraded
        # one: neither existed when the rest of this was written, and a backtest
        # over a period the venue does not cover has to keep working.
        self.positioning = positioning
        self.calendar = calendar
        self.sentiment = sentiment
        # Built here rather than passed in: it depends only on the signal frame's
        # timestamps, so there is nothing for a caller to find on disk and
        # nothing that can be forgotten.
        self.sessions = SessionTimeline(analysis.signal.frame)

    def build(
        self, signal_index: int, history: HistoryStats | None = None
    ) -> MarketSnapshot | None:
        """Build the snapshot for one signal bar, or None if it cannot be built.

        None is returned whenever any context frame is missing or still warming
        up. Emitting a partial snapshot would be worse than emitting none: it looks
        complete, and it would tell the model the weekly frame is neutral when the
        truth is that nothing is known about it yet.
        """
        indices = self.analysis.aligned_indices(signal_index)
        if indices is None:
            return None

        signal = self.analysis.signal
        price = signal.close_at(signal_index)
        atr = signal.atr_at(signal_index)

        bundles = {
            timeframe: (self.analysis.analyses[timeframe], index)
            for timeframe, index in indices.items()
        }
        levels = build_levels(
            bundles,
            signal_timeframe=self.analysis.signal_timeframe,
            price=price,
            atr=atr,
        )

        # Frames go in the configured order, highest first, so the serialised
        # snapshot is stable and the model always reads context before detail.
        ordered = [tf for tf in self.config.timeframes.context if tf in bundles]
        views = [build_timeframe_view(*bundles[timeframe]) for timeframe in ordered]

        return MarketSnapshot(
            symbol=self.symbol,
            ts=signal.ts_at(signal_index),
            signal_timeframe=self.analysis.signal_timeframe,
            price=price,
            atr=atr,
            frames=views,
            levels=levels,
            news=self._scheduled(signal.ts_at(signal_index)),
            positioning=self._positioning(signal_index),
            sentiment=self._sentiment(signal.ts_at(signal_index)),
            session=self._session(signal_index),
            history=history or EMPTY_HISTORY,
        )

    def _session(self, signal_index: int) -> SessionStats:
        view = self.sessions.at(signal_index)
        return SessionStats(
            active=list(view.active),
            is_overlap=view.is_overlap,
            bars_since_open=view.bars_since_open,
            position_in_range=view.position_in_range,
        )

    def _sentiment(self, bar_ts: int) -> SentimentStats:
        if self.sentiment is None:
            return SentimentStats()
        reading = self.sentiment.at(bar_ts + timeframe_ms(self.analysis.signal_timeframe))
        return SentimentStats(
            known=reading.known,
            value=reading.value,
            label=reading.label,
            is_extreme=reading.is_extreme,
        )

    def _positioning(self, signal_index: int) -> PositioningStats:
        if self.positioning is None:
            return PositioningStats()
        view = self.positioning.at(signal_index)
        return PositioningStats(
            known=view.known,
            reading=view.reading,
            bias=view.bias,
            strength=_q(view.strength),
            open_interest_change_pct=None
            if view.oi_change_pct is None
            else _q(view.oi_change_pct),
            open_interest_percentile=None
            if view.oi_percentile is None
            else _q(view.oi_percentile),
            crowd_long_ratio=None if view.crowd_long_ratio is None else _q(view.crowd_long_ratio),
            crowd_is_stretched=view.crowd_is_stretched,
        )

    def _scheduled(self, bar_ts: int) -> list[NewsItem]:
        """Events already on the calendar at this bar, nearest first.

        `minutes_until` is the only number here, and it is the one that matters:
        a decision an hour before a rate decision is a different decision from the
        same one a day before. The event's direction is never guessed -- sentiment
        stays neutral, because a scheduled release has no direction until it
        happens, and inventing one would be the exact failure the news weight was
        set to zero to avoid.
        """
        if self.calendar is None:
            return []
        decision_ts = bar_ts + timeframe_ms(self.analysis.signal_timeframe)
        return [
            NewsItem(
                event=event.name,
                impact=event.impact,
                sentiment=Bias.NEUTRAL,
                minutes_until=event.minutes_until(decision_ts),
            )
            for event in self.calendar.upcoming(decision_ts)
        ]


def build_multi_frame(
    frames: dict[Timeframe, pd.DataFrame], config: EngineConfig
) -> MultiFrameAnalysis:
    return MultiFrameAnalysis(frames, config)
