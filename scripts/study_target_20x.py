"""Wie wahrscheinlich sind 20 000 CHF aus 1 000 -- und wie wahrscheinlich der Ruin?

    python scripts/study_target_20x.py
    python scripts/study_target_20x.py --paths 20000
    python scripts/study_target_20x.py --source forward

Das Ziel ist 1 000 CHF auf 20 000 CHF in sechs Monaten. Ein Backtest, der das
einmal schafft, beantwortet die Frage nicht -- er ist ein Pfad aus einer
Verteilung, und wer ihn zeigt, hat ihn ausgewählt. Dieses Skript rechnet die
Verteilung und stellt die **Zielchance neben die Verlustchance**, wie der
Forschungsauftrag es in Abschnitt 12 verlangt.

## Woraus gezogen wird

Aus den gemessenen R-Werten des Journals, in Wochenblöcken. Replay und
Vorwärts werden **nie** in einen Pool geworfen -- `--source` wählt eine Quelle,
und beide Läufe stehen getrennt im Bericht. Ein Replay-Trade kennt sein Fenster
im Nachhinein, ein Vorwärts-Trade nicht, und ein Mittelwert über beide ist
keine Grösse.

## Was das Skript ausdrücklich nicht tut

**Es erfindet keinen Vorteil.** Die gemessene Verteilung hat ein negatives
Mittel (-0,0906 R im Replay). Szenarien mit positivem Vorteil heissen
`edge_shift` und sind **Hypothesen** -- sie stehen im Bericht als
"modellbedingt" und tragen den unterstellten Wert im Namen. Kein Szenario wird
auf die Zielerreichung optimiert; das wäre die Zielzahl als Parameter zu
maximieren, und der Auftrag verbietet es zu Recht.

**Es behauptet keine Wahrscheinlichkeit über die Zukunft.** 20 000 synthetische
Pfade sind nicht 20 000 neue Marktphasen. Das Monte-Carlo-Intervall deckt die
Ziehunsicherheit, nicht die Modellunsicherheit. Jede Zahl unten ist
**modellbedingt**, bis Vorwärtsdaten sie stützen -- und davon gibt es acht.

## Einheiten, mit Absicht geprüft

`stop_distance_pct` im Journal steht in **Prozent** (Median 1,309), nicht als
Anteil. Für die Hebelrechnung ist der Anteil nötig, also wird durch 100
geteilt -- und danach geprüft, dass das Ergebnis in einem plausiblen Band liegt.
Dieselbe Klasse Fehler hat in diesem Projekt schon eine Vergleichsgrösse still
auf null gesetzt (Millisekunden als Kilosekunden gelesen), und sie fällt nur
auf, wenn jemand sie prüft.
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

from traidingbrain.learn.frozen import load as frozen_load
from traidingbrain.learn.goalsim import (
    GOAL_DAYS,
    Outcome,
    Running,
    Scenario,
    liquidation_distance,
    simulate,
)

JOURNAL = ROOT / "data" / "journal.sqlite"

START_EQUITY = 1_000.0
TARGET_EQUITY = 20_000.0

#: Vorwärts gemessener Takt: 2,27 Trades am Tag über alle Konten.
TRADES_PER_DAY = 2.27

#: Die gemessene Auszahlung über die 2 734 Replay-Trades des Journals. Hier,
#: damit die Trefferquoten-Übersetzung unten nicht gegen eine andere Zahl
#: rechnet als `scripts/goal.py` -- zwei Auszahlungen für dieselbe Frage haben
#: in diesem Projekt schon eine falsche Prozentzahl erzeugt (ZIELRECHNUNG.md,
#: 61,8 % statt 53,28 %).
MEASURED_WIN = 1.816
MEASURED_LOSS = 1.008
MEASURED_HIT = 0.3248

#: Ab diesem Anteil der Pfade gilt ein Szenario als 'erreicht das Ziel
#: ueberwiegend'. Die Haelfte, weil darunter der Median unter dem Ziel liegt.
MOSTLY = 0.5

DEFAULT_PATHS = 20_000
SEED = 20261007

#: Plausibles Band für einen Stop-Abstand als ANTEIL des Preises. Ein Stop
#: unter 0,05 % oder über 25 % ist kein Stop, sondern ein Einheitenfehler.
STOP_BAND = (0.0005, 0.25)

#: Stop-Anteil fuer eine eingefrorene Prediction-Menge, die keinen traegt.
#: GEMESSEN, nicht gewaehlt: Median ueber 2'734 Replay-Trades des Journals
#: am 07.10.2026 (Mittel 0.019554, p10 0.007777, p90 0.037760). Der Median
#: statt des Mittels, weil die Verteilung rechtsschief ist und ein breiter
#: Stop die Positionsgroesse senkt -- die optimistische Richtung.
FROZEN_STOP_FRACTION = 0.013090

#: Laufende Kosten in CHF je Monat. Bei 1 000 CHF Startkapital ist das keine
#: Fussnote: 50 CHF über sechs Monate sind 30 % des Kapitals.
RUNNING_COSTS = Running(items={"LLM-API": 0.0, "VPS": 0.0, "Daten": 0.0})


def bounded_adverse(trade: dict, r_multiple: float) -> float:
    """Wie weit der Preis gegen den Trade lief, SOLANGE er offen war.

    Das gespeicherte `max_adverse_r` kann das nicht sagen. Es wurde bis zum
    07.10.2026 über alle Kerzen gelesen, die den Trade *überlappen* -- also
    inklusive der Bewegung nach dem Ausstieg in der Abschlusskerze. Gemessen:
    Werte bis **147,88 R** auf einem Trade, der nach einer Kerze bei -0,036 R
    ausgestoppt wurde, und 25,3 % der ausgestoppten Trades über 1,6 R.
    `journal/postmortem.py` ist korrigiert; die gespeicherten Zeilen stammen
    von davor.

    Die Schranke hier braucht das Feld nicht. Sie folgt aus dem Ausgang:

    * Ein Trade, der **nicht** ausgestoppt wurde, hat seinen Stop nie erreicht.
      Also lief der Preis um weniger als 1 R gegen ihn.
    * Ein Trade, der **ausgestoppt** wurde, hat ihn genau erreicht -- plus
      Slippage, und die steht im realisierten R. Gemessen: 83 % der Stops
      füllen schlechter als -1 R, Median 1,079 R, Maximum **2,527 R**.

    Das ist keine Schätzung, sondern das, was der Ausgang zulässt. Und es ist
    die Grösse, die die Liquidationsfrage braucht: liquidiert wird, solange die
    Position offen ist, nicht danach.
    """
    if trade.get("exit_reason") == "stop":
        return max(1.0, abs(r_multiple))
    return 1.0


def load(source: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """R, Eröffnungszeit, max_adverse_r und Stop-Anteil je Trade."""
    if not JOURNAL.is_file():
        raise SystemExit(f"Kein Journal unter {JOURNAL}.")
    with sqlite3.connect(JOURNAL) as conn:
        rows = list(
            conn.execute(
                "SELECT r_multiple, opened_ts, payload FROM trades "
                "WHERE source = ? ORDER BY opened_ts",
                (source,),
            )
        )
    if not rows:
        raise SystemExit(f"Keine Trades mit source='{source}'.")

    r, ts, adverse, stop = [], [], [], []
    for value, opened, payload in rows:
        trade = json.loads(payload) if payload else {}
        reason = trade.get("reason") or {}
        post = trade.get("post_mortem") or {}
        percent = reason.get("stop_distance_pct")
        if percent is None or post.get("max_adverse_r") is None:
            continue
        r.append(float(value))
        ts.append(int(opened))
        adverse.append(bounded_adverse(trade, float(value)))
        stop.append(float(percent) / 100.0)  # Prozent -> Anteil

    fractions = np.array(stop)
    low, high = STOP_BAND
    if not ((fractions >= low) & (fractions <= high)).all():
        bad = fractions[(fractions < low) | (fractions > high)]
        raise SystemExit(
            f"{bad.size} Stop-Abstaende liegen ausserhalb [{low}, {high}] als Anteil: "
            f"z.B. {bad[:3]}. Das ist ein Einheitenfehler, keine Marktbeobachtung."
        )
    return np.array(r), np.array(ts, dtype="int64"), np.array(adverse), fractions


def load_frozen(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Dasselbe aus einer eingefrorenen Prediction-Menge.

    Abschnitt 12 des Auftrags verlangt als Eingabe „nur eingefrorene,
    zeitpunktkorrekte Out-of-Sample-Predictions". Ohne diesen Pfad las die
    Zielsimulation das Journal, also die Papierhistorie — und Lieferpunkt 6
    (`learn/frozen.py`) war gebaut, aber nicht angeschlossen.

    **Die Einheitsprüfung ist der Grund, warum `freeze()` `unit` erzwingt.**
    Diese Simulation rechnet in R: sie teilt Bewegung durch Risiko und
    kettet das Ergebnis auf ein Konto. Eine Netto-Rendite je Kerze ist
    durch nichts geteilt. Beide stehen in einer Spalte namens `net_r`, und
    ohne diese Prüfung wäre aus E2s Kerzenreihe eine R-Verteilung geworden,
    die aussieht wie eine und keine ist.

    `max_adverse_r` und der Stop-Abstand stehen nicht in einer eingefrorenen
    Menge — sie sind Eigenschaften des Trade-**Pfades**, nicht der Prediction.
    Deshalb kommen hier Ersatzwerte, und die erste Fassung dieses Docstrings
    nannte sie „konservativ". Für den Stop-Anteil stimmt das (der Median
    statt des Mittels, und ein breiterer Stop senkt die Positionsgrösse).

    **Für `max_adverse_r` ist es falsch, und zwar gefährlich falsch.** `max(1,
    |R|)` sieht den Ausschlag *während* des Trades nicht: ein Trade, der auf
    -2R lief und bei +0,5R schloss, bekommt 1,0 statt 2,0. Die Liquidation
    wird damit **unterschätzt**. Mit diesen Werten stand in der Tabelle
    „0,0 % liquidiert" bei 15x, wo dieselbe Simulation auf echten Pfaden
    100 % liest. Die Liquidationsspalte wird für eine eingefrorene Quelle
    deshalb nicht gerechnet, sondern als nicht bestimmbar ausgewiesen.
    """
    frame, meta = frozen_load(path)
    unit = str(meta.get("unit", "unbekannt"))
    if unit != "net_r_per_signal":
        raise SystemExit(
            f"{path.name} traegt die Einheit '{unit}'.\n"
            f"Diese Simulation rechnet in R -- sie teilt Bewegung durch Risiko und\n"
            f"kettet das Ergebnis auf ein Konto. '{unit}' ist durch nichts geteilt,\n"
            f"und beide heissen in der Datei `net_r`. Hier wird nicht umgerechnet:\n"
            f"wer die Kerzenreihe von E2 als Zielverteilung will, braucht eine\n"
            f"eigene Simulation mit Positionsgroesse und Kapitalbindung."
        )

    taken = frame.loc[frame["selected"].astype(bool)].sort_values("decision_ms")
    if taken.empty:
        raise SystemExit(f"{path.name}: der Arm hat nichts genommen.")

    r = taken["net_r"].to_numpy(dtype=float)
    ts = taken["decision_ms"].to_numpy(dtype="int64")
    adverse = np.maximum(1.0, np.abs(r))
    stop = np.full(r.size, FROZEN_STOP_FRACTION)
    print(
        f"  Eingefroren: {path.name}\n"
        f"    Datenstand {str(meta.get('data_vintage', '?'))[:12]}, "
        f"Signatur {meta.get('run_signature', '?')}\n"
        f"    {len(frame):,} Entscheidungen, davon {len(taken):,} genommen\n"
        f"    ANNAHME: Stop-Anteil pauschal {100 * FROZEN_STOP_FRACTION:.2f}% "
        f"(Median des Journals).\n"
        f"    max_adverse_r steht nicht in dieser Menge und wird NICHT ersetzt "
        f"-- die Liquidationsspalte bleibt leer."
    )
    return r, ts, adverse, stop


