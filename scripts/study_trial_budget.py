"""Wie viele Versuche erlauben fünf Jahre Daten, bevor ein Treffer bedeutungslos ist?

    python scripts/study_trial_budget.py

**Anlass.** Die Literatursuche vom 11.10.2026 hat in acht Ansatzfamilien
keinen einzigen Kandidaten gefunden, der die gegnerische Prüfung überlebt.
Der härteste Befund war aber kein Ansatz, sondern eine Rechnung aus der
Metawissenschaft: **Bailey, Borwein, López de Prado und Zhu** zeigen, wie
lang eine Datenreihe sein muss, damit die beste aus `N` ausprobierten
Konfigurationen nicht schon durch Zufall gut aussieht.

Die Grösse heisst *Minimum Backtest Length*. Mit `gamma` als Euler-Mascheroni-
Konstante:

    E[max_N] ≈ (1 - gamma)·Z^-1[1 - 1/N]  +  gamma*Z^-1[1 - 1/(N*e)]
    MinBTL   ≈ E[max_N]^2              (Jahre, für ein Ziel-Sharpe von 1)

Gelesen: wer `N` Konfigurationen ausprobiert und die beste nimmt, bekommt
allein aus Rauschen ein In-Sample-Sharpe von `E[max_N]/sqrt(T)`. Damit das unter 1
bleibt, braucht es `T >= E[max_N]^2` Jahre.

**Warum das dieses Projekt direkt trifft.** Es hat 24 Experimentfamilien
geschlossen, viele mit mehreren Armen, auf einer Datenreihe von rund fünf
Jahren. Wenn die Zahl der Versuche das Budget überschreitet, dann ist **jeder
weitere positive Fund auf denselben Daten a priori verdächtig** — unabhängig
davon, wie gut das Bonferroni-Intervall aussieht. Bonferroni korrigiert die
Fehlerrate eines Tests; es verlängert nicht die Datenreihe.

Das Skript rechnet beides: wie viele Versuche fünf Jahre tragen, und wie viele
Jahre die tatsächlich gefahrenen Versuche gebraucht hätten.

Nur rechnen. Keine Daten, kein Netz, keine Börse.
"""

from __future__ import annotations

import argparse
import math
import statistics

#: Zwei Versuche sind das Minimum, unter dem die Frage keinen Sinn hat.
MIN_TRIALS = 2

#: Obergrenze der Suche, damit eine kaputte Formel nicht endlos laeuft.
SEARCH_CEILING = 100_000

#: Wie genau die eigene Rechnung die Stuetzpunkte des Papiers treffen muss.
TOLERANCE = 0.02

#: Euler-Mascheroni.
GAMMA = 0.5772156649015329

#: Stützpunkte aus dem Papier, zur Prüfung der eigenen Implementierung.
#: Ohne sie wäre die Formel eine Behauptung über eine Behauptung.
REFERENCE = {7: 1.92, 45: 5.00}


def _inverse_normal(p: float) -> float:
    """Z^-1 über Acklams Näherung, Fehler < 1,15e-9.

    Von Hand, weil `scipy` für eine einzige Funktion eine schwere Abhängigkeit
    wäre und `statistics.NormalDist` hier genügt — letzteres wird darum unten
    als Gegenprobe benutzt.
    """
    return statistics.NormalDist().inv_cdf(p)


def expected_max(trials: int) -> float:
    """Das erwartete Maximum von `N` unabhängigen Standardnormalen."""
    if trials < MIN_TRIALS:
        return 0.0
    return (1.0 - GAMMA) * _inverse_normal(1.0 - 1.0 / trials) + GAMMA * _inverse_normal(
        1.0 - 1.0 / (trials * math.e)
    )


def min_backtest_length(trials: int) -> float:
    """Nötige Jahre, damit das beste aus `N` Ergebnissen kein Rauschen ist."""
    return expected_max(trials) ** 2


def trials_for(years: float) -> int:
    """Wie viele unabhängige Versuche diese Datenlänge trägt."""
    n = 2
    while min_backtest_length(n + 1) <= years:
        n += 1
        if n > SEARCH_CEILING:
            break
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=float, default=5.0,
                        help="Laenge der Datenreihe in Jahren (Default 5, ab 2021)")
    args = parser.parse_args()

    print("=" * 74)
    print("Versuchsbudget: wie viele Konfigurationen tragen diese Daten?")
    print("=" * 74)

    print("\n  Erst die eigene Implementierung gegen das Papier:\n")
    ok = True
    for trials, expected in sorted(REFERENCE.items()):
        got = min_backtest_length(trials)
        good = abs(got - expected) < TOLERANCE
        ok = ok and good
        print(f"    N = {trials:>3}  MinBTL  erwartet {expected:.2f}  gerechnet {got:.2f}  "
              f"{'ok' if good else 'ABWEICHUNG'}")
    if not ok:
        print("\n  Die Formel trifft die Stuetzpunkte nicht. Alles darunter ist wertlos.")
        return 1

    budget = trials_for(args.years)
    print(f"\n  Bei {args.years:.0f} Jahren Daten: **{budget} unabhaengige Versuche**")
    print("  Darueber hinaus ist ein In-Sample-Sharpe von 1 auch bei wahrer")
    print("  Null-Faehigkeit praktisch garantiert.\n")

    head = f"Status bei {args.years:.0f}J"
    print(f"  {'Versuche':>9s} {'E[max]':>8s} {'noetige Jahre':>14s} {head:>16s}")
    print("  " + "-" * 52)
    for trials in (10, 24, 45, 59, 87, 124, 200, 500):
        need = min_backtest_length(trials)
        status = "traegt" if need <= args.years else f"fehlen {need - args.years:.1f} J"
        print(f"  {trials:>9} {expected_max(trials):>8.3f} {need:>13.2f}  {status:>16s}")

    print("\n  Was dieses Projekt tatsaechlich gefahren hat (audit/TRIAL_LEDGER.csv):")
    print("    24 geschlossene Experimentfamilien")
    print("    59 nachrechenbare Zellen aus data/study_*.json")
    print("    87 Arme laut meta.prior_search, 124 behauptete Versuche")
    print()
    for trials, label in ((24, "nur die Familien"), (59, "die nachrechenbaren Zellen"),
                          (87, "die Arme"), (124, "die behaupteten Versuche")):
        need = min_backtest_length(trials)
        verdict = "im Budget" if need <= args.years else "UEBER dem Budget"
        print(f"    {label:28s} N={trials:>4}  braucht {need:5.2f} Jahre  -> {verdict}")

    print("\n  Und die Gegenrichtung, die ehrlicher ist als die Zahl allein:")
    print("    N ist die Zahl UNABHAENGIGER Versuche. Varianten derselben Idee")
    print("    zaehlen weniger als eine ganze; die effektive Zahl liegt zwischen")
    print("    24 und 124 und ist hier nicht gemessen. Was die Rechnung trotzdem")
    print("    sagt: schon bei 45 ist das Budget aufgebraucht, und 45 liegt")
    print("    innerhalb dieser Spanne.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
