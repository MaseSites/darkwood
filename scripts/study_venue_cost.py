"""E0, erster Schritt: was kostet eine Ausführung auf einer Null-Gebühren-Venue?

    python scripts/study_venue_cost.py
    python scripts/study_venue_cost.py --samples 10 --pause 30

Registriert als E0 in `audit/EXPERIMENTS_NEXT.yaml`, erste Priorität.

## Warum dieser Arm der wichtigste ist

Der Zustandsbericht schloss: *"jeder Hebel, der nur die Maut senkt, ist ohne
Wirkung auf das Vorzeichen"*. Das war eine Aussage über **alle** Börsen,
gezogen aus einer Messung auf **einer**. An den Primärquellen geprüft
(07.10.2026) berechnen zwei Venues null Maker- und null bis 0,025 % Taker-Gebühr.

Damit verschiebt sich die Frage: bei null Gebühr entscheidet nicht mehr die
Gebühr, sondern **Spread, Tiefe, Latenz und adverse Selektion** -- vier
Grössen, die dieses Projekt nie gemessen hat.

## Was dieses Skript tut und was es ausdrücklich nicht tut

Es liest. Nur. Keine Authentifizierung, kein Wallet, kein Kapitaltransfer, keine
Order. Das sind die Grenzen, die der Forschungsauftrag für eine neue Venue
setzt, und sie sind hier nicht eine Absicht, sondern die Bauart: es gibt in
diesem Skript keinen Codepfad, der etwas sendet.

Es misst die Kosten, die ein Taker wirklich zahlt -- nicht den obersten Spread,
sondern den **Buch-Walk** für eine konkrete Ordergrösse. Der oberste Spread ist
die Zahl, die man zeigt, wenn man eine Börse verkaufen will; die Zahl, die ein
Trade zahlt, ist der mittlere Füllpreis gegen die Buchmitte.

**Es beweist keinen Vorteil.** Ein billiges Buch ist keine Strategie. Der
gemessene Einstiegsvorsprung dieses Projekts stammt von 5-Minuten-Kerzen einer
ANDEREN Börse, und ein dort gemessenes Signal wird nicht dadurch zu einem hier
belegten, dass die Ausführung billiger ist. Das ist der Rest von E0 und steht
noch aus.

## Drei Vorbehalte, die jede Zahl unten trägt

1. **Momentaufnahmen, keine Verteilung.** Mehrere Stichproben mildern das und
   ersetzen es nicht. Spreads weiten sich im Stress -- also genau dann, wenn
   Signale feuern.
2. **Latenz.** Die Venue dokumentiert für das Standardkonto 300 ms
   Taker-Verzögerung und 300 ms für Cancel/Modify. Diese Messung sieht das
   nicht; sie liest ein Buch, das 300 ms später anders aussehen kann.
3. **Berechtigung ungeklärt.** Ob der Kontoinhaber dort handeln darf, ist in
   diesem Projekt offen und wird durch eine Preismessung nicht geklärt.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.domain.market import DEFAULT_SPEC

CACHE = ROOT / "data" / "quarantine" / "venue_cost"

#: Nur lesende Endpunkte. Es gibt hier absichtlich keinen anderen.
BASE = "https://mainnet.zklighter.elliot.ai/api/v1"
MARKETS_PATH = f"{BASE}/orderBooks"
BOOK_PATH = BASE + "/orderBookOrders?market_id={market_id}&limit=200"

#: Die Märkte, die dieses Projekt handelt und die dort existieren.
WANTED = ("BTC", "ETH", "SOL", "XRP", "DOGE", "LINK")

#: Ordergrössen in USD. 1 000 ist das Startkapital des neuen Ziels; die anderen
#: zwei zeigen, wie die Kosten mit der Grösse wachsen.
NOTIONALS = (100.0, 1_000.0, 5_000.0)

#: Die Groesse, auf die der Vergleich mit dem Vorsprung sich bezieht: das
#: Startkapital des neuen Ziels.
REFERENCE = 1_000.0

#: Die Obergrenze des gemessenen Einstiegsvorsprungs, aus
#: `scripts/study_freqtrade_gross.py` (5-Minuten-Horizont, 83 Wochenblöcke).
#: Sie steht hier als Vergleichsmass, nicht als Versprechen.
EDGE_UPPER = 0.000106

#: Wann eine Ordergroesse als vollstaendig gefuellt gilt. Unter einem
#: Milliardstel USD ist der Rest Rundung, nicht Buch.
FILLED = 1e-9

DEFAULT_SAMPLES = 5
DEFAULT_PAUSE = 20.0
TIMEOUT = 25.0


@dataclass(frozen=True, slots=True)
class Snapshot:
    symbol: str
    spread: float
    depth_ask_usd: float
    walk: dict[float, float]
    """Mittlerer Fuellpreis gegen die Buchmitte, je Ordergroesse."""


def read_json(url: str, *, cache: Path | None) -> object:
    """Lesen, und die Antwort behalten.

    Der Cache ist nicht Bequemlichkeit: ein Urteil, dessen Grundlage nur in
    einer API-Antwort von heute steht, laesst sich morgen nicht pruefen.
    """
    if cache is not None and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    with urllib.request.urlopen(url, timeout=TIMEOUT) as answer:
        raw = answer.read()
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(raw)
    return json.loads(raw)


def market_ids() -> dict[str, tuple[int, float, float]]:
    """Markt-Kennung und die Gebuehren, wie die Venue sie selbst ausliefert.

    Das ist der Unterschied zwischen `documented` und `verified_here`: diese
    Zahlen stehen nicht in einer Dokumentationsseite, sondern in den
    Marktdaten, die die Boerse zu jedem Markt mitgibt.
    """
    payload = read_json(MARKETS_PATH, cache=CACHE / "markets.json")
    assert isinstance(payload, dict)
    out: dict[str, tuple[int, float, float]] = {}
    for book in payload["order_books"]:
        if book["symbol"] in WANTED and book.get("status") == "active":
            out[book["symbol"]] = (
                int(book["market_id"]),
                float(book["maker_fee"]),
                float(book["taker_fee"]),
            )
    return out


def walk_book(asks: list[dict], mid: float, notional: float) -> float | None:
    """Mittlerer Fuellpreis eines Taker-Kaufs gegen die Buchmitte.

    Der oberste Spread sagt, was ein unendlich kleiner Trade zahlt. Diese Zahl
    sagt, was ein echter zahlt -- und sie ist die, die mit dem Vorsprung
    verglichen werden darf.
    """
    left, cost, base = notional, 0.0, 0.0
    for level in asks:
        price, size = float(level["price"]), float(level["remaining_base_amount"])
        take = min(left / price, size)
        cost += take * price
        base += take
        left -= take * price
        if left <= FILLED:
            break
    if left > FILLED * 1000 or base <= 0.0:
        return None
    return cost / base / mid - 1.0


def sample(symbol: str, market_id: int, *, index: int) -> Snapshot | None:
    cache = CACHE / f"book_{symbol}_{index}.json"
    try:
        payload = read_json(BOOK_PATH.format(market_id=market_id), cache=cache)
    except (urllib.error.URLError, TimeoutError) as problem:
        print(f"  ! {symbol}: {problem}")
        return None
    assert isinstance(payload, dict)
    bids, asks = payload.get("bids") or [], payload.get("asks") or []
    if not bids or not asks:
        print(f"  ! {symbol}: leeres Buch")
        return None
    best_bid, best_ask = float(bids[0]["price"]), float(asks[0]["price"])
    mid = (best_bid + best_ask) / 2.0
    depth = sum(float(a["price"]) * float(a["remaining_base_amount"]) for a in asks)
    walk = {}
    for notional in NOTIONALS:
        cost = walk_book(asks, mid, notional)
        if cost is not None:
            walk[notional] = cost
    return Snapshot(symbol, (best_ask - best_bid) / mid, depth, walk)


def compare(round_trips: dict[str, float], *, samples: int) -> None:
    """Die Runde jeder Venue gegen den gemessenen Vorsprung, mit Vorbehalten.

    Getrennt von `main`, weil hier die eine Aussage steht, die das zentrale
    Ergebnis dieses Projekts verschiebt -- und sie soll neben ihren drei
    Vorbehalten stehen, nicht drei Bildschirme darueber.
    """
    old_floor = 2 * DEFAULT_SPEC["maker_fee"]
    old_real = DEFAULT_SPEC["maker_fee"] + DEFAULT_SPEC["taker_fee"]
    print("\n" + "-" * 96)
    print("Gegen die bisherige Boerse und gegen den gemessenen Vorsprung\n")
    print(f"  Maut maker/maker, bisherige Venue (Boden)   {100 * old_floor:.4f}%")
    print(f"  Maut maker/taker, bisherige Venue (real)    {100 * old_real:.4f}%")
    print(f"  Obergrenze des gemessenen Vorsprungs        {100 * EDGE_UPPER:.4f}%")
    print()
    usable = {s: t for s, t in round_trips.items() if not math.isnan(t)}
    for symbol, trip in sorted(usable.items(), key=lambda kv: kv[1]):
        verdict = "UNTER dem Vorsprung" if trip < EDGE_UPPER else "ueber dem Vorsprung"
        print(
            f"  {symbol:5s} Taker/Taker-Runde bei 1'000 USD: {100 * trip:.4f}%"
            f"  ({trip / EDGE_UPPER:.2f}x) -- {verdict}"
        )

    cheapest = min(usable, key=lambda s: usable[s]) if usable else None
    print("\n" + "-" * 96)
    if cheapest and usable[cheapest] < EDGE_UPPER:
        trip = usable[cheapest]
        print(
            f"  Zum ersten Mal in diesem Projekt liegt die GESAMTE Runde einer Venue\n"
            f"  unter der Obergrenze des gemessenen Einstiegsvorsprungs: {cheapest} mit\n"
            f"  {100 * trip:.4f}% gegen {100 * EDGE_UPPER:.4f}%, Faktor {EDGE_UPPER / trip:.1f}.\n"
            f"  Auf der bisherigen Venue war es umgekehrt, Faktor {old_floor / EDGE_UPPER:.1f}\n"
            f"  in die andere Richtung.\n"
            f"\n  Das ist KEIN Vorteil, und die Unterscheidung ist der ganze Punkt:\n"
            f"  der Vorsprung wurde auf 5-Minuten-Kerzen einer ANDEREN Boerse gemessen.\n"
            f"  Ein dort gemessenes Signal wird nicht dadurch zu einem hier belegten,\n"
            f"  dass die Ausfuehrung billiger ist. Was hier gezeigt ist: die Maut ist\n"
            f"  nicht mehr der Grund, warum es nicht gehen kann. Was offen bleibt:\n"
            f"  ob es geht."
        )
    else:
        print(
            "  Keine Venue-Runde liegt unter der Obergrenze des gemessenen Vorsprungs.\n"
            "  Dann bleibt die Maut auch hier der bindende Grund."
        )
    print(
        "\n  Drei Vorbehalte, die jede Zahl oben traegt:\n"
        f"    1. {samples} Momentaufnahmen sind keine Verteilung. Spreads weiten sich\n"
        "       im Stress, also genau dann, wenn Signale feuern.\n"
        "    2. Die Venue dokumentiert 300 ms Taker-Verzoegerung. Diese Messung liest\n"
        "       ein Buch, das 300 ms spaeter anders aussieht.\n"
        "    3. Ob der Kontoinhaber dort handeln darf, ist ungeklaert und wird durch\n"
        "       eine Preismessung nicht geklaert."
    )
    print("-" * 96)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE)
    parser.add_argument("--offline", action="store_true", help="Nur den Cache lesen")
    args = parser.parse_args()

    print("=" * 96)
    print("E0, erster Schritt: Ausfuehrungskosten auf einer Null-Gebuehren-Venue")
    print("=" * 96)
    print("\nNur lesend. Keine Authentifizierung, kein Wallet, keine Order.\n")

    ids = market_ids()
    if not ids:
        raise SystemExit("Keine der gesuchten Maerkte aktiv -- Antwort der Venue pruefen.")

    print("Gebuehren, wie die Venue sie in ihren MARKTDATEN ausliefert:")
    for symbol, (_, maker, taker) in sorted(ids.items()):
        print(f"  {symbol:5s} maker {100 * maker:.4f}%  taker {100 * taker:.4f}%")

    collected: dict[str, list[Snapshot]] = {s: [] for s in ids}
    for index in range(args.samples):
        for symbol, (market_id, _, _) in sorted(ids.items()):
            shot = sample(symbol, market_id, index=index)
            if shot is not None:
                collected[symbol].append(shot)
        if index + 1 < args.samples and not args.offline:
            time.sleep(args.pause)

    print(f"\n{args.samples} Stichproben je Markt.\n")
    print(
        f"  {'Markt':5s} {'Spread Median':>14s} {'Tiefe ask':>13s}"
        + "".join(f"{f'{int(n)} USD':>11s}" for n in NOTIONALS)
        + f"{'Runde 1k':>11s}"
    )
    print("  " + "-" * 88)
    round_trips: dict[str, float] = {}
    for symbol in sorted(collected):
        shots = collected[symbol]
        if not shots:
            print(f"  {symbol:5s} keine Daten")
            continue
        spread = float(np.median([s.spread for s in shots]))
        depth = float(np.median([s.depth_ask_usd for s in shots]))
        cells = []
        for notional in NOTIONALS:
            values = [s.walk[notional] for s in shots if notional in s.walk]
            cells.append(f"{100 * float(np.median(values)):>10.4f}%" if values else f"{'--':>11s}")
        thousand = [s.walk[REFERENCE] for s in shots if REFERENCE in s.walk]
        # Eine Runde ist zwei Seiten. Der Walk misst eine.
        trip = 2.0 * float(np.median(thousand)) if thousand else float("nan")
        round_trips[symbol] = trip
        print(
            f"  {symbol:5s} {100 * spread:>13.4f}% {depth:>12,.0f}$"
            + "".join(cells)
            + f"{100 * trip:>10.4f}%"
        )

    compare(round_trips, samples=args.samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
