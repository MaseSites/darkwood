"""Does the block bootstrap actually account for dependence?

The module exists on the claim that the iid bootstrap returns intervals that are
too narrow for a series of trades. A test suite that only checked shapes and
return types would leave that claim unexamined, so most of these tests are
measurements: build a series whose dependence is known by construction, and
check that the interval responds to it.

The sharpest one is `test_a_full_length_block_cannot_vary`. With a block as long
as the series, every circular resample is a rotation of the original, so every
resampled mean is the sample mean exactly and the interval has zero width. That
is an exact consequence of the wrap-around, not an approximation, and it is the
test that would fail first if the index arithmetic were wrong.
"""

from __future__ import annotations

import numpy as np
import pytest

from traidingbrain.reporting.intervals import (
    MIN_OBSERVATIONS,
    Interval,
    block_bootstrap,
    paired_difference,
    suggested_block,
    two_group_difference,
)

N = 600


def white_noise(seed: int = 1, n: int = N) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, 1.0, size=n)


def autocorrelated(phi: float = 0.9, seed: int = 1, n: int = N) -> np.ndarray:
    """An AR(1) series, scaled to unit variance.

    The scaling matters. An AR(1) built from unit-variance shocks has variance
    1/(1-phi^2), which is five times larger at phi=0.9 -- so an interval built
    from it would be wider for two reasons at once, and the test could not say
    which. Dividing it out leaves dependence as the only difference from white
    noise.
    """
    shocks = np.random.default_rng(seed).normal(0.0, 1.0, size=n)
    series = np.empty(n)
    series[0] = shocks[0]
    for i in range(1, n):
        series[i] = phi * series[i - 1] + shocks[i]
    return series / series.std()


def width(interval: Interval | None) -> float:
    assert interval is not None
    return interval.high - interval.low


# -- the claim the module is built on ------------------------------------- #


def test_dependence_widens_the_interval() -> None:
    """The whole point: a series with memory earns a wider interval.

    Both series have the same length and the same variance. The only difference
    is that one remembers. If the block bootstrap did not notice, there would be
    no reason to have written it.
    """
    independent = width(block_bootstrap(white_noise(), block=1))
    dependent = width(block_bootstrap(autocorrelated(), block=None))
    assert dependent > 1.8 * independent, (
        f"iid width {independent:.4f}, block width {dependent:.4f} -- "
        "the block method is not responding to dependence"
    )


def test_the_iid_method_misses_it() -> None:
    """The same autocorrelated series, resampled one trade at a time.

    This is the measurement that condemns the old helper. Reading the same data
    with block=1 gives a far narrower interval than reading it with blocks, and
    the difference is not a modelling preference -- the series really does have
    the memory the block method is picking up.
    """
    series = autocorrelated()
    naive = width(block_bootstrap(series, block=1))
    honest = width(block_bootstrap(series, block=None))
    assert honest > 1.8 * naive


def test_independence_is_left_alone() -> None:
    """On a series without memory the two methods agree.

    The counterpart to the test above, and the one that stops the module from
    being an interval-widening machine. If blocks inflated every interval, a
    wider one would carry no information.
    """
    series = white_noise()
    naive = width(block_bootstrap(series, block=1))
    blocked = width(block_bootstrap(series, block=None))
    assert 0.75 < blocked / naive < 1.35


def test_suggested_block_grows_with_memory() -> None:
    forgetful = suggested_block(white_noise())
    remembering = suggested_block(autocorrelated(phi=0.9))
    assert remembering > forgetful
    # And more memory asks for more block than less memory.
    assert suggested_block(autocorrelated(phi=0.9)) > suggested_block(autocorrelated(phi=0.4))


# -- exact properties of the wrap-around ---------------------------------- #


def test_a_full_length_block_cannot_vary() -> None:
    """Block == n means every resample is a rotation, so the mean is fixed.

    Exact, not approximate: a rotation is a permutation, and the mean of a
    permutation is the mean. Any off-by-one in the modulo arithmetic -- a
    clipped index, a block that wraps twice, a truncation at the wrong place --
    would repeat or drop an observation and open the interval up.
    """
    series = white_noise(n=50)
    interval = block_bootstrap(series, block=50)
    assert interval is not None
    assert interval.low == pytest.approx(interval.mean, abs=1e-12)
    assert interval.high == pytest.approx(interval.mean, abs=1e-12)


def test_the_mean_is_the_sample_mean_not_a_resampled_one() -> None:
    """`mean` reports the data, so the interval can be read against it.

    A bootstrap can report the mean of its own resamples instead, which differs
    by a little and makes the point estimate depend on the seed.
    """
    series = autocorrelated()
    interval = block_bootstrap(series)
    assert interval is not None
    assert interval.mean == pytest.approx(float(series.mean()))


def test_the_block_length_is_reported() -> None:
    """An interval whose width depends on a parameter has to state it."""
    interval = block_bootstrap(autocorrelated())
    assert interval is not None
    assert interval.block == suggested_block(autocorrelated())
    assert f"Block {interval.block}" in interval.labelled()
    assert interval.n == N


