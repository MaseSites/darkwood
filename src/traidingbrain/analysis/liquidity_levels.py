"""Volume-weighted pivot zones -- Severin's own indicator, ported and measured.

The Pine prototype draws a zone at every confirmed pivot and weights it by the
volume traded in the window around that pivot, then reports what share of the
live weight sits above the price and what share below. Its hypothesis, from the
TikTok it came from, is that price travels toward the heavier untouched side.

**What is already here and is not rebuilt.** Pivots, their confirmation lag and
the rule that a level is only knowable once price has turned away from it are
`structure.py`'s job and it already does them correctly -- the no-lookahead
tests cover it. This module adds the one thing that is genuinely new: a weight
per level, and the balance of weight around the price.

Three changes from V1, each because the original measures something other than
what it means to:

**Relative volume, not raw.** V1 sums the chart's volume over the pivot window.
That number is larger in a busy year than in a quiet one, so a zone from 2021
outweighs a zone from last week for reasons that have nothing to do with the
level. The weight here is the window's volume divided by the median window
volume at that time, which asks "was this level busy *for its moment*".

**Overlapping windows are not silently added.** Two pivots five bars apart with
legs=3 share bars, and V1 counts those bars in both weights and then sums both
into "total liquidity". The totals here are computed over zones whose windows
do not overlap; where they do, the newer zone keeps the shared bars. The
alternative -- pretending the same candle is two separate pools -- inflates
exactly the number the hypothesis is about.

**Nothing is drawn.** The Pine code's lines, labels and capacity limit exist to
keep a chart readable. A measurement has no such constraint, and a capacity
limit that drops the oldest zone would make the result depend on how far back
the series happens to start.

**This module predicts nothing by itself.** It produces a feature. Whether that
feature says anything about what price does next is `study_liquidity.py`'s
question, and the answer is not assumed here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from traidingbrain.analysis.structure import StructureTimeline, SwingKind

#: Bars either side of a pivot, matching the Pine default.
DEFAULT_LEGS = 3

#: Bars after confirmation before a zone is forgotten.
#:
#: V1's default. Long enough that a level survives a quiet stretch, short enough
#: that the balance describes the market somebody is looking at rather than one
#: from three months ago.
DEFAULT_EXPIRY = 600

#: Window for the median that relative volume is measured against.
#:
#: Long enough to span several regimes so a busy fortnight does not become the
#: baseline; short enough to follow a market whose activity trends over years.
VOLUME_BASELINE_BARS = 500


@dataclass(frozen=True)
class LiquidityZone:
    """One pivot level, with when it became knowable and what it weighs."""

    price: float
    upper: bool
    pivot_index: int
    """The bar the extreme formed on."""

    confirmed_index: int
    """The bar it could first be drawn on -- never earlier, which is the whole
    reason the Pine version starts its lines at confirmation rather than
    retroactively at the pivot."""

    weight: float
    """Volume in the pivot's window, relative to what a window weighed at the
    time. One means ordinary."""

    window_start: int
    window_end: int
    touched_index: int | None = None

    def live_at(self, index: int, expiry: int = DEFAULT_EXPIRY) -> bool:
        """Known, not yet touched, not yet expired."""
        if index < self.confirmed_index:
            return False
        if self.touched_index is not None and index >= self.touched_index:
            return False
        return index - self.confirmed_index < expiry


@dataclass(frozen=True)
class Balance:
    """The weight above and below the price at one bar."""

    above: float
    below: float
    nearest_above: float | None
    nearest_below: float | None
    zones_above: int
    zones_below: int

    @property
    def total(self) -> float:
        return self.above + self.below

    @property
    def above_share(self) -> float | None:
        """Share of live weight sitting above the price, 0 to 1.

        None when nothing is live. Not a probability, and the distinction is
        the whole point of the exercise: it is a count of model weight, not of
        orders, and certainly not of what price will do.
        """
        return self.above / self.total if self.total > 0 else None

    @property
    def lean(self) -> float | None:
        """Above minus below, over the total: -1 all below, +1 all above."""
        share = self.above_share
        return None if share is None else 2.0 * share - 1.0


def relative_volume(frame: pd.DataFrame, window: int) -> np.ndarray:
    """Window volume divided by what a window weighed around then.

    The median rather than the mean, because volume has a long right tail: one
    capitulation candle drags a mean up for the whole baseline and makes every
    later zone look light by comparison.
    """
    volume = frame["volume"].to_numpy(dtype="float64")
    rolled = pd.Series(volume).rolling(window, min_periods=window).sum()
    baseline = rolled.rolling(VOLUME_BASELINE_BARS, min_periods=window * 3).median()
    with np.errstate(divide="ignore", invalid="ignore"):
        relative = rolled.to_numpy() / baseline.to_numpy()
    return np.asarray(relative, dtype="float64")


def find_zones(
    frame: pd.DataFrame, structure: StructureTimeline, *, legs: int = DEFAULT_LEGS
) -> list[LiquidityZone]:
    """A zone per confirmed pivot, weighted and dated.

    The swings come from `structure`, which already dates each one to the bar it
    became knowable on. Rebuilding pivot detection here would be a second answer
    to a question this project settled, and the two would drift.
    """
    window = 2 * legs + 1
    relative = relative_volume(frame, window)
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    length = len(frame)

    out: list[LiquidityZone] = []
    for swing in structure.all_swings():
        at = swing.confirmed_index
        if at >= length:
            continue
        weight = relative[at]
        if not np.isfinite(weight) or weight <= 0:
            # Warm-up, or a feed with no volume. Unknown is reported as absent
            # rather than as zero: a zone of weight nought would quietly drag
            # every share it appears in.
            continue

        upper = swing.kind is SwingKind.HIGH
        start = max(0, swing.index - legs)
        end = min(length - 1, swing.index + legs)
        prices = highs if upper else lows
        touched: int | None = None
        for i in range(at, length):
            if (prices[i] >= swing.price) if upper else (prices[i] <= swing.price):
                touched = i
                break

        out.append(
            LiquidityZone(
                price=float(swing.price),
                upper=upper,
                pivot_index=swing.index,
                confirmed_index=at,
                weight=float(weight),
                window_start=start,
                window_end=end,
                touched_index=touched,
            )
        )
    return out


def _without_overlap(zones: list[LiquidityZone]) -> list[LiquidityZone]:
    """Drop zones whose volume window is already claimed by a newer one.

    V1 sums overlapping windows into one "total liquidity", which counts the
    same candles twice and inflates the very number the hypothesis is about.
    Newest wins, because the newer pivot is the one a reader would be looking
    at; the older one keeps existing as a level, it just stops contributing a
    second copy of the same volume.
    """
    kept: list[LiquidityZone] = []
    claimed: set[int] = set()
    for zone in sorted(zones, key=lambda z: z.confirmed_index, reverse=True):
        span = range(zone.window_start, zone.window_end + 1)
        if any(bar in claimed for bar in span):
            continue
        claimed.update(span)
        kept.append(zone)
    return kept


def balance_at(
    zones: list[LiquidityZone],
    index: int,
    price: float,
    *,
    expiry: int = DEFAULT_EXPIRY,
) -> Balance:
    """What weight sits above and below the price on this bar.

    Only zones already confirmed by `index` are counted, which is what keeps
    this readable as of that bar rather than with hindsight.
    """
    live = [z for z in zones if z.live_at(index, expiry)]
    above_zones = [z for z in _without_overlap([z for z in live if z.price > price]) if z.upper]
    below_zones = [z for z in _without_overlap([z for z in live if z.price < price]) if not z.upper]
    return Balance(
        above=float(sum(z.weight for z in above_zones)),
        below=float(sum(z.weight for z in below_zones)),
        nearest_above=min((z.price for z in above_zones), default=None),
        nearest_below=max((z.price for z in below_zones), default=None),
        zones_above=len(above_zones),
        zones_below=len(below_zones),
    )
