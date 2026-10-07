"""Was vor dem Ergebnis vorhergesagt wurde, und was daraus wurde -- getrennt.

Dieses Modul beantwortet eine Frage, die das Projekt seit Tagen offen hat und
nicht beantworten kann: **ist die Confidence-Zahl kalibriert?**

`config/risk.yaml` hält jede Risikostufe über einem Prozent gesperrt, solange
`calibration_proven` auf `false` steht. Bis zum 05.10.2026 war das kein
Beschluss, sondern ein Rechenunfall: Der Deckel verglich
`similar_situations_found` -- die brauchbaren Nachbarn *einer* Kerze, höchstens
`k_neighbours` (120) und nach Filterung weniger -- gegen eine Schwelle von 200.
Die Bedingung war also an jeder Entscheidung wahr, und der Deckel hielt durch
Arithmetik statt durch Absicht.

Und die Frage dahinter ist die falsche: "diese Kerze hat 200 Lookalikes" ist
eine Aussage über Lokalität, nicht darüber, ob eine Wahrscheinlichkeit
kalibriert ist. Beantwortbar wird sie erst, wenn **je Entscheidung** die
Vorhersage gespeichert ist und später, getrennt davon, ihre Auflösung.
`history.index.Case` trägt fünf Felder -- Fingerprint, Zeiten, Ergebnis,
Symbol -- und keines davon ist eine Vorhersage. Das ist die Lücke.

## Warum zwei Datensätze und nicht einer mit nachgetragenen Spalten

Der Forschungsauftrag verlangt: *"Pre-Outcome-Werte unveränderlich speichern.
Prediction und spätere Auflösung sind getrennte Versionen."*

Ein Datensatz mit nachgetragenen Ergebnisspalten erfüllt das nur, solange sich
alle daran halten. Zwei Tabellen erfüllen es strukturell: `record()` schreibt
eine Vorhersage und **weigert sich**, eine vorhandene zu überschreiben;
`resolve()` schreibt eine Auflösung und kann die Vorhersage nicht erreichen.
Das Projekt hat genau diesen Fehler schon gemacht -- `journal/store.py` machte
ein Upsert, sodass ein erneuter Replay die gespeicherte Begründung still
überschrieb, was der Auftrag ausdrücklich verbietet.

## Was die Kalibrierungsprobe umfasst

**Alle** prognostizierten Fälle, nicht nur die, die am Ende gehandelt wurden.
Eine abgelehnte Vorhersage ist eine Vorhersage: wird sie weggelassen, misst man
die Kalibrierung auf einer Teilmenge, die die Entscheidungsregel ausgewählt hat
-- und die Regel hat genau die Fälle genommen, bei denen sie sich sicher war.

Darum trägt `Prediction` auch `decision_taken` und `rejection_reason`: die
Ablehnung ist Teil der Probe und nicht ihr Ausschluss.

## Was hier absichtlich NICHT entschieden wird

Die Schwelle "200 Nachbarn" wird nicht durch eine andere magische Zahl ersetzt.
Ob `calibration_proven` aufgeht, entscheidet nicht eine Fallzahl, sondern
zeitlich unabhängige Information, die Unsicherheit der Kalibrierung selbst und
die Stabilität genau jener Schätzung, die das Sizing verwendet. Dieses Modul
stellt die Messgrössen bereit; den Schalter legt es nicht um.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    decision_id            TEXT    NOT NULL PRIMARY KEY,
    decision_time          INTEGER NOT NULL,
    symbol                 TEXT    NOT NULL,
    setup_id               TEXT    NOT NULL,
    model_version          TEXT    NOT NULL,
    feature_hash           TEXT    NOT NULL,
    calibration_version    TEXT    NOT NULL,
    raw_score              REAL    NOT NULL,
    predicted_probability  REAL    NOT NULL,
    predicted_net_r        REAL    NOT NULL,
    predicted_loss_quantile REAL   NOT NULL,
    expected_cost          REAL    NOT NULL,
    decision_taken         INTEGER NOT NULL,
    rejection_reason       TEXT,
    original_risk_chf      REAL    NOT NULL,
    label_end_time         INTEGER NOT NULL,
    extra                  TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS resolutions (
    decision_id     TEXT    NOT NULL PRIMARY KEY,
    resolution_time INTEGER NOT NULL,
    realized_net_r  REAL    NOT NULL,
    realized_cost   REAL    NOT NULL,
    realized_win    INTEGER NOT NULL,
    note            TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS predictions_by_time ON predictions (decision_time);
"""


class AlreadyPredictedError(ValueError):
    """Eine Vorhersage existiert und wird nicht überschrieben.

    Eigene Klasse, weil der Aufrufer diesen Fall abfangen und als "schon
    aufgezeichnet" behandeln darf, während jeder andere `ValueError` hier ein
    Programmierfehler ist.
    """


class NotPredictedError(ValueError):
    """Eine Auflösung ohne vorherige Vorhersage. Das wäre Rückschau."""


