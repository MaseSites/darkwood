"""The permutation null, which is the only reason to believe the filter.

`scripts/study_filter.py` reported that zero of a hundred shuffled-label runs
matched the real result, p ~ 0.010. Everything that claim is worth depends on
two properties of this module, and both are asserted here directly rather than
reviewed:

* `test_the_test_labels_are_never_shuffled` -- if the null shuffled the test
  outcomes too, it would be scoring noise against noise, its expected result
  would be the base rate by construction, and every real result would look
  significant.
* `test_the_threshold_never_comes_from_the_test_fold` -- if the threshold were
  chosen where it is scored, there would be no out-of-sample number anywhere.

The rest check that the machinery finds a signal when one is there and finds
nothing when it is not, because a null that always rejects is as useless as one
that never does.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from traidingbrain.learn.evaluate import (
    MIN_KEPT_SHARE,
    MIN_TRAIN,
    evaluate,
    permutation_null,
    position,
)
from traidingbrain.learn.splits import DAY_MS, walk_forward

EPOCH = 1_600_000_000_000
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Case:
    """A labelled case whose target either follows its features or does not."""

    opened_ts: int
    closed_ts: int
    target: float
    features: tuple[float, ...]
    taken: bool = False


def build(*, n: int = 2400, signal: float = 0.0, seed: int = 1, every_hours: int = 8) -> list[Case]:
    """Cases spread evenly over time.

    `signal` is how strongly the first feature drives the target. At zero the
    target is pure noise and nothing is learnable, which is the control.
    """
    rng = np.random.default_rng(seed)
    cases: list[Case] = []
    for i in range(n):
        features = tuple(rng.normal(0.0, 1.0, size=4))
        noise = rng.normal(0.0, 1.0)
        opened = EPOCH + i * every_hours * HOUR_MS
        cases.append(
            Case(
                opened_ts=opened,
                closed_ts=opened + 2 * HOUR_MS,
                target=signal * features[0] + noise,
                # Half the cases are "taken", unrelated to the signal, so the
                # baseline is a fair comparison group rather than a good one.
                features=features,
                taken=i % 2 == 0,
            )
        )
    return cases


def folds_over(cases: list[Case]):
    return walk_forward(
        first_ts=cases[0].opened_ts,
        last_ts=cases[-1].closed_ts,
        train_days=180.0,
        validate_days=60.0,
        test_days=60.0,
        embargo_ms=48 * HOUR_MS,
    ).folds


# --------------------------------------------------------------------------- #
# The two properties the p-value rests on
# --------------------------------------------------------------------------- #


def test_the_test_labels_are_never_shuffled() -> None:
    """The null applies a noise-trained model to REAL outcomes.

    If the test labels were shuffled as well, the null would score noise
    against noise and every real result would clear it. The pooled realised
    outcomes must therefore be identical whether or not a shuffler was passed.
    """
    cases = build(signal=0.8)
    folds = folds_over(cases)
    real = evaluate(folds, cases)
    shuffled = evaluate(folds, cases, rng=np.random.default_rng(7))

    assert real.everything, "nothing was evaluated"
    assert shuffled.everything == real.everything, "the test outcomes were shuffled"
    assert shuffled.taken == real.taken, "the baseline group was shuffled"
    # The kept subset must differ, or the shuffling did nothing at all.
    assert shuffled.kept != real.kept


def test_the_threshold_never_comes_from_the_test_fold() -> None:
    """Scored where it was chosen, there would be no out-of-sample number.

    Checked by its consequence: a threshold fitted to the test fold would keep
    a subset whose mean is at least the fold mean, every time. A threshold
    chosen on a previous window has no such guarantee, and on noise it will
    often do worse.
    """
    worse = 0
    for seed in range(8):
        cases = build(signal=0.0, seed=seed)
        outcome = evaluate(folds_over(cases), cases)
        if outcome.kept and outcome.mean(outcome.kept) < outcome.mean(outcome.everything):
            worse += 1
    assert worse >= 2, (
        "the kept subset beat the fold mean every single time on pure noise, "
        "which is what a threshold chosen on the test fold would do"
    )


# --------------------------------------------------------------------------- #
# Does it work at all
# --------------------------------------------------------------------------- #


def test_a_real_signal_is_found_and_beats_the_null() -> None:
    cases = build(signal=1.0)
    folds = folds_over(cases)
    real = evaluate(folds, cases)
    assert real.folds_used >= 2
    assert real.mean(real.kept) > real.mean(real.everything)

    null = permutation_null(folds, cases, runs=12)
    assert null, "the null produced no runs"
    better, p_value = position(real.mean(real.kept), null)
    assert better == 0
    assert p_value == pytest.approx(1 / 13)


def test_pure_noise_mostly_does_not_beat_the_null() -> None:
    """The control, stated over several draws because one draw is not evidence.

    Written as a single seed first, and it failed: noise beat all twelve
    shuffled runs and reported p = 1/13 = 0.077. That is not a bug in the null,
    it is the null working at its stated resolution -- with twelve permutations
    the smallest reportable p *is* 0.077, and a noise instance lands there
    roughly one time in thirteen.

    It is worth keeping as a caution about reading any single p-value from this
    machinery, including the p ~ 0.010 that `scripts/study_filter.py` reported
    from a hundred permutations. Zero out of a hundred is a far stronger
    statement than zero out of twelve, and neither is a certainty.

    So the assertion is over seeds: noise may occasionally clear the null, and
    must not do so usually.
    """
    cleared = 0
    seeds = range(6)
    for seed in seeds:
        cases = build(signal=0.0, seed=seed)
        folds = folds_over(cases)
        real = evaluate(folds, cases)
        null = permutation_null(folds, cases, runs=12, seed=2000 + seed)
        _better, p_value = position(real.mean(real.kept), null)
        if p_value <= 0.1:
            cleared += 1
    assert cleared <= len(list(seeds)) // 2, (
        f"noise cleared the null in {cleared} of {len(list(seeds))} draws, "
        "so the null is not discriminating"
    )


def test_the_null_is_centred_near_the_base_rate() -> None:
    """A noise-trained model keeps an essentially arbitrary subset.

    So the null should sit near the mean of everything, not far above it. If it
    sat well above, the procedure itself would be manufacturing edge and the
    real result would have to clear a much higher bar than it appears to.
    """
    cases = build(signal=0.0, seed=5)
    folds = folds_over(cases)
    real = evaluate(folds, cases)
    null = permutation_null(folds, cases, runs=15)
    assert abs(float(np.mean(null)) - real.mean(real.everything)) < 0.25


# --------------------------------------------------------------------------- #
# Refusals and shape
# --------------------------------------------------------------------------- #


def test_a_fold_too_small_to_fit_is_skipped_not_fudged() -> None:
    """Rather than fitting a dozen features to thirty cases."""
    sparse = build(n=60, every_hours=48)
    outcome = evaluate(folds_over(sparse), sparse)
    assert outcome.folds_used == 0
    assert outcome.kept == []
    assert np.isnan(outcome.error)


def test_the_kept_subset_respects_the_floor() -> None:
    """Without a floor the best validation mean is one signal."""
    cases = build(signal=1.0)
    outcome = evaluate(folds_over(cases), cases)
    assert outcome.kept
    # Keeping at least the floor in each fold means the pooled share cannot
    # fall far below it either.
    assert len(outcome.kept) / len(outcome.everything) > MIN_KEPT_SHARE / 2


def test_the_same_seed_gives_the_same_null() -> None:
    cases = build(signal=0.5)
    folds = folds_over(cases)
    assert permutation_null(folds, cases, runs=5) == permutation_null(folds, cases, runs=5)


def test_a_different_seed_gives_a_different_null() -> None:
    cases = build(signal=0.5)
    folds = folds_over(cases)
    first = permutation_null(folds, cases, runs=5, seed=10)
    second = permutation_null(folds, cases, runs=5, seed=500)
    assert first != second


def test_the_p_value_cannot_be_zero() -> None:
    """A finite number of permutations cannot support a claim of certainty.

    The floor also makes the test's resolution visible: thirty runs cannot
    report better than 0.032 however strong the effect is.
    """
    better, p_value = position(99.0, [0.0] * 30)
    assert better == 0
    assert p_value == pytest.approx(1 / 31)
    assert p_value > 0


def test_the_p_value_counts_ties_against_the_claim() -> None:
    """A null run that merely equals the real result is not evidence for it."""
    better, p_value = position(1.0, [1.0, 0.0, 0.0, 0.0])
    assert better == 1
    assert p_value == pytest.approx(2 / 5)


def test_an_empty_null_still_reports_something_honest() -> None:
    assert position(1.0, []) == (0, 1.0)


def test_lift_is_measured_against_the_taken_baseline() -> None:
    """Not against every signal, which is the comparison that flatters."""
    cases = build(signal=1.0)
    outcome = evaluate(folds_over(cases), cases)
    assert outcome.taken, "no baseline group was collected"
    expected = outcome.mean(outcome.kept) - outcome.mean(outcome.taken)
    assert outcome.lift_over_taken == pytest.approx(expected)


def test_min_train_is_actually_enforced() -> None:
    """Stated as a constant and used, not just documented."""
    cases = build(n=MIN_TRAIN - 10, every_hours=48)
    assert evaluate(folds_over(cases), cases).folds_used == 0


def test_the_pooled_series_covers_only_test_windows() -> None:
    """Anything else would put training cases into the result."""
    cases = build(signal=0.5)
    folds = folds_over(cases)
    outcome = evaluate(folds, cases)
    in_tests = sum(len(fold.within(cases, fold.test)) for fold in folds)
    assert len(outcome.everything) <= in_tests
    assert len(outcome.everything) < len(cases), "the whole set reached the result"
    assert DAY_MS == 86_400_000
