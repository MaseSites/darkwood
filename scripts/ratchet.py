"""The ratchet: who the champion is, what has been tried, what it would take.

    python scripts/ratchet.py                 # show the state
    python scripts/ratchet.py --seed          # write today's history, once

Severin asked how to trade so that it only gets better from here. No strategy
can promise that; a process can. This is the process made visible: one frozen
champion, every challenger ever tried including the failures, and a reserved
window nobody may look at during exploration.

**Why the failures are the valuable rows.** Eight hypotheses were measured on
05.10.2026 and all eight failed. Had the best-looking of the eight been shipped,
noise would have been shipped -- with eight attempts, the best of eight looks
good by construction. A register that held only winners would report a selected
sample as if it were the whole, which is worse than no register. So `--seed`
writes all eight.

**Why they are filed as TEST and not as HOLDOUT, which is the subtle part.**
Those eight were measured on walk-forward test folds, read over and over as
each new idea arrived. The reserved holdout has never been consulted -- every
study in this project passed `holdout_days=0`. So the next holdout consultation
really is the first, and it gets the full confidence budget.

That is not a loophole, it is what a holdout is for: selecting a candidate on
earlier data is free, because the holdout is untouched. What costs is reading
the holdout itself, which is why `Register.consultations()` counts those and
tightens the bar each time.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.journal.version import run_signature
from traidingbrain.learn.register import (
    FAMILY_CONFIDENCE,
    MIN_HOLDOUT_TRADES,
    Register,
    Result,
    Stage,
)

#: What the system does today, measured over four markets and 3,300 taken
#: signals on 05.10.2026 (`scripts/study_refused.py --symbols
#: BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT`). This is the number to beat.
CHAMPION = Result(
    arm="heutige_konfiguration",
    stage=Stage.TEST,
    n=3300,
    mean_r=-0.0340,
    low=-0.080,
    high=0.012,
    note="4 Maerkte, 12.843 gelabelte Signale, Setups A/B/E/F/G, M15, Kostendeckel 0.15",
)

#: The declared horizon series used to be a hand-copied table here. It is
#: gone, and the reason is worth keeping.
#:
#: It recorded "directional hit rate minus base rate" as the arm's value --
#: two quantities estimated separately from the same rows and subtracted. That
#: is not a test, and it fired: a 358-row subset showed 59.50% against a
#: 46.65% base rate and was reported as beating it, while the net interval
#: still spanned zero. The paired difference -- the model's hit minus
#: always-long's hit, row by row, so the market's drift cancels -- gives
#: +12.85 points with an interval of [-3.52, +27.17]. Undecided, like the
#: other twenty-three cells.
#:
#: `scripts/study_panel.py --register` now writes those arms itself, with the
#: paired interval. Twenty-four rows copied by hand is also how a wrong `n`
#: reaches a register, which happened once today already.


#: Moving the entry away from the market, in fractions of the stop distance.
#:
#: The last mechanical lever this project's own arithmetic left open. `net_r` is
#: `(captured move - fee) / stop fraction`, so stop, size and leverage cancel
#: and only a lower fee or more captured movement can change the sign. An audit
#: found the limit sits at the market -- 97.5% of fills take the open branch,
#: 96.2% of those at a price identical to the limit -- so placing it better was
#: the one untried way to capture more, and it would have earned the maker
#: rebate honestly rather than by accounting.
#:
#: It is worse, monotonically, at every offset. `netto je Fill` gets worse too,
#: which is the opposite of what the reward-to-risk arithmetic predicts: a
#: closer stop is hit more often, and the hold duration falls from 11h to 5h
#: across the range. The 0.00 row reproduces the champion's -0.0340 R, which
#: is what makes the rest of the column trustworthy.
#:
#: Recorded per *signal offered*, with an unfilled signal counted as zero. The
#: per-fill figure is a selection number: a larger offset fills fewer and more
#: favourable signals, so it improves even when the account does worse.
#:
#: Source: `scripts/study_entry.py`, 3,324 taken signals, 4 markets, 05.10.2026.
_ENTRY_ROWS: tuple[tuple[float, int, float, float, float, str], ...] = (
    # offset, fills, net per signal, low, high, note
    (0.05, 3187, -0.0473, -0.092, -0.001, "95.9% gefuellt, Intervall ohne Null"),
    (0.10, 3089, -0.0460, -0.092, 0.001, "92.9% gefuellt"),
    (0.20, 2869, -0.0482, -0.097, 0.002, "86.3% gefuellt"),
    (0.30, 2654, -0.0603, -0.113, -0.006, "79.8% gefuellt, Intervall ohne Null"),
    (0.50, 2269, -0.1075, -0.169, -0.046, "68.3% gefuellt, Haltedauer 5h statt 11h"),
)

ENTRY_OFFSET: tuple[Result, ...] = tuple(
    Result(
        arm=f"einstieg_versatz_{offset:.2f}".replace(".", "_"),
        stage=Stage.TEST,
        n=3324,
        mean_r=mean,
        low=low,
        high=high,
        note=f"{note}. Schlechter als die -0.0338 R bei Versatz null.",
    )
    for offset, _fills, mean, low, high, note in _ENTRY_ROWS
)


#: Every challenger measured on 05.10.2026, with the number actually obtained.
#:
#: Two are recorded in a foreign unit. The forward-score arms produced a rank
#: correlation, not an expectancy, and `Register.judge` refuses to let a
#: foreign unit crown anything -- but the attempt is real and has to be
#: countable, because the count is what a later threshold is corrected for.
TRIED: tuple[Result, ...] = (
    Result(
        arm="gebuehr_minus_10",
        stage=Stage.TEST,
        n=3300,
        mean_r=-0.0291,
        low=-0.075,
        high=0.017,
        note="BNB-Rabatt. Besser, aber die Null liegt bei 69% Rabatt.",
    ),
    Result(
        arm="gebuehr_minus_25",
        stage=Stage.TEST,
        n=3300,
        mean_r=-0.0217,
        low=-0.067,
        high=0.024,
        note="VIP 1 + BNB. Reicht nicht; selbst bei Gebuehr null nur +0.0151 R.",
    ),
    Result(
        arm="lernfilter",
        stage=Stage.TEST,
        n=433,
        mean_r=-0.0605,
        low=-0.230,
        high=0.100,
        note=(
            "Findet echte Struktur (0 von 100 Zufallslaeufen, p ~ 0.010) und ist "
            "0.0689 R schlechter als die bestehenden Regeln. Zwei verschiedene Fragen."
        ),
    ),
    Result(
        arm="zieldeckel_1_75R",
        stage=Stage.TEST,
        n=549,
        mean_r=-0.0201,
        low=-0.160,
        high=0.120,
        note="Trefferquote stieg 38.6% -> 41.9%, pro Trade schlechter. Hit rate taeuscht.",
    ),
    Result(
        arm="chance_risiko_regel_lockern",
        stage=Stage.TEST,
        n=4745,
        mean_r=-0.1334,
        low=-0.047,
        high=0.012,
        note="Abgelehnte treffen 55% und verlieren 0.13 R. Die Regel hat recht.",
    ),
    Result(
        arm="kostenregel_lockern",
        stage=Stage.TEST,
        n=4726,
        mean_r=-0.2996,
        low=-0.099,
        high=-0.011,
        note="Schlechteste Gruppe im Protokoll, Intervall ohne Null. Die Regel hat recht.",
    ),
    Result(
        arm="mehr_plaetze",
        stage=Stage.EXPLORE,
        n=0,
        mean_r=0.0,
        low=0.0,
        high=0.0,
        unit="nicht messbar",
        note=(
            "max_open_positions ist toter Konfigurationstext; SimBroker hat einen Platz, "
            "hart im Code. 1 von 24 belegt. Nicht als Arm messbar ohne Umbau."
        ),
    ),
    Result(
        arm="vorhersage_5h",
        stage=Stage.TEST,
        n=34400,
        mean_r=0.0039,
        low=0.0,
        high=0.0,
        unit="Rangkorrelation",
        note="35 Merkmale, p 0.52-0.58. Bei null ist jede Bandbreite gleich gut.",
    ),
    Result(
        arm="vorhersage_10h",
        stage=Stage.TEST,
        n=34395,
        mean_r=0.0045,
        low=0.0,
        high=0.0,
        unit="Rangkorrelation",
        note="35 Merkmale, p 0.26-0.48. Das Modell waehlte schlechter als der Durchschnitt.",
    ),
    *ENTRY_OFFSET,
)


#: The nine strategy families the research order asks for, and where each
#: stands. This is the quantity that can actually halve.
#:
#: Severin asked to be twice as good every day. Returns cannot do that -- from
#: 1,000 CHF a daily doubling exceeds the whole Bitcoin market cap in 31 days
#: and all the money in the world in 39, and doubling today's -0.034 R just
#: makes it -0.068. What *can* halve is the space of places an edge might be,
#: and every decisive test halves it. That is a real daily doubling pointed at
#: the only thing that can take one.
#:
#: Kept here rather than in the register because it is a map of the question,
#: not a record of answers: the register holds what was measured, this says
#: what is left. A family moves only on a measurement, and the note says which.
FAMILIES: tuple[tuple[str, str, str], ...] = (
    (
        "Fortsetzung / Zonen-Rueckkehr",
        "erledigt",
        "Die fünf ausgelieferten Setups. 9 Hypothesen, 8 tot, 1 unentschieden.",
    ),
    ("Volatilitaetsausbruch", "offen", "volatility_percentile existiert, war nie Ausloeser."),
    ("VWAP und Tageszeit", "offen", "VWAP liegt in formulas.py, in keinem Setup benutzt."),
    (
        "Mean Reversion",
        "erledigt",
        "Brutto 0.17 bp auf M15 (700k Beobachtungen), reproduziert das Preprint. Maut 79x.",
    ),
    ("Handelsspannen-Ausbruch", "offen", "Ungeprueft."),
    ("Momentum mit Volumen", "offen", "Als Familie ungeprueft."),
    ("Trendfolge mit Ruecksetzer", "offen", "Teilweise in den Setups, nie als Familie gemessen."),
    ("Regime-Umschaltung", "offen", "Regime wird berechnet, schaltet aber nie die Strategie."),
    ("Funding / Relative Value", "offen", "Daten liegen vor, nur als Kosten benutzt."),
    (
        "Orderflow (Taker-Volumen)",
        "erledigt",
        "30 Zellen, keine positiv. Fortsetzung und Erschoepfung trennen sich nicht.",
    ),
    (
        "Orderflow (Orderbuch-Tiefe)",
        "nicht testbar",
        "Keine historischen Snapshots; heutige genuegen nicht. Taker-Volumen war das Erreichbare.",
    ),
    (
        "Laengere Horizonte (Preis allein)",
        "erledigt",
        "24/72/168h, 2 Modelle, 3 Maerkte: keine Konfiguration schlaegt ihre Basisquote.",
    ),
    (
        "Laengere Horizonte (mit Derivaten)",
        "gesperrt",
        "Herkunft von Open Interest und Kontoverhaeltnis ungeklaert -- siehe coverage.py.",
    ),
)


def report_space() -> None:
    """What is left to look at, and how many decisive tests that is.

    Printed as a count rather than a promise. A daily target on *returns* is
    the pressure that manufactures fake progress -- on 05.10.2026 three tables
    looked like overwhelming findings and were artefacts, and a doubling target
    would have shipped all three. A count of eliminated families cannot be
    flattered: it moves only when something is measured.
    """
    done = [f for f in FAMILIES if f[1] == "erledigt"]
    open_ = [f for f in FAMILIES if f[1] == "offen"]
    blocked = [f for f in FAMILIES if f[1] == "nicht testbar"]
    # "gesperrt" is not "nicht testbar": the test is possible and the data is
    # on disk, but its provenance is unexplained, so the result would not be
    # interpretable. Counting it as untestable would hide work that one
    # verified download unblocks.
    gated = [f for f in FAMILIES if f[1] == "gesperrt"]

    marks = {"erledigt": "[x]", "offen": "[ ]", "nicht testbar": "[-]", "gesperrt": "[!]"}
    print("\n" + "=" * 78)
    print("Der Suchraum -- die einzige Groesse hier, die sich halbieren laesst")
    for name, status, note in FAMILIES:
        print(f"  {marks[status]} {name:34s} {note}")
    remaining = len(open_)
    print(
        f"\n  {len(done)} erledigt, {remaining} offen, {len(blocked)} nicht testbar, "
        f"{len(gated)} gesperrt.\n"
        f"  Bei einem entscheidenden Test pro Familie: {remaining} Tests.\n"
        f"  Halbiert sich der Rest mit jedem Test, sind es "
        f"{math.ceil(math.log2(remaining)) if remaining > 1 else remaining} Schritte."
    )
    if gated:
        print(
            "\n  [!] heisst: messbar, aber das Ergebnis waere nicht deutbar. Die\n"
            "  Derivate-Dateien beginnen 2021-10-01, waehrend das Skript, das sie\n"
            "  holt, laut eigenem Docstring erst ab Maerz 2023 liefern kann. Ein\n"
            "  belegter Neu-Download hebt die Sperre."
        )
    print(
        "\n  Eine taegliche Verdoppelung der Rendite gibt es nicht: von 1.000 CHF\n"
        "  waere das nach 31 Tagen die ganze Bitcoin-Marktkapitalisierung und nach\n"
        "  39 Tagen alles Geld der Welt. Und doppelt so gut wie -0.034 R ist\n"
        "  -0.068 R -- erst das Vorzeichen, dann der Faktor."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Write the champion and today's nine attempts. Append-only, so safe to repeat.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    register = Register(config.engine.paths.data_dir / "experiments.sqlite")
    signature = run_signature(config)
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)

    if args.seed:
        if register.champion() is None:
            register.crown(CHAMPION, run_signature=signature, now_ms=now_ms, note=CHAMPION.note)
            print(f"Champion gekroent: {CHAMPION.arm}")
        for result in TRIED:
            register.record(result, run_signature=signature, now_ms=now_ms)
        print(f"{len(TRIED)} Versuche eingetragen (wiederholbar, es entstehen keine Duplikate).")

    champion = register.champion()
    print("\n" + "=" * 78)
    print(champion.describe() if champion is not None else "Kein Champion. --seed zuerst.")
    print(f"  {champion.note}" if champion is not None else "")

    rows = register.all()
    if rows:
        print(f"\n{len(rows)} Versuche im Register, {register.attempts()} verschiedene Arme:")
        print(f"  {'Arm':30s} {'Stufe':8s} {'n':>6s} {'Ergebnis':>10s}  Einheit")
        for row in rows:
            arm, stage, count, mean, unit = row[0], row[1], row[2], row[3], row[6]
            print(f"  {arm:30s} {stage:8s} {int(count):>6d} {float(mean):>+10.4f}  {unit}")

    consultations = register.consultations()
    required = 1.0 - (1.0 - FAMILY_CONFIDENCE) / max(1, consultations + 1)
    print(
        f"\nPrueffenster: {consultations} Konsultationen bisher.\n"
        f"Der naechste Arm braucht ein {100 * required:.2f}%-Intervall, das den Champion\n"
        f"ausschliesst, und mindestens {MIN_HOLDOUT_TRADES} Trades darin."
    )
    print(
        f"\nDie {len(rows)} Zeilen oben sind auf Testfenstern gemessen, die bei jeder neuen\n"
        "Idee wieder gelesen wurden -- darum ist keine davon ein Urteil. Das zurueck-\n"
        "behaltene Fenster hat noch nie jemand angesehen (jede Studie hat holdout_days=0\n"
        "uebergeben), also ist die naechste Konsultation wirklich die erste. Einen\n"
        "Kandidaten auf frueheren Daten auszuwaehlen ist gratis; was kostet, ist das\n"
        "Prueffenster selbst zu lesen, und genau das wird hier gezaehlt."
    )
    report_space()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
