"""Hängen aufeinanderfolgende Trades zusammen? — die Frage unter jeder Kurvenregel.

**Warum das die entscheidende Vorfrage ist.** Jede Regel auf der Kapitalkurve,
die besser sein soll als „immer gleich gross", unterstellt dasselbe: dass
schlechte Phasen *vorhersagbar* sind. Ein Rückgangsdeckel, eine Pause nach
einer Verlustserie, ein Wiedereinstieg bei neuem Hoch — alle reagieren auf
vergangene Ergebnisse und wetten darauf, dass das nächste Ergebnis davon
abhängt.

Ist diese Abhängigkeit nicht da, ist jede solche Regel **Aberglaube mit
Parametern**: sie pausiert nach schlechtem Zufall und verpasst die Erholung.

**Und die Messung hat beim ersten Hinsehen das Gegenteil gesagt.** Über den
gepoolten Strom aller 7.335 Trades in Zeitordnung:

    Autokorrelation Abstand 1   +0,1774   Zufallsband [-0,0215, +0,0239]
    Verlust nach Verlust        69,98 %
    Verlust nach Gewinn         51,95 %
    Unterschied                +18,03 Prozentpunkte, Band +-2,3

Das sieht nach einem Befund aus. Es ist keiner, und dieses Skript zeigt warum.

**Die Falle: zwölf Märkte, gleichzeitig.** Der gepoolte Strom ist nach
Eröffnungszeit sortiert. Wenn zwölf Positionen am selben Tag offen sind und der
Markt fällt, verlieren sie zusammen — das ist **ein schlechter Tag, zwölfmal
gezählt**, und keine Vorhersagbarkeit. Die gemessene Beta von 1,0 zu BTC sagt
genau das voraus.

Drei Prüfungen trennen das eine vom anderen, und jede ist eine andere Frage:

* **A** — war der vorige Trade überhaupt schon geschlossen? Nur dann hätte eine
  Regel reagieren können.
* **B** — gibt es die Abhängigkeit *innerhalb* eines Marktes, wo
  aufeinanderfolgende Trades wirklich aufeinander folgen?
* **C** — bleibt sie, wenn man nur nicht-überlappende Paare zählt?

    python scripts/study_sequence_dependence.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

#: Wie viele Mischungen die Zufallsbaender bilden. Breite Baender brauchen
#: nicht viele Ziehungen; die Aussage ist "drin oder draussen", kein Quantil
#: am Rand.
RUNDEN = 400
STREUNGSRUNDEN = 2_000

#: Maerkte mit zu wenigen Trades geben ein Band, das alles enthaelt.
MIN_TRADES = 100


def lade(root: Path) -> list[tuple[int, int, float, str]]:
    """(Eroeffnung, Schliessung, R, Symbol), nach Eroeffnungszeit sortiert."""
    zeilen: list[tuple[int, int, float, str]] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            zeilen.append(
                (int(row["opened_ts"]), int(row["closed_ts"]),
                 float(row["r_multiple"]), str(blob["symbol"]))
            )
    zeilen.sort()
    return zeilen


def _band(werte: np.ndarray, k: int, rng: np.random.Generator) -> tuple[float, float]:
    """Was die Autokorrelation rein zufaellig erreicht -- durch Mischen."""
    null = [
        float(np.corrcoef(m[:-k], m[k:])[0, 1])
        for m in (rng.permutation(werte) for _ in range(RUNDEN))
    ]
    lo, hi = np.percentile(null, [2.5, 97.5])
    return float(lo), float(hi)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    args = parser.parse_args(argv)

    zeilen = lade(args.fills)
    rng = np.random.default_rng(7)
    r = np.array([z[2] for z in zeilen])
    print(f"{r.size:,} Trades, Mittel {r.mean():+.4f} R\n")

    # -- Der erste Eindruck, der falsch ist -------------------------------- #
    print("0. DER GEPOOLTE STROM -- was beim ersten Hinsehen herauskommt")
    for k in (1, 2, 3, 5, 10):
        rho = float(np.corrcoef(r[:-k], r[k:])[0, 1])
        lo, hi = _band(r, k, rng)
        marke = "  <- ausserhalb" if (rho < lo or rho > hi) else ""
        print(f"   Abstand {k:2d}: rho {rho:+.4f}   Band [{lo:+.4f}, {hi:+.4f}]{marke}")

    # -- A: konnte eine Regel ueberhaupt reagieren? ------------------------ #
    print("\nA. WAR DER VORIGE TRADE SCHON GESCHLOSSEN?")
    ueberlappt = sum(
        1 for i in range(1, len(zeilen)) if zeilen[i][0] < zeilen[i - 1][1]
    )
    paare = len(zeilen) - 1
    print(f"   ueberlappend: {ueberlappt:,} von {paare:,} ({ueberlappt/paare:.1%})")
    print(
        "   -> Bei diesen war der naechste Trade bereits offen, als das\n"
        "      Ergebnis des vorigen feststand. Keine Regel kann darauf\n"
        "      reagieren -- die Position existierte schon."
    )

    # -- B: innerhalb eines Marktes ---------------------------------------- #
    print("\nB. INNERHALB EINES MARKTES (echte Folge statt Gleichzeitigkeit)")
    for sym in sorted({z[3] for z in zeilen}):
        werte = np.array([z[2] for z in zeilen if z[3] == sym])
        if werte.size < MIN_TRADES:
            continue
        rho = float(np.corrcoef(werte[:-1], werte[1:])[0, 1])
        lo, hi = _band(werte, 1, rng)
        marke = "AUSSERHALB" if (rho < lo or rho > hi) else "innerhalb"
        print(
            f"   {sym:10s} n={werte.size:4d}  rho {rho:+.4f}  "
            f"Band [{lo:+.4f},{hi:+.4f}]  {marke}"
        )

    # -- C: nur nicht-ueberlappende Paare ---------------------------------- #
    print("\nC. NUR PAARE, AUF DIE EINE REGEL REAGIEREN KOENNTE")
    folge = [
        (zeilen[i - 1][2], zeilen[i][2])
        for i in range(1, len(zeilen))
        if zeilen[i][0] >= zeilen[i - 1][1]
    ]
    vorher = np.array([p[0] for p in folge])
    nachher = np.array([p[1] for p in folge])
    rho = float(np.corrcoef(vorher, nachher)[0, 1])
    null = [
        float(np.corrcoef(vorher, rng.permutation(nachher))[0, 1])
        for _ in range(RUNDEN)
    ]
    lo, hi = np.percentile(null, [2.5, 97.5])
    print(f"   n={len(folge):,}  rho {rho:+.4f}  Band [{lo:+.4f}, {hi:+.4f}]")

    verlust_vorher = vorher <= 0
    verlust_nachher = nachher <= 0
    nach_v = float(verlust_nachher[verlust_vorher].mean())
    nach_g = float(verlust_nachher[~verlust_vorher].mean())
    d = nach_v - nach_g
    null_d = []
    for _ in range(STREUNGSRUNDEN):
        m = rng.permutation(verlust_nachher)
        null_d.append(float(m[verlust_vorher].mean() - m[~verlust_vorher].mean()))
    dlo, dhi = np.percentile(null_d, [2.5, 97.5])
    print(f"   Verlust nach Verlust {nach_v:.2%}   nach Gewinn {nach_g:.2%}")
    print(f"   Unterschied {d:+.2%}   Band [{dlo:+.2%}, {dhi:+.2%}]")
    drin = dlo <= d <= dhi
    print(f"   -> {'innerhalb des Zufallsbandes' if drin else 'AUSSERHALB'}")

    print(
        "\nWAS DARAUS FOLGT FUER KURVENREGELN.\n"
        "Eine reaktive Regel braucht zwei Dinge: ein vergangenes Ergebnis, auf\n"
        "das sie reagieren kann, und einen Zusammenhang zum naechsten. Das\n"
        "erste fehlt bei zwei Dritteln der Trades, das zweite ueberall dort,\n"
        "wo man es sauber messen kann.\n\n"
        "Was BLEIBT, ist jede Regel, die NICHT vorhersagt: kleiner handeln, und\n"
        "Kapital beiseitelegen. Beide wirken, weil sie Risiko wegnehmen -- nicht,\n"
        "weil sie etwas wissen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
