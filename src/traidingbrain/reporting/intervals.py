"""Confidence intervals that do not pretend trades are independent.

Every study script in this repository computed its interval the same way::

    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)

That is the iid bootstrap: it resamples single trades, which assumes each trade
is an independent draw. Trades from one strategy are not. They overlap in time,
they sit in the same market regime, and across twelve correlated crypto markets
a bad afternoon produces a dozen losses that are nearly one event. Resampling
them one at a time averages that dependence away and returns an interval that is
too narrow -- confidently too narrow, which is worse than no interval, because a
narrow interval is what makes a finding look real.

The masterplan names the fix directly in section 13: use a method that accounts
for time dependence, such as a block bootstrap on the portfolio return series,
and do not treat overlapping trades as an independent sample.

**What a block bootstrap does.** It resamples contiguous runs of the series
instead of single points. Whatever dependence lives inside a run of length L is
carried into the resample intact, so the spread of the resampled means reflects
it. With ``block=1`` it degenerates to the iid bootstrap exactly, which is how
the tests here demonstrate the difference rather than asserting it.

**The wrap-around.** This is the circular variant: blocks may run off the end of
the series and continue at the beginning. The plain moving-block bootstrap draws
starts from ``[0, n-L]``, which lets the first and last few observations appear
in fewer blocks than the middle ones and quietly down-weights the ends of the
period. Wrapping gives every observation the same weight. It pays for that by
joining the end of the period to its beginning in some blocks, which is a
fiction -- but a fiction about dependence between two distant points, which is
the dependence that is weakest anyway.

**What this cannot fix.** A wider interval is not a better estimate; it is an
honest one. Several results measured on 04.10.2026 carry intervals from the iid
method, and the ones that excluded zero only narrowly are the ones to re-read
with this. The block length is returned alongside the bounds for exactly that
reason: an interval whose width depends on a parameter has to state it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

#: A series of numbers, however the caller happens to hold them. The study
#: scripts keep lists; everything inside here is already an array.
type Numbers = Sequence[float] | np.ndarray

#: Resamples per interval. Enough that the percentile bounds are stable to about
#: a thousandth of an R, which is well below any effect worth acting on.
DRAWS = 3000

#: Below this many observations no interval is reported at all.
#:
#: Not a statistical threshold -- a bootstrap will happily return bounds from
#: four numbers. It is the point below which the bounds say more about the four
#: numbers than about the thing being measured, and a reader shown "[-2.1, +1.8]"
#: treats it as a measurement rather than as the absence of one.
MIN_OBSERVATIONS = 8


@dataclass(frozen=True)
class Interval:
    """A bootstrap interval, with the choices that produced it."""

    mean: float
    low: float
    high: float
    block: int
    n: int

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0 or self.high < 0

    def __str__(self) -> str:
        return f"[{self.low:+.3f}, {self.high:+.3f}]"

    def labelled(self) -> str:
        """The form a report prints: bounds, block length, and the verdict."""
        tail = "  <- Null ausgeschlossen" if self.excludes_zero else ""
        return f"{self} (Block {self.block}, n={self.n}){tail}"


def suggested_block(values: Numbers) -> int:
    """A block length taken from the series' own autocorrelation.

    Two rules, and the larger wins. The cube-root rule ``n ** (1/3)`` is the
    standard default and grows slowly with the sample. The autocorrelation rule
    adds length when the series actually carries dependence: it sums the
    positive part of the autocorrelation function to estimate how many
    observations it takes for the series to forget, and asks for twice that.

    Deliberately not the Politis-White automatic selector. That estimates the
    spectral density at zero and is the right answer for a paper; here the block
    length is reported next to every interval, so a reader can see what was
    chosen and ask for another. A rule that can be explained in four lines and
    is visible in the output is worth more than an optimal one that is neither.

    The sum stops at the first non-positive lag -- Geyer's initial-positive-
    sequence rule. Beyond that point the estimates are mostly noise, and
    including them makes the answer depend on the tail of the series rather than
    on its memory.
    """
    series = np.asarray(values, dtype="float64")
    n = series.size
    if n < MIN_OBSERVATIONS:
        return 1

    floor: int = max(1, round(float(n) ** (1.0 / 3.0)))

    centred = series - series.mean()
    variance = float(centred @ centred)
    if variance <= 0:
        return floor

    reach = min(n - 1, max(10, n // 4))
    total = 0.0
    for lag in range(1, reach + 1):
        rho = float(centred[lag:] @ centred[:-lag]) / variance
        if rho <= 0:
            break
        total += rho

    memory: int = round(1 + 2 * total)
    return max(floor, min(max(1, n // 2), memory))


def _resampled_means(series: np.ndarray, *, length: int, draws: int, seed: int) -> np.ndarray:
    """Means of `draws` circular block resamples, each of the original length."""
    n = series.size
    rng = np.random.default_rng(seed)
    # Enough blocks to cover n, then truncate -- so every resample holds exactly
    # n observations and its mean is comparable to the sample mean.
    count = int(np.ceil(n / length))
    starts = rng.integers(0, n, size=(draws, count))
    offsets = np.arange(length)
    # Wrap with a modulo rather than clipping: a clipped index would repeat the
    # last observation and pull every resampled mean towards it.
    picks = (starts[:, :, None] + offsets[None, None, :]) % n
    means: np.ndarray = series[picks.reshape(draws, count * length)[:, :n]].mean(axis=1)
    return means


def block_bootstrap(
    values: Numbers,
    *,
    block: int | None = None,
    draws: int = DRAWS,
    seed: int = 11,
    level: float = 0.95,
) -> Interval | None:
    """A circular moving-block bootstrap interval for the mean.

    `block=None` asks `suggested_block` for the length. `block=1` is the iid
    bootstrap, which is kept reachable on purpose: it is what every earlier
    study used, and being able to compute both from one function is what makes
    the difference between them a measurement rather than a claim.

    Returns None below `MIN_OBSERVATIONS` rather than bounds nobody should read.
    """
    series = np.asarray(values, dtype="float64")
    n = series.size
    if n < MIN_OBSERVATIONS:
        return None

    length = suggested_block(series) if block is None else max(1, min(int(block), n))
    means = _resampled_means(series, length=length, draws=draws, seed=seed)

    half = (1.0 - level) / 2.0
    return Interval(
        mean=float(series.mean()),
        low=float(np.percentile(means, 100 * half)),
        high=float(np.percentile(means, 100 * (1 - half))),
        block=length,
        n=n,
    )


def paired_difference(
    left: Numbers,
    right: Numbers,
    *,
    block: int | None = None,
    draws: int = DRAWS,
    seed: int = 11,
    level: float = 0.95,
) -> Interval | None:
    """An interval for `mean(right) - mean(left)` over a shared time axis.

    For comparing two arms of a study whose observations line up one-to-one --
    the same signal judged with and without a filter, in the same order. The
    blocks are drawn once and applied to the difference series, so the pairing
    survives the resampling. Bootstrapping the two arms independently and
    subtracting their bounds is a different and much wider thing, and it is the
    mistake this function exists to prevent.

    Requires equal lengths, because unequal ones mean the arms do not pair and
    the difference of their means is not what either arm measured. Two arms that
    traded different numbers of signals need `block_bootstrap` on each and a
    sentence saying they are not paired.
    """
    a = np.asarray(left, dtype="float64")
    b = np.asarray(right, dtype="float64")
    if a.size != b.size:
        raise ValueError(f"arms do not pair: {a.size} against {b.size} observations")
    n = a.size
    if n < MIN_OBSERVATIONS:
        return None

    difference = b - a
    length = suggested_block(difference) if block is None else max(1, min(int(block), n))
    means = _resampled_means(difference, length=length, draws=draws, seed=seed)

    half = (1.0 - level) / 2.0
    return Interval(
        mean=float(difference.mean()),
        low=float(np.percentile(means, 100 * half)),
        high=float(np.percentile(means, 100 * (1 - half))),
        block=length,
        n=n,
    )
