"""Die Gegenseite aufnehmen: Binance-Trades parallel zum Venue-Tape.

    python scripts/collect_binance_tape.py --hours 9.5

**Warum das noetig wurde, und es war ein Befund.** `collect_venue_tape.py`
nimmt seit 17:39 UTC die neue Venue auf. Damit allein ist E0 Punkt 3 nicht
beantwortbar -- *"Teste Signale, die auf der bisherigen Venue entstehen, mit
einer zeitlich korrekt empfangenen Ausfuehrung auf der neuen"* braucht
**beide** Seiten auf demselben Fenster.

Nachgesehen: die gespeicherten Binance-Minuten enden am **01.10. 13:57
UTC**, sechs Tage vor dem Tape. Es gibt keinen Ueberlapp. Ohne diese
Aufnahme waere das Venue-Tape eine Haelfte ohne Gegenstueck gewesen -- und
das haette man erst beim Auswerten gemerkt.

Der Forschungsauftrag sagt es in E0 Punkt 1 ausdruecklich: *"Erfasse fuer
BTC und ETH **parallel** Quotes, Trades, Funding, Instrumentparameter und
lokale Empfangszeiten."* Parallel ist das Wort, auf das es ankommt.

**Was hier besser geht als auf der anderen Seite.** `aggTrades` traegt eine
**pro Symbol** fortlaufende Kennung (`a`), nicht eine globale. Damit ist
eine echte Luecke zaehlbar: springt `a` um mehr als das Gesammelte, sind
genau so viele Trades durchgefallen. Auf der neuen Venue laeuft `trade_id`
global ueber alle Maerkte, weshalb die Luecke dort nur als *Ereignis*
berichtet werden kann und nicht als Zahl. Hier geht beides.

Gemessen am 07.10.2026: 10.1 aggTrades/s auf BTCUSDT, `limit=1000` deckt
also 99 Sekunden. Ein Takt von 30s hat dreifache Reserve.

**Nur lesen.** Kein Schluessel, keine Order.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BASE = "https://fapi.binance.com/fapi/v1/aggTrades"
OUT = ROOT / "data" / "quarantine" / "binance_tape"
TIMEOUT = 20.0

#: Hoechstes `limit` der API.
PAGE = 1000

#: Takt. 10.1 Trades/s auf BTC heisst 99s Abdeckung je Seite; 30s laesst
#: dreifache Reserve, auch wenn die Rate sich verdreifacht.
EVERY = 30.0

#: Neue Datei je Stunde, wie beim Venue-Tape.
ROTATE_MS = 3_600_000

#: Fortschrittsvermerk. Erzwungen getestet, nicht erst nach zehn Minuten
#: zum ersten Mal ausgefuehrt -- genau daran starb der erste Collector.
NOTE_EVERY = 600.0

#: Behalten wird, was die Auswertung braucht. `a` die Kennung, `T` die
#: Zeit, `p`/`q` der Trade, `m` die Aggressor-Seite (true = der Kaeufer war
#: Maker, der Trade lief also am Bid). Verworfen: `f`, `l` (erste und
#: letzte Einzel-Trade-ID der Aggregation) und `nq`.
FIELDS = ("a", "p", "q", "T", "m")


@dataclass
class Market:
    symbol: str
    high_id: int = 0
    polls: int = 0
    trades: int = 0
    #: Echte Zahl durchgefallener Trades. Hier moeglich, weil `a` pro
    #: Symbol laeuft -- anders als die globale trade_id der neuen Venue.
    missed: int = 0
    errors: int = 0
    last_error: str = ""
    next_poll: float = 0.0
    _seen: set[int] = field(default_factory=set)


def path_for(symbol: str, received_ms: int) -> Path:
    hour = (received_ms // ROTATE_MS) * ROTATE_MS
    folder = OUT / symbol
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"trades-{hour}.jsonl"


def poll(market: Market) -> None:
    received = int(time.time() * 1000)
    url = f"{BASE}?symbol={market.symbol}&limit={PAGE}"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:
        rows = json.loads(answer.read())
    if not rows:
        return

    ids = [int(r["a"]) for r in rows]
    oldest, newest = min(ids), max(ids)
    fresh = [r for r in rows if int(r["a"]) > market.high_id]

    if market.high_id and oldest > market.high_id + 1:
        # Echte Zahl, weil `a` pro Symbol fortlaeuft: zwischen der zuletzt
        # gesehenen Kennung und der aeltesten dieser Seite liegen genau so
        # viele Aggregat-Trades, und wir haben keinen davon gesehen.
        market.missed += oldest - market.high_id - 1

    if fresh:
        trimmed = [{k: r[k] for k in FIELDS if k in r} for r in fresh]
        line = json.dumps({"received_ms": received, "trades": trimmed}, ensure_ascii=False)
        with path_for(market.symbol, received).open("a", encoding="utf-8") as sink:
            sink.write(line + "\n")
        market.trades += len(fresh)
    market.high_id = max(market.high_id, newest)
    market.polls += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=9.5)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    args = parser.parse_args()

    markets = [Market(symbol=s.strip().upper()) for s in args.symbols.split(",") if s.strip()]

    print("=" * 74)
    print("Binance-Trades, parallel zum Venue-Tape -- die Gegenseite fuer E0 Punkt 3")
    print("=" * 74)
    print(
        f"\n  Dauer   {args.hours:.1f}h\n  Ziel    {OUT}\n"
        f"  Takt    alle {EVERY:.0f}s, limit={PAGE} (deckt ~99s bei 10 Trades/s)\n"
        f"  Maerkte {', '.join(m.symbol for m in markets)}\n"
        f"\n  Luecken sind hier als ZAHL messbar: `a` laeuft pro Symbol, nicht\n"
        f"  global wie die trade_id der neuen Venue.\n"
        f"\n  Nur lesen. Kein Schluessel, keine Order.\n",
        flush=True,
    )

    started = time.time()
    deadline = started + args.hours * 3600
    last_note = started
    try:
        while time.time() < deadline:
            now = time.time()
            for market in markets:
                if now >= market.next_poll:
                    try:
                        poll(market)
                    except (urllib.error.URLError, TimeoutError, OSError) as problem:
                        market.errors += 1
                        market.last_error = str(problem)[:120]
                    market.next_poll = now + EVERY
            if now - last_note >= NOTE_EVERY:
                done = sum(m.trades for m in markets)
                lost = sum(m.missed for m in markets)
                print(
                    f"  [{(now - started) / 3600:5.2f}h] {done:,} Trades, {lost:,} verloren",
                    flush=True,
                )
                last_note = now
            soonest = min(m.next_poll for m in markets)
            time.sleep(max(0.5, min(5.0, soonest - time.time())))
    except KeyboardInterrupt:
        print("\n  Abgebrochen. Was geschrieben ist, bleibt.")

    ran = (time.time() - started) / 3600
    print(f"\n  Aufgenommen in {ran:.2f}h:")
    print(f"  {'Markt':10s} {'Abfragen':>9s} {'Trades':>10s} {'verloren':>9s} {'Fehler':>7s}")
    print("  " + "-" * 50)
    for m in markets:
        print(f"  {m.symbol:10s} {m.polls:>9,} {m.trades:>10,} {m.missed:>9,} {m.errors:>7,}")
    lost = sum(m.missed for m in markets)
    got = sum(m.trades for m in markets)
    if lost:
        print(
            f"\n  ! {lost:,} von {lost + got:,} Trades sind durchgefallen "
            f"({100 * lost / max(1, lost + got):.2f}%).\n"
            f"    Das ist hier eine ECHTE Zahl, keine Obergrenze: `a` laeuft pro\n"
            f"    Symbol, also ist die Luecke zaehlbar."
        )
    else:
        print("\n  Keine Luecke: die Aufnahme ist lueckenlos.")
    print(f"\n  Liegt unter {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
