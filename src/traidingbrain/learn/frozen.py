"""Out-of-sample predictions, written once and then immutable.

The research order asks for the goal simulation to run on "nur eingefrorene,
zeitpunktkorrekte Out-of-Sample-Predictions und deren Order-/PnL-Pfade". Both
words in "eingefroren" carry weight, and a file is not frozen because it is
called frozen.

**Why this is a module and not a `to_parquet` call.** E1 and E2 computed their
predictions, printed a verdict, and dropped them. Re-running after any change
to the data produced a different answer with no way to tell. That is the shape
of the failure this project keeps finding: not a wrong number, a number whose
provenance has evaporated.

Three properties, each one a thing that went wrong somewhere before:

*One row per decision, not per executed trade.* The order is explicit --
"erwarteter Netto-PnL pro Signal", not per winner. A file holding only the
trades an arm took cannot answer what the arm cost when it was wrong to enter,
and a later reader cannot tell the difference.

*Overwriting is refused, not silently accepted.* A second run under a
different data vintage writes a different file, because the name carries the
fingerprint. A second run under the SAME vintage that produces different rows
raises: either the code changed without the signature changing, or something
is nondeterministic. Both are findings, and both used to be invisible.

*The manifest says what it cannot answer.* `label_end_ms` per row, so a reader
can check the horizon themselves rather than trusting a sentence. And the
vintage of the data, so a restated source cannot quietly reinterpret a frozen
result -- the gap `learn/panel.py::source_fingerprint` exists to close.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

#: Columns every frozen file carries, in this order. A reader that knows this
#: list can consume any experiment's output without special-casing.
REQUIRED: tuple[str, ...] = (
    "decision_ms",
    "market",
    "score",
    "selected",
    "net_r",
    "label_end_ms",
)


#: What the `net_r` column may mean, named rather than assumed.
#:
#: Two frozen sets under different units must not be concatenated, averaged
#: or bootstrapped together. An R-multiple is a result divided by the risk
#: taken; a per-candle return is not divided by anything. Pooling them
#: produces a number with no unit at all, which is the kind of thing that
#: reads as a result.
UNITS: dict[str, str] = {
    "net_r_per_signal": (
        "R-Vielfaches je Signal: Ergebnis geteilt durch den Stop-Abstand, "
        "Kosten und Funding abgezogen. Eine Zeile ist eine Entscheidung."
    ),
    "net_return_per_bar": (
        "Netto-Rendite je Kerze in Preisanteilen, NICHT R. Keine Division "
        "durch ein Risiko, also mit R-Vielfachen nicht vergleichbar und "
        "nicht poolbar. Eine Zeile ist eine Kerze."
    ),
    "net_chf_per_trade": (
        "Ergebnis in CHF je Trade. Traegt die Kapitalbindung, die R "
        "wegkuerzt."
    ),
}


class FrozenConflictError(RuntimeError):
    """A file exists for this exact key and its contents differ."""


@dataclass(frozen=True, slots=True)
class Frozen:
    """A written set of predictions and where it landed."""

    path: Path
    manifest: Path
    rows: int
    digest: str

    def describe(self) -> str:
        return f"{self.path.name}: {self.rows:,} Entscheidungen, sha256 {self.digest[:16]}"


def _digest(frame: pd.DataFrame) -> str:
    """Content hash over the required columns in a fixed order.

    Deliberately not over the whole frame: an experiment may add its own
    columns, and a new diagnostic column is not a different prediction.
    """
    ordered = frame.loc[:, list(REQUIRED)].sort_values(["decision_ms", "market"])
    rows = pd.util.hash_pandas_object(ordered, index=False)
    return hashlib.sha256(rows.to_numpy().tobytes()).hexdigest()


def freeze(
    frame: pd.DataFrame,
    *,
    root: Path,
    experiment: str,
    arm: str,
    signature: str,
    vintage: str,
    horizon_note: str,
    unit: str,
    extra: dict[str, object] | None = None,
) -> Frozen:
    """Write one arm's out-of-sample predictions, refusing to disagree.

    `vintage` is the data state the predictions were computed from --
    `Panel.vintage_id`, or an equivalent fingerprint when the source is the
    ledger rather than a panel. It goes into the filename, so two vintages
    cannot collide, and into the manifest, so neither can be read without it.

    `unit` says what the `net_r` column actually holds, and it has no default
    on purpose. E1 writes R-multiples per signal; E2 writes a net return per
    candle in price fractions. Those are different quantities, and a column
    name they happen to share is not a reason to pool them -- the order's own
    rule says two strategies with different stops are not economically
    identical just because their R agrees. One of `UNITS`.
    """
    if unit not in UNITS:
        raise ValueError(f"Einheit '{unit}' ist nicht angemeldet. Erlaubt: {sorted(UNITS)}")
    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        raise ValueError(f"Eingefrorene Predictions brauchen {missing} -- nicht vorhanden.")
    if frame.empty:
        raise ValueError("Leere Prediction-Menge wird nicht eingefroren.")

    selected = frame["selected"].astype(bool)
    if not selected.any() and unit == "net_r_per_signal":
        raise ValueError(
            f"Arm '{arm}' hat keine einzige Entscheidung genommen.\n"
            f"Je Signal heisst eine Zeile: dieses Signal gesehen, abgelehnt. Ein Arm,\n"
            f"der jedes ablehnt, hat kein Ergebnis -- es gibt keinen Pfad zu simulieren,\n"
            f"und eine Reihe Nullen in die Zielsimulation zu legen waere eine erfundene\n"
            f"Beobachtung.\n"
            f"Je Kerze ({'net_return_per_bar'}) ist das anders: dauerhaft flach IST ein\n"
            f"Pfad, der genau null verdient, und wird eingefroren."
        )

    digest = _digest(frame)
    folder = root / experiment
    folder.mkdir(parents=True, exist_ok=True)
    safe_arm = arm.replace(" ", "_").replace("/", "-")
    target = folder / f"{safe_arm}-{vintage[:12]}.parquet"
    manifest = target.with_suffix(".json")

    if target.is_file():
        previous = _digest(pd.read_parquet(target))
        if previous != digest:
            raise FrozenConflictError(
                f"{target.name} liegt schon da und sagt etwas anderes.\n"
                f"  gespeichert {previous[:16]}\n"
                f"  jetzt       {digest[:16]}\n"
                f"Gleicher Datenstand, andere Predictions: entweder hat sich der Code\n"
                f"geaendert ohne dass die Signatur es sagt, oder der Lauf ist nicht\n"
                f"deterministisch. Beides ist ein Befund, keine Datei zum Ueberschreiben."
            )
    else:
        frame.to_parquet(target, index=False)

    # Das Manifest wird IMMER neu geschrieben, die Parquet-Datei nie. Der
    # Unterschied ist, was die beiden sind: die Predictions sind die
    # Messung, das Manifest ist die abgeleitete Beschreibung. Als dieses
    # Modul `unit` bekam, trugen die schon geschriebenen Manifeste das Feld
    # nicht -- und der Rueckgabepfad fuer einen identischen Lauf kam gar
    # nicht bis hierher. Ein Nachweis, der bei einer Erweiterung still
    # veraltet, ist genau so wertlos wie keiner.
    payload: dict[str, object] = {
        "experiment": experiment,
        "arm": arm,
        "run_signature": signature,
        "data_vintage": vintage,
        "sha256": digest,
        "rows": len(frame),
        "selected": int(selected.sum()),
        "markets": sorted(str(m) for m in frame["market"].unique()),
        "decision_ms_first": int(frame["decision_ms"].min()),
        "decision_ms_last": int(frame["decision_ms"].max()),
        "label_end_ms_last": int(frame["label_end_ms"].max()),
        "horizon": horizon_note,
        "unit": unit,
        "unit_meaning": UNITS[unit],
        "per_row_meaning": (
            "Eine Zeile je ENTSCHEIDUNG, nicht je ausgefuehrtem Trade. "
            "selected=False heisst: der Arm hat dieses Signal gesehen und "
            "abgelehnt. net_r ist das Ergebnis, das er bekommen haette."
        ),
    }
    if extra:
        payload |= extra
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    return Frozen(path=target, manifest=manifest, rows=len(frame), digest=digest)


def load(path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """A frozen set and its manifest, refusing a set without one.

    An unaccompanied parquet file is exactly the thing this module exists to
    prevent: numbers whose data state nobody recorded.
    """
    manifest = path.with_suffix(".json")
    if not manifest.is_file():
        raise ValueError(
            f"{path.name} hat kein Manifest. Ohne Datenstand und Signatur ist eine\n"
            f"Prediction-Menge nicht verwendbar -- sie koennte aus allem gebaut sein."
        )
    frame = pd.read_parquet(path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    stored = str(payload.get("sha256", ""))
    actual = _digest(frame)
    if stored != actual:
        raise FrozenConflictError(
            f"{path.name} wurde nach dem Einfrieren geaendert.\n"
            f"  Manifest {stored[:16]}\n"
            f"  Datei    {actual[:16]}"
        )
    return frame, payload
