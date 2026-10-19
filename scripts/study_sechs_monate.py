"""Wie viel sind aus 1.000 nach sechs Monaten geworden? -- die Verteilung.

**Die Frage, so gestellt, hat keine Zahl als Antwort.** Sie hat eine
Verteilung. Ein Konto mit Hebel ist ein Pfad, und ein Pfad ist zur Haelfte
Reihenfolge. Wer eine einzelne Zahl nennt, nennt eine Ziehung und verschweigt
die anderen.

Darum rechnet dieses Skript ueber ALLE 182-Tage-Fenster, die in den
gespeicherten Daten liegen, und berichtet die Spannweite statt eines Mittels.

**Drei Dinge, die es richtig macht und die eine Ueberschlagsrechnung nicht
tut:**

1. *Margin.* Jede Position bindet `Margin-Anteil x Konto`. Bei 30 % passen
   drei ins Konto; die vierte findet nichts (`sim/broker.py:500`). Ueber die
   gespeicherten Trades waren 67,9 % der Zeit mehr als drei offen -- eine
   Rechnung ohne Margin laedt also Trades auf ein Konto, das keinen Platz
   hatte.
2. *Liquidation, als Rand statt als Zahl.* Liegt der Stop weiter als die
   Liquidation, haette die Boerse vorher geschlossen. Ob das wirklich
   passiert waere, steht nicht in den Daten -- die Fills fuehren keine
   unguenstigste Zwischenbewegung. Also beide Raender.
3. *Der Kontoboden.* Unter einem Rest laesst sich keine Position mehr stellen.

**Was die Zahlen NICHT sind: eine Prognose.** Sie beschreiben, was mit diesen
gespeicherten Trades geschehen waere. Die Zukunft hat andere Trades. Und die
Fenster ueberlappen, sind also nicht unabhaengig -- die Spannweite ist darum
eher zu eng als zu weit.

    python scripts/study_sechs_monate.py
    python scripts/study_sechs_monate.py --margin-anteil 1.0 --hebel 2.1
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from study_plan_slots import START, TAG_MS, lade, lauf

#: Wie weit zwei Fensteranfaenge auseinanderliegen. Kleiner heisst mehr
#: Fenster, aber nicht mehr Information: sie ueberlappen dann staerker.
SCHRITT_TAGE = 30

#: Das Ziel aus dem Auftrag: aus 1.000 sollen 20.000 werden.
ZIEL_FAKTOR = 20.0

#: Ab hier gilt das Konto als praktisch ausgeloescht -- 90 % weg.
RUIN_FAKTOR = 0.10


def perzentil(sortiert: list[float], q: float) -> float:
    if not sortiert:
        return 0.0
    i = min(len(sortiert) - 1, max(0, round(q * (len(sortiert) - 1))))
    return sortiert[i]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--margin-anteil", type=float, default=0.30)
    parser.add_argument("--hebel", type=float, default=7.0)
    parser.add_argument("--tage", type=int, default=182)
    parser.add_argument("--min-trades", type=int, default=50)
    args = parser.parse_args(argv)

    trades = lade(args.fills)
    t0, t1 = int(trades[0]["opened_ts"]), int(trades[-1]["opened_ts"])

    fenster: list[list[dict[str, object]]] = []
    anfang = t0
    while anfang + args.tage * TAG_MS <= t1:
        f = [t for t in trades
             if anfang <= int(t["opened_ts"]) < anfang + args.tage * TAG_MS]
        if len(f) >= args.min_trades:
            fenster.append(f)
        anfang += SCHRITT_TAGE * TAG_MS

    print(f"{args.margin_anteil:.0%} Margin x {args.hebel:g}x Hebel, "
          f"Start {START:,.0f}, {args.tage} Tage je Fenster")
    print(f"{len(fenster)} Fenster aus {(t1 - t0) / TAG_MS:.0f} Tagen Daten, "
          f"je {SCHRITT_TAGE} Tage versetzt -- sie UEBERLAPPEN, sind also "
          f"nicht unabhaengig.\n")

    for streng, lesart in ((False, "guenstig (Gewinner ueberleben die Liquidation)"),
                           (True, "streng   (jeder Trade jenseits der Liquidation faellt)")):
        enden = [
            lauf(f, anteil=args.margin_anteil, hebel=args.hebel,
                 max_offen=None, margin_pruefen=True, liquidation_streng=streng)
            for f in fenster
        ]
        faktoren = sorted(k / START for k, _, _, _ in enden)
        genommen = [e[1] for e in enden]

        print(f"--- {lesart}")
        print(f"    Trades je Fenster: Median {statistics.median(genommen):,.0f} "
              f"(von {statistics.median([len(f) for f in fenster]):,.0f} angebotenen)")
        print(f"    {'schlechtestes':>16s} {perzentil(faktoren, 0.0) * START:12,.0f}")
        print(f"    {'unteres Viertel':>16s} {perzentil(faktoren, 0.25) * START:12,.0f}")
        print(f"    {'MITTE':>16s} {perzentil(faktoren, 0.50) * START:12,.0f}"
              f"   ({perzentil(faktoren, 0.50):.4f}x)")
        print(f"    {'oberes Viertel':>16s} {perzentil(faktoren, 0.75) * START:12,.0f}")
        print(f"    {'bestes':>16s} {perzentil(faktoren, 1.0) * START:12,.0f}"
              f"   ({perzentil(faktoren, 1.0):.2f}x)")
        ueber1 = sum(1 for f in faktoren if f > 1.0) / len(faktoren)
        ueber20 = sum(1 for f in faktoren if f >= ZIEL_FAKTOR) / len(faktoren)
        unter10 = sum(1 for f in faktoren if f < RUIN_FAKTOR) / len(faktoren)
        print(f"    ueber dem Start (1.000):      {ueber1:6.1%}")
        print(f"    bei oder ueber dem ZIEL (20.000): {ueber20:6.1%}")
        print(f"    unter 100 (90 % weg):         {unter10:6.1%}\n")

    print(
        "WAS HIER NICHT DRINSTEHT, UND WARUM.\n"
        "Ein Erwartungswert. Bei multiplikativem Wachstum ist der Mittelwert\n"
        "der Endstaende von wenigen sehr guten Pfaden beherrscht und sagt\n"
        "nichts darueber, was EINEM Konto passiert. Die Mitte und die Viertel\n"
        "sagen das.\n"
        "\n"
        "UND DIE EINSCHRAENKUNG, DIE ALLES TRAEGT: das sind gespeicherte\n"
        "Trades aus der Vergangenheit, nicht die Zukunft. Die gemessene\n"
        "Erwartung je Trade ist -0,0129 R mit einem 95-%-Intervall von\n"
        "[-0,0519, +0,0267] -- sie schliesst null ein. Ein System, dessen\n"
        "Kante nicht verlaesslich von null verschieden ist, hat keinen\n"
        "Erwartungswert, den man sechs Monate fortschreiben koennte. Was\n"
        "fortschreibbar IST, ist der Varianzabzug, und der ist negativ."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
