"""What "eingefroren" has to mean to be worth saying.

These tests are about the failure mode, not the happy path. A `to_parquet`
call already writes a file. What it does not do is notice when the same key
gets two different answers, or refuse a file whose data state nobody recorded.
Both of those have happened in this project under other names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from traidingbrain.learn.frozen import (
    REQUIRED,
    Frozen,
    FrozenConflictError,
    freeze,
    load,
)

HOUR_MS = 3_600_000


def predictions(*, n: int = 8, net_r: float = 0.4, selected_from: int = 2) -> pd.DataFrame:
    """A small hand-checkable set: `n` decisions, some taken, some refused."""
    return pd.DataFrame(
        {
            "decision_ms": [i * HOUR_MS for i in range(n)],
            "market": ["BTCUSDT"] * n,
            "score": [0.1 * i for i in range(n)],
            "selected": [i >= selected_from for i in range(n)],
            "net_r": [net_r if i % 2 else -0.2 for i in range(n)],
            "label_end_ms": [(i + 12) * HOUR_MS for i in range(n)],
        }
    )


def write(
    frame: pd.DataFrame,
    root: Path,
    *,
    arm: str = "E1.4 logistisch",
    unit: str = "net_r_per_signal",
) -> Frozen:
    return freeze(
        frame,
        root=root,
        experiment="E1",
        arm=arm,
        signature="sig-abc",
        vintage="deadbeefcafe0123",
        horizon_note="12h, label_end_ms je Zeile",
        unit=unit,
    )


def test_a_frozen_set_round_trips_with_its_manifest(tmp_path: Path) -> None:
    frame = predictions()
    written = write(frame, tmp_path)

    back, payload = load(written.path)
    assert len(back) == len(frame)
    assert payload["run_signature"] == "sig-abc"
    assert payload["data_vintage"] == "deadbeefcafe0123"
    assert payload["rows"] == 8
    assert payload["selected"] == 6


def test_the_vintage_is_in_the_filename(tmp_path: Path) -> None:
    """Two data states must not land on the same path at all."""
    written = write(predictions(), tmp_path)
    assert "deadbeefcafe" in written.path.name

    other = freeze(
        predictions(),
        root=tmp_path,
        experiment="E1",
        arm="E1.4 logistisch",
        signature="sig-abc",
        vintage="0000111122223333",
        horizon_note="12h",
        unit="net_r_per_signal",
    )
    assert other.path != written.path
    assert written.path.is_file() and other.path.is_file()


def test_the_same_rows_twice_is_not_an_error(tmp_path: Path) -> None:
    """A rerun that genuinely reproduces must not be punished."""
    first = write(predictions(), tmp_path)
    second = write(predictions(), tmp_path)
    assert first.digest == second.digest
    assert first.path == second.path


def test_a_rerun_refreshes_the_manifest_but_never_the_data(tmp_path: Path) -> None:
    """The two halves are not the same kind of thing.

    The predictions are the measurement and are immutable. The manifest is
    a derived description, and when this module gained its `unit` field the
    manifests already on disk did not get it -- the early return for an
    identical rerun never reached the writing code. A record that silently
    goes stale on an extension is worth as much as none.
    """
    frame = predictions()
    first = write(frame, tmp_path)
    before = frame.to_parquet(index=False)

    # Ein zweiter Lauf mit anderem Begleittext, gleichen Zeilen.
    second = freeze(
        frame,
        root=tmp_path,
        experiment="E1",
        arm="E1.4 logistisch",
        signature="sig-abc",
        vintage="deadbeefcafe0123",
        horizon_note="12h -- Formulierung praezisiert",
        unit="net_r_per_signal",
    )
    assert second.path == first.path
    payload = json.loads(second.manifest.read_text(encoding="utf-8"))
    assert payload["horizon"] == "12h -- Formulierung praezisiert"
    assert pd.read_parquet(second.path).to_parquet(index=False) == before


def test_different_rows_under_the_same_key_are_refused(tmp_path: Path) -> None:
    """The one that matters.

    Same signature, same vintage, different predictions: either the code
    changed without the signature saying so, or the run is not
    deterministic. Overwriting would erase the evidence of both.
    """
    write(predictions(net_r=0.4), tmp_path)
    with pytest.raises(FrozenConflictError) as caught:
        write(predictions(net_r=0.9), tmp_path)

    message = str(caught.value)
    assert "gespeichert" in message and "jetzt" in message, (
        "the conflict must name both digests, or nobody can act on it"
    )


def test_a_parquet_without_a_manifest_is_refused(tmp_path: Path) -> None:
    written = write(predictions(), tmp_path)
    written.manifest.unlink()
    with pytest.raises(ValueError, match="kein Manifest"):
        load(written.path)


def test_editing_a_frozen_file_is_detected(tmp_path: Path) -> None:
    """The manifest's hash is checked on read, not just written."""
    written = write(predictions(), tmp_path)
    tampered = pd.read_parquet(written.path)
    tampered.loc[0, "net_r"] = 99.0
    tampered.to_parquet(written.path, index=False)

    with pytest.raises(FrozenConflictError, match="geaendert"):
        load(written.path)


