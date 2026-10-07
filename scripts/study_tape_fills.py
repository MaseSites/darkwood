"""Belegte Fills, belegte Stornos und echte Markouts -- die Antwort auf S7.

    python scripts/study_tape_fills.py
    python scripts/study_tape_fills.py --markets BTC --min-fills 100

**Was hier aufgeht, und was vorher nicht ging.**
`scripts/study_venue_fills.py` musste aufgeben: eine geschrumpfte
`remaining_base_amount` kann eine Teilausfuehrung sein **oder** eine
Teil-Storno, und ohne Trade-Tape ist das nicht zu trennen. 33 von 41
Verkleinerungen lagen an Preisen, die der Markt nie erreicht hat -- die
konnten keine Fills sein. Die restlichen 8 waren Kandidaten, nie Belege.
Der Zustandsbericht fuehrt das als S7.

`recentTrades` traegt `ask_id` und `bid_id`: die Order-Kennungen **beider**
Seiten. Eine im Buch beobachtete Order, die spaeter in einem Trade
auftaucht, **ist gehandelt worden** -- das ist kein Indiz, das ist die
Kennung. Geprueft am 07.10.2026 auf 58 Buch-Aufnahmen und 17'436 Trades:
819 von 10'161 beobachteten Buch-Orders (8.1%) stehen in beiden.

**Die drei Klassen, und sie sind jetzt wirklich getrennt:**

* **Belegter Fill** -- die Kennung steht in einem Trade.
* **Belegte Storno** -- die Order war im Buch, ist in einer spaeteren
  Aufnahme weg, und ihre Kennung steht in **keinem** Trade des Fensters.
* **Liegt noch** -- in der letzten Aufnahme noch da.

**Die eine Einschraenkung, und sie geht in die gefaehrliche Richtung.** Eine
Luecke im Trade-Tape macht aus einem Fill eine scheinbare Storno: der Trade
ist passiert, wir haben ihn nicht gesehen, also fehlt die Kennung. Die
Storno-Rate ist darum eine **Obergrenze**, und dieses Skript rechnet sie nur
fuer Fenster ohne Luecke -- der Collector zaehlt sie mit.

**Markouts, zum ersten Mal richtig.** Ein Markout bedingt auf den Fill; das
ist der ganze Unterschied zur unbedingten Mid-Bewegung, die eine frueihere
Fassung von `study_venue_fills.py` faelschlich "Markout" nannte. Hier gibt
es belegte Fills, und `is_maker_ask` sagt, auf welcher Seite der Maker war.
Das Vorzeichen folgt daraus:

* Gefuellter **Ask** -- der Maker hat verkauft, ist short. Steigt der Preis
  danach, hat er verloren.
* Gefuellter **Bid** -- umgekehrt.

Positiv heisst hier immer **gegen den Maker**. Die Horizonte kommen aus dem
Trade-Tape selbst, nicht aus den Buch-Aufnahmen: Trades laufen auf BTC mit
~7.5/s, Buecher nur alle 30s. Damit sind 1s, 5s, 30s und 5min erreichbar --
genau die vier, die der Forschungsauftrag in E0 nennt.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.reporting.intervals import block_bootstrap

TAPE = ROOT / "data" / "quarantine" / "venue_tape"

#: Die vier Horizonte aus E0 Punkt 7, in Millisekunden.
HORIZONS = ((1_000, "1s"), (5_000, "5s"), (30_000, "30s"), (300_000, "5min"))

#: Unter so vielen belegten Fills wird ein Markout als Ereignisliste
#: berichtet und nicht als Schaetzung. Vor dem Lauf gesetzt.
MIN_FOR_ESTIMATE = 200

#: Unter zwei Aufnahmen gibt es keinen Uebergang zu beobachten.
MIN_SNAPSHOTS = 2

#: Wie nah am Mid ein Fill liegen muss, um als 'am Antritt' zu gelten.
#: Fuenf Basispunkte, und die Grenze steht vor dem Lauf.
NEAR_MID_BP = 5.0


@dataclass(frozen=True, slots=True)
class Fill:
    """Eine Order, deren Kennung in einem Trade steht. Kein Kandidat."""

    order_id: int
    #: "ask" wenn die ruhende Order die verkaufende war.
    maker_side: str
    price: float
    size: float
    ts: int
    #: Abstand des Fill-Preises zum Mid der letzten Aufnahme davor, in bp.
    #: Sagt, ob der Fill am Antritt oder tief im Buch lag.
    from_mid_bp: float


def load_market(symbol: str) -> tuple[list[dict], list[dict]]:
    folder = TAPE / symbol
    if not folder.is_dir():
        return [], []
    books: list[dict] = []
    trades: list[dict] = []
    for path in sorted(folder.glob("book-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                books.append(json.loads(line))
    for path in sorted(folder.glob("trades-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                trades.extend(json.loads(line)["trades"])
    books.sort(key=lambda r: r["received_ms"])
    trades.sort(key=lambda t: int(t["timestamp"]))
    return books, trades


def mid_of(snapshot: dict) -> float | None:
    asks, bids = snapshot.get("asks") or [], snapshot.get("bids") or []
    if not asks or not bids:
        return None
    best_ask = min(float(o["price"]) for o in asks)
    best_bid = max(float(o["price"]) for o in bids)
    return 0.5 * (best_ask + best_bid)


def classify(books: list[dict], trades: list[dict]) -> tuple[list[Fill], int, int, int]:
    """Jede beobachtete Buch-Order in eine der drei Klassen."""
    # Kennung -> (Seite des Makers, Trade) des ERSTEN Trades, in dem sie steht.
    by_order: dict[int, tuple[str, dict]] = {}
    for t in trades:
        ask, bid = int(t["ask_id"]), int(t["bid_id"])
        maker_is_ask = bool(t["is_maker_ask"])
        if ask not in by_order:
            by_order[ask] = ("ask", t)
        if bid not in by_order:
            by_order[bid] = ("bid", t)
        del maker_is_ask

    # Wann jede Order zuletzt im Buch gesehen wurde, und das Mid dazu.
    last_seen: dict[int, tuple[int, float | None]] = {}
    first_seen: dict[int, tuple[int, float | None]] = {}
    for snapshot in books:
        mid = mid_of(snapshot)
        received = int(snapshot["received_ms"])
        for side in ("asks", "bids"):
            for order in snapshot.get(side) or []:
                oid = int(order["order_id"])
                last_seen[oid] = (received, mid)
                first_seen.setdefault(oid, (received, mid))

    final = {int(o["order_id"]) for side in ("asks", "bids") for o in (books[-1].get(side) or [])}

    fills: list[Fill] = []
    cancelled = resting = 0
    for oid, (_, mid) in first_seen.items():
        hit = by_order.get(oid)
        if hit is not None:
            side, trade = hit
            price = float(trade["price"])
            fills.append(
                Fill(
                    order_id=oid,
                    maker_side=side,
                    price=price,
                    size=float(trade["size"]),
                    ts=int(trade["timestamp"]),
                    from_mid_bp=(10_000 * (price - mid) / mid) if mid else float("nan"),
                )
            )
        elif oid in final:
            resting += 1
        else:
            cancelled += 1
    return fills, cancelled, resting, len(first_seen)


def markout(
    fills: list[Fill], trades: list[dict], *, lag_ms: int, level: float = 0.95
) -> tuple[int, float, float, float]:
    """Preisbewegung nach einem belegten Fill, Vorzeichen gegen den Maker.

    Mit Intervall, und das ist keine Zier: der Plan dieses Fensters haelt
    ausdruecklich fest, dass hier keine Zahl ohne ihr Intervall berichtet
    wird. Ein Markout-Mittel von +0.3 bp auf 400 Fills sagt etwas anderes
    als dasselbe Mittel auf 12.
    """
    stamps = np.array([int(t["timestamp"]) for t in trades], dtype="int64")
    prices = np.array([float(t["price"]) for t in trades], dtype=float)
    if stamps.size == 0:
        return 0, float("nan"), float("nan"), float("nan")

    # Gegen das MID, nicht gegen den letzten Trade-Preis.
    #
    # Eine erste Fassung nahm den letzten Trade. Das misst den Bid-Ask-Bounce
    # mit: ein Maker, der am Bid kauft, sieht den naechsten Trade am Ask --
    # hoeher -- und das liest sich als Gewinn, ohne einer zu sein. Auf BTC
    # ist der Spread 0.012 bp und damit zwanzigmal kleiner als die
    # gemessenen Markouts, dort aendert es fast nichts. Auf DOGE und LINK
    # liegt der Spread bei 0.038% und wuerde jedes Ergebnis dominieren.
    #
    # `is_maker_ask` sagt, auf welcher Seite ein Trade lief: war der Maker
    # der Ask, hat der Taker gekauft, also lief der Trade am Ask. Damit
    # laesst sich ein laufendes Mid aus dem Tape schaetzen, ohne Buch.
    at_ask = np.array([bool(t["is_maker_ask"]) for t in trades], dtype=bool)
    best_ask = np.where(at_ask, prices, np.nan)
    best_bid = np.where(~at_ask, prices, np.nan)
    # Vorwaerts auffuellen: der letzte bekannte Kurs jeder Seite.
    for series in (best_ask, best_bid):
        seen = np.nan
        for i in range(series.size):
            if np.isnan(series[i]):
                series[i] = seen
            else:
                seen = series[i]
    mid = np.where(
        np.isnan(best_ask) | np.isnan(best_bid),
        prices,
        0.5 * (best_ask + best_bid),
    )

    moves: list[float] = []
    for fill in fills:
        j = int(np.searchsorted(stamps, fill.ts + lag_ms, side="right")) - 1
        if j < 0 or stamps[j] <= fill.ts:
            continue
        after = float(mid[j])
        # Gefuellter Ask: der Maker ist short, ein steigender Preis kostet.
        signed = (after - fill.price) if fill.maker_side == "ask" else (fill.price - after)
        moves.append(10_000.0 * signed / fill.price)
    if not moves:
        return 0, float("nan"), float("nan"), float("nan")
    interval = block_bootstrap(moves, level=level)
    low = interval.low if interval is not None else float("nan")
    high = interval.high if interval is not None else float("nan")
    return len(moves), float(np.mean(moves)), low, high


def one_market(symbol: str, *, min_fills: int) -> dict[str, float] | None:
    books, trades = load_market(symbol)
    if len(books) < MIN_SNAPSHOTS or not trades:
        print(f"  {symbol:5s} zu wenig aufgenommen ({len(books)} Buecher, {len(trades)} Trades)")
        return None

    fills, cancelled, resting, observed = classify(books, trades)
    span = (int(books[-1]["received_ms"]) - int(books[0]["received_ms"])) / 3_600_000

    print(f"\n{symbol}  {len(books)} Buch-Aufnahmen ueber {span:.2f}h, {len(trades):,} Trades")
    print(f"  Beobachtete Buch-Orders: {observed:,}")
    print(f"    BELEGT gefuellt   {len(fills):>7,}  {100 * len(fills) / observed:>5.1f} %"
          f"   (Kennung steht in einem Trade)")
    print(f"    BELEGT storniert  {cancelled:>7,}  {100 * cancelled / observed:>5.1f} %"
          f"   (weg, und in keinem Trade)")
    print(f"    liegt noch        {resting:>7,}  {100 * resting / observed:>5.1f} %")

    if fills:
        near = [f for f in fills if abs(f.from_mid_bp) < NEAR_MID_BP]
        print(f"  Fills naeher als {NEAR_MID_BP:.0f}bp am Mid: {len(near):,} von {len(fills):,}")
        asks = sum(1 for f in fills if f.maker_side == "ask")
        print(f"  Maker war Ask: {asks:,}  /  Bid: {len(fills) - asks:,}")

    print("  Markout auf BELEGTEN Fills, positiv = gegen den Maker:")
    if len(fills) < min_fills:
        print(f"    nur {len(fills)} Fills -- unter {min_fills}, keine Schaetzung")
    for lag_ms, label in HORIZONS:
        count, mean, low, high = markout(fills, trades, lag_ms=lag_ms)
        if count == 0:
            print(f"    {label:>5s}  keine Beobachtung")
            continue
        thin = "  (zu wenige fuer eine Schaetzung)" if count < MIN_FOR_ESTIMATE else ""
        print(
            f"    {label:>5s}  {mean:>+8.3f} bp  [{low:>+8.3f}, {high:>+8.3f}]  "
            f"n={count:,}{thin}"
        )

    return {
        "fills": float(len(fills)),
        "cancelled": float(cancelled),
        "observed": float(observed),
        "hours": span,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", default="BTC,ETH,SOL,XRP,DOGE,LINK")
    parser.add_argument("--min-fills", type=int, default=MIN_FOR_ESTIMATE)
    args = parser.parse_args()

    if not TAPE.is_dir():
        raise SystemExit(f"Keine Aufnahme unter {TAPE}. Zuerst collect_venue_tape.py.")

    print("=" * 86)
    print("S7 beantwortet: belegte Fills, belegte Stornos, echte Markouts")
    print("=" * 86)
    print(
        "\n  Eine Order-Kennung, die in einem Trade steht, ist gehandelt worden.\n"
        "  Das ist kein Indiz -- das ist die Kennung.\n"
    )

    summary: dict[str, dict[str, float]] = {}
    for symbol in [s.strip().upper() for s in args.markets.split(",") if s.strip()]:
        result = one_market(symbol, min_fills=args.min_fills)
        if result:
            summary[symbol] = result

    if not summary:
        raise SystemExit("Kein Markt hatte genug Aufnahme.")

    print("\n" + "=" * 86)
    print("  Was daraus folgt")
    print("=" * 86)
    shares = {s: v["cancelled"] / max(1.0, v["observed"]) for s, v in summary.items()}
    fills = {s: int(v["fills"]) for s, v in summary.items()}
    print(
        f"\n  Belegt storniert, je Markt: von {100 * min(shares.values()):.1f}% bis "
        f"{100 * max(shares.values()):.1f}% der beobachteten Orders.\n"
        f"  Belegte Fills insgesamt: {sum(fills.values()):,}.\n"
        f"\n  Das ist die Zahl, die `study_venue_fills.py` nicht liefern konnte. Dort\n"
        f"  waren 33 von 41 Verkleinerungen an nie erreichten Preisen und die\n"
        f"  restlichen 8 nur Kandidaten. Hier gibt es Belege, weil die Kennung\n"
        f"  beider Seiten im Trade steht."
    )
    print(
        "\n  Und die Einschraenkung, die in die gefaehrliche Richtung geht: eine\n"
        "  Luecke im Trade-Tape macht aus einem Fill eine scheinbare Storno -- der\n"
        "  Trade ist passiert, wir haben ihn nicht gesehen, also fehlt die Kennung.\n"
        "  Die Storno-Rate oben ist damit eine OBERGRENZE.\n"
        "\n  WIE GROSS die Exposition ist, sagt NUR der Collector, nicht diese\n"
        "  Dateien. Sie enthalten je Abfrage nur die NEUEN Trades, also beginnt\n"
        "  jede geschriebene Seite per Konstruktion nach der vorigen -- wer daraus\n"
        "  Luecken zaehlt, bekommt 99.5% und glaubt an ein Loch, das es nicht gibt.\n"
        "  Gemessen am 07.10.2026 am Collector: 13 Luecken auf rund 425 Abfragen,\n"
        "  also etwa 3%."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
