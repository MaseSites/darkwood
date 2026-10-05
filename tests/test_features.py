"""Can anything the model sees have come from the outcome?

The answer has to be no by construction, not by review. `row` takes a
`SignalRecord`, which is written before the market answers and has no outcome
field, so there is nothing to leak. `test_the_feature_row_cannot_see_an_outcome`
checks that the record type really is that shape, because the guarantee is only
worth what the type is worth.

The rest pins the two encodings that would otherwise be quietly wrong: the hour
as a cycle rather than a line, and the setup columns fixed rather than
discovered per fold.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import numpy as np
import pytest

from traidingbrain.domain.enums import Rule, Side
from traidingbrain.journal.record import Source
from traidingbrain.journal.signals import Action, SignalRecord
from traidingbrain.learn.features import NAMES, SETUPS, matrix, row

EPOCH = 1_600_000_000_000


def record(**overrides: object) -> SignalRecord:
    defaults: dict[str, object] = {
        "signal_id": "BTCUSDT-1-A",
        "run_signature": "test",
        "decided_ts": EPOCH,
        "symbol": "BTCUSDT",
        "source": Source.REPLAY,
        "action": Action.TAKEN,
        "refused_by": None,
        "detail": "",
        "setup_key": "A",
        "setup_timeframe": "",
        "signal_timeframe": "M15",
        "side": Side.LONG,
        "entry": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "reward_risk": 2.0,
        "cost_fraction": 0.08,
        "risk_amount": 10.0,
        "qty": 5.0,
        "leverage": 5.0,
    }
    return SignalRecord(**(defaults | overrides))  # type: ignore[arg-type]


def value(name: str, item: SignalRecord) -> float:
    return row(item)[NAMES.index(name)]


# --------------------------------------------------------------------------- #
# The guarantee
# --------------------------------------------------------------------------- #


def test_the_feature_row_cannot_see_an_outcome() -> None:
    """The record type has nowhere to put one, so the function cannot read one.

    This is the same kind of structural argument as the scale invariance in the
    labeller: not "we were careful", but "there is no path". If an outcome field
    is ever added to SignalRecord, this fails and somebody has to think.
    """
    fields = {field.name for field in dataclasses.fields(SignalRecord)}
    outcome_shaped = {
        "gross_r",
        "net_r",
        "r_multiple",
        "exit_price",
        "exit_reason",
        "barrier",
        "fees",
        "won",
        "pnl",
        "closed_ts",
        "minutes_held",
    }
    assert not (fields & outcome_shaped), (
        f"an outcome reached the feature source: {fields & outcome_shaped}"
    )


def test_the_realised_cost_is_not_among_the_features() -> None:
    """The 04.10.2026 near-miss, pinned.

    `cost_fraction` is the planned estimate from the risk layer. A realised fee
    would encode which door the trade left through, and "winners had lower
    costs" would come back as a finding worth +0.65 R.
    """
    assert "kosten_anteil" in NAMES
    planned = record(cost_fraction=0.08)
    assert value("kosten_anteil", planned) == pytest.approx(0.08)
    # Two signals identical except for their eventual outcome cannot differ,
    # because there is no outcome to differ by.
    assert row(planned) == row(record(cost_fraction=0.08, detail="egal"))


def test_account_sized_quantities_stay_out() -> None:
    """Position size and risk in francs are the account's state, not the market's.

    Including them would make a model fitted at a thousand francs of equity
    inapplicable at two thousand, and would let the walk-forward learn the
    account's growth curve instead of the signals.
    """
    assert "risiko_betrag" not in NAMES
    assert "menge" not in NAMES
    big = record(risk_amount=1_000.0, qty=500.0)
    assert row(big) == row(record())


# --------------------------------------------------------------------------- #
# Encodings
# --------------------------------------------------------------------------- #


def test_the_hour_is_a_cycle_not_a_line() -> None:
    """Midnight and 23:00 are an hour apart, not at opposite ends of a scale.

    A raw hour column lets a linear model say only "later is better", which is
    the one shape a daily rhythm cannot have.
    """
    day = 86_400_000
    midnight = record(decided_ts=EPOCH - EPOCH % day)
    late = record(decided_ts=midnight.decided_ts + 23 * 3_600_000)
    noon = record(decided_ts=midnight.decided_ts + 12 * 3_600_000)

    def point(item: SignalRecord) -> np.ndarray:
        return np.array([value("stunde_sin", item), value("stunde_cos", item)])

    near = float(np.linalg.norm(point(midnight) - point(late)))
    far = float(np.linalg.norm(point(midnight) - point(noon)))
    assert near < far, "23:00 is further from midnight than noon is"
    assert far == pytest.approx(2.0), "noon should be diametrically opposite"
    # And both components stay on the unit circle.
    assert np.linalg.norm(point(noon)) == pytest.approx(1.0)


def test_the_hour_is_read_in_utc() -> None:
    """One timezone, stated. The journal's hours are UTC and so are these."""
    stamp = datetime(2026, 10, 5, 7, 30, tzinfo=UTC)
    item = record(decided_ts=int(stamp.timestamp() * 1000))
    angle = 2.0 * np.pi * 7 / 24.0
    assert value("stunde_sin", item) == pytest.approx(float(np.sin(angle)))


def test_the_setup_columns_are_fixed_not_discovered() -> None:
    """Every fold must have the same columns, or the coefficients differ in meaning.

    Discovering the setups from each window would drop a column whenever a rare
    setup did not fire, and two folds' weights would stop being comparable.
    """
    assert len(matrix([record(setup_key="A")])[0]) == len(NAMES)
    only_g = matrix([record(setup_key="G")])
    assert only_g.shape[1] == len(NAMES)
    assert value("setup_G", record(setup_key="G")) == 1.0
    assert value("setup_A", record(setup_key="G")) == 0.0
    # Exactly one setup column is ever hot.
    hot = [value(f"setup_{key}", record(setup_key="B")) for key in SETUPS]
    assert sum(hot) == 1.0


def test_an_unknown_setup_is_all_zeros_rather_than_an_error() -> None:
    """A setup added to the guide later must not crash a study of old data."""
    hot = [value(f"setup_{key}", record(setup_key="Z")) for key in SETUPS]
    assert sum(hot) == 0.0


def test_side_is_an_indicator() -> None:
    assert value("long", record(side=Side.LONG)) == 1.0
    assert value("long", record(side=Side.SHORT)) == 0.0


def test_the_stop_distance_is_a_percentage_of_price() -> None:
    """So a thousand-dollar market and a ten-cent one are comparable."""
    small = record(entry=100.0, stop=98.0)
    big = record(entry=100_000.0, stop=98_000.0)
    assert value("stopweite_pct", small) == pytest.approx(2.0)
    assert value("stopweite_pct", big) == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def test_the_matrix_matches_the_names() -> None:
    rows = matrix([record(), record(setup_key="B"), record(side=Side.SHORT)])
    assert rows.shape == (3, len(NAMES))
    assert rows.dtype == np.dtype("float64")
    assert np.all(np.isfinite(rows))


def test_no_signals_gives_an_empty_matrix_of_the_right_width() -> None:
    """A fold with nothing in it must not change the feature space."""
    empty = matrix([])
    assert empty.shape == (0, len(NAMES))


def test_the_refusing_rule_is_not_a_feature() -> None:
    """It is a function of the other features, and a study of whether a rule
    earns its place must not hand the rule's own verdict to the model."""
    assert not any("regel" in name or "refused" in name for name in NAMES)
    assert row(record(refused_by=Rule.COSTS, action=Action.REFUSED)) == row(record())