@dataclass(frozen=True, slots=True)
class Prediction:
    """Was zum Entscheidungszeitpunkt bekannt war. Unveränderlich.

    Kein Feld hier darf nach dem Ergebnis gesetzt oder geändert werden. Wer ein
    Ergebnisfeld braucht, schreibt eine `Resolution`.
    """

    decision_id: str
    decision_time: int
    symbol: str
    setup_id: str
    model_version: str
    feature_hash: str
    calibration_version: str
    raw_score: float
    predicted_probability: float
    predicted_net_r: float
    predicted_loss_quantile: float
    expected_cost: float
    decision_taken: bool
    original_risk_chf: float
    label_end_time: int
    rejection_reason: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.predicted_probability <= 1.0:
            raise ValueError(
                f"predicted_probability={self.predicted_probability} liegt ausserhalb [0,1]. "
                "Ein Rohscore ist keine Wahrscheinlichkeit; dafuer ist raw_score da."
            )
        if self.label_end_time < self.decision_time:
            raise ValueError(
                "label_end_time liegt vor decision_time -- ein Label kann nicht "
                "feststehen, bevor entschieden wurde."
            )
        if self.decision_taken and self.rejection_reason:
            raise ValueError("Ein genommener Trade hat keinen Ablehnungsgrund.")
        if not self.decision_taken and not self.rejection_reason:
            raise ValueError(
                "Eine Ablehnung ohne Grund ist der Zustand, aus dem dieses Projekt "
                "schon einmal tausend Ablehnungen und keine Erkenntnis hatte."
            )


@dataclass(frozen=True, slots=True)
class Resolution:
    """Was daraus wurde. Wird später geschrieben und berührt die Vorhersage nicht."""

    decision_id: str
    resolution_time: int
    realized_net_r: float
    realized_cost: float
    realized_win: bool
    note: str = ""


