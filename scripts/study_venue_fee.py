"""Was kostet es, dass die Gebühr von der falschen Börse kam?

**Der Befund, gemessen am 18.10.2026.** `config/settings.yaml` steht auf
`exchange.name: binance`, und Binance veröffentlicht über ccxt für alle zwölf
aktiven Perpetuals `taker = 0.0005` und `maker = 0.0002`. `DEFAULT_SPEC` in
`domain/market.py:83` trägt `taker_fee = 0.00055` -- **Bybits** Satz. Alle 7.335
Replay-Fills sind unter dieser Zahl entstanden.

Das ist kein Modellierungsstreit, sondern eine Herkunftsverwechslung: dieselbe
Klasse Fehler, die Phase 1 im Derivatespeicher behoben hat, nur in der
Gebührenspalte. Und sie zeigt in die ungünstige Richtung -- der Lauf hat sich
9,1 % zu viel Takergebühr berechnet.

**Warum das ohne Neulauf exakt zu rechnen ist.** Jeder gespeicherte Fill trägt
`entry_price`, `exit_price`, `qty`, `fees`, `risk_amount` und `net_pnl`. Die
Gebühr ist also rekonstruierbar, und dieses Skript rekonstruiert sie **erst
einmal gegen die gespeicherte Zahl**, bevor es irgendetwas korrigiert. Stimmt
die Rekonstruktion nicht bis auf Rundung, bricht der Lauf ab: eine Korrektur auf
einem Modell, das die Vergangenheit nicht reproduziert, ist eine erfundene Zahl.

**Was es nicht leistet.** Eine billigere Gebühr lässt MEHR Signale durch das
Kostengate (`sim/plan.py`, `max_cost_fraction_of_risk`). Die Population wäre
also leicht grösser, und dieser Teil braucht einen echten Neulauf. Gemessen wird
hier ausschliesslich der Effekt auf die **genommene** Population -- das ist die
Untergrenze des Effekts und die einzige Zahl, die ohne CPU-Stunden belegbar ist.
Der Bericht sagt das in seiner letzten Zeile selbst.

    python scripts/study_venue_fee.py
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from traidingbrain.learn.target import required_mean_r
from traidingbrain.sim.metrics import bootstrap_mean

#: Was in `DEFAULT_SPEC` steht und unter dem die 7.335 Fills entstanden sind.
LEGACY_MAKER, LEGACY_TAKER = 0.0002, 0.00055

#: Was Binance am 18.10.2026 über ccxt für alle zwölf Perpetuals nennt.
#: Gemessen, nicht aus einer Gebührenseite abgeschrieben.
BINANCE_MAKER, BINANCE_TAKER = 0.0002, 0.0005

#: Die Rekonstruktion darf höchstens so weit neben der gespeicherten Gebühr
#: liegen. 1e-9 relativ ist Fliesskomma-Rauschen; alles darüber heisst, dass
#: das Modell hier falsch ist.
TOLERANZ = 1e-9

#: Dieselbe Frage fuer das gespeicherte R, absolut statt relativ.
R_TOLERANZ = 1e-6

#: Wie viele abweichende Faelle der Bericht nennt, bevor er abkuerzt. Die Zahl
#: entscheidet nichts -- der Lauf bricht bei der ERSTEN Abweichung ab.
BEISPIELE = 5


#: Die Rollenverteilungen, die hier überhaupt vorkommen können.
#:
#: Gemessen und nicht angenommen: der erste Lauf dieses Skripts hat 4.651 von
#: 7.335 Fills mit `maker/taker` reproduziert und bei 2.684 abgebrochen --
#: **allen** mit `state = closed_target`. Ein Zielausstieg ist eine Limit-Order,
#: also Maker, und das ist der Grund. Die Wache hat damit genau das getan, wofür
#: sie da ist: ein Gebührenmodell aus dem Kopf wäre um 37 % der Population
#: falsch gewesen und hätte trotzdem eine glatte Zahl geliefert.
ROLLEN: tuple[tuple[str, str], ...] = (
    ("maker", "taker"),
    ("maker", "maker"),
    ("taker", "taker"),
)


@dataclass(frozen=True, slots=True)
class Fill:
    """Nur die Felder, die für die Gebühr zählen."""

    symbol: str
    state: str
    entry_notional: float
    exit_notional: float
    fees: float
    funding: float
    gross_pnl: float
    risk_amount: float
    r_multiple: float
    #: Welche Rollenverteilung die gespeicherte Gebühr reproduziert. Leer,
    #: solange `bestimme_rollen` nicht gelaufen ist.
    rollen: tuple[str, str] = ()  # type: ignore[assignment]


def lade(root: Path) -> list[Fill]:
    fills: list[Fill] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        symbol = str(blob["symbol"])
        for row in blob["fills"]:
            qty = float(row["qty"])
            fills.append(
                Fill(
                    symbol=symbol,
                    state=str(row["state"]),
                    entry_notional=float(row["entry_price"]) * qty,
                    exit_notional=float(row["exit_price"]) * qty,
                    fees=float(row["fees"]),
                    funding=float(row["funding"]),
                    gross_pnl=float(row["gross_pnl"]),
                    risk_amount=float(row["risk_amount"]),
                    r_multiple=float(row["r_multiple"]),
                )
            )
    return fills


#: Ein Gebührenplan: welcher Satz für welche Rolle gilt.
Plan = dict[str, float]

LEGACY_PLAN: Plan = {"maker": LEGACY_MAKER, "taker": LEGACY_TAKER}
BINANCE_PLAN: Plan = {"maker": BINANCE_MAKER, "taker": BINANCE_TAKER}
#: Policy A: die Makerrolle ist unbewiesen (`maker_role_proven = False`), also
#: zahlt jede Seite Taker. Das ist die sicherste ausführbare Baseline und nach
#: der Präzisierung vom 17.10.2026 ausdrücklich nicht „aus den historischen
#: Daten belegbar" -- sie ist die vorsichtige Annahme, nicht die gemessene.
TAKER_PLAN: Plan = {"maker": BINANCE_TAKER, "taker": BINANCE_TAKER}
#: Keine erreichbare Politik, sondern die **Obergrenze**. Wenn selbst hier der
#: Erwartungswert nicht reicht, ist die Kostenachse geschlossen -- und das ist
#: eine andere Aussage als „die Gebühren sind klein". Null-Gebühren-Venues
#: existieren, der Punkt ist also nicht rein hypothetisch; die Zahl beantwortet
#: trotzdem vor allem die Frage, wie viel Kopffreiheit auf dieser Achse
#: überhaupt noch liegt.
NULL_PLAN: Plan = {"maker": 0.0, "taker": 0.0}


def gebuehr(fill: Fill, plan: Plan, rollen: tuple[str, str] | None = None) -> float:
    ein, aus = rollen or fill.rollen
    return fill.entry_notional * plan[ein] + fill.exit_notional * plan[aus]


def r_unter(fill: Fill, plan: Plan, rollen: tuple[str, str] | None = None) -> float:
    """Dasselbe R wie gespeichert, nur unter einem anderen Gebührenplan.

    `r_multiple = net_pnl / risk_amount` und
    `net_pnl = gross_pnl - fees + funding`.

    **Das Pluszeichen ist gemessen, nicht geraten.** Der erste Versuch stand
    hier mit einem Minus, und `pruefe_r` hat ihn bei 4.603 von 7.335 Fills
    angehalten -- genau bei denen mit `funding != 0`. Der Bruch war jedes Mal
    exakt `2 * funding`. `funding` ist in diesem Speicher also
    **vorzeichenbehaftet**: positiv heisst *erhalten*, nicht *bezahlt*. Die
    anderen 2.732 Fills haben Funding 0 und hätten beide Vorzeichen bestätigt
    -- ein Test auf einer Teilmenge, die die Frage nicht stellt, wäre grün
    gewesen.
    """
    netto = fill.gross_pnl - gebuehr(fill, plan, rollen) + fill.funding
    return netto / fill.risk_amount


def bestimme_rollen(fills: list[Fill]) -> tuple[list[Fill], list[str]]:
    """Welche Rollenverteilung reproduziert die gespeicherte Gebühr?

    Entschieden je Fill und aus den Zahlen, nicht aus dem Zustandsnamen. Der
    Zustand ist danach die *Gegenprobe*: wenn `closed_target` und
    `maker/maker` nicht zusammenfallen, stimmt eine der beiden Annahmen nicht.
    """
    erkannt: list[Fill] = []
    abweichungen: list[str] = []
    for fill in fills:
        nenner = max(abs(fill.fees), 1e-12)
        passend = [
            rollen
            for rollen in ROLLEN
            if abs(gebuehr(fill, LEGACY_PLAN, rollen) - fill.fees) / nenner <= TOLERANZ
        ]
        if len(passend) == 1:
            erkannt.append(dataclasses.replace(fill, rollen=passend[0]))
        elif len(abweichungen) < BEISPIELE:
            kandidaten = ", ".join(
                f"{r[0]}/{r[1]}={gebuehr(fill, LEGACY_PLAN, r):.10f}" for r in ROLLEN
            )
            abweichungen.append(
                f"{fill.symbol} {fill.state}: gespeichert {fill.fees:.10f}; "
                f"{len(passend)} Treffer unter [{kandidaten}]"
            )
    return erkannt, abweichungen


def pruefe_r(fills: list[Fill]) -> list[str]:
    """Und reproduziert `r_unter` mit dem Legacy-Plan das gespeicherte R?"""
    schlecht: list[str] = []
    for fill in fills:
        nach = r_unter(fill, LEGACY_PLAN)
        if abs(nach - fill.r_multiple) > R_TOLERANZ and len(schlecht) < BEISPIELE:
            schlecht.append(
                f"{fill.symbol} {fill.state}: gespeichert {fill.r_multiple:+.9f}, "
                f"gerechnet {nach:+.9f}"
            )
    return schlecht


SZENARIEN: tuple[tuple[str, Plan, bool, str], ...] = (
    (
        "Legacy wie gespeichert",
        LEGACY_PLAN,
        False,
        "maker 0.0200 % / taker 0.0550 % -- Bybits Taker auf Binance-Kerzen",
    ),
    (
        "Venue-korrekt, gleiche Rollen",
        BINANCE_PLAN,
        False,
        "maker 0.0200 % / taker 0.0500 % -- was Binance am 18.10.2026 nennt",
    ),
    (
        "Venue-korrekt, ohne Makerannahme",
        TAKER_PLAN,
        True,
        "taker 0.0500 % auf JEDER Seite -- Policy A, Makerrolle unbewiesen",
    ),
    (
        "Null Gebuehren (Obergrenze)",
        NULL_PLAN,
        False,
        "0 % auf beiden Seiten -- keine erreichbare Politik, sondern die "
        "OBERGRENZE dessen, was eine Kostenverbesserung je liefern kann",
    ),
)


def berichte_plaene(fills: list[Fill], *, draws: int) -> None:
    """Abschnitt 2: ein Erwartungswert je Gebührenplan, alle gegen Legacy."""
    print("\n2. ERWARTUNGSWERT JE GEBÜHRENPLAN (ganze genommene Population)")
    basis: np.ndarray | None = None
    for name, plan, alles_taker, erklaerung in SZENARIEN:
        rollen = ("taker", "taker") if alles_taker else None
        werte = np.array([r_unter(f, plan, rollen) for f in fills], dtype=float)
        summe = sum(gebuehr(f, plan, rollen) for f in fills)
        print(f"\n   {name}")
        print(f"     {erklaerung}")
        print(f"     Erwartungswert {bootstrap_mean(werte, samples=draws)} R je Trade")
        print(f"     Gebühr gesamt  {summe:,.2f} USDT")
        if basis is None:
            basis = werte
        else:
            print(f"     d gegen Legacy {bootstrap_mean(werte - basis, samples=draws)}")


def berichte_maerkte(fills: list[Fill], maerkte: list[str], *, draws: int) -> None:
    """Abschnitt 3: damit ein Mittelwert keinen Ausreisser versteckt."""
    print("\n3. d DER VENUE-KORREKTUR JE MARKT (gleiche Rollen)")
    for symbol in maerkte:
        teil = [f for f in fills if f.symbol == symbol]
        vorher = np.array([r_unter(f, LEGACY_PLAN) for f in teil])
        nachher = np.array([r_unter(f, BINANCE_PLAN) for f in teil])
        taker_anteil = sum(1 for f in teil if "taker" in f.rollen) / len(teil)
        print(
            f"   {symbol:10s} n={len(teil):5,}  taker-Beine {taker_anteil:5.1%}  "
            f"{vorher.mean():+.4f} -> {nachher.mean():+.4f} R   "
            f"d {bootstrap_mean(nachher - vorher, samples=draws)}"
        )


def berichte_obergrenze(
    fills: list[Fill], *, draws: int, growth: float, trades: float, risk: float
) -> None:
    """Abschnitt 4: die Obergrenze der Kostenachse gegen die Anforderung.

    Die eine Zahl, für die dieses Skript existiert. Alles davor sagt, wie teuer
    ein Gebührenplan ist; diese Zeile sagt, ob die Achse überhaupt gross genug
    ist, um die Frage zu entscheiden.
    """
    print("\n4. DIE OBERGRENZE GEGEN DIE ANFORDERUNG")
    null = np.array([r_unter(f, NULL_PLAN) for f in fills], dtype=float)
    legacy = np.array([r_unter(f, LEGACY_PLAN) for f in fills], dtype=float)
    obergrenze = bootstrap_mean(null, samples=draws)
    gebraucht = required_mean_r(growth=growth, trades=trades, risk=risk)
    print(
        f"   Kostenachse insgesamt wert : "
        f"{bootstrap_mean(null - legacy, samples=draws)} R je Trade"
    )
    print(f"   Obergrenze (null Gebuehren): {obergrenze} R je Trade")
    print(
        f"   Anforderung                : {gebraucht:+.4f} R je Trade "
        f"({growth:g}x ueber {trades:g} Trades bei {risk:.0%} Risiko)"
    )
    if obergrenze.value > 0:
        print(
            f"   Verhaeltnis                : die Obergrenze ist "
            f"{gebraucht / obergrenze.value:.0f}x zu klein"
        )
    else:
        print("   Verhaeltnis                : die Obergrenze ist nicht positiv")
    schluss = "schliesst die Null aus" if obergrenze.excludes_zero else "enthaelt die Null"
    print(f"   Und ihr Intervall {schluss}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--draws", type=int, default=20_000)
    # Der Masterauftrag: 1.000 -> 20.000 CHF.
    #
    # **Diese drei Vorgaben waren falsch und sind am 18.10.2026 korrigiert.**
    # Sie standen auf 312 Trades und 3 % Risiko und ergaben +0.3216 R -- eine
    # DRITTE Marke neben den beiden, die derselbe Abend sonst benutzt hat. Die
    # Kadenz kommt aus den Daten (`scripts/goal_bar.py`): 5 Plaetze bei 33,00 h
    # mittlerer Haltedauer sind 3,64 Trades/Tag, ueber 182 Tage also 662. Und
    # das Risiko ist 1 %, nicht der 3-%-Deckel -- `risk.sizing` setzt 1 %, und
    # 3 % ist die absolute Obergrenze, die nur bei kalibrierter Zuversicht
    # ueberhaupt freigeschaltet wuerde.
    #
    # Die Marke lautet damit +0.4536 R. Alle drei bleiben Argumente, damit die
    # Zahl nachgerechnet und nicht geglaubt wird; `tests/test_goal_bar.py`
    # nagelt sie fest.
    parser.add_argument("--growth", type=float, default=20.0)
    parser.add_argument("--trades", type=float, default=662.0)
    parser.add_argument("--risk", type=float, default=0.01)
    args = parser.parse_args(argv)

    fills = lade(args.root)
    if not fills:
        print(f"keine Fills unter {args.root}", file=sys.stderr)
        return 2

    maerkte = sorted({f.symbol for f in fills})
    print(f"{len(fills):,} Fills über {len(maerkte)} Märkte aus {args.root}")
    print(f"Märkte: {', '.join(maerkte)}\n")

    # -- 1. Stimmt das Gebührenmodell überhaupt? ---------------------------- #
    fills, abweichungen = bestimme_rollen(fills)
    print("1. REKONSTRUKTION DER GESPEICHERTEN GEBÜHR")
    for rollen in ROLLEN:
        treffer = sum(1 for f in fills if f.rollen == rollen)
        print(f"   {rollen[0]:5s} ein / {rollen[1]:5s} aus : {treffer:,}")
    for zeile in abweichungen:
        print(f"     ! {zeile}")
    if abweichungen:
        print(
            "\n   ABBRUCH: das Gebührenmodell reproduziert die gespeicherten "
            "Zahlen nicht. Eine Korrektur darauf wäre erfunden.",
            file=sys.stderr,
        )
        return 1

    schlecht = pruefe_r(fills)
    print(f"   R reproduziert          : {len(fills) - len(schlecht):,} von {len(fills):,}")
    for zeile in schlecht:
        print(f"     ! {zeile}")
    if schlecht:
        print("\n   ABBRUCH: R ist nicht reproduzierbar.", file=sys.stderr)
        return 1

    # Die Gegenprobe: fällt die gemessene Rolle mit dem Ausstiegsgrund
    # zusammen? Wenn ja, ist die Rollenzuordnung keine Kurvenanpassung an die
    # Gebührenspalte, sondern sagt etwas über den Ausstieg.
    print("\n   Gegenprobe Rolle gegen Ausstiegsgrund:")
    paare: dict[tuple[str, tuple[str, str]], int] = {}
    for fill in fills:
        paare[(fill.state, fill.rollen)] = paare.get((fill.state, fill.rollen), 0) + 1
    for (state, rollen), anzahl in sorted(paare.items()):
        print(f"     {state:16s} {rollen[0]}/{rollen[1]:5s} {anzahl:6,}")

    berichte_plaene(fills, draws=args.draws)
    berichte_maerkte(fills, maerkte, draws=args.draws)
    berichte_obergrenze(
        fills,
        draws=args.draws,
        growth=args.growth,
        trades=args.trades,
        risk=args.risk,
    )

    print(
        "\nZWEI GRENZEN DIESER MESSUNG, beide in dieselbe Richtung:\n"
        "  1. Gerechnet auf der GENOMMENEN Population. Eine billigere Gebuehr\n"
        "     laesst zusaetzliche Signale durch das Kostengate, die Population\n"
        "     waere also groesser.\n"
        "  2. Und genau das macht die Obergrenze zu OPTIMISTISCH, nicht zu\n"
        "     vorsichtig: bei null Gebuehren kann die Kostenregel\n"
        "     (`max_cost_fraction_of_risk`) ueberhaupt nicht mehr ausloesen, und\n"
        "     die von ihr abgelehnte Population ist gemessen brutto-negativ.\n"
        "     Die +R oben behaelt also den Nutzen einer Auswahl, deren Kosten\n"
        "     sie gleichzeitig auf null setzt. Ein echter Nullgebuehren-Lauf\n"
        "     waere schlechter, nicht besser."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
