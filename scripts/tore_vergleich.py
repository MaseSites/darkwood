"""Tore zu gegen Tore offen -- der Vergleich, der die Frage entscheidet.

Am 20.10.2026 wurden die beiden Wirtschaftlichkeitstore des Plankontos auf
Anweisung geoeffnet (Kostendeckel 0.08 -> 1.0, Chance-Risiko 1.5 -> 0.01).
Anlass war ein Tag, an dem die abgelehnten Signale +74 USD getragen haetten.

Dagegen stand eine Messung ueber 3.553 abgelehnte Signale: netto -0.1464 R je
Trade gegen -0.0323 R der genommenen. Beides sind Behauptungen ueber die
Zukunft, und genau deshalb gibt es dieses Skript: in ein paar Wochen steht
hier eine Zahl statt zweier Meinungen.

**Warum der Vergleich ueberhaupt moeglich ist.** Die Laufsignatur traegt beide
Tore -- den Kostendeckel schon immer, das Chance-Risiko seit dem 20.10. (bis
dahin eine Luecke: wer nur das CRV aenderte, hinterliess keine Spur). Die
Zeilen vor und nach der Umstellung sind dadurch mechanisch trennbar statt nur
der Absicht nach:

    zu      ...|0.08|M15|refused-v1|portfolio|cap5|plan30x7
    offen   ...|1.0|M15|refused-v1|portfolio|cap5|crv0.01|plan30x7

**Was dieser Vergleich NICHT ist.** Die beiden Haelften liegen
HINTEREINANDER, nicht nebeneinander. Es gibt keine Kontrollgruppe -- der
Nutzer hat sich bewusst dagegen entschieden. Ein Unterschied kann darum auch
vom Markt kommen statt von den Toren. Das ist eine Schwaeche der Anlage und
kein Rechenfehler; sie laesst sich nicht wegrechnen, nur benennen.

**Die Zahl, auf die es ankommt, ist R und nicht USD.** USD haengt an der
Kontogroesse zum Zeitpunkt des Trades, R nicht. Beide stehen da, aber das
Urteil haengt an R.

    python scripts/tore_vergleich.py
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sqlite3
import sys
from statistics import NormalDist

ROOT = pathlib.Path(__file__).resolve().parent.parent
JOURNAL = ROOT / "data" / "journal.sqlite"

#: Die gemessene Erwartung der abgelehnten Population (study_refused.py,
#: ADAUSDT, 3.553 Signale, ein Codestand). Daran wird gemessen, nicht an null:
#: die Frage ist nicht "verdient es?", sondern "verdient es mehr, als die
#: Messung vorhersagt?".
ERWARTUNG_ABGELEHNT = -0.1464
ERWARTUNG_GENOMMEN = -0.0323
#: Unter so vielen geschlossenen Trades wird nicht geurteilt.
MIN_TRADES = 30


def zeilen() -> list[dict]:
    con = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=20)
    raus = []
    for sym, r, pnl, opened, closed, payload in con.execute(
        """SELECT symbol, r_multiple, net_pnl, opened_ts, closed_ts, payload
           FROM trades WHERE payload IS NOT NULL AND closed_ts IS NOT NULL"""
    ):
        try:
            p = json.loads(payload)
        except json.JSONDecodeError:
            continue
        sig = p.get("run_signature")
        if not sig or "plan30x7" not in sig:
            continue
        raus.append({
            "symbol": sym, "r": float(r or 0.0), "pnl": float(pnl or 0.0),
            "opened": int(opened or 0), "closed": int(closed or 0),
            "offen": "crv0.01" in sig, "grund": p.get("exit_reason", "?"),
        })
    con.close()
    raus.sort(key=lambda z: z["closed"])
    return raus


def signale(offen: bool) -> tuple[int, int]:
    """(Vorschlaege, davon abgelehnt) unter der jeweiligen Signatur.

    Ohne diese Zahl liest sich "0 Trades" wie ein fehlendes Ergebnis. Es ist
    aber das Ergebnis: unter geschlossenen Toren wurden 29 von 29 Signalen
    abgelehnt. Eine Null, die aus einer Entscheidung kommt, muss anders
    aussehen als eine, die aus fehlenden Daten kommt.
    """
    pfad = ROOT / "data" / "signals.sqlite"
    if not pfad.exists():
        return (0, 0)
    con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True, timeout=20)
    muster = "%crv0.01%plan30x7%" if offen else "%cap5|plan30x7%"
    ges = con.execute(
        "SELECT COUNT(*) FROM signals WHERE run_signature LIKE ?", (muster,)
    ).fetchone()[0]
    abl = con.execute(
        "SELECT COUNT(*) FROM signals WHERE run_signature LIKE ? AND action='abgelehnt'",
        (muster,),
    ).fetchone()[0]
    con.close()
    return (ges, abl)


def block(name: str, rows: list[dict], erwartung: float, *, offen: bool) -> None:
    print(f"\n  {name}")
    ges, abl = signale(offen)
    if ges:
        print(f"    {ges} Signale, davon {abl} abgelehnt, {ges - abl} genommen")
    if not rows:
        if ges and abl == ges:
            print("    0 geschlossene Trades -- und das ist das Ergebnis, nicht")
            print("    eine Luecke: die Tore haben jedes einzelne Signal abgelehnt.")
        else:
            print("    noch keine geschlossenen Trades (offene zaehlen nicht mit).")
        return
    rs = [z["r"] for z in rows]
    n = len(rs)
    mittel = sum(rs) / n
    pnl = sum(z["pnl"] for z in rows)
    treffer = sum(1 for r in rs if r > 0) / n
    print(f"    {n} Trades  |  {mittel:+.4f} R je Trade  |  {pnl:+.2f} USD  "
          f"|  Treffer {treffer*100:.0f} %")
    if n >= 2:
        sd = math.sqrt(sum((r - mittel) ** 2 for r in rs) / (n - 1))
        se = sd / math.sqrt(n)
        z = NormalDist().inv_cdf(0.975)
        lo, hi = mittel - z * se, mittel + z * se
        print(f"    95 %-Intervall [{lo:+.4f}, {hi:+.4f}]")
        if n < MIN_TRADES:
            print(f"    UNENTSCHEIDBAR: unter {MIN_TRADES} Trades wird nicht geurteilt.")
        elif lo > erwartung:
            print(f"    BESSER als die Messung erwartet ({erwartung:+.4f} R) "
                  f"-- das Intervall liegt darueber.")
        elif hi < erwartung:
            print(f"    SCHLECHTER als die Messung erwartet ({erwartung:+.4f} R).")
        else:
            print(f"    Mit der Messung vertraeglich ({erwartung:+.4f} R liegt im Intervall).")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trades", action="store_true", help="Jeden Trade einzeln zeigen.")
    a = p.parse_args(argv)

    alle = zeilen()
    zu = [z for z in alle if not z["offen"]]
    offen = [z for z in alle if z["offen"]]

    print("=" * 74)
    print("PLANKONTO -- Tore zu gegen Tore offen")
    print("=" * 74)

    block(f"TORE ZU    (bis 20.10. 13:00, Kostendeckel 0.08 / CRV 1.5)",
          zu, ERWARTUNG_GENOMMEN, offen=False)
    block(f"TORE OFFEN (ab 20.10. 13:00, Kostendeckel 1.0 / CRV 0.01)",
          offen, ERWARTUNG_ABGELEHNT, offen=True)

    if a.trades and offen:
        import datetime as dt
        print(f"\n  {'geschlossen':<16} {'Symbol':<10} {'R':>8} {'USD':>9}  Grund")
        for z in offen:
            t = dt.datetime.fromtimestamp(z["closed"] / 1000)
            print(f"  {t:%d.%m %H:%M:%S}    {z['symbol']:<10} {z['r']:>+8.3f} "
                  f"{z['pnl']:>+9.2f}  {z['grund']}")

    print("\n  Hinweis zur Anlage: die beiden Haelften liegen HINTEREINANDER,")
    print("  nicht nebeneinander. Ohne Kontrollgruppe kann ein Unterschied auch")
    print("  vom Markt kommen. Das ist benennbar, nicht wegzurechnen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