class PredictionStore:
    """Vorhersagen und Auflösungen auf Platte, getrennt und append-only."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- schreiben ---------------------------------------------------------- #

    def record(self, prediction: Prediction) -> None:
        """Eine Vorhersage aufzeichnen. Überschreibt nie.

        Ein zweiter Aufruf mit derselben `decision_id` ist ein Fehler und kein
        stilles Update: zwei verschiedene Vorhersagen für eine Entscheidung
        heissen, dass eine davon das Ergebnis kannte.
        """
        row = asdict(prediction)
        row["decision_taken"] = int(prediction.decision_taken)
        row["extra"] = json.dumps(prediction.extra, ensure_ascii=False, sort_keys=True)
        columns = ", ".join(row)
        marks = ", ".join(":" + key for key in row)
        with closing(self._connect()) as conn:
            try:
                conn.execute(f"INSERT INTO predictions ({columns}) VALUES ({marks})", row)
            except sqlite3.IntegrityError as clash:
                raise AlreadyPredictedError(
                    f"{prediction.decision_id} ist schon vorhergesagt. Eine Vorhersage "
                    f"wird nicht ueberschrieben."
                ) from clash
            conn.commit()

    def resolve(self, resolution: Resolution) -> None:
        """Eine Auflösung aufzeichnen. Verlangt eine vorhandene Vorhersage.

        Und sie muss **nach** dem Label-Ende liegen. Eine Auflösung davor wäre
        ein Ergebnis, das noch nicht existiert.
        """
        with closing(self._connect()) as conn:
            found = conn.execute(
                "SELECT label_end_time FROM predictions WHERE decision_id = ?",
                (resolution.decision_id,),
            ).fetchone()
            if found is None:
                raise NotPredictedError(
                    f"{resolution.decision_id} hat keine Vorhersage. Ein Ergebnis ohne "
                    f"vorher aufgezeichnete Erwartung ist Rueckschau."
                )
            if resolution.resolution_time < int(found[0]):
                raise ValueError(
                    f"{resolution.decision_id} wird um {int(found[0]) - resolution.resolution_time}"
                    f" ms vor seinem Label-Ende aufgeloest."
                )
            row = asdict(resolution)
            row["realized_win"] = int(resolution.realized_win)
            columns = ", ".join(row)
            marks = ", ".join(":" + key for key in row)
            conn.execute(
                f"INSERT OR REPLACE INTO resolutions ({columns}) VALUES ({marks})", row
            )
            conn.commit()

    # -- lesen -------------------------------------------------------------- #

    def predictions(self, *, until_ms: int | None = None) -> list[Prediction]:
        query = "SELECT * FROM predictions"
        params: tuple[int, ...] = ()
        if until_ms is not None:
            query += " WHERE decision_time <= ?"
            params = (until_ms,)
        query += " ORDER BY decision_time"
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [_as_prediction(row) for row in rows]

    def matched(self, *, taken_only: bool = False) -> list[tuple[Prediction, Resolution]]:
        """Paare aus Vorhersage und Auflösung.

        `taken_only` ist vorhanden und steht per Voreinstellung auf `False`,
        weil die Kalibrierungsprobe **alle** prognostizierten Fälle umfasst.
        Nur die genommenen zu messen heisst, die Kalibrierung auf einer
        Teilmenge zu messen, die die Entscheidungsregel ausgewaehlt hat.
        """
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT p.*, r.resolution_time, r.realized_net_r, r.realized_cost, "
                "r.realized_win, r.note FROM predictions p "
                "JOIN resolutions r ON r.decision_id = p.decision_id "
                + ("WHERE p.decision_taken = 1 " if taken_only else "")
                + "ORDER BY p.decision_time"
            ).fetchall()
        return [
            (
                _as_prediction(row),
                Resolution(
                    decision_id=row["decision_id"],
                    resolution_time=row["resolution_time"],
                    realized_net_r=row["realized_net_r"],
                    realized_cost=row["realized_cost"],
                    realized_win=bool(row["realized_win"]),
                    note=row["note"],
                ),
            )
            for row in rows
        ]


def _as_prediction(row: sqlite3.Row) -> Prediction:
    """Eine Zeile zurück in den Datensatz, ohne die Ergebnisspalten.

    Eine eigene Funktion, weil beide Leser sie brauchen und weil die Liste der
    *auszulassenden* Spalten der Ort ist, an dem ein Ergebnisfeld versehentlich
    in eine Vorhersage wandern würde. `row.keys()` ist hier richtig und nicht
    das von ruff vorgeschlagene `in row`: über eine `sqlite3.Row` zu iterieren
    liefert die Werte, nicht die Spaltennamen.
    """
    skip = {
        "decision_taken",
        "extra",
        "resolution_time",
        "realized_net_r",
        "realized_cost",
        "realized_win",
        "note",
    }
    fields = {key: row[key] for key in row.keys() if key not in skip}  # noqa: SIM118
    return Prediction(
        **fields,
        decision_taken=bool(row["decision_taken"]),
        extra=json.loads(row["extra"]),
    )


# -- Kennzahlen ------------------------------------------------------------- #


def brier_score(probabilities: Sequence[float], outcomes: Sequence[bool]) -> float:
    """Mittlerer quadratischer Fehler der Wahrscheinlichkeit. Kleiner ist besser.

    Allein nicht interpretierbar: ein Modell, das immer die Basisrate sagt,
    erreicht einen anständigen Brier-Score ohne jede Trennschärfe. Darum steht
    `reliability` daneben und nicht darunter.
    """
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.size != y.size or p.size == 0:
        raise ValueError(f"{p.size} Wahrscheinlichkeiten gegen {y.size} Ergebnisse")
    return float(np.mean((p - y) ** 2))


def log_loss(
    probabilities: Sequence[float], outcomes: Sequence[bool], *, floor: float = 1e-9
) -> float:
    """Log-Loss, mit abgeschnittenen Extremen.

    `floor` ist nötig, weil eine Vorhersage von genau 0 oder 1, die falsch
    liegt, sonst unendlich kostet und die Kennzahl von einem einzigen Fall
    bestimmt wird.
    """
    p = np.clip(np.asarray(probabilities, dtype=float), floor, 1.0 - floor)
    y = np.asarray(outcomes, dtype=float)
    if p.size != y.size or p.size == 0:
        raise ValueError(f"{p.size} Wahrscheinlichkeiten gegen {y.size} Ergebnisse")
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


@dataclass(frozen=True, slots=True)
class Bin:
    """Ein Band des Reliability-Diagramms, mit seiner Belegung.

    Die Belegung gehört dazu. Ein Band mit drei Fällen, das perfekt kalibriert
    aussieht, sagt nichts -- und ohne `count` daneben sieht man das nicht.
    """

    low: float
    high: float
    count: int
    mean_predicted: float
    mean_observed: float

    @property
    def gap(self) -> float:
        return self.mean_predicted - self.mean_observed


def reliability(
    probabilities: Sequence[float], outcomes: Sequence[bool], *, bins: int = 10
) -> list[Bin]:
    """Vorhergesagt gegen beobachtet, in Bändern, mit Belegung."""
    p = np.asarray(probabilities, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    if p.size != y.size:
        raise ValueError(f"{p.size} Wahrscheinlichkeiten gegen {y.size} Ergebnisse")
    edges = np.linspace(0.0, 1.0, bins + 1)
    out: list[Bin] = []
    for low, high in pairwise(edges):
        # Das letzte Band schliesst oben ein, sonst fiele p == 1.0 heraus.
        inside = (p >= low) & (p < high) if high < 1.0 else (p >= low) & (p <= high)
        if not inside.any():
            out.append(Bin(float(low), float(high), 0, float("nan"), float("nan")))
            continue
        out.append(
            Bin(
                float(low),
                float(high),
                int(inside.sum()),
                float(p[inside].mean()),
                float(y[inside].mean()),
            )
        )
    return out


def expected_calibration_error(bins: Iterable[Bin]) -> float:
    """Nach Belegung gewichteter mittlerer Abstand zwischen Vorhersage und Beobachtung."""
    populated = [b for b in bins if b.count > 0]
    total = sum(b.count for b in populated)
    if not total:
        raise ValueError("Kein belegtes Band -- nichts zu messen.")
    return float(sum(b.count * abs(b.gap) for b in populated) / total)
