"""Can anything from the evaluation period reach the training set?

Every test here is a version of that one question. The leak this module exists
to stop does not come through the features -- those can be verified bar by bar,
and `test_no_lookahead.py` does -- it comes through the label, which covers an
interval rather than a point. A case decided before the test window but settled
inside it carries the test period in its answer key.

`test_a_case_settled_in_the_choice_window_is_dropped` is the one that matters.
If it ever passes while the purge is removed, the purge was not doing anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import pytest

from traidingbrain.learn.splits import (
    DAY_MS,
    Fold,
    Window,
    pooled_test_cases,
    walk_forward,
)

JANUARY = 1_600_000_000_000
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Decision:
    """A case, which is only ever two timestamps as far as splitting cares."""

    opened_ts: int
    closed_ts: int
    name: str = ""


def plan(**overrides: object):
    defaults: dict[str, object] = {
        "first_ts": JANUARY,
        "last_ts": JANUARY + 900 * DAY_MS,
        "train_days": 360.0,
        "validate_days": 90.0,
        "test_days": 90.0,
        "embargo_ms": 48 * HOUR_MS,
    }
    return walk_forward(**(defaults | overrides))  # type: ignore[arg-type]


def one_fold(embargo_ms: int = 48 * HOUR_MS) -> Fold:
    return Fold(
        index=1,
        train=Window(JANUARY, JANUARY + 100 * DAY_MS),
        validate=Window(JANUARY + 100 * DAY_MS, JANUARY + 130 * DAY_MS),
        test=Window(JANUARY + 130 * DAY_MS, JANUARY + 160 * DAY_MS),
        embargo_ms=embargo_ms,
    )


# --------------------------------------------------------------------------- #
# The leak
# --------------------------------------------------------------------------- #


def test_a_case_settled_in_the_choice_window_is_dropped() -> None:
    """Decided in training, resolved in validation: its answer key is not ours.

    No feature in this case is dishonest. The leak is entirely in the label,
    which is partly made of the period the model is about to be scored on.
    """
    fold = one_fold()
    leaking = Decision(
        opened_ts=fold.train.end_ts - HOUR_MS,
        closed_ts=fold.validate.start_ts + 6 * HOUR_MS,
        name="leaks",
    )
    kept, purge = fold.training([leaking])
    assert kept == []
    assert purge.overlapped == 1
    assert purge.kept == 0


def test_the_barrier_is_validation_not_test() -> None:
    """Validation decides the threshold, so a case leaking into it is fitted too.

    Purging only up to the test window is the subtler version of the same
    mistake: the threshold would be chosen on data the model had trained on.
    """
    fold = one_fold()
    into_validation = Decision(
        opened_ts=fold.train.end_ts - DAY_MS,
        closed_ts=fold.validate.start_ts + DAY_MS,
    )
    kept, purge = fold.training([into_validation])
    assert kept == [] and purge.overlapped == 1


def test_the_embargo_drops_the_stretch_just_before() -> None:
    """Settled inside the gap: closed, but still nearly the same event."""
    fold = one_fold(embargo_ms=48 * HOUR_MS)
    just_before = Decision(
        opened_ts=fold.train.start_ts + DAY_MS,
        closed_ts=fold.validate.start_ts - HOUR_MS,
    )
    kept, purge = fold.training([just_before])
    assert kept == []
    assert purge.embargoed == 1
    assert purge.overlapped == 0, "this one did not overlap; it was embargoed"

    # With no embargo the same case is admissible, which is what makes the
    # previous assertion about the embargo rather than about the purge.
    kept_without, purge_without = one_fold(embargo_ms=0).training([just_before])
    assert len(kept_without) == 1 and purge_without.embargoed == 0


def test_a_case_that_closed_well_before_survives() -> None:
    fold = one_fold()
    clean = Decision(
        opened_ts=fold.train.start_ts + DAY_MS,
        closed_ts=fold.train.start_ts + 2 * DAY_MS,
    )
    kept, purge = fold.training([clean])
    assert kept == [clean]
    assert (purge.overlapped, purge.embargoed) == (0, 0)


def test_cases_decided_outside_the_training_window_are_not_counted() -> None:
    """Not dropped -- never considered. The distinction keeps the report honest."""
    fold = one_fold()
    later = Decision(opened_ts=fold.test.start_ts, closed_ts=fold.test.start_ts + HOUR_MS)
    kept, purge = fold.training([later])
    assert kept == []
    assert purge.considered == 0, "a case from another period is not a purged case"


def test_an_open_ended_case_in_the_test_window_is_kept() -> None:
    """Evaluation windows are not purged, on purpose.

    A trade opened inside the test period whose outcome runs past its end is
    still a decision the system made then. Dropping it would remove exactly the
    trades somebody was still sitting in, which skew towards losers --
    `sim/engine.py:244` refuses the same temptation.
    """
    fold = one_fold()
    still_running = Decision(
        opened_ts=fold.test.end_ts - HOUR_MS,
        closed_ts=fold.test.end_ts + 20 * DAY_MS,
    )
    assert fold.within([still_running], fold.test) == [still_running]


def test_the_purge_report_adds_up() -> None:
    fold = one_fold()
    cases = [
        Decision(fold.train.start_ts + DAY_MS, fold.train.start_ts + 2 * DAY_MS, "clean"),
        Decision(fold.train.start_ts + 2 * DAY_MS, fold.train.start_ts + 3 * DAY_MS, "clean"),
        Decision(fold.train.end_ts - HOUR_MS, fold.validate.start_ts + HOUR_MS, "overlap"),
        Decision(fold.train.start_ts + DAY_MS, fold.validate.start_ts - HOUR_MS, "embargo"),
    ]
    kept, purge = fold.training(cases)
    assert len(kept) == 2
    assert (purge.kept, purge.overlapped, purge.embargoed) == (2, 1, 1)
    assert purge.considered == 4
    assert "2 von 4" in purge.summary()
    assert "50.0% verworfen" in purge.summary()


# --------------------------------------------------------------------------- #
# Laying out the walk
# --------------------------------------------------------------------------- #


def test_the_windows_of_a_fold_are_disjoint_and_in_order() -> None:
    for fold in plan().folds:
        assert fold.train.end_ts == fold.validate.start_ts
        assert fold.validate.end_ts == fold.test.start_ts
        assert fold.train.start_ts < fold.test.start_ts


def test_test_windows_do_not_overlap_by_default() -> None:
    """The default step makes them abut, so the pooled result counts each day once."""
    folds = plan().folds
    assert len(folds) >= 2
    for earlier, later in pairwise(folds):
        assert earlier.test.end_ts <= later.test.start_ts


def test_a_smaller_step_overlaps_and_pooling_removes_the_duplicates() -> None:
    """More folds from the same data means the same days scored twice.

    Allowed, because sometimes more folds is what is wanted -- but then the
    pooled number has to deduplicate, or those days get double the weight.
    """
    dense = plan(step_days=30.0)
    assert len(dense.folds) > len(plan().folds)

    cases = [Decision(JANUARY + d * DAY_MS, JANUARY + d * DAY_MS + HOUR_MS) for d in range(900)]
    counted = sum(len(f.within(cases, f.test)) for f in dense.folds)
    pooled = pooled_test_cases(dense, cases)
    assert len(pooled) < counted, "overlapping windows should double-count before pooling"
    assert len({(c.opened_ts, c.closed_ts) for c in pooled}) == len(pooled)
    # And the pooled series is in time order, which every interval depends on.
    assert [c.opened_ts for c in pooled] == sorted(c.opened_ts for c in pooled)


def test_too_short_a_period_gives_no_folds_rather_than_a_bad_one() -> None:
    """A number with no warning is worse than no number."""
    short = plan(last_ts=JANUARY + 100 * DAY_MS)
    assert short.folds == ()


def test_the_holdout_sits_outside_every_fold() -> None:
    reserved = plan(holdout_days=120.0)
    assert reserved.holdout is not None
    assert reserved.holdout.days == pytest.approx(120.0)
    for fold in reserved.folds:
        assert fold.test.end_ts <= reserved.holdout.start_ts
    # And reserving it costs folds, which is the trade being made.
    assert len(reserved.folds) <= len(plan().folds)
    assert "verbraucht" in reserved.describe()


def test_no_holdout_means_none_rather_than_an_empty_window() -> None:
    assert plan(holdout_days=0.0).holdout is None


@pytest.mark.parametrize(
    "bad",
    [
        {"train_days": 0.0},
        {"validate_days": -1.0},
        {"test_days": 0.0},
        {"embargo_ms": -1},
        {"step_days": 0.0},
    ],
)
def test_impossible_layouts_are_refused(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        plan(**bad)
