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

#: Starttakt. **Und ein Befund daran.** Die erste Fassung stand fest auf 30s,
#: begruendet mit 10.1 Trades/s auf BTC: `limit=1000` deckt dann 99s, also
#: dreifache Reserve. Nach neun Stunden am 08.10.2026 meldete der Zaehler
#: 693,220 gesammelte gegen **1,099,312 verlorene** Trades -- 38.7 % Abdeckung.
#:
#: Die Rechnung war nicht falsch, sie war abgelaufen. Der Markt fiel in diesen
#: Stunden (BTC 84,751 -> 80,991) und handelte 27.7 Trades/s je Symbol, also
#: 2.7x so viel wie bei der Kalibrierung. `limit=1000` deckt dann 36s, und
#: gegen einen Takt von 30s ist das 1.20x Reserve -- eine langsame Antwort oder
#: ein Schub genuegt. **Ein einmal gemessener Takt ist eine Konstante, die
#: stillschweigend verfaellt.** Darum regelt er sich jetzt selbst.
EVERY = 15.0

#: Untergrenze. Eine Abfrage mit `limit=1000` kostet Gewicht 20, erlaubt sind
#: 2400/min je IP. Zwei Maerkte alle 8s sind 300/min -- und diese IP teilt sich
#: der Papierhaendler, der hier schon einmal ans Limit gelaufen ist, als
#: versehentlich zwei von ihm liefen.
FLOOR = 8.0

#: Harte Obergrenze, wenn nichts verloren geht. Kein Grund, schneller zu
#: fragen als noetig: jede Abfrage ist Gewicht, das der Papierhaendler auch
#: braucht.
#:
#: Sie ist nur die HARTE Grenze. Die wirksame Obergrenze rechnet `Market.
#: ceiling()` aus der gemessenen Rate, und zwar wegen eines Befunds des Laufs
#: vom 08.10.2026: 94.9 % Abdeckung, und alle 37 Verkuerzungen kamen von
#: vollen Seiten. Der Melder arbeitete also -- aber die feste 30s liessen den
#: Takt danach wieder dorthin zurueckdriften. Bei den gemessenen 35.1 Trades/s
#: deckt eine Seite 28.5s, und ein Takt von 30s verliert dann zwangslaeufig.
#: Eine Obergrenze, die die Rate nicht kennt, ist derselbe Fehler wie der
#: feste Takt davor, nur eine Ebene hoeher.
CEILING = 30.0

#: Reserve zwischen Seitenabdeckung und Takt. Dieselbe Zahl wie im
#: Venue-Collector, damit beide Aufnahmen dieselbe Vorsicht haben.
SAFETY = 3.0

#: So viele verlustfreie Abfragen hintereinander, bevor der Takt sich wieder
#: entspannt. Einseitig schnell: halbieren bei einem einzigen Verlust,
#: verlangsamen erst nach Belegen.
CALM = 20

#: Neue Datei je Stunde, wie beim Venue-Tape.
ROTATE_MS = 3_600_000

#: Fortschrittsvermerk. Erzwungen getestet, nicht erst nach zehn Minuten
#: zum ersten Mal ausgefuehrt -- genau daran starb der erste Collector.
NOTE_EVERY = 600.0

