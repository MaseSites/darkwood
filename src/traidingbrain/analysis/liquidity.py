"""Liquidity: where stops are resting, and whether they have just been taken.

Three ideas, each defined so that it can only be recognised from bars that have
already closed.

**Pools.** Two or more swing highs at nearly the same price leave a cluster of
stop orders just above them. The same below swing lows. These are the levels price
tends to reach for, and they are built only from swings the structure timeline has
already confirmed.

**Sweeps.** A bar that pushes through such a pool and then closes back on the
original side has taken the liquidity and rejected the level. Judged on the close,
so it is a fact about a finished bar rather than a guess about a forming one.

**Fair value gaps.** Three bars where the middle one moved far enough that the
first and third do not overlap. The imbalance is knowable on the third bar, so
unlike swings these carry no confirmation lag. A gap stays active until price
trades back into it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from traidingbrain.analysis.structure import StructureTimeline, Swing, SwingKind

#: How many swings at the same price it takes to call it a pool. One swing is a
#: level; two is a crowd of stops resting behind it, which is the thing price
#: actually reaches for.
MIN_POOL_SIZE = 2


class ZoneKind(StrEnum):
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    FVG_BULLISH = "fvg_bullish"
    FVG_BEARISH = "fvg_bearish"


@dataclass(frozen=True)
class Zone:
    """A price band that matters: a stop cluster or an unfilled imbalance."""

    kind: ZoneKind
    low: float
    high: float
    created_index: int

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2.0

    @property
    def height(self) -> float:
        return self.high - self.low

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True)
class LiquidityState:
    """What was knowable about liquidity at one bar."""

    index: int
    sweep_up: bool
    sweep_down: bool
    bars_since_sweep: int | None
    zones: tuple[Zone, ...]

    def zones_of(self, kind: ZoneKind) -> tuple[Zone, ...]:
        return tuple(z for z in self.zones if z.kind is kind)


def find_pools(
    swings: list[Swing], kind: SwingKind, tolerance: float, max_pools: int = 4
) -> list[tuple[float, float, int]]:
    """Group swings that sit at nearly the same price into (low, high, index) bands.

    `tolerance` is an absolute price distance -- callers pass ATR times a
    configured fraction, so the definition of "nearly the same" scales with how
    much the market is moving rather than being a fixed number of dollars.

    Only clusters of two or more count. A single swing high is a level; two at the
    same price is a pool, and the difference is whether there is a crowd of stops
    sitting there.
    """
    candidates = [s for s in swings if s.kind is kind]
    if len(candidates) < MIN_POOL_SIZE:
        return []

    ordered = sorted(candidates, key=lambda s: s.price)
    clusters: list[list[Swing]] = [[ordered[0]]]
    for swing in ordered[1:]:
        if abs(swing.price - clusters[-1][-1].price) <= tolerance:
            clusters[-1].append(swing)
        else:
            clusters.append([swing])

    pools = [
        (
            min(s.price for s in cluster),
            max(s.price for s in cluster),
            max(s.confirmed_index for s in cluster),
        )
        for cluster in clusters
        if len(cluster) >= MIN_POOL_SIZE
    ]
    pools.sort(key=lambda p: p[2], reverse=True)
    return pools[:max_pools]


def find_fair_value_gaps(
    frame: pd.DataFrame, atr: pd.Series, min_size_atr: float = 0.25
) -> list[Zone]:
    """Three-bar imbalances, each recognisable on its own third bar.

    Bullish when the third bar's low sits above the first bar's high: price moved
    so quickly that a band of prices went untraded on the way up. Bearish is the
    mirror. Gaps smaller than `min_size_atr` are noise rather than imbalance.
    """
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    atr_values = atr.to_numpy(dtype="float64")

    zones: list[Zone] = []
    for i in range(2, len(frame)):
        unit = atr_values[i]
        if np.isnan(unit) or unit <= 0:
            continue
        floor = min_size_atr * unit

        if lows[i] - highs[i - 2] >= floor:
            zones.append(
                Zone(
                    kind=ZoneKind.FVG_BULLISH,
                    low=float(highs[i - 2]),
                    high=float(lows[i]),
                    created_index=i,
                )
            )
        elif lows[i - 2] - highs[i] >= floor:
            zones.append(
                Zone(
                    kind=ZoneKind.FVG_BEARISH,
                    low=float(highs[i]),
                    high=float(lows[i - 2]),
                    created_index=i,
                )
            )
    return zones


#: How many confirmed swings per side stay in view when looking for pools.
#:
#: Both a correctness and a speed decision. A pool formed two thousand bars ago is
#: not where today's stops are resting, and rescanning every swing ever confirmed
#: on every bar turns this pass quadratic -- on a few years of fifteen-minute data
#: that is the difference between a second and an afternoon.
MAX_TRACKED_SWINGS = 24


@dataclass
class _Cursor:
    last_sweep_index: int | None = None
    last_sweep_up: bool = False
    last_sweep_down: bool = False
    open_gaps: list[Zone] = field(default_factory=list)
    recent_swings: list[Swing] = field(default_factory=list)

    def remember(self, swing: Swing) -> None:
        self.recent_swings.append(swing)
        highs = [s for s in self.recent_swings if s.kind is SwingKind.HIGH][-MAX_TRACKED_SWINGS:]
        lows = [s for s in self.recent_swings if s.kind is SwingKind.LOW][-MAX_TRACKED_SWINGS:]
        self.recent_swings = sorted(highs + lows, key=lambda s: s.confirmed_index)


class LiquidityTimeline:
    """Liquidity state per bar, built in one forward pass."""

    def __init__(
        self,
        frame: pd.DataFrame,
        structure: StructureTimeline,
        atr: pd.Series,
        *,
        equal_tolerance_atr: float = 0.15,
        sweep_lookback_bars: int = 50,
        fvg_min_size_atr: float = 0.25,
        max_zones: int = 8,
    ) -> None:
        self.sweep_lookback_bars = sweep_lookback_bars
        self.max_zones = max_zones
        self._states = self._build(frame, structure, atr, equal_tolerance_atr, fvg_min_size_atr)

    def _build(
        self,
        frame: pd.DataFrame,
        structure: StructureTimeline,
        atr: pd.Series,
        equal_tolerance_atr: float,
        fvg_min_size_atr: float,
    ) -> list[LiquidityState]:
        highs = frame["high"].to_numpy(dtype="float64")
        lows = frame["low"].to_numpy(dtype="float64")
        closes = frame["close"].to_numpy(dtype="float64")
        atr_values = atr.to_numpy(dtype="float64")
        n = len(frame)

        gaps_by_index: dict[int, list[Zone]] = {}
        for zone in find_fair_value_gaps(frame, atr, fvg_min_size_atr):
            gaps_by_index.setdefault(zone.created_index, []).append(zone)

        # Swings are folded in as they are confirmed rather than re-queried per
        # bar, so this pass stays linear in the number of bars.
        arriving: dict[int, list[Swing]] = {}
        for swing in structure.all_swings():
            arriving.setdefault(swing.confirmed_index, []).append(swing)

        cursor = _Cursor()
        states: list[LiquidityState] = []

        for i in range(n):
            unit = atr_values[i]
            tolerance = equal_tolerance_atr * unit if not np.isnan(unit) else 0.0

            for swing in arriving.get(i, []):
                cursor.remember(swing)

            known = cursor.recent_swings
            high_pools = find_pools(known, SwingKind.HIGH, tolerance)
            low_pools = find_pools(known, SwingKind.LOW, tolerance)

            swept_up = False
            swept_down = False

            # A sweep is a push through a pool that the close rejected. Judged on
            # the finished bar, never on the one still printing.
            for low, high, created in high_pools:
                if created < i and highs[i] > high and closes[i] < low:
                    swept_up = True
                    break
            for low, high, created in low_pools:
                if created < i and lows[i] < low and closes[i] > high:
                    swept_down = True
                    break

            if swept_up or swept_down:
                cursor.last_sweep_index = i
                cursor.last_sweep_up = swept_up
                cursor.last_sweep_down = swept_down

            cursor.open_gaps.extend(gaps_by_index.get(i, []))
            cursor.open_gaps = [
                gap
                for gap in cursor.open_gaps
                if gap.created_index == i or not _is_filled(gap, lows[i], highs[i])
            ]

            within_window = (
                cursor.last_sweep_index is not None
                and i - cursor.last_sweep_index <= self.sweep_lookback_bars
            )
            zones = self._collect_zones(high_pools, low_pools, cursor.open_gaps)

            states.append(
                LiquidityState(
                    index=i,
                    sweep_up=bool(within_window and cursor.last_sweep_up),
                    sweep_down=bool(within_window and cursor.last_sweep_down),
                    bars_since_sweep=(
                        None if cursor.last_sweep_index is None else i - cursor.last_sweep_index
                    ),
                    zones=zones,
                )
            )
        return states

    def _collect_zones(
        self,
        high_pools: list[tuple[float, float, int]],
        low_pools: list[tuple[float, float, int]],
        open_gaps: list[Zone],
    ) -> tuple[Zone, ...]:
        zones = [
            Zone(kind=ZoneKind.EQUAL_HIGHS, low=low, high=high, created_index=created)
            for low, high, created in high_pools
        ] + [
            Zone(kind=ZoneKind.EQUAL_LOWS, low=low, high=high, created_index=created)
            for low, high, created in low_pools
        ]
        zones.extend(open_gaps[-self.max_zones :])
        zones.sort(key=lambda z: z.created_index, reverse=True)
        return tuple(zones[: self.max_zones])

    def state_at(self, index: int) -> LiquidityState:
        return self._states[index]

    def __len__(self) -> int:
        return len(self._states)


def _is_filled(gap: Zone, bar_low: float, bar_high: float) -> bool:
    """A gap is done once price has traded back through its midpoint.

    Requiring a full fill leaves stale zones lying around for months; the midpoint
    is where the imbalance has substantially been resolved.
    """
    return bar_low <= gap.mid <= bar_high
