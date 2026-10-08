"""Quotes UND Trades der neuen Venue aufnehmen, zeitgestempelt. Der eine naechste Schritt.

    python scripts/collect_venue_tape.py --hours 11
    python scripts/collect_venue_tape.py --hours 1 --markets BTC,ETH

**Warum das der naechste Schritt war.** Abschnitt 18 des Zustandsberichts
nennt genau eine Sache: die parallele, zeitgestempelte Aufnahme von Quotes
*und Trades*. Drei offene Punkte haengen daran, und keiner kommt ohne sie
weiter -- E0 Punkt 3 (uebertraegt sich ein Signal auf die neue Venue), S7
(dieses Buch kann ohne Trade-Tape keinen Fill belegen) und E5 (Orderflow).

**Was den Blocker aufhebt.** `recentTrades` liefert je Trade `ask_id` und
`bid_id` -- die Order-Kennungen *beider* Seiten -- dazu `is_maker_ask` fuer
die Aggressor-Richtung und `transaction_time` in Mikrosekunden. Damit laesst
sich eine im Buch beobachtete Order per Kennung in den Trades
wiederfinden. Genau das war unmoeglich: `study_venue_fills.py` konnte eine
geschrumpfte `remaining_base_amount` nicht von einer Teil-Storno
unterscheiden und musste 33 von 41 Verkleinerungen als nicht belegbar
verwerfen. Mit der Kennung ist ein Fill ein Fill.

**Das Intervall ist gemessen, nicht gewaehlt.** `limit=100` ist das Maximum
der API (500 gibt HTTP 400). Gemessen am 07.10.2026:

    BTC   7.53 Trades/s  -> 100 Trades in  13.2s
    ETH   3.72 Trades/s  -> 100 Trades in  26.6s
    SOL   1.55 Trades/s  -> 100 Trades in  64.1s
    XRP   0.13 Trades/s  -> 100 Trades in 767.8s
    DOGE  0.05 Trades/s  -> 100 Trades in  1862s
    LINK  0.02 Trades/s  -> 100 Trades in  4152s

Wer BTC alle 30 Sekunden abfragt, verliert zwei Drittel der Trades und
sieht es nicht. Darum traegt jeder Markt sein eigenes Intervall, mit
Sicherheitsfaktor, und darum zaehlt dieses Skript **Luecken**: `trade_id`
ist monoton, also verraet ein Sprung, der groesser ist als das Gesammelte,
dass etwas fehlt. Eine Aufnahme mit stillen Loechern ist schlimmer als
keine, weil sie wie eine vollstaendige aussieht.

**Was hier nicht passiert.** Nur Lesen. Kein Schluessel, keine Order, kein
Konto. Die Venue bleibt Daten- und Shadow-Quelle, bis Kontoberechtigung,
Orderschutz und tatsaechliche Handelsrechte einen eigenen Review bestanden
haben -- und der wird nicht dadurch vorbereitet, dass hier Daten liegen.
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

BASE = "https://mainnet.zklighter.elliot.ai/api/v1"
MARKETS_PATH = f"{BASE}/orderBooks"
TRADES_PATH = BASE + "/recentTrades?market_id={market_id}&limit=100"
BOOK_PATH = BASE + "/orderBookOrders?market_id={market_id}&limit=100"

OUT = ROOT / "data" / "quarantine" / "venue_tape"
TIMEOUT = 20.0

#: Hoechstes `limit`, das die API annimmt. 500 gibt HTTP 400.
PAGE = 100

#: Gemessene Trades je Sekunde, 07.10.2026. Daraus faellt das Intervall:
#: Zeit bis `PAGE` Trades voll sind, geteilt durch SAFETY.
RATE = {"BTC": 7.53, "ETH": 3.72, "SOL": 1.55, "XRP": 0.13, "DOGE": 0.05, "LINK": 0.02}

#: Sicherheitsfaktor auf das Intervall. 3 heisst: abfragen, wenn die Seite
#: zu einem Drittel voll ist. Die Rate schwankt -- eine aktive Minute auf
#: BTC macht leicht das Doppelte des Mittels, und dann ist ein Faktor 1
#: schon zu knapp.
SAFETY = 3.0

#: Grenzen. Schneller als sekuendlich braucht kein Markt, und langsamer als
#: minuetlich verliert die langsamen Maerkte aus dem Blick.
MIN_EVERY = 1.0
MAX_EVERY = 60.0

#: Das Buch seltener als die Trades. Es dient dazu, eine Order VOR ihrem
#: Fill gesehen zu haben -- dafuer braucht es nicht jede Aenderung, sondern
#: genug Aufnahmen ueber die Zeit.
BOOK_EVERY = 30.0

#: Wie oft ein Fortschrittsvermerk kommt. Zehn Minuten: oft genug, um
#: einen haengenden Lauf zu erkennen, selten genug, dass elf Stunden
#: keine Logwand werden.
NOTE_EVERY = 600.0

#: Nach so vielen Sekunden ohne einen einzigen neuen Trade meldet sich die
#: Aufnahme laut. Fuenf Minuten: laenger als jede normale Flaute auf BTC
#: (7.5 Trades/s), kurz genug, dass ein Ausfall nicht die Nacht kostet.
STALL_AFTER = 300.0

#: Neue Datei je Stunde. Haelt eine einzelne Datei lesbar und macht einen
#: Abbruch billig: was geschrieben ist, bleibt.
ROTATE_MS = 3_600_000

#: Die Felder eines Trades, die aufgehoben werden -- und nur die.
#:
#: Die Antwort traegt 31 Felder zu 1'054 Bytes je Trade. Bei 13 Trades/s
#: auf BTC sind das 49 MB/h, ueber elf Stunden rund 800 MB, und das Ganze
#: liegt in einem OneDrive-Ordner, der jede Aenderung synchronisiert.
#:
#: Gekuerzt wird nach Verwendung, nicht nach Gefuehl:
#:   trade_id, timestamp, transaction_time  -- Ordnung und Zeit (us!)
#:   price, size, usd_amount                -- der Trade selbst
#:   ask_id, bid_id                         -- der JOIN ans Orderbuch, und
#:                                             damit der ganze Grund, dass
#:                                             diese Aufnahme den S7-Blocker
#:                                             aufhebt
#:   is_maker_ask                           -- Aggressor-Seite, also das
#:                                             Vorzeichen des Markouts
#:   maker_fee                              -- was der Maker wirklich zahlte
#:   ask_account_id, bid_account_id         -- ob derselbe Steller sich
#:                                             zurueckzieht (S7)
#:
#: Verworfen: tx_hash, type, market_id (steht im Pfad), market_kind, alle
#: `*_id_str`-Dubletten, `*_client_id*`, block_height (transaction_time ist
#: feiner), `*_position_size_before`, `*_entry_quote_before`,
#: `*_initial_margin_fraction_before`, `*_order_version`.
#:
#: Das ist unwiderruflich fuer DIESE Aufnahme. Wer eines davon braucht,
#: ergaenzt die Liste und nimmt neu auf -- darum steht hier, was fehlt.
TRADE_FIELDS = (
    "trade_id",
    "timestamp",
    "transaction_time",
    "price",
    "size",
    "usd_amount",
    "ask_id",
    "bid_id",
    "is_maker_ask",
    "maker_fee",
    "ask_account_id",
    "bid_account_id",
)

#: Dasselbe fuer eine Buchzeile. `order_index` ordnet die Warteschlange,
#: `order_id` ist der Join, der Rest ist Preis und Menge.
BOOK_FIELDS = (
    "order_id",
    "order_index",
    "price",
    "remaining_base_amount",
    "initial_base_amount",
    "owner_account_index",
)


def trim(row: dict[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    """Nur die angemeldeten Felder, in fester Reihenfolge."""
    return {key: row[key] for key in fields if key in row}


def interval_for(symbol: str) -> float:
    """Wie oft dieser Markt abgefragt werden muss, um nichts zu verlieren."""
    rate = RATE.get(symbol, 1.0)
    if rate <= 0:
        return MAX_EVERY
    return max(MIN_EVERY, min(MAX_EVERY, PAGE / rate / SAFETY))


@dataclass
class Tally:
    """Was die Aufnahme ueber sich selbst weiss."""

    polls: int = 0
    trades: int = 0
    books: int = 0
    errors: int = 0
    #: Abfragen, deren aelteste Zeile JUENGER war als die zuletzt gesehene
    #: -- dann liegt dazwischen etwas, das nie gesehen wurde.
    #:
    #: Ereignisse, nicht Trades. Die erste Fassung rechnete die Zahl der
    #: verlorenen Trades aus der Differenz der `trade_id` und meldete 97%
    #: Verlust, wo es keinen gab: die Kennung laeuft GLOBAL ueber alle
    #: Maerkte, also enthaelt die Luecke zwischen zwei ETH-Trades alle
    #: BTC-Trades dazwischen. Wie viele Trades fehlen, sagen diese Daten
    #: nicht -- also wird es nicht behauptet.
    gaps: int = 0
    #: Abfragen, die die Seite voll ausgeschoepft haben. Eine volle Seite
    #: heisst: es gab mindestens so viele Trades, moeglicherweise mehr.
    saturated: int = 0
    last_error: str = ""


@dataclass
class Market:
    symbol: str
    market_id: int
    every: float
    next_trades: float = 0.0
    next_book: float = 0.0
    #: Hoechste gesehene `trade_id`. Monoton, also verraet eine Seite, die
    #: darueber beginnt, dass etwas dazwischen fehlt.
    high_id: int = 0
    tally: Tally = field(default_factory=Tally)

    def adapt(self, *, got: int, gap: bool) -> None:
        """Den Takt an die wirkliche Rate anpassen.

        Ein fester Faktor auf eine einmal gemessene Rate reicht nicht: die
        gemessenen 3.72 Trades/s auf ETH waren im Probelauf 10.6, und bei
        9 Sekunden Takt lief die Seite ueber. Raten schwanken um ein
        Mehrfaches, und eine Konstante kann das nicht wissen.

        Also: bei voller Seite oder erkannter Luecke halbieren, bei duenner
        Seite langsam wachsen lassen. Das korrigiert sich selbst, egal was
        die Rate tut.
        """
        if gap or got >= PAGE:
            self.every = max(MIN_EVERY, self.every / 2.0)
        elif got < PAGE * 0.25:
            self.every = min(MAX_EVERY, self.every * 1.15)


def read_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:
        return json.loads(answer.read())


def discover(wanted: list[str]) -> list[Market]:
    payload = read_json(MARKETS_PATH)
    assert isinstance(payload, dict)
    out: list[Market] = []
    for book in payload["order_books"]:
        symbol = book["symbol"]
        if symbol in wanted and book.get("status") == "active":
            out.append(
                Market(
                    symbol=symbol,
                    market_id=int(book["market_id"]),
                    every=interval_for(symbol),
                )
            )
    return out


def path_for(symbol: str, kind: str, received_ms: int) -> Path:
    hour = (received_ms // ROTATE_MS) * ROTATE_MS
    folder = OUT / symbol
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{kind}-{hour}.jsonl"


def append(symbol: str, kind: str, payload: dict[str, object], received_ms: int) -> None:
    """Eine Zeile anhaengen, mit der LOKALEN Empfangszeit.

    Die Empfangszeit ist nicht die Boersenzeit, und das ist Absicht: der
    Forschungsauftrag verlangt lokale Empfangszeiten, weil die Differenz
    zwischen beiden die Latenz ist, die ein Backtest sonst verschweigt.
    """
    line = json.dumps({"received_ms": received_ms, **payload}, ensure_ascii=False)
    with path_for(symbol, kind, received_ms).open("a", encoding="utf-8") as sink:
        sink.write(line + "\n")


def poll_trades(market: Market) -> None:
    received = int(time.time() * 1000)
    payload = read_json(TRADES_PATH.format(market_id=market.market_id))
    assert isinstance(payload, dict)
    trades = payload.get("trades") or []
    if not trades:
        return

    ids = [int(t["trade_id"]) for t in trades]
    newest, oldest = max(ids), min(ids)

    fresh = [t for t in trades if int(t["trade_id"]) > market.high_id]
    # Luecke, wenn diese Seite nach der zuletzt gesehenen Kennung BEGINNT:
    # dann ist dazwischen etwas passiert, das keine Abfrage gesehen hat.
    # Ob und wie viele Trades das waren, sagen diese Daten nicht -- die
    # Kennung laeuft global ueber alle Maerkte.
    gap = bool(market.high_id) and oldest > market.high_id
    if gap:
        market.tally.gaps += 1
    # Auf den NEUEN Zeilen, nicht auf der Seitengroesse. Die erste Fassung
    # pruefte `len(trades) >= PAGE` und meldete damit 24 von 24 Abfragen als
    # "voll" -- natuerlich, die API gibt 100 zurueck, wenn man 100 anfragt.
    # Eine Kennzahl, die immer 100% liest, sagt nichts. Was zaehlt: war die
    # ganze Seite neu? Dann lagen moeglicherweise aeltere dahinter, die man
    # nie gesehen hat.
    if len(fresh) >= PAGE:
        market.tally.saturated += 1

    if fresh:
        rows = [trim(r, TRADE_FIELDS) for r in fresh]
        append(market.symbol, "trades", {"trades": rows}, received)
        market.tally.trades += len(fresh)
    market.high_id = max(market.high_id, newest)
    market.tally.polls += 1
    market.adapt(got=len(fresh), gap=gap)


def poll_book(market: Market) -> None:
    received = int(time.time() * 1000)
    payload = read_json(BOOK_PATH.format(market_id=market.market_id))
    assert isinstance(payload, dict)
    append(
        market.symbol,
        "book",
        {
            "asks": [trim(r, BOOK_FIELDS) for r in (payload.get("asks") or [])],
            "bids": [trim(r, BOOK_FIELDS) for r in (payload.get("bids") or [])],
        },
        received,
    )
    market.tally.books += 1


def report(markets: list[Market], *, started: float) -> None:
    ran = time.time() - started
    print(
        f"\n  Aufgenommen in {ran / 3600:.2f}h:\n"
        f"  {'Markt':6s} {'Takt':>7s} {'Abfragen':>9s} {'Trades':>9s} {'Buecher':>8s} "
        f"{'Luecken':>8s} {'volle S.':>9s} {'Fehler':>7s}"
    )
    print("  " + "-" * 74)
    for m in markets:
        t = m.tally
        print(
            f"  {m.symbol:6s} {m.every:>6.1f}s {t.polls:>9,} {t.trades:>9,} "
            f"{t.books:>8,} {t.gaps:>8,} {t.saturated:>9,} {t.errors:>7,}"
        )
    gaps = sum(m.tally.gaps for m in markets)
    polls = sum(m.tally.polls for m in markets)
    if gaps:
        print(
            f"\n  ! {gaps:,} von {polls:,} Abfragen ({100 * gaps / max(1, polls):.1f}%) begannen\n"
            f"    NACH der zuletzt gesehenen Kennung -- dazwischen liegen Trades, die\n"
            f"    keine Abfrage gesehen hat.\n"
            f"\n    WIE VIELE sagen diese Daten nicht, und die erste Fassung dieses\n"
            f"    Skripts behauptete es trotzdem: sie rechnete die Differenz der\n"
            f"    trade_id als Trade-Zahl und meldete 97% Verlust. Die Kennung laeuft\n"
            f"    GLOBAL ueber alle Maerkte -- die Luecke zwischen zwei ETH-Trades\n"
            f"    enthaelt jeden BTC-Trade dazwischen.\n"
            f"\n    Die Abdeckung ist also unvollstaendig. Was aufgenommen wurde, ist\n"
            f"    richtig; es ist nur nicht alles."
        )
    else:
        print("\n  Keine Abfrage begann nach einer Luecke: die Aufnahme ist durchgehend.")
    print(f"\n  Liegt unter {OUT}")


def banner(markets: list[Market], *, hours: float) -> None:
    """Was dieser Lauf vorhat, bevor er es tut."""
    print("=" * 72)
    print("Aufnahme: Quotes UND Trades, mit lokaler Empfangszeit")
    print("=" * 72)
    print(f"\n  Dauer    {hours:.1f}h\n  Ziel     {OUT}")
    print(f"  Buch     alle {BOOK_EVERY:.0f}s je Markt")
    print(f"  Stillstand wird nach {STALL_AFTER / 60:.0f} Minuten ohne Trade gemeldet")
    print("\n  Trade-Takt je Markt, aus der gemessenen Rate und PAGE=100:")
    for m in markets:
        print(f"    {m.symbol:6s} id {m.market_id:>3d}  alle {m.every:5.1f}s "
              f"({RATE.get(m.symbol, 0):.2f} Trades/s gemessen)")
    print("\n  Nur lesen. Kein Schluessel, keine Order.\n", flush=True)


def watch_stall(
    markets: list[Market], *, collected_before: int, since: float, now: float
) -> tuple[int, float]:
    """Meldet laut, wenn die Aufnahme nichts mehr aufnimmt.

    STILLSTAND ist ein Ereignis, kein Nichts.

    In der Nacht vom 07. auf den 08.10.2026 fiel die Verbindung nach einer
    Stunde aus. Der Prozess lief weiter, zaehlte Fehler und schrieb brav
    alle zehn Minuten denselben Vermerk: "60'297 Trades" -- sieben Stunden
    lang dieselbe Zahl. Gemerkt hat es niemand, auch der Wachhund nicht,
    denn der prueefte auf TOD und der Prozess lebte.

    Zwoelf Stunden Aufnahmezeit, verloren an eine Kennzahl, die sich nicht
    bewegte und das nicht sagte.
    """
    collected = sum(m.tally.trades for m in markets)
    if collected > collected_before:
        return collected, now
    if now - since >= STALL_AFTER:
        errors = sum(m.tally.errors for m in markets)
        recent = next((m.tally.last_error for m in markets if m.tally.last_error), "")
        print(
            f"  ! STILLSTAND: seit {(now - since) / 60:.0f} Minuten kein neuer Trade. "
            f"{errors:,} Fehler insgesamt.\n    zuletzt: {recent[:150]}",
            flush=True,
        )
        return collected, now
    return collected, since


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=11.0)
    parser.add_argument("--markets", default="BTC,ETH,SOL,XRP,DOGE,LINK")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    wanted = [s.strip().upper() for s in args.markets.split(",") if s.strip()]
    markets = discover(wanted)
    if not markets:
        raise SystemExit(f"Keine aktiven Maerkte unter {wanted}.")

    banner(markets, hours=args.hours)

    started = time.time()
    deadline = started + args.hours * 3600
    last_note = started
    last_progress = started
    last_count = 0

    try:
        while time.time() < deadline:
            now = time.time()
            for market in markets:
                if now >= market.next_trades:
                    try:
                        poll_trades(market)
                    except (urllib.error.URLError, TimeoutError, OSError) as problem:
                        market.tally.errors += 1
                        market.tally.last_error = str(problem)[:120]
                    market.next_trades = now + market.every
                if now >= market.next_book:
                    try:
                        poll_book(market)
                    except (urllib.error.URLError, TimeoutError, OSError) as problem:
                        market.tally.errors += 1
                        market.tally.last_error = str(problem)[:120]
                    market.next_book = now + BOOK_EVERY

            last_count, last_progress = watch_stall(
                markets, collected_before=last_count, since=last_progress, now=now
            )

            if not args.quiet and now - last_note >= NOTE_EVERY:
                # `gaps`, nicht `missed`. Der alte Name ueberlebte hier die
                # Umbenennung und riss den Lauf nach genau zehn Minuten ab --
                # also erst dann, wenn dieser Zweig zum ersten Mal lief. Jeder
                # Rauchtest lief kuerzer als NOTE_EVERY und hat den Pfad nie
                # beruehrt. Ein Codepfad, dessen Ausloeser laenger ist als der
                # Test, ist ungetestet, egal wie gruen der Test war.
                done = sum(m.tally.trades for m in markets)
                books = sum(m.tally.books for m in markets)
                gaps = sum(m.tally.gaps for m in markets)
                print(
                    f"  [{(now - started) / 3600:5.2f}h] {done:,} Trades, "
                    f"{books:,} Buecher, {gaps:,} Luecken",
                    flush=True,
                )
                last_note = now

            # Bis zur naechsten faelligen Abfrage schlafen, nicht blind.
            soonest = min(min(m.next_trades, m.next_book) for m in markets)
            time.sleep(max(0.2, min(5.0, soonest - time.time())))
    except KeyboardInterrupt:
        print("\n  Abgebrochen. Was geschrieben ist, bleibt.")

    report(markets, started=started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