def test_an_added_diagnostic_column_is_not_a_different_prediction(tmp_path: Path) -> None:
    """The hash covers the required columns, deliberately.

    Adding a column that explains a prediction does not change it, and a
    scheme that said otherwise would make every new diagnostic look like a
    conflict.
    """
    write(predictions(), tmp_path)
    richer = predictions()
    richer["why"] = ["weil"] * len(richer)
    again = write(richer, tmp_path)
    assert again.rows == len(richer)


def test_an_empty_set_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Leere"):
        write(predictions().iloc[0:0], tmp_path)


def test_a_per_signal_arm_that_took_nothing_is_refused(tmp_path: Path) -> None:
    """A file of pure refusals is not an out-of-sample result.

    It has no PnL path to simulate, and recording it as one would put a row
    of zeros into the goal simulation as though it were evidence.
    """
    nothing = predictions()
    nothing["selected"] = False
    with pytest.raises(ValueError, match="keine einzige Entscheidung"):
        write(nothing, tmp_path, unit="net_r_per_signal")


def test_a_per_bar_arm_that_stayed_flat_is_kept(tmp_path: Path) -> None:
    """Staying out all year is a path, and it earns exactly zero.

    E2's hold zone on Ridge does this: the forecast never beats the cost of
    switching, so the arm never enters. That is a finding about the
    forecast, not an empty file -- and the asymmetry with the test above is
    the point, not an exemption.
    """
    flat = predictions()
    flat["selected"] = False
    flat["net_r"] = 0.0
    written = write(flat, tmp_path, arm="E2.2 Haltezone", unit="net_return_per_bar")

    payload = json.loads(written.manifest.read_text(encoding="utf-8"))
    assert payload["selected"] == 0
    assert payload["rows"] == len(flat)

    back, _ = load(written.path)
    assert float(back["net_r"].sum()) == 0.0


@pytest.mark.parametrize("column", REQUIRED)
def test_every_required_column_is_actually_required(tmp_path: Path, column: str) -> None:
    with pytest.raises(ValueError, match="brauchen"):
        write(predictions().drop(columns=[column]), tmp_path)


def test_the_manifest_records_the_refused_rows_too(tmp_path: Path) -> None:
    """Per signal, not per winner -- the order's wording, made checkable."""
    written = write(predictions(n=10, selected_from=7), tmp_path)
    payload = json.loads(written.manifest.read_text(encoding="utf-8"))
    assert payload["rows"] == 10
    assert payload["selected"] == 3
    assert "nicht je ausgefuehrtem Trade" in str(payload["per_row_meaning"])


def test_the_unit_must_be_declared_and_must_be_a_known_one(tmp_path: Path) -> None:
    """No default. An R-multiple and a per-candle return are different things.

    They share a column name here for one reason -- a common reader -- and
    that is exactly the circumstance in which somebody concatenates them.
    """
    with pytest.raises(ValueError, match="nicht angemeldet"):
        write(predictions(), tmp_path, unit="irgendwas")


def test_the_manifest_states_what_the_number_means(tmp_path: Path) -> None:
    per_signal = write(predictions(), tmp_path, arm="E1.4", unit="net_r_per_signal")
    per_bar = write(predictions(), tmp_path, arm="E2.1", unit="net_return_per_bar")

    first = json.loads(per_signal.manifest.read_text(encoding="utf-8"))
    second = json.loads(per_bar.manifest.read_text(encoding="utf-8"))

    assert first["unit"] != second["unit"]
    assert "R-Vielfaches" in str(first["unit_meaning"])
    assert "NICHT R" in str(second["unit_meaning"])


def test_the_manifest_carries_the_label_horizon(tmp_path: Path) -> None:
    """So a reader can check the purge themselves instead of trusting prose."""
    frame = predictions(n=5)
    written = write(frame, tmp_path)
    payload = json.loads(written.manifest.read_text(encoding="utf-8"))
    assert payload["decision_ms_last"] == 4 * HOUR_MS
    assert payload["label_end_ms_last"] == 16 * HOUR_MS
    assert payload["label_end_ms_last"] > payload["decision_ms_last"], (
        "a label that ends before its decision would be a leak"
    )
