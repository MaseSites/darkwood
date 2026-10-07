"""Welche Trefferquote verlangt 20x -- und woher kam die falsche Zahl?

    python scripts/study_hitrate_table.py
    python scripts/study_hitrate_table.py --growth 20 --trades 312

`audit/ZIELRECHNUNG.md` nennt fuer 20x bei 3 % Risiko und 312 Trades mit der
gemessenen Auszahlung **61,8 %**. Diese Zahl ist mit keiner im Projekt
gemessenen Auszahlung reproduzierbar, und `git log --follow` zeigt, dass
`learn/target.py` seit dem Commit, der jenes Dokument einführte, unverändert
ist. Sie wurde also nie von diesem Code erzeugt.

Das ist derselbe Fehler, den jenes Dokument bei der 56,6 % aufgedeckt hat: eine
Zahl, die in einem Satz steht statt in einem Skript. Dieses Skript existiert,
damit die Zahlen künftig aus einer Funktion kommen und jeder sie nachrechnen
kann.

Es rechnet jede Zelle **zweimal**: einmal über `learn/target.py` und einmal über
eine hier unabhängig hingeschriebene Formel. Stimmen die beiden nicht überein,
bricht das Skript ab. Ein Test, der die Implementierungsformel kopiert, prüft
nichts -- zwei Wege zum selben Wert prüfen etwas.

Zwei Auszahlungen sind im Projekt gemessen, auf **verschiedenen Populationen**:

* `Payout(win=1.5612, loss=1.0384)` über die 3 300 gelabelten Signale des
  Champions.
* `Payout(win=1.816, loss=1.008)` über die 2 734 Replay-Trades des Journals.

Beide sind Messungen, und sie antworten verschieden. Der Zustandsbericht nannte
die zweite und zitierte daneben eine Zahl, die angeblich aus der ersten kam --
ohne zu sagen, dass es zwei verschiedene Grundgesamtheiten sind. Darum stehen
hier immer beide.

**Was diese Tabelle nicht ist.** Es sind Quoten für erwartetes **Log-Wachstum**
im Zweipunktmodell, keine Wahrscheinlichkeiten, das Ziel zu erreichen. Sie
unterstellen konstante bedingte Auszahlungen und dieselbe Risikofraktion je
Trade. Weil echte R-Werte streuen, ist jede dieser Quoten durch Jensen eine
**Untergrenze**: `E[ln(1+fR)] < ln(1+f·E[R])`.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.learn.target import SYMMETRIC, Payout, required_hit_rate

#: Die beiden im Projekt gemessenen Auszahlungen, mit ihrer Grundgesamtheit.
MEASURED: tuple[tuple[str, Payout], ...] = (
    ("Champion, 3.300 gelabelte Signale", Payout(win=1.5612, loss=1.0384)),
    ("Journal, 2.734 Replay-Trades", Payout(win=1.816, loss=1.008)),
    ("symmetrisch, +-1 R", SYMMETRIC),
)

TRADE_COUNTS = (60, 156, 312, 624)
RISKS = (0.01, 0.02, 0.03)

#: Die Zahl, die in `audit/ZIELRECHNUNG.md` steht und nirgends herauskommt.
CLAIMED = 0.618

#: Toleranz zwischen Projektfunktion und unabhaengiger Handrechnung.
AGREEMENT = 1e-9


def by_hand(*, growth: float, trades: float, risk: float, payout: Payout) -> float:
    """Dieselbe Groesse, unabhaengig hingeschrieben.

    Zweipunktmodell mit Log-Wachstum: ein Gewinn multipliziert das Kapital mit
    `1 + f*w`, ein Verlust mit `1 - f*l`. Gesucht ist der Anteil Gewinne, bei
    dem `n` solche Schritte im Mittel `ln(G)` ergeben.
    """
    a = math.log(1.0 + risk * payout.win)
    b = math.log(1.0 - risk * payout.loss)
    return (math.log(growth) / trades - b) / (a - b)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--growth", type=float, default=20.0)
    parser.add_argument("--trades", type=int, default=312)
    args = parser.parse_args()

    print("=" * 78)
    print(f"Noetige Trefferquote fuer {args.growth:.0f}x, im Zweipunktmodell")
    print("=" * 78)

    for label, payout in MEASURED:
        print(f"\n{label}   (+{payout.win:.4f} R / -{payout.loss:.4f} R)")
        print(f"  {'Trades':>7s}" + "".join(f"{risk:>11.0%}" for risk in RISKS))
        for trades in TRADE_COUNTS:
            cells = []
            for risk in RISKS:
                value = required_hit_rate(
                    growth=args.growth, trades=trades, risk=risk, payout=payout
                )
                check = by_hand(growth=args.growth, trades=trades, risk=risk, payout=payout)
                if abs(value - check) > AGREEMENT:
                    raise SystemExit(
                        f"Projektfunktion und Handrechnung weichen ab: "
                        f"{value:.10f} gegen {check:.10f} bei n={trades}, risk={risk}."
                    )
                cells.append(f"{100 * value:>10.2f}%")
            print(f"  {trades:>7d}" + "".join(cells))
    print("\n  Werte ueber 100% heissen: in diesem Modell unerreichbar.")

    print("\n" + "=" * 78)
    print(f"Die Zahl {100 * CLAIMED:.1f}% aus audit/ZIELRECHNUNG.md")
    print("=" * 78)
    print(f"\nBei n={args.trades}, Risiko 3%, wie dort angegeben:\n")
    closest, gap = None, math.inf
    for label, payout in MEASURED:
        value = required_hit_rate(growth=args.growth, trades=args.trades, risk=0.03, payout=payout)
        print(f"  {label:36s} -> {100 * value:6.2f}%")
        if abs(value - CLAIMED) < gap:
            closest, gap = label, abs(value - CLAIMED)
    named = required_hit_rate(
        growth=args.growth, trades=args.trades, risk=0.03, payout=MEASURED[0][1]
    )
    print(
        f"\n  Keine davon ergibt {100 * CLAIMED:.1f}%. Am naechsten liegt '{closest}'\n"
        f"  mit {100 * gap:.2f} Prozentpunkten Abstand. Die Auszahlung, die das Dokument\n"
        f"  selbst als Quelle nennt, ergibt {100 * named:.2f}%."
    )
    print(
        "\n  `git log --follow -- src/traidingbrain/learn/target.py` zeigt keinen Commit\n"
        "  nach ef30e93, der jenes Dokument einfuehrte. Die Zahl wurde also nie von\n"
        "  diesem Code erzeugt; sie ist handgeschrieben und falsch.\n"
        "\n  Das ist derselbe Fehler, den jenes Dokument bei der 56,6% aufdeckte, im\n"
        "  selben Dokument wiederholt. Deshalb dieses Skript."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
