"""Regime: what kind of market this is, and how violently it is moving.

Both readings are relative to the symbol's own recent history, never to a fixed
number and never to the whole dataset. A 2% daily range is calm for SOL and
extraordinary for a stablecoin pair, and an ATR percentile computed over the full
file tells the model on every bar how this moment compares to years it has not
lived through yet.

`UNKNOWN` is a real answer here, used whenever the indicators have not warmed up.
Forcing a classification onto the first fifty bars of a file produces confident
nonsense at exactly the point where there is least to go on.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from traidingbrain.analysis.indicators import IndicatorSet, rolling_percentile_rank, slope
from traidingbrain.analysis.liquidity import LiquidityTimeline
from traidingbrain.analysis.structure import StructureTimeline
from traidingbrain.domain.enums import Bias, RegimeKind, VolBucket

#: Percentile boundaries for the volatility buckets.
VOL_BREAKPOINTS: tuple[float, float, float] = (0.25, 0.60, 0.85)

#: Normalised slope beyond which a market counts as directional rather than flat.
TREND_SLOPE_FLOOR = 1e-4


@dataclass(frozen=True)
class RegimeState:
    index: int
    kind: RegimeKind
    volatility: VolBucket
    volatility_percentile: float
    trend_strength: float

    @property
    def is_trending(self) -> bool:
        return self.kind in (RegimeKind.TREND_UP, RegimeKind.TREND_DOWN)


def bucket_volatility(percentile: float) -> VolBucket:
    if np.isnan(percentile):
        return VolBucket.NORMAL
    low, normal, high = VOL_BREAKPOINTS
    if percentile < low:
        return VolBucket.LOW
    if percentile < normal:
        return VolBucket.NORMAL
    if percentile < high:
        return VolBucket.HIGH
    return VolBucket.EXTREME


class RegimeTimeline:
    """Regime and volatility per bar."""

    def __init__(
        self,
        frame: pd.DataFrame,
        indicators: IndicatorSet,
        structure: StructureTimeline,
        liquidity: LiquidityTimeline,
        *,
        volatility_window: int = 200,
        trend_window: int = 100,
    ) -> None:
        self._states = self._build(
            frame,
            indicators,
            structure=structure,
            liquidity=liquidity,
            volatility_window=volatility_window,
            trend_window=trend_window,
        )

    def _build(
        self,
        frame: pd.DataFrame,
        indicators: IndicatorSet,
        *,
        structure: StructureTimeline,
        liquidity: LiquidityTimeline,
        volatility_window: int,
        trend_window: int,
    ) -> list[RegimeState]:
        close = frame["close"]
        atr_pct = indicators.atr / close
        percentile = rolling_percentile_rank(atr_pct, volatility_window).to_numpy(dtype="float64")
        trend_slope = slope(close, trend_window).to_numpy(dtype="float64")
        fast = indicators.ema_fast.to_numpy(dtype="float64")
        slow = indicators.ema_slow.to_numpy(dtype="float64")

        states: list[RegimeState] = []
        for i in range(len(frame)):
            vol_pct = percentile[i]
            volatility = bucket_volatility(vol_pct)
            strength = trend_slope[i]

            structure_state = structure.state_at(i)
            liquidity_state = liquidity.state_at(i)

            kind = self._classify(
                structure_trend=structure_state.trend,
                slope_value=strength,
                fast_above_slow=_compare(fast[i], slow[i]),
                volatility=volatility,
                swept_both_ways=liquidity_state.sweep_up and liquidity_state.sweep_down,
            )
            states.append(
                RegimeState(
                    index=i,
                    kind=kind,
                    volatility=volatility,
                    volatility_percentile=float(vol_pct) if not np.isnan(vol_pct) else 0.5,
                    trend_strength=float(strength) if not np.isnan(strength) else 0.0,
                )
            )
        return states

    @staticmethod
    def _classify(
        *,
        structure_trend: Bias,
        slope_value: float,
        fast_above_slow: int,
        volatility: VolBucket,
        swept_both_ways: bool,
    ) -> RegimeKind:
        """Combine structure, slope and moving averages into one label.

        Three independent readings have to agree before a market is called
        trending. Any one of them alone is noisy enough to flip on a single bar,
        and a regime that flickers makes the history engine useless -- it would be
        matching setups to a label that was an accident of timing.
        """
        if np.isnan(slope_value) or fast_above_slow == 0:
            return RegimeKind.UNKNOWN

        # Liquidity taken on both sides while volatility is extreme, and structure
        # has gone nowhere: price is hunting stops rather than going somewhere.
        if swept_both_ways and volatility in (VolBucket.HIGH, VolBucket.EXTREME):
            return RegimeKind.MANIPULATION

        directional = abs(slope_value) >= TREND_SLOPE_FLOOR
        if not directional:
            return RegimeKind.RANGE

        if slope_value > 0 and fast_above_slow > 0 and structure_trend is not Bias.BEARISH:
            return RegimeKind.TREND_UP
        if slope_value < 0 and fast_above_slow < 0 and structure_trend is not Bias.BULLISH:
            return RegimeKind.TREND_DOWN
        return RegimeKind.RANGE

    def state_at(self, index: int) -> RegimeState:
        return self._states[index]

    def __len__(self) -> int:
        return len(self._states)


def _compare(fast: float, slow: float) -> int:
    """+1 when the fast average leads, -1 when it lags, 0 while warming up."""
    if np.isnan(fast) or np.isnan(slow):
        return 0
    if fast > slow:
        return 1
    if fast < slow:
        return -1
    return 0
