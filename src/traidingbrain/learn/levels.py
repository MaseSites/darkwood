"""Where price stands relative to the levels nobody has traded through yet.

This is the feature family `learn/outlook.py` had to leave out, and the one
Severin's ADA reading actually pointed at. The dashboard said "85/100,
deutlich, Richtung aufwaerts" while ADA ran +10.84% and the system took
nothing, and `why_no_trade.py` gave the reason in one line: *125 Zonen
unberuehrt, davon 0 in Reichweite*. The setups wait for price to come back to a
level; in a strong trend it never does. So the quantity worth measuring is not
"is there a level" but "how far is the nearest one, in ATR".

The first study of the forward horizon omitted all of this for a compute
reason. `ZoneTimeline.known_at` and `unmitigated_at` return a list slice per
call, which is O(levels found so far) and therefore quadratic over a pass of
175,537 bars. With 11,492 zones and 18,311 gaps on BTC alone that is not a
constant factor, it is the difference between a run and no run.

**The sweep, and the invariant that makes it linear.** A level sitting above
the price can only stop being "above and untouched" by price reaching it: an
interval cannot be crossed without being entered. So each level leaves the
pending set exactly once, and two heaps -- levels above ordered by their lower
edge, levels below by their upper edge -- answer "nearest untouched above" and
"nearest untouched below" in log time per bar. Total work is one push and one
pop per level plus a lookup per bar, instead of a list copy per bar.

**One deliberate difference from `ZoneTimeline`.** That class defines a touch as
the bar's range overlapping the zone. Here a level above is dropped once
`bar_high >= level.low`, which also drops a level that price *jumped over*
between bars without any single bar overlapping it. Crypto has those gaps, and
a level price has traded clean through is no longer a level price might return
to -- treating it as still pending would quietly report a wall that is not
there. The two definitions agree on every bar that is not a jump.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

#: Distance reported when there is no pending level on that side, in ATR.
#:
#: A cap rather than NaN or infinity: the feature matrix has to stay finite,
#: and "further away than twenty ATR" and "none at all" mean the same thing to
#: a model deciding whether a level is in reach.
FAR = 20.0

#: What counts as "in reach", in ATR. The same unit the setups think in.
REACH = 1.0


@dataclass(frozen=True)
class Level:
    """A price band that became visible at a bar.

    `low`/`high` are prices; `created_index` is the first bar from which the
    level may be known. Reaching one earlier than that is the lookahead this
    whole module has to avoid.
    """

    low: float
    high: float
    created_index: int


@dataclass(frozen=True)
class Distances:
    """Per-bar arrays, all of them aligned with the frame."""

    above: np.ndarray
    below: np.ndarray
    in_reach: np.ndarray

    def __len__(self) -> int:
        return int(self.above.size)


def pending_distances(
    *,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    atr: np.ndarray,
    levels: list[Level],
    far: float = FAR,
    reach: float = REACH,
) -> Distances:
    """One forward sweep: nearest untouched level above and below, per bar.

    Distances are in ATR and signed positive on both sides -- `above` is how
    far up the nearest pending level is, `below` how far down. A model can
    learn an asymmetry from that; a single signed distance could not express
    "walls on both sides" at all.

    Levels become visible at `created_index` and never earlier, which is what
    keeps this honest: a zone confirmed at bar 500 is not a feature at bar 499
    however obvious it looks afterwards.
    """
    total = int(closes.size)
    above_out = np.full(total, far, dtype="float64")
    below_out = np.full(total, far, dtype="float64")
    reach_out = np.zeros(total, dtype="float64")

    by_creation = sorted(levels, key=lambda level: level.created_index)
    cursor = 0

    # Heaps of pending levels. Above is a min-heap on the lower edge -- the
    # first one price will reach going up. Below is a min-heap on the negated
    # upper edge, which is a max-heap on the edge itself.
    above: list[tuple[float, float]] = []
    below: list[tuple[float, float]] = []

    for index in range(total):
        close = closes[index]
        unit = atr[index]

        # Levels that become visible on this bar. Classified once: a level that
        # already contains the price is neither above nor below and is dropped,
        # since "price is inside it" is not a distance.
        while cursor < len(by_creation) and by_creation[cursor].created_index <= index:
            level = by_creation[cursor]
            cursor += 1
            if level.low > close:
                heapq.heappush(above, (level.low, level.high))
            elif level.high < close:
                heapq.heappush(below, (-level.high, level.low))

        # Levels price has reached on this bar leave the pending set for good.
        high = highs[index]
        low = lows[index]
        while above and above[0][0] <= high:
            heapq.heappop(above)
        while below and -below[0][0] >= low:
            heapq.heappop(below)

        if not (np.isfinite(unit) and unit > 0 and np.isfinite(close)):
            continue

        near_up = (above[0][0] - close) / unit if above else far
        near_down = (close - (-below[0][0])) / unit if below else far
        above_out[index] = min(max(near_up, 0.0), far)
        below_out[index] = min(max(near_down, 0.0), far)
        # Counted from the heaps rather than by scanning every pending level:
        # only the nearest on each side can be within one ATR often enough to
        # matter, and a full count would put the quadratic cost straight back.
        reach_out[index] = float(above_out[index] <= reach) + float(below_out[index] <= reach)

    return Distances(above=above_out, below=below_out, in_reach=reach_out)


def zones_of(zones: object) -> list[Level]:
    """Structural zones as levels, readable from the bar they were confirmed on.

    Reads the private lists on `ZoneTimeline` on purpose. The public accessors
    are `known_at` and `unmitigated_at`, and both return a list slice per call,
    which is the cost this module exists to avoid. What is needed here is the
    whole set once, with its confirmation bar attached.
    """
    found = getattr(zones, "_zones", None)
    if not found:
        return []
    return [
        Level(low=float(zone.low), high=float(zone.high), created_index=int(zone.confirmed_index))
        for zone in found
    ]


def gaps_of(gaps: list[object]) -> list[Level]:
    """Fair-value gaps as levels.

    These carry no confirmation lag -- a three-bar imbalance is recognisable on
    its own third bar -- so `created_index` is already the first bar at which
    the gap may be known.
    """
    return [
        Level(
            low=float(gap.low),  # type: ignore[attr-defined]
            high=float(gap.high),  # type: ignore[attr-defined]
            created_index=int(gap.created_index),  # type: ignore[attr-defined]
        )
        for gap in gaps
    ]


def swing_distances(
    *, closes: np.ndarray, atr: np.ndarray, structure: object, far: float = FAR
) -> Distances:
    """Distance to the last confirmed swing high and low, in ATR.

    No sweep needed: `StructureTimeline.state_at` already answers this in
    constant time and carries the confirmation lag, so a swing is not readable
    before the bar that confirmed it.
    """
    total = int(closes.size)
    high_out = np.full(total, far, dtype="float64")
    low_out = np.full(total, far, dtype="float64")
    for index in range(total):
        unit = atr[index]
        close = closes[index]
        if not (np.isfinite(unit) and unit > 0 and np.isfinite(close)):
            continue
        state = structure.state_at(index)  # type: ignore[attr-defined]
        if state.last_swing_high is not None:
            high_out[index] = min(abs(state.last_swing_high.price - close) / unit, far)
        if state.last_swing_low is not None:
            low_out[index] = min(abs(state.last_swing_low.price - close) / unit, far)
    return Distances(above=high_out, below=low_out, in_reach=np.zeros(total, dtype="float64"))
