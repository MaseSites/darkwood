"""Kalender- und Strike-Abstand zur Entscheidungszeit aufzeichnen (E26-Sammler).

    python scripts/record_ebenen.py            # ein Zyklus, zwoelf Maerkte
    python scripts/record_ebenen.py --status   # was bisher liegt

Laeuft als geplante Aufgabe `traidingBrain-ebenen` alle 15 Minuten, 20 Sekunden
nach der Viertelstunde, damit der Balken geschlossen ist. Schreibt je Markt
eine Zeile in `data/ebenen.sqlite` (Schema und Definitionen in
`traidingbrain/data/ebenen.py`). Nichts hiervon liest der Entscheidungspfad.

Quellen, je Zyklus einmal:
* Preis: Binance USD-M `ticker/price` je Markt (dieselbe Boerse wie der Haendler).
* Kalender: `data/macro_calendar.yaml` ueber `MacroCalendar.load`, plus die
  regelhaft abgeleiteten Termine.
* Strikes: Deribit ueber `traidingbrain.api.optionen.lage`, nur BTC und ETH --
  fuer die anderen zehn Maerkte fuehrt Deribit keine Optionen (gemessen 21.10.).
  Es wird NUR das offene Interesse je Strike benutzt, keine GEX-Zahl.

Eine Quelle, die nicht antwortet, laesst ihre Spalten leer und steht in
`quelle`; der Zyklus faellt deshalb nicht aus. Ein leerer Wert ist eine
Messung ("nicht erreichbar"), ein uebersprungener Zyklus waere keine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.api.optionen import WAEHRUNG, lage
from traidingbrain.data.calendar import MacroCalendar
from traidingbrain.data.ebenen import (
    entscheidungszeit,
    kalender_abstand,
    oeffne,
    schreibe,
    strike_abstand,
)

DB = ROOT / "data" / "ebenen.sqlite"
KALENDER = ROOT / "data" / "macro_calendar.yaml"
BINANCE = "https://fapi.binance.com/fapi/v1"
MARKETS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOGEUSDT", "BNBUSDT", "LTCUSDT", "DOTUSDT", "ATOMUSDT",
)


def preise() -> tuple[dict[str, float], str]:
    """Alle Preise in einem Aufruf; bei Ausfall leer plus Grund."""
    req = urllib.request.Request(
        f"{BINANCE}/ticker/price", headers={"User-Agent": "traidingBrain ebenen; read-only"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            rows = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {}, f"binance:{type(exc).__name__}"
    return {r["symbol"]: float(r["price"]) for r in rows if r.get("symbol") in MARKETS}, "binance"


def zyklus(now_ms: int | None = None) -> int:
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    ts = entscheidungszeit(now_ms)
    geschrieben_utc = datetime.now(UTC).isoformat(timespec="seconds")
    kalender = MacroCalendar.load(KALENDER)
    kal = kalender_abstand(kalender, ts)
    kurse, kurs_quelle = preise()

    strikes: dict[str, tuple[list[tuple[float, float]], float, str]] = {}
    for symbol, waehrung in WAEHRUNG.items():
        try:
            o = lage(symbol, max_strikes=200)
        except Exception as exc:
            strikes[symbol] = ([], 0.0, f"deribit:{type(exc).__name__}")
            continue
        paare = [(z.strike, z.call_oi + z.put_oi) for z in o.strikes]
        strikes[symbol] = (paare, o.spot, f"deribit:{waehrung}" if o.verfuegbar else "deribit:leer")

    con = oeffne(DB)
    neu = 0
    for symbol in MARKETS:
        preis = kurse.get(symbol)
        paare, spot, strike_quelle = strikes.get(symbol, ([], 0.0, "keine-optionen"))
        st = strike_abstand(preis if preis else spot, paare)
        zeile = {
            "ts": ts, "symbol": symbol, "preis": preis,
            "kalender_min_high": kal.min_high, "kalender_min_medium": kal.min_medium,
            "kalender_name": kal.name,
            "strike_naechst": st.naechst, "strike_abstand_pct": st.abstand_pct,
            "strike_oi": st.oi, "strike_max": st.max_strike,
            "strike_max_abstand_pct": st.max_abstand_pct, "strike_max_oi": st.max_oi,
            "quelle": f"{kurs_quelle}|{strike_quelle}", "geschrieben_utc": geschrieben_utc,
        }
        neu += int(schreibe(con, zeile))
    con.close()
    print(f"[{geschrieben_utc}] ts={ts} {neu}/{len(MARKETS)} neu  Kalender high={kal.min_high} "
          f"medium={kal.min_medium} ({kal.name})  Preise={len(kurse)} "
          f"BTC-Strike={strikes.get('BTCUSDT', ([], 0, ''))[2]}", flush=True)
    return 0


def status() -> int:
    if not DB.exists():
        print("noch keine Aufzeichnung")
        return 0
    con = oeffne(DB)
    n, erster, letzter, maerkte = con.execute(
        "SELECT COUNT(*), MIN(ts), MAX(ts), COUNT(DISTINCT symbol) FROM ebenen"
    ).fetchone()
    print(f"{n} Zeilen, {maerkte} Maerkte, von {erster} bis {letzter}")
    for row in con.execute(
        "SELECT ts, symbol, preis, kalender_min_high, strike_abstand_pct, strike_oi, quelle "
        "FROM ebenen WHERE symbol IN ('BTCUSDT','ETHUSDT') ORDER BY ts DESC LIMIT 6"
    ):
        print("  ", row)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    return status() if args.status else zyklus()


if __name__ == "__main__":
    raise SystemExit(main())