def scenarios() -> list[Scenario]:
    """Die Szenarioliste aus Abschnitt 12 des Auftrags, vorab festgelegt.

    Reihenfolge und Namen stehen hier, bevor eine Zahl gelesen wird. Kein
    Szenario wird nachträglich hinzugefügt, um ein freundlicheres Ergebnis zu
    bekommen -- ein neues gehört in `audit/EXPERIMENTS_NEXT.yaml` und erhöht
    dort die Vergleichszahl.
    """
    out: list[Scenario] = [
        Scenario(
            "1 gemessen, 1% Risiko",
            risk_fraction=0.01,
            note="Kontrolle: die gemeldete Lage, unveraendert.",
        ),
        Scenario("1b gemessen, 0.5% Risiko", risk_fraction=0.005),
        Scenario("1c gemessen, 2% Risiko", risk_fraction=0.02),
        Scenario("1d gemessen, 3% Risiko (Deckel)", risk_fraction=0.03),
        Scenario(
            "1e gemessen, 5% Risiko (nur Stress)",
            risk_fraction=0.05,
            note="UEBER dem harten Deckel. Stressszenario, keine Freigabe.",
        ),
    ]
    # Hebelarme bei gleichem CHF-Stoprisiko, wie der Auftrag sie verlangt.
    for leverage in (1.0, 3.0, 5.0, 10.0, 15.0):
        out.append(
            Scenario(
                f"2 Hebel {leverage:.0f}x, 1% Risiko",
                risk_fraction=0.01,
                leverage=leverage,
                note="Gleiches CHF-Stoprisiko; der Hebel wirkt nur ueber die Liquidation.",
            )
        )
    # Hypothesen. Jede traegt ihren unterstellten Vorteil im Namen.
    for shift in (0.05, 0.10, 0.20, 0.40):
        out.append(
            Scenario(
                f"3 HYPOTHESE Vorteil +{shift:.2f} R, 1% Risiko",
                risk_fraction=0.01,
                edge_shift=shift,
                note="MODELLBEDINGT. Kein Arm im Register belegt diesen Vorteil.",
            )
        )
    out += [
        Scenario(
            "4a Vorteil halbiert, Kosten x1.5",
            risk_fraction=0.01,
            edge_shift=0.05,
            cost_multiplier=1.5,
            note="MODELLBEDINGT, pessimistische Lesart von Szenario 3.",
        ),
        Scenario(
            "5a Korrelation erhoeht (Streuung x1.5)",
            risk_fraction=0.01,
            spread_multiplier=1.5,
            note="Gleichzeitige Verluste wirken wie ein groesserer Einzelverlust.",
        ),
        Scenario(
            "5b Feed-/Orderausfall 10%",
            risk_fraction=0.01,
            failure_rate=0.10,
            note="Ein ausgefallener Trade ist kein Verlust, sondern ein Nicht-Ereignis.",
        ),
    ]
    return out


