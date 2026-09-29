"""Out-of-sample machinery.

These tests are about the tooling, not about any strategy. The tooling's job is to
refuse to overclaim, and the way it fails is by being quietly generous: a split
that leaks, a bootstrap that reports a narrower interval than the data supports, a
verdict that calls three-out-of-four folds a success.

So most of what is asserted here is a refusal.
"""

from __future__ import annotations

import numpy as np
import pytest

from traidingbrain.domain.enums import ExitReason, Side, TradeState
from traidingbrain.sim.broker import Fill
from traidingbrain.sim.evaluate import (
    MIN_TRADES_PER_WINDOW,
    Evaluation,
    FoldResult,
    Window,
    block_bootstrap,
    split,
    walk_forward,
)
from traidingbrain.sim.metrics import bootstrap_mean, compute_metrics

DAY = 86_400_000
START = 1_700_000_000_000
END = START + 800 * DAY


def fill(r_multiple: float, index: int = 0) -> Fill:
    """A trade with a chosen R, and self-consistent numbers around it."""
    risk = 100.0
    return Fill(
        proposal_id=f"p{index}",
        snapshot_hash="h",
        side=Side.LONG,
        state=TradeState.CLOSED_TARGET if r_multiple > 0 else TradeState.CLOSED_STOP,
        reason=ExitReason.TARGET if r_multiple > 0 else ExitReason.STOP,
        entry_price=100.0,
        exit_price=100.0 + r_multiple,
        qty=1.0,
        leverage=5.0,
        opened_ts=START + index * DAY,
        closed_ts=START + index * DAY + 3600_000,
        gross_pnl=r_multiple * risk,
        fees=0.0,
        funding=0.0,
        risk_amount=risk,
    )


# --------------------------------------------------------------------------- #
# Splitting
# --------------------------------------------------------------------------- #


def test_the_split_is_chronological() -> None:
    """Never random.

    A random split over a time series leaks: the test set surrounds the training
    set, so every gap is bracketed by data the strategy has already seen.
    """
    train, test = split(START, END, 0.5)

    assert train.start_ts == START
    assert train.end_ts == test.start_ts
    assert test.end_ts == END
    assert train.days == pytest.approx(test.days, rel=0.01)


def test_the_split_fraction_is_respected() -> None:
    train, test = split(START, END, 0.75)
    assert train.days == pytest.approx(600, abs=1)
    assert test.days == pytest.approx(200, abs=1)


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.1, 1.5])
def test_a_degenerate_split_is_refused(fraction: float) -> None:
    with pytest.raises(ValueError, match="strictly between"):
        split(START, END, fraction)


def test_walk_forward_windows_never_overlap_their_own_training() -> None:
    """Each test window sits strictly after the data it was trained on."""
    for train, test in walk_forward(START, END, folds=4):
        assert test.start_ts >= train.end_ts
        assert test.end_ts > test.start_ts


def test_walk_forward_training_windows_grow() -> None:
    """Anchored rather than rolling: nothing is deliberately forgotten, which is
    how the system would actually be operated."""
    pairs = walk_forward(START, END, folds=4)
    lengths = [train.days for train, _ in pairs]
    assert lengths == sorted(lengths)
    assert all(train.start_ts == START for train, _ in pairs)


def test_a_single_fold_is_refused() -> None:
    with pytest.raises(ValueError, match="folds"):
        walk_forward(START, END, folds=1)


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #


def test_the_block_bootstrap_is_wider_than_the_naive_one() -> None:
    """Trades cluster, and pretending they do not narrows the interval.

    A strategy in a trend takes a run of winners and then a run of losers when the
    trend ends. Resampling single trades treats those as interchangeable draws and
    reports more certainty than the data contains.
    """
    rng = np.random.default_rng(4)
    # Alternating regimes: twenty good trades, then twenty bad, repeated.
    values: list[float] = []
    for block in range(20):
        mean = 0.8 if block % 2 == 0 else -0.6
        values.extend(rng.normal(mean, 0.3, size=20))
    fills = [fill(v, i) for i, v in enumerate(values)]

    naive = bootstrap_mean(np.array(values))
    blocked = block_bootstrap(fills, block_size=20)

    assert blocked.high - blocked.low > naive.high - naive.low, (
        "the block bootstrap reported no more uncertainty than the naive one, "
        "so the clustering is not being preserved"
    )


def test_an_empty_bootstrap_is_zero_rather_than_an_error() -> None:
    assert block_bootstrap([]).value == 0.0


def test_a_tiny_sample_reports_its_own_range() -> None:
    result = block_bootstrap([fill(1.0, 0), fill(-1.0, 1)], block_size=10)
    assert result.low == pytest.approx(-1.0)
    assert result.high == pytest.approx(1.0)


def test_an_interval_that_spans_zero_knows_it() -> None:
    assert not bootstrap_mean(np.array([1.0, -1.0, 0.5, -0.5] * 20)).excludes_zero
    assert bootstrap_mean(np.array([1.0, 1.1, 0.9, 1.05] * 20)).excludes_zero


# --------------------------------------------------------------------------- #
# Verdicts that refuse to overclaim
# --------------------------------------------------------------------------- #


def make_evaluation(r_by_fold: list[list[float]]) -> Evaluation:
    folds = []
    for i, values in enumerate(r_by_fold):
        fills = [fill(v, j) for j, v in enumerate(values)]
        curve = [(START + j * 3600_000, 10_000.0) for j in range(len(values) + 2)]
        folds.append(
            FoldResult(
                window=Window(f"fold {i}", START + i * 100 * DAY, START + (i + 1) * 100 * DAY),
                result=type(
                    "R",
                    (),
                    {
                        "metrics": compute_metrics(f"fold {i}", fills, curve, 10_000.0),
                        "fills": fills,
                    },
                )(),
            )
        )
    return Evaluation(strategy="test", folds=folds)


def test_a_thin_sample_establishes_nothing() -> None:
    evaluation = make_evaluation([[1.0] * 5, [1.0] * 5])
    assert "nothing is established" in evaluation.verdict()


def test_three_good_folds_out_of_four_is_not_called_a_success() -> None:
    """Consistency is the claim, and three out of four is not consistency.

    Reporting it as one is how a strategy gets adopted on the strength of the
    periods that happened to suit it.
    """
    evaluation = make_evaluation([[0.5] * 25, [0.4] * 25, [0.6] * 25, [-0.5] * 25])
    verdict = evaluation.verdict()
    assert "3 of 4" in verdict
    assert "not consistent" in verdict


def test_every_fold_positive_is_reported_with_its_spread() -> None:
    evaluation = make_evaluation([[0.5] * 25, [0.4] * 25, [0.6] * 25, [0.45] * 25])
    verdict = evaluation.verdict()
    assert "all 4 folds" in verdict
    assert "spread" in verdict


def test_spread_across_folds_is_reported() -> None:
    """The number that says how much of a headline result was the period."""
    steady = make_evaluation([[0.5] * 25, [0.5] * 25, [0.5] * 25])
    erratic = make_evaluation([[1.5] * 25, [-1.0] * 25, [0.8] * 25])

    assert steady.spread < 0.05
    assert erratic.spread > 0.5


def test_min_trades_threshold_is_not_zero() -> None:
    """A guard against the threshold being quietly relaxed to make a report pass."""
    assert MIN_TRADES_PER_WINDOW >= 30
