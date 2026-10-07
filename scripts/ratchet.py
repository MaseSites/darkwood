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
    (
        "Volatilitaetsausbruch",
        "erledigt",
        "42 Zustandszellen, 2 Horizonte: kein Treffer. Der eine Kandidat (hohe "
        "ATR-Perzentile) scheitert an der Korrektur UND wiederholt sich im "
        "anderen Fenster nur zu 0.16-0.26x.",
    ),
    (
        "VWAP und Tageszeit",
        "erledigt",
        "Drei Sessions, 2 Horizonte: Differenz unter 0.01%, Intervalle mit Null.",
    ),
    (
        "Mean Reversion",
        "erledigt",
        "Brutto 0.17 bp auf M15 (700k Beobachtungen), reproduziert das Preprint. Maut 79x.",
    ),
    ("Handelsspannen-Ausbruch", "erledigt", "Donchian-Position in Terzilen: kein Band ohne Null."),
    (
        "Momentum mit Volumen",
        "erledigt",
        "Bewegung gekreuzt mit Relativvolumen: kein Band ohne Null.",
    ),
    (
        "Trendfolge mit Ruecksetzer",
        "erledigt",
        "Umgekehrt widerlegt: OHNE Ruecksetzer ist am besten (+0.367%), und das "
        "wiederholt sich im anderen Fenster nur zu 0.29x. Tiefe Ruecksetzer sind "
        "schlechter, nicht besser.",
    ),
    (
        "Regime-Umschaltung",
        "erledigt",
        "Umschaltgewinn als Differenz der Differenzen: +0.257% [-0.073, +0.609] auf "
        "24h, +0.007% [-1.139, +1.121] auf 168h. Beide mit Null.",
    ),
    (
        "Funding / Relative Value",
        "erledigt",
        "Funding als Perzentil-Merkmal, 2 Horizonte: kein Band ohne Null.",
    ),
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
        "Makro (FRED)",
        "erledigt",
        "Sechs Serien ohne Schluessel ueber den CSV-Weg, 10-65 Jahre. P gegen P+M "
        "auf gemeinsamem Fenster: auf ALLEN drei Horizonten schlechter als Preis "
        "allein (+1.87 -> +1.21, -0.03 -> -0.44, -0.75 -> -1.02). Durchgehende "
        "Richtung ist die Signatur von Rauschen. P+M+O mit 22 Merkmalen ebenso: "
        "-1.61 bis +0.91, jedes Intervall mit Null.",
    ),
    (
        "On-Chain und Stablecoin-Liquiditaet",
        "erledigt",
        "Erste Achse ausserhalb der Boerse. Coin Metrics Community (9-11.8 J) plus "
        "DefiLlama (8.8 J), inkl. Boersen-Zu-/Abfluessen -- die der Auftrag als "
        "kostenlos unbestaetigt einstufte. P gegen P+O auf gemeinsamem Fenster, "
        "16 statt 7 Merkmale: kein Vorsprung, und bei 72h/LightGBM ein Intervall "
        "ohne Null in die FALSCHE Richtung (-3.66). Fluesse nur fuer BTC und ETH.",
    ),
    (
        "Laengere Horizonte (mit Derivaten)",
        "erledigt",
        "Herkunft nachgemessen (Bybit, exakt). P gegen P+D auf gemeinsamem Fenster: "
        "Unterschied +-1.6 Punkte ohne Richtung, jedes Intervall mit Null.",
    ),
    (
        "Funding-Carry (ohne Richtung)",
        "erledigt",
        "Nicht 'Funding als Merkmal fuer die Richtung' (das ist die Zeile darueber "
        "und ist tot), sondern Funding EINSAMMELN: Perp short gegen Spot long, "
        "Preis herausgehedgt, keine Vorhersage noetig. 12 Maerkte, 3.8-6.7 Jahre: "
        "11 von 12 mit Intervall ueber Null, +5.5% bis +14.8% p.a. aufs Notional "
        "(BNBUSDT bei null -- und das ist ECHT: seine 49.6% exakten Nullen sind an "
        "200 identischen Zeitstempeln zu 73/73 auch bei Binance null, also "
        "observed_zero. Der Ausschluss am 06.10. war ein Fehler). "
        "HERKUNFT: das Verzeichnis mischt zwei Boersen -- 4 Maerkte Bybit, 8 Binance, "
        "an identischen Zeitstempeln gemessen. panel.py fuehrt funding seit je als "
        "'gemischte Boerse'; die Studie hat check_provenance nie aufgerufen. "
        "Auf dem GEMEINSAMEN Kalenderfenster fallen 11 von 12 (Bybit 4/4, Binance "
        "7/8) -- der Rueckgang ueberlebt, aber zwoelf korrelierte Maerkte sind EINE "
        "Beobachtung eines gemeinsamen Trends, nicht zwoelf. Ursache offen. "
        "Basisrisiko ungemessen (keine Spot-Reihe), Liquidation des Short-Beins "
        "nicht modelliert. Auswahl der guten Perioden hilft nicht: bei PERFEKTER "
        "Voraussicht schlaegt sie in 7 von 11 Maerkten nicht einmal das blosse "
        "Durchhalten, weil jede Auswahl die Maut erneut zahlt. Beste Zelle "
        "ueberhaupt, mit Kenntnis jeder zukuenftigen Rate: 12.000 -> 12.027.",
    ),
    (
        "Ausgangspolitik (E3)",
        "erledigt",
        "E3, vorab registriert. Die Frage, die am laengsten offen blieb, weil der "
        "Bericht sie mit einer Kuerzungsrechnung geschlossen hatte: Groesse und "
        "Hebel kuerzen sich aus net_r heraus, der STOP nicht -- er verschiebt den "
        "Ausstiegszeitpunkt und damit den ganzen Pfad. study_stop_path.py hatte "
        "gemessen, dass die Annahme 'gleicher Pfad' oft verletzt ist, und "
        "ausdruecklich gesagt, dass nur ein neu simulierter Pfad entscheidet. "
        "7.255 Faelle, 12 Maerkte, jeder Arm auf DENSELBEN Einstiegen, gepaart je "
        "Trade, korrigiert auf 46 Vergleiche: Basis (Stop+Ziel, 48h) -0.0205 R bei "
        "14.4h Haltezeit; Stop+24h-Uhr ohne Ziel -0.0824 R, gepaart -0.0619 "
        "[-0.1316, +0.0071]; Stop+2.0-ATR-Trail -0.0762 R, gepaart -0.0557 "
        "[-0.1123, -0.0060] -- ZUVERLAESSIG SCHLECHTER, Intervall ohne Null auf "
        "der falschen Seite. "
        "WARUM: das Ziel arbeitet. 31.1% der Trades verlassen darueber, und beide "
        "Alternativen nehmen genau diese Tuer weg. Bei E3.3 faellt die Haltezeit "
        "von 14.4 auf 7.9h und der Trail greift in 99% der Faelle -- ein "
        "Trailing-Stop, der fast immer zuerst greift, ist kein Gewinnschutz, "
        "sondern ein engerer Stop mit mehr Schritten. "
        "UND UMGEKEHRT, erstmals in diesem Register: die BESTEHENDE Politik ist "
        "messbar besser als beide Alternativen. Das macht das System nicht "
        "profitabel, aber es schliesst eine Richtung, in die zu optimieren waere. "
        "Die 2.0 ATR standen vorab fest und wurden nicht nachjustiert.",
    ),
    (
        "Carry nach Basis, Maut und Margin (E6)",
        "erledigt",
        "E6.1, und es nimmt dem Projekt die letzte Zahl mit positivem Vorzeichen. "
        "Der Carry las +5.5 bis +14.8% p.a. aufs Notional -- das ist die EINNAHME, "
        "nicht der Ertrag. Blockiert war E6 an 'keine Spot-Reihe auf der Platte'; "
        "backfill_spot.py holt sie fuer die acht Maerkte mit BINANCE-Funding (die "
        "anderen vier tragen Bybit und waeren kein Same-Venue-Arm), je 33.013 "
        "Stundenkerzen. "
        "DIE BASIS WAR NICHT DAS PROBLEM, und das ist selbst ein Ergebnis: mit "
        "Spot long und Perp short ist der Preis-PnL exakt q*(b_ein - b_aus), alles "
        "andere kuerzt sich, und die Basis bewegt sich ueber 30 Tage um +-0.002% -- "
        "sie kehrt zurueck, weil Perp und Spot konvergieren. Hypothese geprueft und "
        "widerlegt. DIE MAUT war es: 0.280% je Runde gegen 0.2 bis 0.5% Funding in "
        "30 Tagen. "
        "Die Maut faellt je RUNDE, das Funding je ZEIT, also verduennt langes "
        "Halten sie -- Vorhersage aus der Zerlegung, alle vier Haltedauern "
        "berichtet. Bei 180 Tagen +1.5554% je Fenster mit [+0.2405, +3.0046], das "
        "ERSTE MAL im Projekt, dass etwas nach voller Kostenrechnung ein "
        "korrigiertes Intervall ohne Null schafft. "
        "UND DANN FIEL ES AM ZWEITEN TOR: Replikation frueher +2.9374% gegen "
        "spaeter -0.1120%, Verhaeltnis -0.04x gegen das Band 0.5-2.0, Vorzeichen "
        "gekippt. Der ganze Befund stammt aus der frueheren Haelfte -- der "
        "Anschluss an das bekannte Schrumpfen des Fundings in 11 von 12 Maerkten. "
        "Ab 2024-11-18 allein: bei keiner Haltedauer positiv, bei 30 Tagen "
        "zuverlaessig NEGATIV mit [-0.3323, -0.0762]. Ein Tor allein haette hier "
        "einen Kandidaten gemeldet -- das ist der Fall, der die Doppelpruefung "
        "rechtfertigt. "
        "Hebel rettet die Kapitaleffizienz nicht: Spot bindet voll, der Short "
        "bindet Margin, bei 1x ist der Nenner 2x Notional, und selbst bei 1x wird "
        "das Short-Bein in bis zu 4.2% der 30-Tage-Fenster liquidiert, bei 5x in "
        "ueber einem Drittel.",
    ),
    (
        "Haltezone (Wechsel statt Signal bepreisen)",
        "erledigt",
        "E2, vorab registriert. Der vorhandene Kostenfilter fragt 'ist die runde "
        "Fahrt klein gegen das Risiko'; das ist etwas anderes als 'rechtfertigt der "
        "erwartete Gewinn einen WECHSEL'. Eine bestehende Position zu halten kostet "
        "keine runde Fahrt. BTC und ETH auf H1, 8.780 Kerzen Bestaetigungsfenster, "
        "Ridge und XGBoost, Hauptschwelle 1.5x vorab festgelegt: die Haltezone "
        "handelt fast nicht, weil der Forecast nie genug verspricht (Ridge: 0 "
        "Wechsel; XGBoost: 27 bzw. 49). Ihr Ergebnis ist von null nicht zu trennen "
        "(+0.12% [-93.4, +87.9] auf BTC). Die NAIVEN Arme dagegen haben Intervalle, "
        "die die Null negativ ausschliessen: -124% bis -176%, davon 94 bis 171 "
        "Punkte reine Maut. Churning ist belegt schaedlich; die Zone ist belegt "
        "wirkungslos. "
        "WICHTIGER ALS DAS ERGEBNIS: die erste Fassung meldete +1018% netto. Die "
        "Merkmale nutzten close[t], das Ziel open[t+1]/open[t] -- auf H1 ist das "
        "dasselbe, Korrelation +0.9999. Um eine Kerze verschoben: -0.0059. Neuntes "
        "Scheinfund, groesstes bisher. `assert_no_leak` bricht jetzt ab, wenn ein "
        "Merkmal ueber 0.2 mit dem Ziel korreliert.",
    ),
    (
        "Meta-Labeling (Auswahl unter den Signalen)",
        "erledigt",
        "E1, vorab registriert in audit/EXPERIMENTS_NEXT.yaml. Die Begruendung, mit "
        "der die Frage vorher geschlossen war, traegt nicht: ein Pool ohne Vorteil "
        "schliesst keine positive Teilmenge aus (study_subset.py: Pool -0.0906 R, "
        "rating_band=eindeutig +0.0311 R, beides ex ante bekannt). "
        "Gemessen auf 42.849 gelabelten Kandidaten aus 11 Maerkten, genommene UND "
        "abgelehnte, drei Zeitfenster mit 72h Purge, Schwelle im Entwicklungsfenster "
        "eingefroren: Pool -0.1485 R, Zufallsfilter gleicher Selektivitaet -0.1626 R, "
        "logistische Regression -0.1052 R, flaches LightGBM -0.0908 R. "
        "BEIDE Modelle schlagen den Zufallsfilter -- es gibt also Auswahlsignal -- "
        "und bleiben absolut NEGATIV. Abnahme (a) verfehlt. "
        "Lehrstueck dazu: auf nur zwei Maerkten las dieselbe Rechnung +0.0160 R und "
        "sah wie ein Kandidat aus. Elf Maerkte drehen das Vorzeichen.",
    ),
    (
        "Querschnitt (Markt gegen Markt)",
        "erledigt",
        "Die einzige Richtung, die der Auftrag nie benannt hat: alle 87 Arme davor "
        "massen einen Markt gegen seine EIGENE Zukunft, mit 'immer long' als Basis "
        "-- also den gemeinsamen Faktor gegen sich selbst. Long oberstes Drittel / "
        "short unterstes, 12 Maerkte, 5 Jahre, 6 Zellen: eine ohne Null (mom_7/1T, "
        "+0.1036% brutto, +0.0710% nach zwei Beinen Maut), und die faellt an der "
        "Korrektur (99.17%) UND wiederholt sich nur zu 0.04x (+0.1897% -> +0.0071%). "
        "Der gemeinsame Faktor war nicht das, was die Suche verdeckt hat.",
    ),
)


