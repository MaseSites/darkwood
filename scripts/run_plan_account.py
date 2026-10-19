"""Das neue Konto: 1.000 CHF, Severins Grössenregel, Trade für Trade sichtbar.

**Was dieses Skript ist.** Ein getrenntes Papierkonto, das dieselben Einstiege
nimmt wie das bestehende System, sie aber nach der Vorwärtsregel bemisst:
ein fester Anteil des Kontos als Margin, mal Hebel. Nach jedem Trade wächst
oder schrumpft die Margin mit dem Konto -- das Aufstocken, das im Auftrag steht
(300, dann 350, dann 400, dann 470).

**Was es nicht ist: ein neuer Backtest.** Die Einstiege, Stops, Ziele und
Ausgänge stehen fest; sie kommen aus den 7.335 gespeicherten Trades. Verändert
wird ausschliesslich die GRÖSSE. Das ist der saubere Schnitt: eine Grössenregel
kann nicht ändern, welcher Trade gewinnt, nur wie viel er bewegt.

**Und was es darum ÜBERSCHÄTZT: die Zahl der Trades.** Dieses Skript reiht die
Trades hintereinander auf und nimmt jeden -- es unterstellt, dass immer Platz
war. War es nicht. Jede Position bindet `Margin-Anteil mal Konto`, bei 30 % passen
also **drei** ins Konto, und die vierte findet nichts mehr
(`sim/broker.py:500` lehnt genau so ab). Über die gespeicherten Trades waren
67,9 % der Zeit mehr als drei gleichzeitig offen.

Gemessen in `scripts/study_plan_slots.py`: mit Margin-Buchhaltung wären **43 %
der Einstiege abgelehnt** worden, und der Median über 30-Tage-Fenster steigt
von 0,34x auf **0,67x**. Die Richtung ist vorhersagbar -- weniger Trades einer
Population mit negativer Erwartung heisst weniger Verlust -- die Grösse war es
nicht. Wer eine Zahl über das ERGEBNIS braucht, nimmt jenes Skript; dieses hier
beantwortet die engere Frage, was die Grössenregel je Trade tut.

Drei Dinge, die der reine R-Vergleich nicht zeigt und dieses Skript darum
mitrechnet:

1. **Liquidation.** Liegt der Stop weiter entfernt als `1/Hebel - MMR`,
   schliesst die Börse zuerst und die ganze Margin ist weg -- nicht der
   geplante Betrag. Gemessen trifft das 1,20 % der Trades bei 7x.
2. **Der Kontoboden.** Unter einem Rest ist keine Position mehr stellbar.
3. **Die Reihenfolge.** Ein Pfad ist ein Pfad. Der aggregierte Teil zeigt ihn,
   `scripts/study_leverage_plan.py` zeigt die Verteilung über Umordnungen.

    python scripts/run_plan_account.py
    python scripts/run_plan_account.py --margin-anteil 0.05 --hebel 2 --zeige 40
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from traidingbrain.domain.enums import Side
from traidingbrain.risk.plansize import (
    PlanSize,
    UnsizeablePlanError,
    plan_size,
)

#: Das Konto, wie im Auftrag genannt.
START = 1_000.0

#: Unter diesem Rest ist das Konto handlungsunfaehig.
BODEN = 0.01


def lade(root: Path) -> list[dict[str, object]]:
    """Alle Trades in Zeitordnung, ueber alle Maerkte."""
    zeilen: list[dict[str, object]] = []
    for path in sorted(root.glob("*.json")):
        blob = json.loads(path.read_text(encoding="utf-8"))
        for row in blob["fills"]:
            row["symbol"] = blob["symbol"]
            zeilen.append(row)
    zeilen.sort(key=lambda r: int(r["opened_ts"]))
    return zeilen


def zeige_trade(
    nr: int,
    row: dict[str, object],
    p: PlanSize,
    *,
    r: float,
    vorher: float,
    konto: float,
    schritt: float,
    vermerk: str,
) -> None:
    """Ein Trade in drei Zeilen, mit allen zehn Groessen darin.

    Die mittlere Zeile ist der Zweck des ganzen Skripts: sie nennt das Risiko
    als Anteil des Kontos, und genau diese Zahl kommt in der Anweisung
    "300 CHF bei 7x" nicht vor.
    """
    print(
        f"  {nr:3d}. {row['symbol']!s:9s} {row['side']!s:5s} "
        f"R={r:+6.2f} | Margin {p.margin:8,.2f} ({p.margin_share:.0%}) "
        f"Nominal {p.notional:10,.2f}"
    )
    print(
        f"       Stop {p.stop_fraction:6.2%} entfernt -> Risiko "
        f"{p.loss_at_stop:8,.2f} = {p.loss_at_stop_share:6.2%} des Kontos | "
        f"Liquidation {p.liquidation_fraction:.2%} {vermerk}"
    )
    print(f"       Konto {vorher:10,.2f} -> {konto:10,.2f}  ({schritt:+9,.2f})")


def berichte_ergebnis(
    *,
    konto: float,
    hoch: float,
    start: float,
    gewinner: int,
    liquidiert: int,
    boden_bei: int,
    gesamt: int,
) -> None:
    """Der Endstand. Getrennt, damit `main` lesbar bleibt."""
    print(f"\n{'=' * 70}")
    gelaufen = boden_bei if boden_bei else gesamt
    print(f"ERGEBNIS NACH {gelaufen:,} VON {gesamt:,} TRADES")
    print(f"  Konto          {konto:12,.2f}  ({konto / start:.4f}x des Starts)")
    print(f"  Hoechststand   {hoch:12,.2f}")
    if hoch > 0:
        print(f"  Rueckgang      {1 - konto / hoch:12.2%}")
    print(
        f"  Gewinner       {gewinner:,} von {gelaufen:,} "
        f"({gewinner / max(gelaufen, 1):.1%})"
    )
    print(f"  liquidiert     {liquidiert:,} Trades vor ihrem Stop")
    if boden_bei:
        print(
            f"\n  KONTOBODEN nach {boden_bei:,} Trades -- die restlichen "
            f"{gesamt - boden_bei:,} konnten nicht mehr gestellt werden."
        )


def berichte_kurve(
    kurve: list[tuple[int, float, int]],
    hoch_bei: tuple[int, float, int],
    *,
    start: float,
) -> None:
    """Die Form der Kurve -- das Wichtigste an diesem Lauf.

    Der Endstand allein verschweigt, dass der Plan unterwegs funktioniert hat.
    Genau das ist die Eigenschaft, die ihn gefaehrlich macht: er belohnt lange
    genug, um ueberzeugend zu sein.
    """
    if not kurve:
        return
    n, wert, ts = hoch_bei
    print(f"\n  HOECHSTSTAND bei Trade {n:,} am {_tag(ts)}: {wert:,.2f} "
          f"({wert / start:.2f}x)")
    print("\n  DIE FORM DER KURVE")
    for q in (0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        idx = min(max(int(len(kurve) * q) - 1, 0), len(kurve) - 1)
        nr, k, t = kurve[idx]
        print(f"    nach {nr:4,} Trades ({_tag(t)}): {k:10,.2f}  {k / start:7.3f}x")


def _tag(ms: int) -> str:
    return f"{datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC):%d.%m.%Y}"


def juengstes_fenster(
    trades: list[dict[str, object]], tage: int | None, *, start: float
) -> list[dict[str, object]]:
    """Nur die juengsten N Tage der Daten -- oder alles, wenn None.

    **Gemessen vom juengsten Trade der DATEN, nicht von heute.** Die
    gespeicherten Kerzen enden irgendwann; "die letzten 30 Tage" ab heute
    koennte ein leeres Fenster sein, und ein leeres Fenster sieht aus wie ein
    Befund ("die Regel handelt nicht mehr"), obwohl es nur heisst, dass die
    Daten aelter sind.

    Das Konto faengt im Ausschnitt wieder bei `start` an. Das ist eine andere
    Frage als die ueber den ganzen Zeitraum -- naemlich "was taete die Regel
    JETZT mit 1.000", nicht "wohin fuehrt der ganze Pfad" -- und die Ausgabe
    sagt das, damit die beiden Zahlen nicht verwechselt werden.
    """
    if tage is None:
        return trades
    ende = max(int(t["opened_ts"]) for t in trades)
    grenze = ende - tage * 86_400_000
    im_fenster = [t for t in trades if int(t["opened_ts"]) >= grenze]
    print(
        f"AUSSCHNITT: die letzten {tage} Tage der Daten "
        f"({_tag(grenze)} bis {_tag(ende)}) -- {len(im_fenster):,} von "
        f"{len(trades):,} Trades.\n"
        f"Das Konto startet in diesem Fenster wieder bei {start:,.2f}, "
        f"traegt also NICHT den Verlauf davor.\n"
    )
    return im_fenster


def _argumente(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fills", type=Path, default=Path("data/replay_fills"))
    parser.add_argument("--start", type=float, default=START)
    parser.add_argument("--margin-anteil", type=float, default=0.30)
    parser.add_argument("--hebel", type=float, default=7.0)
    parser.add_argument("--zeige", type=int, default=20,
                        help="wie viele Trades einzeln ausgeschrieben werden")
    parser.add_argument(
        "--letzte-tage", type=int, default=None,
        help="nur die juengsten N Tage des Nachspiels -- zeigt, was die Regel "
             "zuletzt getan haette, statt was sie 2008 getan haette",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _argumente(argv)

    trades = juengstes_fenster(lade(args.fills), args.letzte_tage, start=args.start)
    if not trades:
        print("Keine Trades in diesem Fenster.")
        return 1

    konto = args.start
    hoch = konto
    liquidiert = boden_bei = 0
    gewinner = 0
    kurve: list[tuple[int, float, int]] = []   # (Trade-Nr, Konto, opened_ts)
    hoch_bei = (0, konto, 0)
    print(
        f"NEUES KONTO: {args.start:,.2f} | {args.margin_anteil:.0%} Margin "
        f"x {args.hebel:g}x Hebel | {len(trades):,} Trades in Zeitordnung\n"
    )
    print(f"DIE ERSTEN {args.zeige} TRADES, EINZELN\n")

    for i, row in enumerate(trades):
        if konto <= args.start * BODEN:
            boden_bei = i
            break
        entry = float(row["entry_price"])
        qty = float(row["qty"])
        if entry <= 0 or qty <= 0:
            continue
        seite = Side.SHORT if str(row["side"]).lower() == "short" else Side.LONG
        weite = float(row["risk_amount"]) / qty
        stop = entry + weite if seite is Side.SHORT else entry - weite
        try:
            p = plan_size(
                equity=konto,
                margin_share=args.margin_anteil,
                leverage=args.hebel,
                entry=entry,
                stop=stop,
                side=seite,
            )
        except UnsizeablePlanError:
            continue

        r = float(row["r_multiple"])
        if p.stop_beyond_liquidation and r < 0:
            schritt = -p.margin
            liquidiert += 1
            vermerk = "LIQUIDIERT"
        else:
            schritt = p.loss_at_stop * r
            vermerk = ""
        vorher = konto
        konto = max(konto + schritt, 0.0)
        if konto > hoch:
            hoch = konto
            hoch_bei = (i + 1, konto, int(row['opened_ts']))
        kurve.append((i + 1, konto, int(row['opened_ts'])))
        gewinner += 1 if r > 0 else 0

        if i < args.zeige:
            zeige_trade(
                i + 1, row, p, r=r, vorher=vorher, konto=konto,
                schritt=schritt, vermerk=vermerk,
            )

    berichte_ergebnis(
        konto=konto,
        hoch=hoch,
        start=args.start,
        gewinner=gewinner,
        liquidiert=liquidiert,
        boden_bei=boden_bei,
        gesamt=len(trades),
    )
    berichte_kurve(kurve, hoch_bei, start=args.start)
    print(
        "\nDIE REIHENFOLGE IST EIN PFAD. Was ueber viele Umordnungen passiert,\n"
        "rechnet scripts/study_leverage_plan.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