def test_the_same_seed_gives_the_same_interval() -> None:
    series = autocorrelated()
    assert block_bootstrap(series, seed=7) == block_bootstrap(series, seed=7)
    assert block_bootstrap(series, seed=7) != block_bootstrap(series, seed=8)


# -- refusals ------------------------------------------------------------- #


def test_too_few_observations_is_no_interval() -> None:
    """Bounds from four numbers describe the four numbers."""
    assert block_bootstrap([1.0, -2.0, 0.5, 3.0]) is None
    assert block_bootstrap(list(range(MIN_OBSERVATIONS))) is not None


def test_a_constant_series_has_no_width() -> None:
    """Zero variance must not divide by zero in the block rule."""
    interval = block_bootstrap([2.0] * 40)
    assert interval is not None
    assert interval.low == pytest.approx(2.0)
    assert interval.high == pytest.approx(2.0)


def test_excludes_zero_reads_both_signs() -> None:
    assert Interval(1.0, 0.2, 1.8, 3, 50).excludes_zero
    assert Interval(-1.0, -1.8, -0.2, 3, 50).excludes_zero
    assert not Interval(0.1, -0.4, 0.6, 3, 50).excludes_zero


# -- pairing -------------------------------------------------------------- #


def test_unequal_arms_are_refused_rather_than_truncated() -> None:
    """Arms of different length do not pair, and silently zipping them lies.

    Two arms that traded different numbers of signals are the normal case for a
    filter study, and the tempting fix -- truncate to the shorter -- would
    compare signal 400 of one arm with signal 400 of the other, which are
    different trades at different times.
    """
    with pytest.raises(ValueError, match="do not pair"):
        paired_difference([1.0] * 20, [1.0] * 19)


def test_pairing_removes_the_shared_noise() -> None:
    """The reason to pair: a common market component cancels in the difference.

    Both arms here are the same market noise plus a small constant edge for the
    right arm. Differencing first measures the edge against the disagreement
    between the arms; bootstrapping each arm separately measures it against the
    market's whole variance, which is far larger and buries it.

    So the paired interval excludes zero and the separate ones cannot, on
    identical data. This is the function's entire justification.
    """
    rng = np.random.default_rng(3)
    market = rng.normal(0.0, 1.0, size=400)
    edge = 0.15
    left = market + rng.normal(0.0, 0.05, size=400)
    right = market + edge + rng.normal(0.0, 0.05, size=400)

    paired = paired_difference(left, right)
    assert paired is not None
    assert paired.mean == pytest.approx(edge, abs=0.02)
    assert paired.excludes_zero

    separately = block_bootstrap(left), block_bootstrap(right)
    assert separately[0] is not None and separately[1] is not None
    # The arms overlap heavily, so differencing their bounds says nothing.
    assert separately[0].high > separately[1].low
    assert width(paired) < 0.25 * width(separately[0])


def test_pairing_finds_nothing_when_there_is_nothing() -> None:
    """Two arms that differ only by noise must not produce a finding."""
    rng = np.random.default_rng(5)
    market = rng.normal(0.0, 1.0, size=400)
    left = market + rng.normal(0.0, 0.1, size=400)
    right = market + rng.normal(0.0, 0.1, size=400)
    paired = paired_difference(left, right)
    assert paired is not None
    assert not paired.excludes_zero


# -- two independent groups ---------------------------------------------- #


def test_two_group_difference_finds_a_real_gap() -> None:
    rng = np.random.default_rng(11)
    low = rng.normal(0.0, 1.0, size=300)
    high = rng.normal(0.8, 1.0, size=300)
    result = two_group_difference(high, low)
    assert result is not None
    assert result.mean == pytest.approx(0.8, abs=0.2)
    assert result.excludes_zero


def test_two_group_difference_finds_nothing_in_noise() -> None:
    rng = np.random.default_rng(12)
    result = two_group_difference(rng.normal(size=300), rng.normal(size=300))
    assert result is not None
    assert not result.excludes_zero


def test_a_stricter_level_widens_the_interval() -> None:
    """The point of carrying `level`: a correction that binds.

    A study printing a Bonferroni threshold and then reading a 95% interval has
    corrected nothing, which is what `scripts/study_winners.py` did.
    """
    rng = np.random.default_rng(13)
    a, b = rng.normal(0.4, 1.0, size=300), rng.normal(size=300)
    nominal = two_group_difference(a, b, level=0.95)
    corrected = two_group_difference(a, b, level=1 - 0.05 / 10)
    assert nominal is not None and corrected is not None
    assert width(corrected) > width(nominal)


def test_groups_of_unequal_size_are_fine() -> None:
    """Unlike the paired version, which must refuse them."""
    rng = np.random.default_rng(14)
    result = two_group_difference(rng.normal(size=400), rng.normal(size=90))
    assert result is not None
    assert result.n == 90


def test_a_group_too_small_gives_no_interval() -> None:
    rng = np.random.default_rng(15)
    assert two_group_difference(rng.normal(size=300), [1.0, 2.0, 3.0]) is None
