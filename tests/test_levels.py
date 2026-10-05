"""The level sweep: cheap, and honest about when a level becomes visible.

`learn/levels.py` exists because the public accessors on `ZoneTimeline` copy a
list per call, which is quadratic over a pass of 175,537 bars and so removed
this whole feature family from the first forward study -- the family Severin's
ADA reading pointed at. Making it cheap is only useful if it stays correct, and
two things could go wrong silently:

* **A level read before it was confirmed.** That is lookahead, and it would
  make the features look excellent and be worthless.
* **A level that price has traded clean through still counted as pending.** The
  feature then reports a wall that is not there, which is the opposite error
  and just as quiet.

Hand-built series, so every expected distance is arithmetic rather than
whatever the sweep happens to produce.
"""

from __future__ import annotations

import numpy as np

from traidingbrain.learn.levels import FAR, Level, pending_distances


def series(closes: list[float], *, pad: float = 0.5) -> dict[str, np.ndarray]:
    """Bars whose range is the close plus a fixed pad, so reach is exact."""
    values = np.array(closes, dtype="float64")
    return {
        "closes": values,
        "highs": values + pad,
        "lows": values - pad,
        "atr": np.ones(values.size, dtype="float64"),
    }


def sweep(closes: list[float], levels: list[Level], *, pad: float = 0.5):
    return pending_distances(levels=levels, **series(closes, pad=pad))


# --------------------------------------------------------------------------- #
# Visibility
# --------------------------------------------------------------------------- #


def test_a_level_is_invisible_before_it_was_confirmed() -> None:
    """The lookahead this module has to avoid.

    A zone confirmed at bar 3 is not a feature at bar 2, however obvious it
    looks once the series is complete.
    """
    out = sweep([100.0] * 6, [Level(low=110.0, high=111.0, created_index=3)])

    assert out.above[0] == FAR
    assert out.above[2] == FAR, "a level was read one bar before it existed"
    assert out.above[3] == 10.0, "and it must appear on the bar that confirmed it"


def test_the_distance_is_measured_in_atr() -> None:
    """So markets and eras compare, which is the whole reason for the unit."""
    bars = series([100.0] * 4)
    bars["atr"] = np.array([1.0, 2.0, 4.0, 5.0], dtype="float64")
    out = pending_distances(levels=[Level(low=110.0, high=111.0, created_index=0)], **bars)

    assert out.above[0] == 10.0
    assert out.above[1] == 5.0
    assert out.above[2] == 2.5


# --------------------------------------------------------------------------- #
# Leaving the pending set
# --------------------------------------------------------------------------- #


def test_a_level_price_reaches_stops_being_pending() -> None:
    """Otherwise the feature reports a wall price has already gone through."""
    out = sweep(
        [100.0, 105.0, 110.5, 112.0],
        [Level(low=110.0, high=111.0, created_index=0)],
    )

    assert out.above[0] == 10.0
    assert out.above[1] == 5.0
    # Bar 2 reaches into it, so from here there is nothing pending above.
    assert out.above[2] == FAR
    assert out.above[3] == FAR


def test_a_level_jumped_over_does_not_stay_pending() -> None:
    """The one place this differs from `ZoneTimeline`, deliberately.

    That class calls a touch an overlap of the bar's range with the zone. Here
    price jumping from below a level to above it between bars also clears it:
    crypto has those gaps, and a level price has traded clean through is not
    one price might return to.
    """
    out = sweep(
        [100.0, 130.0],
        [Level(low=110.0, high=111.0, created_index=0)],
        pad=0.1,
    )

    assert out.above[0] == 10.0
    assert out.above[1] == FAR, "a jumped-over level was still counted as a wall"


def test_a_level_leaves_the_set_once_and_does_not_come_back() -> None:
    """The invariant that makes the sweep linear instead of quadratic."""
    out = sweep(
        [100.0, 110.5, 100.0, 100.0],
        [Level(low=110.0, high=111.0, created_index=0)],
    )

    assert out.above[1] == FAR
    assert out.above[2] == FAR, "a cleared level reappeared when price fell back"


# --------------------------------------------------------------------------- #
# Sides and shape
# --------------------------------------------------------------------------- #


def test_both_sides_are_reported_as_positive_distances() -> None:
    """A single signed number could not say "walls on both sides" at all."""
    out = sweep(
        [100.0],
        [
            Level(low=105.0, high=106.0, created_index=0),
            Level(low=94.0, high=95.0, created_index=0),
        ],
    )

    assert out.above[0] == 5.0
    assert out.below[0] == 5.0


def test_the_nearest_level_wins_on_each_side() -> None:
    out = sweep(
        [100.0],
        [
            Level(low=120.0, high=121.0, created_index=0),
            Level(low=105.0, high=106.0, created_index=0),
            Level(low=80.0, high=81.0, created_index=0),
            Level(low=97.0, high=98.0, created_index=0),
        ],
    )

    assert out.above[0] == 5.0
    assert out.below[0] == 2.0


def test_a_level_containing_the_price_is_neither_above_nor_below() -> None:
    """"Price is inside it" is not a distance, and reporting zero would say
    the opposite of what is true -- that a wall is immediately adjacent."""
    out = sweep([100.0], [Level(low=99.0, high=101.0, created_index=0)])

    assert out.above[0] == FAR
    assert out.below[0] == FAR


def test_nothing_pending_reads_as_far_not_as_zero() -> None:
    out = sweep([100.0, 100.0], [])

    assert list(out.above) == [FAR, FAR]
    assert list(out.below) == [FAR, FAR]
    assert list(out.in_reach) == [0.0, 0.0]


def test_distances_are_capped_so_the_matrix_stays_finite() -> None:
    """A NaN or an infinity reaching a ridge fit poisons every coefficient."""
    out = sweep([100.0], [Level(low=1_000_000.0, high=1_000_001.0, created_index=0)])

    assert out.above[0] == FAR
    assert np.isfinite(out.above).all()


def test_in_reach_counts_the_sides_within_one_atr() -> None:
    out = sweep(
        [100.0],
        [
            Level(low=100.8, high=101.0, created_index=0),
            Level(low=99.0, high=99.2, created_index=0),
        ],
        pad=0.05,
    )

    assert out.in_reach[0] == 2.0


def test_a_bar_without_a_usable_atr_is_left_at_the_cap() -> None:
    """ATR is the denominator of every distance here, so zero invalidates it."""
    bars = series([100.0, 100.0])
    bars["atr"] = np.array([0.0, np.nan], dtype="float64")
    out = pending_distances(levels=[Level(low=105.0, high=106.0, created_index=0)], **bars)

    assert list(out.above) == [FAR, FAR]
    assert np.isfinite(out.above).all()


def test_the_arrays_line_up_with_the_frame() -> None:
    """Features are read by bar index, so a shorter array is a silent misalignment."""
    out = sweep([100.0] * 17, [])

    assert len(out) == 17
    assert out.above.size == out.below.size == out.in_reach.size == 17
