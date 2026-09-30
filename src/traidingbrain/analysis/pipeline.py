"""One timeframe's analysis, bundled -- and the rule for lining timeframes up.

Multi-timeframe analysis has its own lookahead trap, separate from the one in
`structure`. A decision taken at the close of an H1 bar may use the daily bar only
if that daily bar has also closed. Using the daily candle that *contains* the
current hour means reading a candle whose high, low and close are still being
written by the very hour being decided on -- the most direct form of knowing the
answer.

`index_at_or_before` is the only supported way to line frames up, and it takes a
decision time rather than an index so the question it answers is explicit: which
bars had finished by the moment the decision was made?
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from traidingbrain.analysis.candles import CandleTimeline
from traidingbrain.analysis.indicators import IndicatorSet, compute_all
from traidingbrain.analysis.liquidity import LiquidityTimeline
from traidingbrain.analysis.regime import RegimeTimeline
from traidingbrain.analysis.structure import StructureTimeline
from traidingbrain.analysis.zones import ZoneTimeline
from traidingbrain.config.settings import EngineConfig
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import Timeframe


def decision_time_ms(bar_ts: int, timeframe: Timeframe) -> int:
    """When a decision on this bar is actually taken: the moment it closes."""
    return bar_ts + timeframe_ms(timeframe)


def index_at_or_before(frame: pd.DataFrame, timeframe: Timeframe, as_of_ms: int) -> int | None:
    """Index of the newest bar that had *closed* by `as_of_ms`.

    Returns None when the frame has no closed bar that early, which is a real
    answer during warm-up rather than something to paper over with index 0.
    """
    if frame.empty:
        return None
    closes = frame["ts"].to_numpy(dtype="int64") + timeframe_ms(timeframe)
    eligible = np.nonzero(closes <= as_of_ms)[0]
    if eligible.size == 0:
        return None
    return int(eligible[-1])


@dataclass
class FrameAnalysis:
    """Everything computed for one timeframe, indexed the same way as its frame."""

    timeframe: Timeframe
    frame: pd.DataFrame
    indicators: IndicatorSet
    structure: StructureTimeline
    liquidity: LiquidityTimeline
    regime: RegimeTimeline
    candles: CandleTimeline
    zones: ZoneTimeline
    _columns: dict[str, np.ndarray] = field(default_factory=dict, compare=False)

    def __len__(self) -> int:
        return len(self.frame)

    def column(self, name: str) -> np.ndarray:
        """A column as a numpy array, built once.

        These are read once per bar across a whole backtest, and `Series.iloc`
        costs about a microsecond a call. At twenty thousand bars times five
        frames that is measurable.
        """
        cached = self._columns.get(name)
        if cached is None:
            cached = self.frame[name].to_numpy()
            self._columns[name] = cached
        return cached

    def ts_at(self, index: int) -> int:
        return int(self.column("ts")[index])

    def close_at(self, index: int) -> float:
        return float(self.column("close")[index])

    def atr_at(self, index: int) -> float:
        return self.indicators.at("atr", index)

    def is_ready(self, index: int) -> bool:
        """Are all indicators warmed up, and is the ATR usable as a scale unit?

        ATR is the denominator for every normalised distance, so a zero or NaN
        there does not degrade the snapshot -- it invalidates it.
        """
        if index < 0 or index >= len(self.frame):
            return False
        if not self.indicators.is_ready(index):
            return False
        unit = self.atr_at(index)
        return bool(np.isfinite(unit)) and unit > 0.0


def analyse(frame: pd.DataFrame, timeframe: Timeframe, config: EngineConfig) -> FrameAnalysis:
    """Run the full analysis stack over one timeframe.

    Order matters: structure feeds liquidity (pools are built from confirmed
    swings), both feed regime, and structure feeds zones -- an order block is
    only valid at the CHoCH that validates it, so it cannot be found without the
    structure timeline that dates the CHoCH.
    """
    indicators = compute_all(
        frame,
        atr_period=config.indicators.atr_period,
        rsi_period=config.indicators.rsi_period,
        ema_fast=config.indicators.ema_fast,
        ema_slow=config.indicators.ema_slow,
        macd_fast=config.indicators.macd.fast,
        macd_slow=config.indicators.macd.slow,
        macd_signal=config.indicators.macd.signal,
        bb_period=config.indicators.bb.period,
        bb_std=config.indicators.bb.std,
        volume_ma=config.indicators.volume_ma,
    )
    structure = StructureTimeline(
        frame,
        lookback=config.structure.swing_lookback,
        max_sequence_length=config.structure.max_sequence_length,
    )
    liquidity = LiquidityTimeline(
        frame,
        structure,
        indicators.atr,
        equal_tolerance_atr=config.liquidity.equal_level_tolerance_atr,
        sweep_lookback_bars=config.liquidity.sweep_lookback_bars,
        fvg_min_size_atr=config.liquidity.fvg_min_size_atr,
    )
    regime = RegimeTimeline(
        frame,
        indicators,
        structure,
        liquidity,
        volatility_window=config.regime.volatility_window,
        trend_window=config.regime.trend_window,
    )
    return FrameAnalysis(
        timeframe=timeframe,
        frame=frame,
        indicators=indicators,
        structure=structure,
        liquidity=liquidity,
        regime=regime,
        candles=CandleTimeline(frame, indicators.atr),
        zones=ZoneTimeline(frame, indicators.atr, structure),
    )


class MultiFrameAnalysis:
    """Analysis across every context timeframe, aligned on demand.

    Built once per symbol per run. Alignment is recomputed per decision rather than
    cached by index, because the mapping from an H1 bar to a daily bar depends on
    the decision time and getting it wrong by one bar is exactly the failure this
    module exists to prevent.
    """

    def __init__(self, frames: dict[Timeframe, pd.DataFrame], config: EngineConfig) -> None:
        self.config = config
        self.signal_timeframe = config.timeframes.signal
        self.analyses: dict[Timeframe, FrameAnalysis] = {
            timeframe: analyse(frame, timeframe, config)
            for timeframe, frame in frames.items()
            if timeframe in config.timeframes.context
        }
        if self.signal_timeframe not in self.analyses:
            raise ValueError(
                f"the signal timeframe {self.signal_timeframe} must be among the loaded frames; "
                f"got {sorted(self.analyses)}"
            )

    @property
    def signal(self) -> FrameAnalysis:
        return self.analyses[self.signal_timeframe]

    def aligned_indices(self, signal_index: int) -> dict[Timeframe, int] | None:
        """Map a signal bar to the newest closed bar on every other timeframe.

        Returns None when any context frame has no closed bar yet, or when any of
        them is still warming up. A partial snapshot is worse than no snapshot: it
        looks complete and quietly tells the model that the weekly frame is
        neutral when the truth is that it is unknown.
        """
        signal = self.signal
        if not signal.is_ready(signal_index):
            return None

        as_of = decision_time_ms(signal.ts_at(signal_index), self.signal_timeframe)
        indices: dict[Timeframe, int] = {}
        for timeframe, analysis in self.analyses.items():
            index = index_at_or_before(analysis.frame, timeframe, as_of)
            if index is None or not analysis.is_ready(index):
                return None
            indices[timeframe] = index
        return indices

    def first_ready_index(self) -> int | None:
        """The earliest signal bar at which a complete snapshot can be built."""
        for index in range(len(self.signal)):
            if self.aligned_indices(index) is not None:
                return index
        return None
