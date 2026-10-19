"""Was Margin x Hebel wirklich einstellt -- Arithmetik und Messung getrennt.

**Die Frage, die dieses Skript beantwortet.** Der Auftrag lautet "300 von 1.000
bei 7x Hebel". Darin kommt die eine Zahl nicht vor, auf die es ankommt: wie
viel des Kontos ein einzelner Trade riskiert. Bei Vorwaertsbemessung ist das
Risiko keine Eingabe, sondern ein ERGEBNIS:

    Risiko = Margin-Anteil x Hebel x Stopweite

**Und die Stopweite ist nach unten festgenagelt.** Das Kostentor laesst nur
Trades durch, deren Runden-Kosten hoechstens `max_cost_fraction_of_risk` des
Risikos ausmachen. Diese Bedingung reduziert sich exakt auf eine
Mindest-Stopweite (`risk/sizing.py:min_economic_stop_fraction`):

    Stopweite >= c / max_cost_fraction_of_risk

Bei Binance-Gebuehren und 8 % Deckel sind das 1,2500 %. Daraus folgt ein
RISIKOBODEN, den keine Einstellung dieser Groessenregel unterbieten kann:

    Risikoboden = Margin-Anteil x Hebel x 1,2500 %

Bei 30 % x 7x sind das 2,625 % je Trade. Es gibt keinen Weg, mit dieser Regel
weniger zu riskieren -- ausser `Margin x Hebel` zu senken. Das ist der ganze
Inhalt der linken Tabellenhaelfte, und daran ist nichts geschaetzt.

**Was die rechte Haelfte ist, und was sie NICHT ist.** Die Ergebnisspalten
stammen aus denselben 7.335 gespeicherten Trades, ueber 30-Tage-Fenster. Sie
sind IN-SAMPLE und beschreiben, was gewesen waere -- keine Vorhersage. Wer die
beste Zeile ablaest und sie "die optimale Einstellung" nennt, hat eine
Einstellung an Daten angepasst und misst sie anschliessend an denselben.

**Die Zeile, die dazugehoert, auch wenn sie unbequem ist:** "gar nicht
handeln" steht als Referenz mit 1,0000x in der Tabelle. Ueber eine Population
mit negativer Erwartung schlaegt sie jede Einstellung mit `f > 0` -- der
Logertrag je Trade ist `m*f*EV - (m*f*SD)^2/2`, und beide Terme sind negativ,
sobald `EV < 0`. Das ist Arithmetik, keine Meinung, und `study_leverage_plan.py`
hat es ueber 20.000 Umordnungen bestaetigt.

    python scripts/study_plan_frontier.py
    python scripts/study_plan_frontier.py --fenster-tage 90
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.risk.plansize import UnsizeablePlanError, plan_size
from traidingbrain.risk.sizing import min_economic_stop_fraction

TAG_MS = 86_400_000

#: Der Start jedes Fensters. Dieselbe Zahl wie im Auftrag.
START = 1_000.0

#: Unter diesem Rest gilt das Konto als handlungsunfaehig.
BODEN = 0.01

#: Die Einstellungen. Der Auftrag (30 % x 7x) steht darin, und daneben
#: Nachbarn in BEIDE Richtungen -- eine Tabelle, die nur nach unten geht,
#: beantwortet die Frage "ist mehr besser" nicht, sondern unterstellt sie.
EINSTELLUNGEN: tuple[tuple[float, float], ...] = (
    (0.30, 7.0),    # der Auftrag
    (0.30, 10.0),
    (0.50, 7.0),
    (0.30, 5.0),
    (0.30, 3.0),
    (0.30, 2.67),   # Risikoboden 1,0 %
    (0.30, 2.0),
    (0.10, 7.0),
    (0.10, 2.0),
    (0.05, 1.0),
)


def lade(root: Path) -> list[dict[str, object]]:
    zeilen: list[dict[str, object]] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            row["symbol"] = blob["symbol"]
            zeilen.append(row)
    zeilen.sort(key=lambda r: int(r["opened_ts"]))
    return zeilen


def _stop(row: dict[str, object]) -> tuple[float, float, Side] | None:
    """Einstieg, Stop und Seite aus einem gespeicherten Fill."""
    entry, qty = float(row["entry_price"]), float(row["qty"])
    if entry <= 0 or qty <= 0:
        return None
    seite = Side.SHORT if str(row["side"]).lower() == "short" else Side.LONG
    weite = float(row["risk_amount"]) / qty
    return entry, entry + weite if seite is Side.SHORT else entry - weite, seite


def ein_fenster(
    fenster: list[dict[str, object]], anteil: float, hebel: float
) -> tuple[float, int] | None:
    """Endstand eines Fensters und wie viele Trades liquidiert wurden."""
    konto, liq = START, 0
    for row in fenster:
        if konto <= START * BODEN:
            return konto, liq
        gelesen = _stop(row)
        if gelesen is None:
            continue
        entry, stop, seite = gelesen
        try:
            p = plan_size(equity=konto, margin_share=anteil, leverage=hebel,
                          entry=entry, stop=stop, side=seite)
        except UnsizeablePlanError:
            continue
        r = float(row["r_multiple"])
        if p.stop_beyond_liquidation and r < 0:
            schritt, liq = -p.margin, liq + 1
        else:
            schritt = p.loss_at_stop * r
        konto = max(konto + schritt, 0.0)
    return konto, liq


def risikoverteilung(
    trades: list[dict[str, object]], anteil: float, hebel: float
) -> tuple[float, float, float]:
    """Median, 99. Perzentil und Liquidationsanteil -- bei UNVERAENDERTEM Konto.

    Bewusst auf dem Startkonto gerechnet und nicht entlang eines Pfades: hier
    geht es um die Regel, nicht um einen Verlauf. Entlang eines Pfades waere
    jede Zahl eine Mischung aus Regel und Reihenfolge.
    """
    anteile: list[float] = []
    ueber_liq = 0
    for row in trades:
        gelesen = _stop(row)
        if gelesen is None:
            continue
        entry, stop, seite = gelesen
        try:
            p = plan_size(equity=START, margin_share=anteil, leverage=hebel,
                          entry=entry, stop=stop, side=seite)
        except UnsizeablePlanError:
            continue
        anteile.append(p.loss_at_stop_share)
        ueber_liq += 1 if p.stop_beyond_liquidation else 0
    if not anteile:
        return 0.0, 0.0, 0.0
    anteile.sort()
    p99 = anteile[min(len(anteile) - 1, int(0.99 * len(anteile)))]
    return statistics.median(anteile), p99, ueber_liq / len(anteile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--fenster-tage", type=int, default=30)
    parser.add_argument("--min-trades", type=int, default=20)
    args = parser.parse_args(argv)

    cfg = load_config()
    schlupf = cfg.engine.simulation.slippage_bps
    deckel = cfg.risk.limits.max_cost_fraction_of_risk
    # Die Gebuehr, unter der die gespeicherten Fills ENTSTANDEN sind. Die
    # laufende Boerse ist guenstiger (1,2500 %); diese Tabelle rechnet mit der
    # Quelle ihrer eigenen Daten, sonst beschreibt sie eine andere Population.
    spec = SymbolSpec(symbol="X", **DEFAULT_SPEC)
    min_stop = min_economic_stop_fraction(spec, schlupf, deckel)

    trades = lade(args.fills)
    t0, t1 = int(trades[0]["opened_ts"]), int(trades[-1]["opened_ts"])

    fenster: list[list[dict[str, object]]] = []
    anfang = t0
    while anfang + args.fenster_tage * TAG_MS <= t1:
        f = [t for t in trades
             if anfang <= int(t["opened_ts"]) < anfang + args.fenster_tage * TAG_MS]
        if len(f) >= args.min_trades:
            fenster.append(f)
        anfang += args.fenster_tage * TAG_MS

    print(f"{len(trades):,} Trades ueber {(t1 - t0) / TAG_MS:.0f} Tage, "
          f"{len(fenster)} Fenster a {args.fenster_tage} Tage "
          f"(mindestens {args.min_trades} Trades)")
    print(f"Mindest-Stopweite dieser Population: {min_stop:.4%} "
          f"(Kostendeckel {deckel:.0%}, Schlupf {schlupf:g} bp)\n")

    print("                 |  ARITHMETIK (keine Anpassung)   |  GEMESSEN, IN-SAMPLE")
    print(f"{'Einstellung':16s} | {'m':>5s} {'Boden':>7s} {'Median':>7s} {'p99':>7s} "
          f"{'>Liq':>6s} | {'Median':>8s} {'>1.0x':>7s} {'ruin':>6s}")
    print("-" * 92)

    for anteil, hebel in EINSTELLUNGEN:
        m = anteil * hebel
        boden = m * min_stop
        med_r, p99_r, liq_anteil = risikoverteilung(trades, anteil, hebel)
        enden = [e for e in (ein_fenster(f, anteil, hebel) for f in fenster) if e]
        faktoren = sorted(k / START for k, _ in enden)
        ruiniert = sum(1 for k, _ in enden if k <= START * BODEN) / max(len(enden), 1)
        ueber = sum(1 for f in faktoren if f > 1.0) / max(len(faktoren), 1)
        marke = "  <- Auftrag" if (anteil, hebel) == (0.30, 7.0) else ""
        print(
            f"{f'{anteil:.0%} x {hebel:g}x':16s} | {m:5.2f} {boden:7.2%} "
            f"{med_r:7.2%} {p99_r:7.2%} {liq_anteil:6.1%} | "
            f"{statistics.median(faktoren):8.4f} {ueber:7.1%} {ruiniert:6.1%}{marke}"
        )

    print(f"{'gar nicht handeln':16s} | {0.0:5.2f} {0.0:7.2%} {0.0:7.2%} {0.0:7.2%} "
          f"{0.0:6.1%} | {1.0:8.4f} {0.0:7.1%} {0.0:6.1%}  <- Referenz")

    print(
        "\nWIE DIESE TABELLE ZU LESEN IST.\n"
        "  m          = Margin-Anteil x Hebel. Der Nominalhebel aufs Konto.\n"
        "  Boden      = m x Mindest-Stopweite. Das KLEINSTE Risiko, das diese\n"
        "               Einstellung ueberhaupt eingehen kann. Reine Arithmetik.\n"
        "  Median/p99 = das tatsaechliche Risiko je Trade ueber die echten\n"
        "               Stopweiten, auf unveraendertem Konto gerechnet.\n"
        "  >Liq       = Anteil der Trades, deren Stop WEITER liegt als die\n"
        "               Liquidation. Dort schliesst die Boerse zuerst, und die\n"
        "               ganze Margin ist weg statt des geplanten Betrags.\n"
        "  Median,\n"
        "  >1.0x,ruin = Ergebnis ueber die Fenster. IN-SAMPLE.\n"
        "\n"
        "WAS SIE NICHT IST: eine Empfehlung. Die Ergebnisspalten sind an\n"
        "denselben Daten gemessen, aus denen die Einstellungen stammen. Die\n"
        "beste Zeile abzulesen und sie 'optimal' zu nennen, ist genau der\n"
        "Fehler, gegen den der Rest dieses Projekts gebaut ist.\n"
        "\n"
        "Die linke Haelfte ist dagegen belastbar: sie haengt an keiner\n"
        "Stichprobe, nur an der Formel und am Kostendeckel. Wer den\n"
        "Risikoboden senken will, muss m senken -- es gibt keinen anderen Weg."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