def report(
    outcomes: list[Outcome], *, source: str, trades: int, liquidation_known: bool = True
) -> None:
    """Die Tabelle. `liquidation_known=False` leert die Liquidationsspalte.

    Ein Hinweis über der Tabelle genügt dafür nicht. Solange dort „0,0 %"
    steht, ist das die Zahl, die jemand zitiert — und bei einer
    eingefrorenen Quelle stammt sie aus einem Ersatzwert, der den Ausschlag
    während des Trades nicht kennt und die Liquidation deshalb
    unterschätzt. Eine leere Zelle kann man nicht falsch zitieren.
    """
    print("\n" + "=" * 110)
    print(
        f"Zielchance und Verlustchance nebeneinander -- "
        f"Quelle: {source}, {trades} Trades je Pfad"
    )
    print("=" * 110)
    header = (
        f"\n  {'Szenario':34s} {'Ziel Ende':>10s} {'Ziel je':>8s} {'<Start':>7s} "
        f"{'<=500':>7s} {'<=200':>7s} {'Liquid.':>8s} {'Median':>9s} {'CVaR5%':>8s}"
    )
    print(header)
    print("  " + "-" * 106)
    for out in outcomes:
        liquid = f"{100 * out.liquidated:>7.1f}%" if liquidation_known else f"{'--':>8s}"
        print(
            f"  {out.scenario:34s} {100 * out.reached_at_end:>9.2f}% "
            f"{100 * out.reached_ever:>7.2f}% {100 * out.below_start:>6.1f}% "
            f"{100 * out.below_half:>6.1f}% {100 * out.below_ruin:>6.1f}% "
            f"{liquid} {out.median_end:>9.0f} {out.cvar_5:>8.0f}"
        )

    print("\n  Quantile des Endkapitals in CHF:\n")
    print(f"  {'Szenario':34s} {'5%':>9s} {'25%':>9s} {'50%':>9s} {'75%':>9s} {'95%':>9s}")
    print("  " + "-" * 82)
    for out in outcomes:
        cells = "".join(f"{out.quantiles[q]:>9.0f} " for q in (5, 25, 50, 75, 95))
        print(f"  {out.scenario:34s} {cells}")


