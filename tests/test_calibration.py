"""Vorhersage und Auflösung getrennt halten, und die Kennzahlen von Hand prüfen.

Zwei Dinge werden hier geprüft, und beide haben einen konkreten Anlass im
Projekt.

**Erstens die Trennung.** `journal/store.py` machte ein Upsert, sodass ein
erneuter Replay die gespeicherte Begründung still überschrieb -- genau das, was
der Forschungsauftrag verbietet. Eine Vorhersage, die nachträglich geändert
werden kann, ist keine. Darum muss `record()` beim zweiten Aufruf scheitern und
`resolve()` ohne vorherige Vorhersage ebenfalls.

**Zweitens die Kennzahlen.** Die Erwartungswerte unten sind mit der Hand
gerechnet und im Testtext ausgeschrieben, nicht aus der Implementierung
abgeleitet. Ein Test, der die Formel des Codes nachbaut, prüft nur, ob zweimal
dasselbe getippt wurde -- dieses Projekt hat einen Test gehabt, der eine
handgerechnete Epoche behauptete und dabei zwei Tage falsch lag, während der
Code recht hatte. Die Lehre war: der Test muss eine *unabhängige* Quelle für
seine Erwartung haben.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from traidingbrain.learn.calibration import (
    AlreadyPredictedError,
    Bin,
    NotPredictedError,
    Prediction,
    PredictionStore,
    Resolution,
    brier_score,
    expected_calibration_error,
    log_loss,
    reliability,
)

HOUR = 3_600_000
START = 1_790_000_000_000


def prediction(
    decision_id: str = "d1",
    *,
    at: int = START,
    probability: float = 0.6,
    taken: bool = True,
    reason: str | None = None,
    horizon: int = 12,
) -> Prediction:
    return Prediction(
        decision_id=decision_id,
        decision_time=at,
        symbol="BTCUSDT",
        setup_id="A",
        model_version="test-1",
        feature_hash="abc123",
        calibration_version="sigmoid-1",
        raw_score=0.35,
        predicted_probability=probability,
        predicted_net_r=0.08,
        predicted_loss_quantile=-1.02,
        expected_cost=0.0007,
        decision_taken=taken,
        rejection_reason=reason,
        original_risk_chf=10.0,
        label_end_time=at + horizon * HOUR,
    )


@pytest.fixture
def store(tmp_path: Path) -> PredictionStore:
    return PredictionStore(tmp_path / "predictions.sqlite")


# -- Die Trennung ----------------------------------------------------------- #


def test_a_prediction_is_written_once_and_never_overwritten(store: PredictionStore) -> None:
    """Zwei Vorhersagen für eine Entscheidung heissen, dass eine das Ergebnis kannte."""
    store.record(prediction())
    with pytest.raises(AlreadyPredictedError, match="schon vorhergesagt"):
        store.record(prediction(probability=0.9))

    kept = store.predictions()
    assert len(kept) == 1
    assert kept[0].predicted_probability == pytest.approx(0.6), "Der zweite Wert ist eingesickert"


def test_a_resolution_without_a_prediction_is_refused(store: PredictionStore) -> None:
    """Ein Ergebnis ohne vorher aufgezeichnete Erwartung ist Rückschau."""
    with pytest.raises(NotPredictedError, match="keine Vorhersage"):
        store.resolve(
            Resolution(
                decision_id="niemals",
                resolution_time=START + 99 * HOUR,
                realized_net_r=1.4,
                realized_cost=0.0007,
                realized_win=True,
            )
        )


def test_a_resolution_before_the_label_end_is_refused(store: PredictionStore) -> None:
    """Ein Ergebnis, das vor seinem Label-Ende eintrifft, existiert noch nicht.

    Die Grenze, die bei FreqAI an der internen Teilung fehlt, wird hier
    erzwungen: `label_end_time` ist die Zeit, zu der das Label FESTSTEHT.
    """
    store.record(prediction(horizon=12))
    with pytest.raises(ValueError, match="vor seinem Label-Ende"):
        store.resolve(
            Resolution(
                decision_id="d1",
                resolution_time=START + 6 * HOUR,
                realized_net_r=0.5,
                realized_cost=0.0007,
                realized_win=True,
            )
        )


def test_resolving_leaves_the_prediction_untouched(store: PredictionStore) -> None:
    store.record(prediction(probability=0.42))
    store.resolve(
        Resolution(
            decision_id="d1",
            resolution_time=START + 20 * HOUR,
            realized_net_r=-1.03,
            realized_cost=0.0008,
            realized_win=False,
        )
    )
    predicted, resolved = store.matched()[0]
    assert predicted.predicted_probability == pytest.approx(0.42)
    assert predicted.predicted_net_r == pytest.approx(0.08)
    assert resolved.realized_net_r == pytest.approx(-1.03)


def test_a_rejection_must_carry_a_reason() -> None:
    """Tausend Ablehnungen ohne Grund waren der Zustand, der nichts hergab."""
    with pytest.raises(ValueError, match="Ablehnung ohne Grund"):
        prediction(taken=False, reason=None)
    with pytest.raises(ValueError, match="keinen Ablehnungsgrund"):
        prediction(taken=True, reason="kosten")


def test_a_score_outside_zero_one_is_not_a_probability() -> None:
    with pytest.raises(ValueError, match="ausserhalb"):
        prediction(probability=1.4)


def test_the_calibration_sample_includes_refused_cases_by_default(
    store: PredictionStore,
) -> None:
    """Nur die genommenen zu messen heisst, auf der Auswahl der Regel zu messen.

    Die Regel hat genau die Fälle genommen, bei denen sie sich sicher war. Wer
    die Kalibrierung darauf misst, misst sie auf der Teilmenge, die das
    Ergebnis am stärksten vorwegnimmt.
    """
    for index, taken in enumerate([True, False, True, False]):
        store.record(
            prediction(
                f"d{index}",
                at=START + index * HOUR,
                taken=taken,
                reason=None if taken else "kosten",
            )
        )
        store.resolve(
            Resolution(
                decision_id=f"d{index}",
                resolution_time=START + (index + 13) * HOUR,
                realized_net_r=0.4 if taken else -0.2,
                realized_cost=0.0007,
                realized_win=taken,
            )
        )
    assert len(store.matched()) == 4
    assert len(store.matched(taken_only=True)) == 2


# -- Die Kennzahlen, mit unabhängig gerechneten Erwartungen ----------------- #


def test_brier_score_against_a_hand_computed_value() -> None:
    """Vier Fälle, von Hand gerechnet.

    p = 0.9 / y = 1 -> (0.9-1)^2 = 0.01
    p = 0.8 / y = 0 -> (0.8-0)^2 = 0.64
    p = 0.3 / y = 0 -> 0.09
    p = 0.6 / y = 1 -> 0.16
    Summe 0.90, geteilt durch 4 = 0.225
    """
    got = brier_score([0.9, 0.8, 0.3, 0.6], [True, False, False, True])
    assert got == pytest.approx(0.225)


def test_a_perfect_forecaster_scores_zero_and_the_worst_scores_one() -> None:
    assert brier_score([1.0, 0.0], [True, False]) == pytest.approx(0.0)
    assert brier_score([0.0, 1.0], [True, False]) == pytest.approx(1.0)


def test_log_loss_against_a_hand_computed_value() -> None:
    """Zwei Fälle, beide mit p = 0.5.

    -[1*ln(0.5) + 0*ln(0.5)] und -[0*ln(0.5) + 1*ln(0.5)], gemittelt
    = -ln(0.5) = ln(2) = 0.6931472...
    """
    got = log_loss([0.5, 0.5], [True, False])
    assert got == pytest.approx(math.log(2.0))


def test_log_loss_does_not_become_infinite_on_a_confident_mistake() -> None:
    """Ohne Abschneiden würde ein einziger Fall die Kennzahl bestimmen."""
    got = log_loss([0.0], [True])
    assert math.isfinite(got)
    assert got > 10.0, "Ein sicherer Irrtum muss teuer sein, nur nicht unendlich"


def test_reliability_bins_report_their_occupancy() -> None:
    """Ein Band mit drei Fällen sagt nichts -- und ohne count sieht man das nicht."""
    bins = reliability([0.05, 0.15, 0.95], [False, False, True], bins=10)
    assert len(bins) == 10
    populated = [b for b in bins if b.count]
    assert [b.count for b in populated] == [1, 1, 1]
    assert bins[0].mean_predicted == pytest.approx(0.05)
    assert bins[0].mean_observed == pytest.approx(0.0)
    empty = [b for b in bins if b.count == 0]
    assert all(math.isnan(b.mean_predicted) for b in empty)


def test_a_probability_of_exactly_one_lands_in_the_last_bin() -> None:
    """Sonst fällt der sicherste Fall still heraus."""
    bins = reliability([1.0], [True], bins=4)
    assert bins[-1].count == 1
    assert sum(b.count for b in bins) == 1


def test_expected_calibration_error_weights_by_occupancy() -> None:
    """Von Hand: ein Band mit 90 Fällen und Abstand 0.1, eines mit 10 und 0.5.

    (90*0.1 + 10*0.5) / 100 = (9 + 5) / 100 = 0.14
    """
    bins = [
        Bin(0.0, 0.5, 90, 0.4, 0.3),
        Bin(0.5, 1.0, 10, 0.9, 0.4),
    ]
    assert expected_calibration_error(bins) == pytest.approx(0.14)


def test_expected_calibration_error_refuses_an_empty_sample() -> None:
    with pytest.raises(ValueError, match="Kein belegtes Band"):
        expected_calibration_error([Bin(0.0, 1.0, 0, float("nan"), float("nan"))])


def test_mismatched_lengths_are_an_error_not_a_silent_truncation() -> None:
    with pytest.raises(ValueError, match="gegen"):
        brier_score([0.5, 0.5], [True])
    with pytest.raises(ValueError, match="gegen"):
        log_loss([0.5], [True, False])