def decide(rows: list[tuple], *, consultations: int) -> None:
    """The three-way verdict the research order asks for, read off the register.

    "Belastbarer Kandidat, noch unklar, oder kein belegter Vorteil." It is
    computed here rather than asserted, so it cannot drift away from what was
    actually measured.

    **Two rows of the table must not be compared, and it is easy to miss.**
    Every row stores `champion_mean_r`, and for every row that number is the
    champion's **R**. Rows measured in rank correlation or in hit-rate edge
    carry it too, so a query like `low > champion_mean_r` across the whole
    table reports 37 "winners" -- correlation intervals clearing an R figure
    because the two happen to be on comparable-looking scales. I wrote exactly
    that query while adding this function and believed it for about a minute.

    `Register.judge` is not fooled: its first check is `unit != "R"`. This
    function applies the same rule, and says so out loud, because the trap sits
    in plain sight in the table above and the next reader deserves the warning
    rather than the lesson.
    """
    # arm, stage, n, mean_r, low, high, unit, champion_mean_r, ...
    comparable = [r for r in rows if r[6] == "R"]
    holdout = [r for r in comparable if r[1] == "holdout"]
    tested = [r for r in comparable if r[1] == "test"]

    def excludes_champion(row: tuple) -> bool:
        low, high, base = float(row[4]), float(row[5]), float(row[7])
        # A zero-width interval is not a narrow one, it is a missing one: some
        # arms were recorded before an interval was computed for them, and
        # [0.0000, 0.0000] would otherwise sail past every comparison below
        # while carrying no evidence at all.
        return low < high and low > base

    no_interval = [r for r in comparable if float(r[4]) >= float(r[5])]
    winners = [r for r in holdout if excludes_champion(r)]
    candidates = [r for r in tested if excludes_champion(r)]

    print("\n" + "=" * 78)
    print("Die Entscheidung, die der Forschungsauftrag verlangt")
    print("=" * 78)
    print(
        f"\n  {len(rows)} Zeilen im Register, davon {len(comparable)} in R gemessen und damit\n"
        f"  ueberhaupt mit dem Champion vergleichbar: {len(tested)} aus Testfenstern,\n"
        f"  {len(holdout)} aus dem Prueffenster. Nur das Prueffenster kann ein Urteil tragen."
    )
    if no_interval:
        names = ", ".join(sorted({r[0] for r in no_interval}))
        print(
            f"\n  Ohne Intervall aufgenommen ({len(no_interval)} Zeilen): {names}.\n"
            f"  Null Breite ist kein enges Intervall, sondern gar keins -- diese Zeilen\n"
            f"  zaehlen unten nirgends mit."
        )

    if winners:
        print(f"\n  BELASTBARER KANDIDAT: {', '.join(sorted({r[0] for r in winners}))}")
    elif holdout:
        print("\n  NOCH UNKLAR: Prueffenster-Ergebnisse liegen vor, aber keines schliesst")
        print("  den Champion aus.")
    else:
        print("\n  KEIN BELEGTER VORTEIL.")
        print(
            f"\n  Kein Arm ist je im Prueffenster gemessen worden "
            f"({consultations} Konsultationen)."
        )
        if candidates:
            names = ", ".join(sorted({r[0] for r in candidates}))
            print(
                f"\n  Auf Testfenstern gibt es {len(set(r[0] for r in candidates))} Arm mit einem "
                f"Intervall ueber dem\n  Champion: {names}. Das ist ein Kandidat und kein Urteil "
                f"-- die Testfenster\n  sind ueber jeden je versuchten Arm gelesen worden, und "
                f"genau so sahen alle\n  acht verworfenen Hypothesen zuerst aus."
            )
        else:
            print(
                "\n  Auch auf den Testfenstern hat kein Arm ein Intervall, das den Champion\n"
                "  ausschliesst."
            )
        print(
            "\n  Das Prueffenster ist unangetastet, und das ist eine Entscheidung, keine\n"
            "  Luecke: es aufzubrauchen, ohne einen Kandidaten zu haben, der die\n"
            "  Konsultation wert ist, haette die einzige Munition verschossen, die noch\n"
            "  da ist."
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
        f"{len(gated)} gesperrt."
    )
    if remaining:
        print(
            f"  Bei einem entscheidenden Test pro Familie: {remaining} Tests.\n"
            f"  Halbiert sich der Rest mit jedem Test, sind es "
            f"{math.ceil(math.log2(remaining)) if remaining > 1 else remaining} Schritte."
        )
    else:
        # An exhausted map is a state, not a bug, and "0 Tests, 0 Schritte"
        # read like one. It is also the most informative thing this register
        # has ever printed, so it says so in words.
        print(
            "\n  DIE KARTE IST ABGEARBEITET. Jede Familie, die der Forschungsauftrag\n"
            "  benannt hat, ist gemessen, und keine ist positiv. Das ist kein\n"
            "  Scheitern des Suchens, sondern sein Ergebnis: der angemeldete Raum\n"
            "  ist leer.\n"
            "\n  Was daraus NICHT folgt: dass es nichts gibt. Es folgt, dass es nicht\n"
            "  in diesem Raum liegt -- in Preis, Volumen, Volatilitaet, Spanne,\n"
            "  Tageszeit, Orderfluss, Positionierung, Funding, Regime oder Horizont.\n"
            "  Diese Liste war der Auftrag, nicht die Welt.\n"
            "\n  Auch die erste Achse AUSSERHALB der Boerse ist inzwischen gemessen:\n"
            "  Kettenaktivitaet, Boersen-Zu- und -Abfluesse, Stablecoin-Umlauf, 9 bis\n"
            "  11.8 Jahre je Markt. Sie traegt nichts bei, und bei einem Horizont\n"
            "  macht sie das Modell messbar schlechter.\n"
            "\n  Was wirklich offen bleibt, sind drei Dinge und keines davon ist eine\n"
            "  Strategie-Idee:\n"
            "    1. FRED-Makrodaten. Brauchen einen kostenlosen API-Schluessel, der\n"
            "       hier nicht vorliegt. Connector-Muster steht, Serien sind benannt.\n"
            "    2. Boersenfluesse jenseits von BTC und ETH. Das Community-Angebot\n"
            "       liefert sie fuer zwei Maerkte; mehr ist kostenpflichtig.\n"
            "    3. Das Vorwaerts-Protokoll. Das einzige Beweismittel, das Replay\n"
            "       nicht erzeugen kann, und es waechst nur mit der Zeit."
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
    decide(rows, consultations=consultations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