def required_r(*, risk: float, trades: int) -> float:
    """Welches mittlere R je Trade das Ziel verlangt, bei diesem Risiko und Takt.

    Aus dem Log-Wachstum: `trades * ln(1 + risk*R) = ln(20)`. Die Zahl steht
    hier, weil sie die Tabelle oben in einem Satz zusammenfasst -- und weil sie
    gegen den Register-Champion gehalten werden kann, was eine
    Wahrscheinlichkeit nicht kann.

    Sie ist durch Jensen eine **Untergrenze**: echte R-Werte streuen, und
    `E[ln(1+fR)] < ln(1+f*E[R])`. Das wirkliche nötige Mittel liegt darüber.
    """
    growth = TARGET_EQUITY / START_EQUITY
    return (float(np.exp(np.log(growth) / trades)) - 1.0) / risk


def verdict(outcomes: list[Outcome], *, paths: int, trades: int) -> None:
    measured = [o for o in outcomes if "HYPOTHESE" not in o.scenario and o.scenario.startswith("1")]
    hypothetical = [o for o in outcomes if "HYPOTHESE" in o.scenario]
    best_measured = max(measured, key=lambda o: o.reached_at_end)
    worst_ruin = max(measured, key=lambda o: o.below_ruin)

    print("\n" + "=" * 110)
    print("Urteil")
    print("=" * 110)
    print(
        f"\n  Auf der GEMESSENEN Verteilung erreicht das beste Risikoprofil das Ziel in\n"
        f"  {100 * best_measured.reached_at_end:.2f}% der Pfade ({best_measured.scenario}).\n"
        f"  Dasselbe Profil, das am haeufigsten unter 200 CHF faellt, tut das in\n"
        f"  {100 * worst_ruin.below_ruin:.1f}% der Pfade ({worst_ruin.scenario}).\n"
    )
    print(
        "  Das ist die Antwort auf die Frage des Auftrags, und sie ist unbequem:\n"
        "  bei negativem gemessenem Mittel erhoeht mehr Risiko die Ruinchance\n"
        "  schneller als die Zielchance. Das ist keine Meinung, sondern was\n"
        "  Log-Wachstum bei negativem Drift tut."
    )
    print("\n  Welches mittlere R je Trade das Ziel verlangt, bei diesem Takt --")
    print("  und welche Trefferquote das bei der GEMESSENEN Auszahlung bedeutet:\n")
    print(f"    {'Risiko':>7s}  {'noetiges R':>11s}  {'Trefferquote':>13s}  {'Luecke':>8s}")
    for risk in (0.005, 0.01, 0.02, 0.03):
        needed = required_r(risk=risk, trades=trades)
        # E[R] = p*win - (1-p)*loss  nach p aufgeloest.
        share = (needed + MEASURED_LOSS) / (MEASURED_WIN + MEASURED_LOSS)
        if 0.0 <= share <= 1.0:
            gap = 100 * (share - MEASURED_HIT)
            print(
                f"    {risk:>6.1%}  {needed:>+10.3f} R  {100 * share:>12.2f}%"
                f"  {gap:>+7.1f} Pp"
            )
        else:
            print(f"    {risk:>6.1%}  {needed:>+10.3f} R  {'unerreichbar':>13s}")
    print(
        "\n  Daneben, zum Vergleich: der Register-Champion liegt bei -0.0340 R, die\n"
        "  gemessene Replay-Verteilung bei -0.0906 R, und das mittlere GEPLANTE\n"
        "  Chance-Risiko-Verhaeltnis ist 2.15 -- also was herauskaeme, wenn jeder\n"
        "  Trade sein Ziel traefe und keiner seinen Stop. Jede dieser Zahlen ist\n"
        "  durch Jensen eine Untergrenze, weil echte R-Werte streuen."
    )
    if hypothetical:
        reach = next(
            (
                o
                for o in sorted(hypothetical, key=lambda x: x.reached_at_end)
                if o.reached_at_end > MOSTLY
            ),
            None,
        )
        print(
            "\n  Unter HYPOTHESE (modellbedingt, von keinem Arm im Register belegt):\n"
        )
        for o in hypothetical:
            print(
                f"    {o.scenario:40s} Ziel {100 * o.reached_at_end:6.2f}%  "
                f"Ruin {100 * o.below_ruin:5.1f}%  Median {o.median_end:>8.0f} CHF"
            )
        if reach is not None:
            print(
                f"\n  Der kleinste unterstellte Vorteil, der das Ziel in ueber der Haelfte\n"
                f"  der Pfade erreicht, ist '{reach.scenario}'. Zum Vergleich: der\n"
                f"  Register-Champion liegt bei -0.0340 R, und kein Arm von 87 hat ein\n"
                f"  Intervall, das die Null ausschliesst."
            )
        else:
            print(
                "\n  Keiner der unterstellten Vorteile erreicht das Ziel in ueber der\n"
                "  Haelfte der Pfade."
            )

    total = RUNNING_COSTS.total()
    print(
        f"\n  Laufende Kosten, die aus dem Startkapital bezahlt werden: "
        f"{total:.0f} CHF ueber sechs Monate\n"
        f"  = {100 * RUNNING_COSTS.share_of(START_EQUITY):.1f}% des Startkapitals.\n"
        f"  Heute steht hier 0, weil nur lokale Ressourcen und freie Archive benutzt\n"
        f"  werden. Jeder bezahlte Dienst gehoert in diese Zeile, BEVOR er laeuft:\n"
        f"  50 CHF im Monat waeren 300 CHF, also 30% des Kapitals."
    )
    print(
        f"\n  Und was diese Tabelle nicht ist: {paths:,} synthetische Pfade sind nicht\n"
        f"  {paths:,} neue Marktphasen. Das Monte-Carlo-Intervall deckt die\n"
        f"  Ziehunsicherheit, nicht die Modellunsicherheit. Jede Zahl oben ist\n"
        f"  MODELLBEDINGT, bis Vorwaertsdaten sie stuetzen -- und davon gibt es acht."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", type=int, default=DEFAULT_PATHS)
    parser.add_argument("--source", default="replay", choices=("replay", "live"))
    parser.add_argument(
        "--frozen",
        type=Path,
        default=None,
        help=(
            "Eine eingefrorene Prediction-Menge aus data/frozen/ statt des Journals. "
            "Abschnitt 12 des Auftrags verlangt genau das als Eingabe."
        ),
    )
    parser.add_argument("--days", type=int, default=GOAL_DAYS)
    args = parser.parse_args()

    if args.frozen is not None:
        r, ts, adverse, stop = load_frozen(args.frozen)
    else:
        r, ts, adverse, stop = load(args.source)
    trades = round(TRADES_PER_DAY * args.days)

    label = args.frozen.name if args.frozen is not None else args.source
    print("=" * 110)
    print(
        f"Zielsimulation: {START_EQUITY:,.0f} CHF -> {TARGET_EQUITY:,.0f} CHF"
        f" in {args.days} Tagen"
    )
    print("=" * 110)
    print(
        f"\n  Quelle           {label} ({r.size:,} Trades, Mittel {r.mean():+.4f} R)\n"
        f"  Takt             {TRADES_PER_DAY} Trades/Tag -> {trades} Trades je Pfad\n"
        f"  Pfade            {args.paths:,}, Seed {SEED}\n"
        f"  Stop-Abstand     Median {100 * float(np.median(stop)):.3f}% des Preises\n"
        f"  max_adverse_r    Median {float(np.median(adverse)):.3f}"
    )
    print("\n  Liquidationsabstand je Hebel, als Anteil des Preises:")
    for leverage in (1.0, 3.0, 5.0, 10.0, 15.0):
        distance = liquidation_distance(leverage)
        in_r = distance / float(np.median(stop))
        if args.frozen is not None:
            # Die Spalte wird NICHT gerechnet, und das ist der Punkt. Eine
            # eingefrorene Prediction-Menge traegt keinen `max_adverse_r` --
            # das ist eine Eigenschaft des Trade-PFADES, nicht der Vorhersage.
            # Der Ersatzwert max(1, |R|) ist fuer das Ergebnis je Trade
            # richtig und fuer die Liquidation falsch, und zwar in der
            # GEFAEHRLICHEN Richtung: ein Trade, der auf -2R lief und bei
            # +0.5R schloss, bekommt 1.0 statt 2.0. Mit diesen Werten stand
            # hier "0.0% liquidiert" bei 15x, wo dieselbe Simulation auf
            # echten Pfaden 100% liest.
            print(
                f"    {leverage:>5.0f}x  {100 * distance:>7.3f}%  = {in_r:>6.2f} R des "
                f"Median-Stops  ->  NICHT BESTIMMBAR aus einer eingefrorenen Menge"
            )
            continue
        share = float((adverse >= distance / stop).mean())
        print(
            f"    {leverage:>5.0f}x  {100 * distance:>7.3f}%  = {in_r:>6.2f} R des "
            f"Median-Stops  -> {100 * share:>5.1f}% der Trades waeren liquidiert worden"
        )
    if args.frozen is not None:
        print(
            "\n  ! Die Liquidations- und Ruinspalten dieser Tabelle sind mit einer\n"
            "    eingefrorenen Quelle NICHT zu lesen. Der Hebelteil der Frage braucht\n"
            "    echte Pfade: `--source replay` ohne `--frozen`. Belegt ist hier die\n"
            "    Verteilung des Ergebnisses je Trade dieses Arms, nichts darueber."
        )

    outcomes = [
        simulate(
            r_values=r,
            stamps=ts,
            adverse_r=adverse,
            stop_fraction=stop,
            scenario=scenario,
            start_equity=START_EQUITY,
            target_equity=TARGET_EQUITY,
            trades=trades,
            paths=args.paths,
            seed=SEED,
        )
        for scenario in scenarios()
    ]
    report(outcomes, source=label, trades=trades, liquidation_known=args.frozen is None)
    verdict(outcomes, paths=args.paths, trades=trades)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
