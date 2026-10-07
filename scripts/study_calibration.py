"""Ist die Bewertung kalibriert? Die Frage, die `calibration_proven` blockiert.

    python scripts/study_calibration.py
    python scripts/study_calibration.py --bins 8

`config/risk.yaml` hält jede Risikostufe über einem Prozent gesperrt, solange
`calibration_proven` auf `false` steht. Bis zum 05.10.2026 war das kein
Beschluss, sondern ein Rechenunfall: der Deckel verglich die brauchbaren
Nachbarn **einer** Kerze -- höchstens 120, nach Filterung weniger -- gegen eine
Schwelle von 200. Die Bedingung war an jeder Entscheidung wahr, und der Deckel
hielt durch Arithmetik statt durch Absicht.

Und die Frage dahinter war die falsche. „Diese Kerze hat 200 Lookalikes" ist
eine Aussage über Lokalität, nicht darüber, ob eine Zahl kalibriert ist. Die
richtige Frage lautet: **sagt die gespeicherte Bewertung etwas über den
Ausgang?**

## Warum das jetzt beantwortbar ist, ohne den laufenden Händler anzufassen

Das Journal speichert bei jedem Trade den `reason`-Block, und der entsteht
**vor** dem Ergebnis: `rating` (6 bis 96), `clarity`, `agreement`, `consensus`,
`breadth`. Das sind echte Vorhersage-Felder, nur nie als solche ausgewertet.
Dieses Skript baut daraus `Prediction`/`Resolution`-Paare und rechnet, was
`learn/calibration.py` bereitstellt: Brier, Log-Loss und ein
Reliability-Diagramm **mit Belegung**.

Kein Eingriff in den Vorwärtslauf. Die Alternative wäre, die Felder erst ab
heute aufzuzeichnen und in Monaten zu messen -- und die 2 734 vorhandenen
Trades wegzuwerfen.

## Was eine Bewertung in eine Wahrscheinlichkeit verwandelt, und warum das heikel ist

`rating` ist eine gewichtete Faktorsumme, keine Wahrscheinlichkeit. Sie auf
[0, 1] zu skalieren ist eine Setzung, nicht eine Messung -- und genau deshalb
wird hier **beides** berichtet:

* die **rohe** Skalierung `rating/100`, also die Zahl, die das System heute
  implizit als Zuversicht behandelt, und
* eine **auf dem Trainingsfenster kalibrierte** Variante (Sigmoid), die zeigt,
  wie weit die rohe Zahl daneben liegt.

Kalibriert wird nur auf dem früheren Fenster, gemessen nur auf dem späteren.
Eine Kalibrierung auf allen Daten würde genau die Abweichung wegrechnen, die
sie messen soll.

**Was dieses Skript nicht tut:** es legt `calibration_proven` nicht um. Der
Schalter braucht mehr als einen Brier-Score -- er braucht zeitlich unabhängige
Information, die Unsicherheit der Kalibrierung selbst und die Stabilität genau
jener Schätzung, die das Sizing verwendet. Hier wird gemessen, nicht
entschieden.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.learn.calibration import (
    Prediction,
    PredictionStore,
    Resolution,
    brier_score,
    expected_calibration_error,
    log_loss,
    reliability,
)

JOURNAL = ROOT / "data" / "journal.sqlite"
SCRATCH = ROOT / "data" / "quarantine" / "calibration.sqlite"

#: Zeitlicher Schnitt. Das frühere Fenster kalibriert, das spätere misst.
TRAIN_SHARE = 0.6

#: Der Horizont, bis zu dem ein Label feststeht -- hier der tatsächliche
#: Schliesszeitpunkt des Trades, weil das Journal ihn kennt.
DEFAULT_BINS = 10

#: Ziehungen fuer den gepaarten Brier-Vergleich.
BOOTSTRAP_DRAWS = 5_000

SEED = 20261007


def load_pairs() -> list[tuple[int, float, float, bool, str]]:
    """Zeit, Rohbewertung, Netto-R, Gewinn, Setup -- je Replay-Trade."""
    if not JOURNAL.is_file():
        raise SystemExit(f"Kein Journal unter {JOURNAL}.")
    with sqlite3.connect(JOURNAL) as conn:
        rows = list(
            conn.execute(
                "SELECT opened_ts, closed_ts, r_multiple, payload FROM trades "
                "WHERE source='replay' ORDER BY opened_ts"
            )
        )
    out = []
    for opened, closed, r_multiple, payload in rows:
        reason = (json.loads(payload) or {}).get("reason") or {}
        rating = reason.get("rating")
        if rating is None:
            continue
        out.append(
            (
                int(opened),
                float(rating),
                float(r_multiple),
                float(r_multiple) > 0.0,
                str(reason.get("setup_key", "?")),
                int(closed),
            )
        )
    if not out:
        raise SystemExit("Keine Trades mit gespeicherter Bewertung.")
    return out  # type: ignore[return-value]


def fill_store(records: list) -> PredictionStore:
    """Die Paare in den Speicher, der Vorhersage und Auflösung trennt.

    Der Umweg über den Speicher ist nicht Zierde: er erzwingt, dass jedes
    Vorhersagefeld vor dem Ergebnis gesetzt ist, und er weigert sich, eine
    Auflösung vor dem Label-Ende anzunehmen. Ein Skript, das direkt auf Arrays
    rechnet, könnte beides verletzen, ohne dass es auffällt.
    """
    if SCRATCH.exists():
        SCRATCH.unlink()
    store = PredictionStore(SCRATCH)
    for index, (opened, rating, net_r, won, setup, closed) in enumerate(records):
        store.record(
            Prediction(
                decision_id=f"replay-{index}",
                decision_time=opened,
                symbol="pooled",
                setup_id=setup,
                model_version="rating-as-shipped",
                feature_hash="journal-reason-block",
                calibration_version="raw",
                raw_score=rating,
                predicted_probability=min(max(rating / 100.0, 0.0), 1.0),
                predicted_net_r=0.0,
                predicted_loss_quantile=-1.0,
                expected_cost=0.0,
                decision_taken=True,
                original_risk_chf=10.0,
                label_end_time=closed,
            )
        )
        store.resolve(
            Resolution(
                decision_id=f"replay-{index}",
                resolution_time=closed,
                realized_net_r=net_r,
                realized_cost=0.0,
                realized_win=won,
            )
        )
    return store


def sigmoid_fit(
    scores: np.ndarray, outcomes: np.ndarray, *, steps: int = 600
) -> tuple[float, float]:
    """Platt-Skalierung, auf dem Trainingsfenster. Zwei Parameter, von Hand.

    Sigmoid zuerst und nicht Isotonic: bei dünner Belegung überfittet Isotonic,
    und die Belegung ist hier in den Randbändern dünn -- was das
    Reliability-Diagramm unten zeigt, statt es zu verschweigen.
    """
    x = (scores - scores.mean()) / (scores.std() or 1.0)
    a, b = 0.0, 0.0
    rate = 0.2
    for _ in range(steps):
        p = 1.0 / (1.0 + np.exp(-(a * x + b)))
        error = p - outcomes
        a -= rate * float(np.mean(error * x))
        b -= rate * float(np.mean(error))
    return a, b


def apply_sigmoid(
    scores: np.ndarray, fit: tuple[float, float], reference: np.ndarray
) -> np.ndarray:
    a, b = fit
    x = (scores - reference.mean()) / (reference.std() or 1.0)
    return 1.0 / (1.0 + np.exp(-(a * x + b)))


def report(name: str, probabilities: np.ndarray, outcomes: np.ndarray, *, bins: int) -> None:
    print(f"\n{name}")
    print(f"  Brier      {brier_score(probabilities.tolist(), outcomes.tolist()):.4f}")
    print(f"  Log-Loss   {log_loss(probabilities.tolist(), outcomes.tolist()):.4f}")
    bands = reliability(probabilities.tolist(), outcomes.tolist(), bins=bins)
    print(f"  ECE        {expected_calibration_error(bands):.4f}")
    print(f"\n  {'Band':>12s} {'n':>6s} {'vorhergesagt':>13s} {'beobachtet':>11s} {'Abstand':>9s}")
    for band in bands:
        if band.count == 0:
            continue
        print(
            f"  {band.low:>5.2f}-{band.high:<5.2f} {band.count:>6d} "
            f"{band.mean_predicted:>12.3f} {band.mean_observed:>11.3f} {band.gap:>+9.3f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bins", type=int, default=DEFAULT_BINS)
    args = parser.parse_args()

    records = load_pairs()
    store = fill_store(records)
    pairs = store.matched()
    print("=" * 84)
    print("Ist die gespeicherte Bewertung kalibriert?")
    print("=" * 84)
    print(f"\n{len(pairs):,} Paare aus Vorhersage und Aufloesung, aus dem Replay-Journal.")

    scores = np.array([p.raw_score for p, _ in pairs])
    outcomes = np.array([float(r.realized_win) for _, r in pairs])
    base = float(outcomes.mean())
    cut = int(len(pairs) * TRAIN_SHARE)

    print(
        f"Basisquote (Anteil Gewinner): {100 * base:.2f}%\n"
        f"Bewertung: {scores.min():.0f} bis {scores.max():.0f}, Median {np.median(scores):.0f}\n"
        f"Schnitt auf Zeit: {cut:,} kalibrieren, {len(pairs) - cut:,} messen"
    )

    later_scores, later_outcomes = scores[cut:], outcomes[cut:]

    # Die Zahl, die das System heute implizit als Zuversicht behandelt.
    report(
        "ROH -- rating/100, wie ausgeliefert",
        np.clip(later_scores / 100.0, 0.0, 1.0),
        later_outcomes,
        bins=args.bins,
    )

    # Und was eine Kalibrierung auf dem FRUEHEREN Fenster daraus macht.
    fit = sigmoid_fit(scores[:cut], outcomes[:cut])
    report(
        "KALIBRIERT -- Sigmoid, nur auf dem frueheren Fenster gefittet",
        apply_sigmoid(later_scores, fit, scores[:cut]),
        later_outcomes,
        bins=args.bins,
    )

    # Und die Basisquote als Massstab: ein Modell, das immer sie sagt.
    report(
        "BASISQUOTE -- immer der Anteil Gewinner des frueheren Fensters",
        np.full(later_scores.size, float(outcomes[:cut].mean())),
        later_outcomes,
        bins=args.bins,
    )

    print("\n" + "-" * 84)
    raw = np.clip(later_scores / 100.0, 0.0, 1.0)
    flat = np.full(later_scores.size, float(outcomes[:cut].mean()))
    fitted = apply_sigmoid(later_scores, fit, scores[:cut])
    raw_brier = brier_score(raw.tolist(), later_outcomes.tolist())
    flat_brier = brier_score(flat.tolist(), later_outcomes.tolist())
    fitted_brier = brier_score(fitted.tolist(), later_outcomes.tolist())
    print(
        f"  Brier roh {raw_brier:.4f} | kalibriert {fitted_brier:.4f} "
        f"| Basisquote {flat_brier:.4f}\n"
    )

    # Ein Vergleich zweier Brier-Scores braucht sein Intervall. Eine erste
    # Fassung dieses Skripts erklaerte 0.2246 gegen 0.2247 zum Sieg -- einen
    # Unterschied in der vierten Dezimale, auf 1.094 Faellen. Gepaart
    # gebootstrapt, weil beide Vorhersagen auf DENSELBEN Trades gemessen sind.
    rng = np.random.default_rng(SEED)
    per_case = (fitted - later_outcomes) ** 2 - (flat - later_outcomes) ** 2
    draws = np.array(
        [
            per_case[rng.integers(0, per_case.size, per_case.size)].mean()
            for _ in range(BOOTSTRAP_DRAWS)
        ]
    )
    low, high = (float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5)))
    print(
        f"  Kalibriert minus Basisquote, gepaart: {per_case.mean():+.5f} "
        f"[{low:+.5f}, {high:+.5f}]\n"
        f"  (negativ heisst besser als die Basisquote)"
    )
    if high < 0.0:
        print(
            "\n  Die kalibrierte Bewertung schlaegt die Basisquote belegt. Es steckt\n"
            "  Trennschaerfe in der Zahl -- wie viel, sagt der Abstand, und ob sie\n"
            "  fuers Sizing reicht, sagt dieser Lauf NICHT."
        )
    else:
        print(
            "\n  Die kalibrierte Bewertung ist von der Basisquote NICHT zu trennen.\n"
            "  Nach der Kalibrierung traegt die Zahl also keine Trennschaerfe: sie\n"
            "  sagt dasselbe wie 'immer der Anteil Gewinner'. Ein Sizing, das sich\n"
            "  auf sie stuetzt, stuetzt sich darauf, dass alle Trades gleich sind."
        )
    worst = max(
        (b for b in reliability(raw.tolist(), later_outcomes.tolist(), bins=args.bins) if b.count),
        key=lambda b: abs(b.gap),
    )
    print(
        f"\n  Und die rohe Zahl ist nicht nur ohne Trennschaerfe, sie ist stark\n"
        f"  ueberzuversichtlich: im Band {worst.low:.2f}-{worst.high:.2f} sagt sie\n"
        f"  {worst.mean_predicted:.3f} und beobachtet {worst.mean_observed:.3f}, auf\n"
        f"  {worst.count} Faellen. Das System behandelt diese Zahl heute als Zuversicht."
    )
    print(
        f"\n  Der Abstand zwischen roh und kalibriert ({raw_brier - fitted_brier:+.4f}) misst,\n"
        f"  wie weit `rating/100` von einer Wahrscheinlichkeit entfernt ist.\n"
        f"\n  Zusammen heisst das: der Schalter bleibt nicht aus Datenmangel zu, sondern\n"
        f"  weil in der Zahl, die er freigeben wuerde, nichts steckt. Das ist die\n"
        f"  haertere Aussage -- mehr Faelle wuerden sie nicht aendern.\n"
        f"\n  `calibration_proven` bleibt false. Dieser Lauf misst; er entscheidet nicht.\n"
        f"  Der Schalter braucht zeitlich unabhaengige Information, die Unsicherheit\n"
        f"  der Kalibrierung selbst und die Stabilitaet genau der Schaetzung, die das\n"
        f"  Sizing verwendet -- nicht einen Brier-Score."
    )
    print("-" * 84)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
