"""Turning a market state into a vector that can be compared to other states.

The question the history engine answers is "have we been here before, and what
happened?" -- so the vector has to capture what makes two moments *similar as
setups*, not similar as prices.

Everything here is scale-free and instrument-free, for the same reason the model's
input is: a fingerprint that encoded price or symbol would only ever match the
same instrument at the same level, which is almost never, and the index would stay
empty. Built from ATR ratios and ordinal states, a setup on BTC at 40,000 can
match one on XRP at 0.60 -- and that is the whole point, because it is what turns
four thin histories into one usable one.

Ordinal encodings are deliberate over one-hot. Volatility runs low, normal, high,
extreme; that is an order, and a distance metric should know that extreme is
further from low than normal is. One-hot would make every regime equidistant from
every other, which is false.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe, VolBucket
from traidingbrain.domain.snapshot import MarketSnapshot, TimeframeView

#: Frames contributing to the fingerprint, coarsest first. M15 is left out: at that
#: resolution almost every bar looks different from every other, which pushes
#: neighbours apart without saying anything about the setup.
FINGERPRINT_FRAMES: tuple[Timeframe, ...] = (
    Timeframe.W1,
    Timeframe.D1,
    Timeframe.H4,
    Timeframe.H1,
)

#: Indicators taken from the signal frame, in a fixed order.
FINGERPRINT_INDICATORS: tuple[str, ...] = (
    "RSI",
    "EMA_SPREAD_ATR",
    "MACD_HIST_ATR",
    "BB_PERCENT_B",
    "VOLUME_RATIO",
    "CLOSE_IN_RANGE",
)

_TREND: dict[Bias, float] = {Bias.BEARISH: -1.0, Bias.NEUTRAL: 0.0, Bias.BULLISH: 1.0}

_VOLATILITY: dict[VolBucket, float] = {
    VolBucket.LOW: 0.0,
    VolBucket.NORMAL: 0.33,
    VolBucket.HIGH: 0.67,
    VolBucket.EXTREME: 1.0,
}

#: Regime is not an ordered scale, so it is split into the two things a distance
#: metric can meaningfully compare: how directional it is, and how disorderly.
_REGIME_DIRECTION: dict[RegimeKind, float] = {
    RegimeKind.TREND_UP: 1.0,
    RegimeKind.TREND_DOWN: -1.0,
    RegimeKind.RANGE: 0.0,
    RegimeKind.MANIPULATION: 0.0,
    RegimeKind.UNKNOWN: 0.0,
}

_REGIME_DISORDER: dict[RegimeKind, float] = {
    RegimeKind.TREND_UP: 0.0,
    RegimeKind.TREND_DOWN: 0.0,
    RegimeKind.RANGE: 0.5,
    RegimeKind.MANIPULATION: 1.0,
    RegimeKind.UNKNOWN: 0.5,
}

#: Cap on bars-since values before scaling, so one very old event does not
#: dominate the distance.
RECENCY_HORIZON_BARS = 40.0


@dataclass(frozen=True)
class FeatureNames:
    """Names in the same order as the vector, for debugging a bad match."""

    names: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.names)


def _recency(bars: int | None) -> float:
    """Recent events count for more; absent ones count for nothing.

    Mapped so that 'just happened' is 1 and 'long ago or never' is 0, which is how
    a distance metric should treat them -- a break forty bars ago is much closer to
    no break than it is to a break two bars ago.
    """
    if bars is None:
        return 0.0
    return max(0.0, 1.0 - min(float(bars), RECENCY_HORIZON_BARS) / RECENCY_HORIZON_BARS)


def _frame_features(view: TimeframeView) -> list[float]:
    return [
        _TREND[view.trend],
        _VOLATILITY[view.volatility],
        _REGIME_DIRECTION[view.regime],
        _REGIME_DISORDER[view.regime],
        _recency(view.structure.bars_since_bos) if view.structure.bos else 0.0,
        _recency(view.structure.bars_since_choch) if view.structure.choch else 0.0,
        _recency(view.liquidity.bars_since_sweep) if view.liquidity.sweep_up else 0.0,
        _recency(view.liquidity.bars_since_sweep) if view.liquidity.sweep_down else 0.0,
    ]


_FRAME_FEATURE_NAMES = (
    "trend",
    "volatility",
    "regime_direction",
    "regime_disorder",
    "bos_recency",
    "choch_recency",
    "sweep_up_recency",
    "sweep_down_recency",
)


def feature_names() -> FeatureNames:
    names: list[str] = []
    for frame in FINGERPRINT_FRAMES:
        names.extend(f"{frame.value}.{feature}" for feature in _FRAME_FEATURE_NAMES)
    names.extend(f"ind.{name}" for name in FINGERPRINT_INDICATORS)
    names.extend(["atr_pct_scaled", "nearest_above_atr", "nearest_below_atr"])
    return FeatureNames(tuple(names))


#: Bounds used to squash each signal-frame indicator into roughly [-1, 1], so no
#: single reading dominates the distance simply by having a larger natural range.
_INDICATOR_SCALE: dict[str, tuple[float, float]] = {
    "RSI": (50.0, 50.0),
    "EMA_SPREAD_ATR": (0.0, 2.0),
    "MACD_HIST_ATR": (0.0, 1.0),
    "BB_PERCENT_B": (0.5, 0.5),
    "VOLUME_RATIO": (1.0, 2.0),
    "CLOSE_IN_RANGE": (0.5, 0.5),
}


def fingerprint(snapshot: MarketSnapshot) -> np.ndarray:
    """One vector describing the shape of this moment.

    Missing frames contribute zeros rather than being skipped, so every vector has
    the same length and the same meaning position by position -- otherwise a
    snapshot taken before the weekly frame warmed up would be compared against a
    different set of features entirely.
    """
    values: list[float] = []
    by_frame = {view.timeframe: view for view in snapshot.frames}

    for frame in FINGERPRINT_FRAMES:
        view = by_frame.get(frame)
        values.extend(_frame_features(view) if view else [0.0] * len(_FRAME_FEATURE_NAMES))

    signal = by_frame.get(snapshot.signal_timeframe)
    readings = {r.name: r.value for r in signal.indicators} if signal else {}
    for name in FINGERPRINT_INDICATORS:
        centre, span = _INDICATOR_SCALE[name]
        raw = readings.get(name, centre)
        values.append(max(-1.0, min(1.0, (raw - centre) / span)) if span else 0.0)

    # Volatility in absolute terms, lightly scaled: 1% ATR is ordinary for a
    # crypto major, 4% is extraordinary.
    values.append(min(1.0, snapshot.atr_pct / 0.04))

    above = [level.distance_atr for level in snapshot.levels if level.distance_atr > 0]
    below = [level.distance_atr for level in snapshot.levels if level.distance_atr < 0]
    values.append(min(1.0, min(above) / 4.0) if above else 1.0)
    values.append(max(-1.0, max(below) / 4.0) if below else -1.0)

    return np.array(values, dtype="float64")


def dimension() -> int:
    return len(FINGERPRINT_FRAMES) * len(_FRAME_FEATURE_NAMES) + len(FINGERPRINT_INDICATORS) + 3
