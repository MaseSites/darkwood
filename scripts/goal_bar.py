"""Die Marke, abgeleitet — und jede Verwechslung daneben, damit keine zurückkommt.

**Der Anlass ist mein eigener Fehler, am 18.10.2026 von einem unabhängigen
Prüfer gefunden.** Ich habe den ganzen Abend mit **+0.42 R** als Anforderung für
das 20x-Sechsmonatsziel gerechnet. Die Zahl gehört aber zu einem *anderen Ziel*:

    Faktor 1,25 (12.000 -> 15.000) über 51 Trades bei 1 % = +0.4385 R

51 Gelegenheiten sind das **kurze Fenster bis 30.10.2026**, nicht sechs Monate.
Über sechs Monate sind es 662 Trades, und dort lautet die Marke **+0.4536 R**.
Dass die beiden Zahlen fast gleich aussehen, ist Zufall und war die Falle: die
51 gehören zu Faktor 1,25, die 662 zu Faktor 20.

Dazu zwei Folgefehler, beide in derselben Richtung — sie haben das System
günstiger aussehen lassen:

* „+0.42 R liegt beim 5-fachen der oberen Intervallgrenze" — richtig ist das
  **7,07-fache** gegen meine eigene Zahl und das **7,64-fache** gegen die
  korrekte.
* `scripts/study_venue_fee.py` trug eine **dritte** Marke: +0.3216 R aus
  20x / 312 Trades / **3 %** Risiko. Wieder ein anderes Risiko und eine andere
  Trade-Zahl.

Drei unverträgliche Marken in einem Abend, weil die Zahl in Prosa getragen und
nicht gerechnet wurde. Dieses Skript ist die Reparatur: es rechnet sie, zeigt
alle Verwechslungen **nebeneinander** und lässt sich nicht als Satz zitieren.

**Und der Punkt, der dabei am meisten zählt:** die Marke hängt an der Kadenz.
Weniger Trades heissen eine **höhere** Marke je Trade. Ein Kandidat, der auf
langsameren Zeitebenen besser aussieht, muss darum an *seiner eigenen* Kadenz
gemessen werden — sonst liest sich eine geringere Frequenz als Verbesserung.

    python scripts/goal_bar.py
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import numpy as np

from traidingbrain.learn.target import (
    required_mean_r,
    shortfall_from_variance,
    sustainable_rate,
)
from traidingbrain.sim.metrics import bootstrap_mean

#: Das Sechsmonatsziel des Masterauftrags.
ZIEL_20X, TAGE_6M = 20.0, 182.0

#: Das kurze Fenster, zu dem die 51 Gelegenheiten gehören. 12.000 -> 15.000.
ZIEL_FRIST, TRADES_FRIST = 1.25, 51.0

#: Platzdeckel aus `config/risk.yaml`.
SLOTS = 5

#: Die Kadenz des Kandidaten „Setup A auf D1+H4". Aus Briefing 02; weniger
#: Trades, also eine HOEHERE Marke -- genau die Kopplung, die dieses Skript
#: sichtbar machen soll.
TRADES_A_D1H4 = 401.0


def lade_r(root: Path) -> tuple[np.ndarray, list[float], dict[str, np.ndarray]]:
    """R-Werte, Haltedauern in Stunden, und dieselben R je Markt.

    Die dritte Rueckgabe ist fuer das geclusterte Intervall noetig: ein Mittel
    ueber zwoelf Maerkte braucht die Marktgrenzen, und sie hinterher aus einer
    flachen Liste zu erraten ist nicht moeglich.
    """
    r: list[float] = []
    halte: list[float] = []
    je_markt: dict[str, np.ndarray] = {}
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        werte = [float(row["r_multiple"]) for row in blob["fills"]]
        je_markt[str(blob["symbol"])] = np.array(werte, dtype=float)
        r.extend(werte)
        halte.extend(
            (int(row["closed_ts"]) - int(row["opened_ts"])) / 3_600_000.0
            for row in blob["fills"]
        )
    return np.array(r, dtype=float), halte, je_markt


def bonferroni_cluster_interval(
    je_markt: dict[str, np.ndarray], *, comparisons: int, draws: int
) -> tuple[float, float]:
    """Das operative Intervall dieses Projekts: Bonferroni UND Cluster je Markt.

    Zwei Korrekturen, und jede hat ihren eigenen Grund:

    * **Bonferroni**, weil das Register `total_comparisons` Vergleiche fuehrt und
      ein Abnahmekriterium dieses Projekts ein korrigiertes Intervall ohne die
      Null verlangt.
    * **Cluster je Markt**, weil 7.335 Fills ueber zwoelf Maerkte nicht
      unabhaengig sind. Gemessen am 18.10.2026: die Halbbreite waechst von
      0.0319 (i.i.d.) auf 0.0391 (geclustert), also um ein Viertel -- und mit
      Bonferroni zusammen von 0.0319 auf **0.0649**, also auf das Doppelte.
      `sim/metrics.bootstrap_mean` tut keines von beidem; es bleibt
      unveraendert, weil es in gespeicherten Berichten steckt, aber es ist fuer
      ein NIVEAU ueber mehrere Maerkte zu eng.

    Gezogen werden Maerkte, nicht Fills, und der Mittelwert wird nach echter
    Marktgroesse gewichtet -- sonst zaehlte BTCUSDT mit 263 Fills so viel wie
    ATOMUSDT mit 910.

    Die Ziehungszahl ist nicht beliebig: bei alpha = 0.05/73 liegen in jedem
    Schwanz nur `draws * alpha/2` Resamples. Mit 20.000 sind das 6,8, und ein
    Quantil aus sieben Punkten ist saatabhaengig -- dieser Fehler ist in diesem
    Projekt schon einmal passiert. Mit 200.000 sind es 68,5.
    """
    namen = list(je_markt)
    summen = np.array([je_markt[n].sum() for n in namen])
    zahlen = np.array([je_markt[n].size for n in namen])
    rng = np.random.default_rng(7)
    idx = rng.integers(0, len(namen), size=(draws, len(namen)))
    mittel = summen[idx].sum(axis=1) / zahlen[idx].sum(axis=1)
    alpha = 0.05 / comparisons
    return (
        float(np.quantile(mittel, alpha / 2.0)),
        float(np.quantile(mittel, 1.0 - alpha / 2.0)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--draws", type=int, default=20_000)
    # Die Vergleichszahl des Registers. Als Argument, damit sie nachgerechnet
    # und nicht geglaubt wird.
    parser.add_argument("--comparisons", type=int, default=73)
    args = parser.parse_args(argv)

    r_werte, halte, je_markt = lade_r(args.fills)
    mittel = statistics.fmean(halte)
    median = statistics.median(halte)
    pro_tag = sustainable_rate(slots=SLOTS, holds_h=halte)
    trades_6m = pro_tag * TAGE_6M

    print(f"{len(r_werte):,} Fills aus {args.fills}\n")
    print("1. DIE KADENZ, GEMESSEN")
    print(f"   Haltedauer  Mittel {mittel:7.2f} h   Median {median:7.2f} h")
    print(f"   {SLOTS} Plaetze / MITTEL  -> {pro_tag:6.2f} Trades/Tag")
    print(f"   ueber {TAGE_6M:.0f} Tage          -> {trades_6m:7.0f} Trades")
    print(
        f"   (Mit dem MEDIAN kaeme {SLOTS / median * 24.0:6.2f}/Tag heraus, also "
        f"{SLOTS / median * 24.0 * TAGE_6M:,.0f} Trades -- Little's Law braucht\n"
        f"    den Mittelwert, und dieser Fehler hat die Marke schon einmal\n"
        f"    um Faktor 5 zu klein gemacht.)"
    )

    # -- 2. Die eine richtige Marke, und jede Verwechslung daneben ---------- #
    print("\n2. DIE MARKE -- UND DIE DREI, DIE ICH VERWECHSELT HABE")
    faelle = (
        ("20x ueber 6 Monate", ZIEL_20X, trades_6m, args.risk, "DIE RICHTIGE MARKE"),
        (
            "Faktor 1,25 bis 30.10.",
            ZIEL_FRIST,
            TRADES_FRIST,
            args.risk,
            "<- hier kamen meine '+0.42 R' her, anderes ZIEL und anderes FENSTER",
        ),
        (
            "20x ueber 51 Trades",
            ZIEL_20X,
            TRADES_FRIST,
            args.risk,
            "<- die Verknuepfung, die ich implizit behauptet habe",
        ),
        (
            "20x, 312 Trades, 3 %",
            ZIEL_20X,
            312.0,
            0.03,
            "<- die dritte Marke, aus study_venue_fee.py",
        ),
        (
            "20x bei A-Kadenz",
            ZIEL_20X,
            TRADES_A_D1H4,
            args.risk,
            "<- weniger Trades, HOEHERE Marke",
        ),
    )
    for name, ziel, n, risiko, note in faelle:
        marke = required_mean_r(growth=ziel, trades=n, risk=risiko)
        print(f"   {name:24s} n={n:7.0f} @{risiko:.0%}  {marke:+8.4f} R   {note}")

    marke = required_mean_r(growth=ZIEL_20X, trades=trades_6m, risk=args.risk)

    # -- 3. Was +0.42 R wirklich erreicht ---------------------------------- #
    print("\n3. WAS EINE MARKE WIRKLICH ERREICHT (Gegenprobe in die andere Richtung)")
    for r in (0.42, marke):
        for n, label in ((TRADES_FRIST, "51 Trades"), (trades_6m, f"{trades_6m:.0f} Trades")):
            erreicht = (1.0 + r * args.risk) ** n
            print(f"   {r:+.4f} R ueber {label:14s} -> Faktor {erreicht:7.3f}")

    # -- 4. Gegen das Gemessene, mit GENANNTEM Intervall -------------------- #
    print("\n4. GEGEN DAS GEMESSENE")
    print(
        "   Welches Intervall, steht dabei -- und das ist kein Formalismus.\n"
        "   Der erste Entwurf dieses Skripts nannte 23.66x, weil er das\n"
        "   unkorrigierte i.i.d.-Intervall zitierte. Das operative Tor dieses\n"
        "   Projekts ist Bonferroni UND Clusterung je Markt."
    )
    einfach = bootstrap_mean(r_werte, samples=args.draws)
    operativ = bonferroni_cluster_interval(
        je_markt, comparisons=args.comparisons, draws=max(args.draws, 200_000)
    )
    print(f"\n   Punktwert                       {float(r_werte.mean()):+.4f} R")
    print(f"   i.i.d., 95 %, unkorrigiert      [{einfach.low:+.4f}, {einfach.high:+.4f}]")
    print(
        f"   Bonferroni({args.comparisons}) + Cluster     "
        f"[{operativ[0]:+.4f}, {operativ[1]:+.4f}]   <- das operative"
    )
    print(f"\n   Marke                           {marke:+.4f} R")
    print(f"   gegen die obere Grenze, i.i.d.  {marke / einfach.high:6.2f}x  (zu guenstig)")
    print(f"   gegen die obere Grenze, operativ {marke / operativ[1]:6.2f}x")

    # -- 5. Die konstante-R-Annahme, bemessen ------------------------------ #
    print("\n5. DIE ANNAHME HINTER DER FORMEL, BEMESSEN")
    print(
        "   `required_mean_r` nimmt an, dass JEDER Trade dasselbe R liefert.\n"
        "   Bei einer streuenden Verteilung ist das zusammengesetzte Wachstum\n"
        "   kleiner (Jensen), die Marke also eine OPTIMISTISCHE Untergrenze."
    )
    verschoben = r_werte - float(r_werte.mean()) + marke
    tatsaechlich, als_konstant = shortfall_from_variance(
        r_values=verschoben, risk=args.risk, trades=trades_6m
    )
    print(
        f"   Dieselbe Verteilung auf den Mittelwert {marke:+.4f} R verschoben:\n"
        f"     konstantes Modell sagt   {als_konstant:8.2f}x\n"
        f"     die echte Streuung gibt  {tatsaechlich:8.2f}x\n"
        f"     Fehlbetrag               {als_konstant - tatsaechlich:8.2f}x"
    )
    print(
        "\n   Also: die Marke oben reicht NICHT fuer 20x, wenn die Streuung so\n"
        "   bleibt wie gemessen. Sie ist die Untergrenze, nicht die Anforderung."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
