"""The numeric filter, with the answers worked out independently.

Three of these tests exist because of mistakes that would not announce
themselves:

* `test_the_scaler_is_fitted_on_the_training_rows_only` -- standardising the
  whole matrix before splitting lets the test fold's mean and variance into the
  training set. Every feature stays honest one by one, and the leak is in the
  preprocessing.
* `test_a_constant_feature_does_not_poison_the_fit` -- zero variance divides by
  zero, and a single nan coefficient makes every prediction nan.
* `test_collinear_features_do_not_raise` -- two identical columns make the
  normal matrix singular, which would take a whole walk-forward run down.
"""

from __future__ import annotations

import numpy as np
import pytest

from traidingbrain.learn.model import (
    Ridge,
    Standardiser,
    brier_score,
    mean_squared_error,
    reliability,
)

NAMES = ("a", "b", "c")


def sample(n: int = 400, seed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Rows whose target is a known linear function plus noise.

    Deliberately on wildly different scales -- one in units of 1, one of 100,
    one of 0.01 -- because that is what the real feature set looks like
    (percent, hours, multiples of risk) and it is where an unstandardised
    penalty goes wrong.
    """
    rng = np.random.default_rng(seed)
    rows = np.column_stack(
        [
            rng.normal(0.0, 1.0, size=n),
            rng.normal(50.0, 100.0, size=n),
            rng.normal(0.0, 0.01, size=n),
        ]
    )
    target = 0.5 * rows[:, 0] + 0.01 * rows[:, 1] + 20.0 * rows[:, 2] + rng.normal(0.0, 0.1, size=n)
    return rows, target


# --------------------------------------------------------------------------- #
# Does it learn the thing
# --------------------------------------------------------------------------- #


def test_it_recovers_a_relation_it_was_shown() -> None:
    """With little penalty, the ranking of the standardised weights is right.

    Asserted on the ordering rather than on the raw coefficients, because
    standardising rescales them -- which is the point of doing it.
    """
    rows, target = sample()
    model = Ridge.fit(rows, target, names=NAMES, alpha=0.01)
    weights = model.weights()
    # Each true coefficient times its feature's spread: 0.5, 1.0, 0.2.
    assert list(weights) == ["b", "a", "c"]
    assert model.intercept == pytest.approx(float(target.mean()))


def test_predictions_are_close_on_data_it_was_fitted_to() -> None:
    rows, target = sample()
    model = Ridge.fit(rows, target, names=NAMES, alpha=0.01)
    # The noise floor is 0.1 standard deviations, so 0.02 of squared error is
    # about as good as anything can do here.
    assert mean_squared_error(model.predict(rows), target) < 0.02


def test_a_bigger_penalty_shrinks_every_weight() -> None:
    """The whole reason alpha exists, stated as a property."""
    rows, target = sample()
    light = Ridge.fit(rows, target, names=NAMES, alpha=0.01)
    heavy = Ridge.fit(rows, target, names=NAMES, alpha=10_000.0)
    assert np.all(np.abs(heavy.coef) < np.abs(light.coef))
    # And it shrinks towards the training mean, not towards zero R.
    assert heavy.predict(rows).std() < light.predict(rows).std()
    assert heavy.predict(rows).mean() == pytest.approx(float(target.mean()), abs=1e-6)


def test_the_same_data_gives_the_same_model() -> None:
    """Closed form, so there is no seed and nothing to be flaky about."""
    rows, target = sample()
    first = Ridge.fit(rows, target, names=NAMES, alpha=1.0)
    second = Ridge.fit(rows, target, names=NAMES, alpha=1.0)
    assert np.array_equal(first.coef, second.coef)
    assert first.intercept == second.intercept


def test_standardising_makes_one_alpha_mean_the_same_thing_everywhere() -> None:
    """Rescale a feature's units and the fitted model must not change.

    Without standardisation the penalty falls almost entirely on whichever
    feature has the smallest units, so "alpha = 1" would mean something
    different for a percentage than for a count of hours.
    """
    rows, target = sample()
    scaled = rows.copy()
    scaled[:, 2] *= 1000.0
    a = Ridge.fit(rows, target, names=NAMES, alpha=1.0)
    b = Ridge.fit(scaled, target, names=NAMES, alpha=1.0)
    assert np.allclose(a.predict(rows), b.predict(scaled))


# --------------------------------------------------------------------------- #
# The leak and the crashes
# --------------------------------------------------------------------------- #


def test_the_scaler_is_fitted_on_the_training_rows_only() -> None:
    """The preprocessing leak, which leaves every feature looking honest.

    A model fitted on the first half must predict the second half identically
    whether or not the second half exists -- if the scaler had seen it, the
    predictions would move.
    """
    rows, target = sample(n=400)
    train, test = rows[:200], rows[200:]
    model = Ridge.fit(train, target[:200], names=NAMES, alpha=1.0)

    first = model.predict(test)
    # Fit again with the test rows available but not passed in; nothing may move.
    again = Ridge.fit(train, target[:200], names=NAMES, alpha=1.0)
    assert np.array_equal(first, again.predict(test))
    # And the scaler's statistics are the training ones.
    assert np.allclose(model.scaler.mean, train.mean(axis=0))
    assert np.allclose(model.scaler.scale, train.std(axis=0))


def test_a_constant_feature_does_not_poison_the_fit() -> None:
    rows, target = sample()
    rows[:, 1] = 7.0
    model = Ridge.fit(rows, target, names=NAMES, alpha=1.0)
    assert np.all(np.isfinite(model.coef))
    assert np.all(np.isfinite(model.predict(rows)))
    assert model.weights()["b"] == pytest.approx(0.0, abs=1e-9)


def test_collinear_features_do_not_raise() -> None:
    """Two identical columns make the normal matrix singular."""
    rows, target = sample()
    rows[:, 2] = rows[:, 0]
    model = Ridge.fit(rows, target, names=NAMES, alpha=0.0)
    assert np.all(np.isfinite(model.coef))


def test_a_single_row_does_not_raise() -> None:
    """Degenerate but reachable: a fold with almost nothing in it."""
    model = Ridge.fit(np.array([[1.0, 2.0, 3.0]]), np.array([0.5]), names=NAMES, alpha=1.0)
    assert np.all(np.isfinite(model.predict(np.array([[1.0, 2.0, 3.0]]))))


@pytest.mark.parametrize(
    ("rows", "target", "names", "alpha", "match"),
    [
        (np.zeros((3, 2)), np.zeros(4), ("a", "b"), 1.0, "rows against"),
        (np.zeros((3, 2)), np.zeros(3), ("a", "b", "c"), 1.0, "columns against"),
        (np.zeros(3), np.zeros(3), ("a",), 1.0, "2-D"),
        (np.zeros((3, 1)), np.zeros(3), ("a",), -1.0, "negative"),
    ],
)
def test_mismatched_input_is_refused(
    rows: np.ndarray, target: np.ndarray, names: tuple[str, ...], alpha: float, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        Ridge.fit(rows, target, names=names, alpha=alpha)


def test_weights_are_named_and_ordered_by_size() -> None:
    rows, target = sample()
    model = Ridge.fit(rows, target, names=NAMES, alpha=0.01)
    weights = model.weights()
    assert set(weights) == set(NAMES)
    sizes = [abs(value) for value in weights.values()]
    assert sizes == sorted(sizes, reverse=True)
    assert "Achsenabschnitt" in model.describe()


def test_the_standardiser_handles_a_zero_variance_column() -> None:
    scaler = Standardiser.fit(np.array([[1.0, 5.0], [2.0, 5.0], [3.0, 5.0]]))
    assert scaler.scale[1] == 1.0
    assert np.all(np.isfinite(scaler.apply(np.array([[2.0, 5.0]]))))


# --------------------------------------------------------------------------- #
# Calibration diagnostics
# --------------------------------------------------------------------------- #


def test_brier_rewards_a_calibrated_forecast() -> None:
    outcome = np.array([1.0, 1.0, 0.0, 0.0])
    assert brier_score(np.array([1.0, 1.0, 0.0, 0.0]), outcome) == pytest.approx(0.0)
    assert brier_score(np.array([0.5, 0.5, 0.5, 0.5]), outcome) == pytest.approx(0.25)
    assert brier_score(np.array([0.0, 0.0, 1.0, 1.0]), outcome) == pytest.approx(1.0)


def test_reliability_bins_predicted_against_observed() -> None:
    rng = np.random.default_rng(2)
    probability = rng.uniform(0.0, 1.0, size=4000)
    outcome = (rng.uniform(size=4000) < probability).astype("float64")
    curve = reliability(probability, outcome, bins=5)
    assert len(curve) == 5
    for predicted, observed, count in curve:
        assert count > 0
        # A perfectly calibrated generator, so the two should track closely.
        assert abs(predicted - observed) < 0.06


def test_reliability_leaves_out_empty_bins() -> None:
    """An empty bin is not a place the model was wrong."""
    curve = reliability(np.array([0.05, 0.06, 0.95]), np.array([0.0, 0.0, 1.0]), bins=10)
    assert len(curve) == 2
    assert [count for _, _, count in curve] == [2, 1]


def test_reliability_keeps_a_prediction_of_exactly_one() -> None:
    """The last bin takes its upper edge, or a certain forecast disappears."""
    curve = reliability(np.array([1.0, 1.0]), np.array([1.0, 0.0]), bins=4)
    assert [count for _, _, count in curve] == [2]