#: Nach so vielen Sekunden ohne neuen Trade meldet sich die Aufnahme laut.
#: In der Nacht vom 07./08.10.2026 fiel die Verbindung nach einer Stunde
#: aus; beide Collectoren liefen zwoelf Stunden weiter und zaehlten still
#: Fehler. 338 Fehler gegen 59 Abfragen, und der Bericht meldete am Ende
#: 'Keine Luecke' -- richtig und vollkommen irrefuehrend.
STALL_AFTER = 300.0

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
    #: Der eigene Takt, je Markt. BTC und ETH handeln nicht gleich viel.
    every: float = EVERY
    #: Wann die erste Abfrage lief, fuer die Ratenschaetzung.
    first_ms: float = 0.0
    #: Wie oft der Takt verkuerzt wurde, und wie oft die Seite voll war.
    tightened: int = 0
    saturated: int = 0
    _calm: int = 0
    _seen: set[int] = field(default_factory=set)

    def rate(self) -> float:
        """Gemessene Trades je Sekunde, oder 0 solange nichts gemessen ist."""
        if not self.first_ms or self.trades <= 0:
            return 0.0
        elapsed = time.time() - self.first_ms
        return self.trades / elapsed if elapsed > 1.0 else 0.0

    def ceiling(self) -> float:
        """Wirksame Obergrenze: so langsam, dass eine Seite dreifach reicht.

        Ohne Messung gilt die harte Grenze. Mit Messung gilt, was die Rate
        erlaubt -- und das ist bei einem schnellen Markt deutlich weniger als
        30s. Verloren geht sonst genau dann etwas, wenn der Markt interessant
        wird, was der schlechteste Zeitpunkt dafuer ist.
        """
        measured = self.rate()
        if measured <= 0:
            return CEILING
        return max(FLOOR, min(CEILING, PAGE / (SAFETY * measured)))

    def adapt(self, *, lost: bool, full: bool) -> None:
        """Takt nachziehen.

        Eine Luecke ist der Beleg, dass der Takt zu langsam war. Eine volle
        Seite ist ein Warnzeichen ohne Beleg: `len(fresh) == PAGE` heisst, dass
        genau so viele neue Trades da waren, wie die Seite tragen kann -- es
        koennten mehr gewesen sein, und wir wuessten es nicht. Beides verkuerzt,
        weil der Beleg hier teuer ist und die Abfrage billig.
        """
        if lost or full:
            self.every = max(FLOOR, self.every / 2)
            self.tightened += 1
            self._calm = 0
            if full:
                self.saturated += 1
            return
        self._calm += 1
        if self._calm >= CALM:
            self.every = min(self.ceiling(), self.every * 1.5)
            self._calm = 0


def path_for(symbol: str, received_ms: int) -> Path:
    hour = (received_ms // ROTATE_MS) * ROTATE_MS
    folder = OUT / symbol
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"trades-{hour}.jsonl"


def poll(market: Market) -> tuple[bool, bool]:
    """Eine Seite holen. Gibt zurueck, ob etwas verloren ging und ob sie voll war."""
    received = int(time.time() * 1000)
    if not market.first_ms:
        market.first_ms = time.time()
    url = f"{BASE}?symbol={market.symbol}&limit={PAGE}"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:
        rows = json.loads(answer.read())
    if not rows:
        return False, False

    ids = [int(r["a"]) for r in rows]
    oldest, newest = min(ids), max(ids)
    fresh = [r for r in rows if int(r["a"]) > market.high_id]

    # Erst ab der zweiten Abfrage aussagekraeftig: beim ersten Mal ist
    # `high_id` null, also ist jede Zeile neu und die Seite zwangslaeufig voll.
    started = market.high_id > 0
    lost = started and oldest > market.high_id + 1
    full = started and len(fresh) >= PAGE

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
    return lost, full


def report(markets: list[Market], *, started: float) -> None:
    ran = (time.time() - started) / 3600
    print(f"\n  Aufgenommen in {ran:.2f}h:")
    print(
        f"  {'Markt':10s} {'Abfragen':>9s} {'Trades':>10s} {'verloren':>11s} "
        f"{'Abdeckung':>10s} {'Takt':>6s} {'enger':>6s} {'Fehler':>7s}"
    )
    print("  " + "-" * 78)
    for m in markets:
        seen = m.trades + m.missed
        share = 100 * m.trades / seen if seen else 100.0
        print(
            f"  {m.symbol:10s} {m.polls:>9,} {m.trades:>10,} {m.missed:>11,} "
            f"{share:>9.1f}% {m.every:>5.0f}s {m.tightened:>6,} {m.errors:>7,}"
            f"   (Rate {m.rate():.1f}/s, Obergrenze {m.ceiling():.0f}s)"
        )
    lost = sum(m.missed for m in markets)
    got = sum(m.trades for m in markets)
    rate = (lost + got) / max(1.0, ran * 3600) / max(1, len(markets))
    if lost:
        print(
            f"\n  ! {lost:,} von {lost + got:,} Trades sind durchgefallen "
            f"({100 * lost / max(1, lost + got):.2f}%).\n"
            f"    Das ist hier eine ECHTE Zahl, keine Obergrenze: `a` laeuft pro\n"
            f"    Symbol, also ist die Luecke zaehlbar.\n"
            f"\n    Gemessene Rate: {rate:.1f} Trades/s je Markt. `limit={PAGE}` deckt\n"
            f"    damit {PAGE / max(0.1, rate):.0f}s. Wer diese Aufnahme auswertet, zitiert die\n"
            f"    Abdeckung oben mit -- eine Luecken-Statistik auf einem lueckenhaften\n"
            f"    Tape ist eine Aussage ueber den Collector, nicht ueber den Markt."
        )
    else:
        print("\n  Keine Luecke: die Aufnahme ist lueckenlos.")
    print(
        f"\n  Takt zu Beginn {EVERY:.0f}s, Spanne {FLOOR:.0f}-{CEILING:.0f}s, "
        f"{sum(m.tightened for m in markets):,}x verkuerzt "
        f"(davon {sum(m.saturated for m in markets):,}x wegen voller Seite)."
    )
    print(f"\n  Liegt unter {OUT}")


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
        f"  Takt    {EVERY:.0f}s zu Beginn, regelt sich selbst in {FLOOR:.0f}-{CEILING:.0f}s\n"
        f"          (halbiert bei Luecke oder voller Seite, entspannt nach {CALM} sauberen)\n"
        f"  Maerkte {', '.join(m.symbol for m in markets)}\n"
        f"\n  Luecken sind hier als ZAHL messbar: `a` laeuft pro Symbol, nicht\n"
        f"  global wie die trade_id der neuen Venue.\n"
        f"\n  Nur lesen. Kein Schluessel, keine Order.\n",
        flush=True,
    )

    started = time.time()
    deadline = started + args.hours * 3600
    last_note = started
    last_progress = started
    last_count = 0
    try:
        while time.time() < deadline:
            now = time.time()
            for market in markets:
                if now >= market.next_poll:
                    try:
                        lost, full = poll(market)
                        market.adapt(lost=lost, full=full)
                    except (urllib.error.URLError, TimeoutError, OSError) as problem:
                        market.errors += 1
                        market.last_error = str(problem)[:120]
                    market.next_poll = now + market.every
            collected = sum(m.trades for m in markets)
            if collected > last_count:
                last_count, last_progress = collected, now
            elif now - last_progress >= STALL_AFTER:
                errs = sum(m.errors for m in markets)
                recent = next((m.last_error for m in markets if m.last_error), "")
                print(
                    f"  ! STILLSTAND: seit {(now - last_progress) / 60:.0f} Minuten kein "
                    f"neuer Trade. {errs:,} Fehler.\n    zuletzt: {recent[:150]}",
                    flush=True,
                )
                last_progress = now

            if now - last_note >= NOTE_EVERY:
                done = sum(m.trades for m in markets)
                lost = sum(m.missed for m in markets)
                share = 100 * done / max(1, done + lost)
                takt = "/".join(f"{m.every:.0f}s" for m in markets)
                print(
                    f"  [{(now - started) / 3600:5.2f}h] {done:,} Trades, {lost:,} verloren, "
                    f"{share:.1f}% Abdeckung, Takt {takt}",
                    flush=True,
                )
                last_note = now
            soonest = min(m.next_poll for m in markets)
            time.sleep(max(0.5, min(5.0, soonest - time.time())))
    except KeyboardInterrupt:
        print("\n  Abgebrochen. Was geschrieben ist, bleibt.")

    report(markets, started=started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
