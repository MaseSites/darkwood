"""E9 -- Ist unsere Fuell-Annahme realistisch? Gegen das echte Buch gemessen.

    python scripts/study_fill_realism.py --markets BTC,ETH,SOL

**Die Frage.** `sim/broker.py` fuellt eine Einstiegs-Limit-Order, wenn der
Preis durch ihr Level handelt:

    reached = high >= limit if self.config.fill_on_touch else high > limit

`fill_on_touch` steht auf `false`, also ist die Regel strenger als blosse
Beruehrung -- der Preis muss DURCH das Level. Was sie nicht kennt, ist die
**Warteschlange**. Wer bei einem Preis steht, wird nicht gefuellt, nur weil
dort gehandelt wurde; es kommt darauf an, wie viel Volumen vor einem liegt
und ob der Steller vorher storniert.

**Warum nicht gegen Liquids Paper-Modus.** Das waere die naheliegende
Referenz und sie taugt nicht:

  1. Liquids Fuellmodell ist **nicht dokumentiert**. Ein Unterschied gegen
     eine Blackbox sagt, dass zwei Modelle sich unterscheiden -- nicht,
     welches recht hat.
  2. Liquid laeuft gegen Live-Daten. Unsere Journal-Trades sind historisch,
     und ein Replay gibt es dort nicht.
  3. Liquids Perp-Gebuehren (Taker 0.095 %, Maker 0.065 %) sind das 1.7- bzw.
     3.25-fache der im Simulator angesetzten. Jede PnL-Differenz waere von
     der Gebuehr dominiert und nicht von der Fuellung.

**Wogegen stattdessen.** Gegen das aufgenommene Tape der neuen Venue, wo eine
Fuellung **belegt** ist statt modelliert: das Buch traegt `order_id`, die
Trades tragen `ask_id` und `bid_id`. Eine Kennung, die in einem Trade
auftaucht, ist gehandelt worden. Das ist kein zweiter Simulator, das ist die
Boerse.

**Die Messung.** Fuer jede beobachtete ruhende Order:

    unsere Regel sagt "gefuellt"  <=>  waehrend ihrer Lebenszeit hat ein Trade
                                       STRENG jenseits ihres Preises gedruckt
                                       (Ask: trade > preis, Bid: trade < preis)

    die Wirklichkeit sagt         <=>  ihre Kennung steht in einem Trade

Daraus die **Falschfuell-Rate**: Anteil der Orders, fuer die unsere Regel
"gefuellt" sagt, waehrend die Order belegt storniert wurde.

**Vorab festgelegt** (audit/EXPERIMENTS_NEXT.yaml, Arm E9): die beobachtete
Population sind die Orders anderer Leute, alle 30 s abgetastet, also sind
langlebige ueberrepraesentiert. Das verzerrt zu mehr beobachteten Stornos und
damit zu einer HOEHEREN Falschfuell-Rate. Die Zahl ist eine **Obergrenze**,
und das steht vor dem Lauf fest.
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

#: Bonferroni auf die 49 angemeldeten Vergleiche.
COMPARISONS = 49
LEVEL = 1.0 - 0.05 / COMPARISONS

#: Unter so vielen beobachteten Orders keine Rate.
MIN_ORDERS = 200

#: Abstandsklassen vom Mid, in Basispunkten. Unsere Einstiege liegen nicht am
#: Antritt, sondern an einem Strukturlevel -- darum die Aufschluesselung statt
#: einer einzigen Zahl, die alles mittelt.
BUCKETS = ((0.0, 1.0), (1.0, 5.0), (5.0, 20.0), (20.0, 100.0), (100.0, 1e9))


@dataclass
class Order:
    order_id: int
    side: str
    price: float
    from_mid_bp: float
    first_ms: int
    last_ms: int
    proven_filled: bool
    rule_says_filled: bool


def load(symbol: str) -> tuple[list[dict], list[dict]]:
    """Buchaufnahmen und Trades eines Marktes, zeitlich sortiert."""
    books: list[dict] = []
    trades: list[dict] = []
    folder = TAPE / symbol
    for path in sorted(folder.glob("book-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                books.append(json.loads(line))
    for path in sorted(folder.glob("trades-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            trades.extend(json.loads(line)["trades"])
    books.sort(key=lambda b: int(b["received_ms"]))
    trades.sort(key=lambda t: int(t["timestamp"]))
    return books, trades


def mid_of(snapshot: dict) -> float | None:
    asks = snapshot.get("asks") or []
    bids = snapshot.get("bids") or []
    if not asks or not bids:
        return None
    best_ask = min(float(o["price"]) for o in asks)
    best_bid = max(float(o["price"]) for o in bids)
    return 0.5 * (best_ask + best_bid)


def collect(books: list[dict], trades: list[dict]) -> list[Order]:
    """Jede beobachtete Order mit beidem: belegtem Ausgang und Regel-Urteil."""
    traded_ids: set[int] = set()
    for t in trades:
        traded_ids.add(int(t["ask_id"]))
        traded_ids.add(int(t["bid_id"]))

    seen: dict[int, dict] = {}
    for snapshot in books:
        mid = mid_of(snapshot)
        received = int(snapshot["received_ms"])
        for side in ("asks", "bids"):
            for raw in snapshot.get(side) or []:
                oid = int(raw["order_id"])
                price = float(raw["price"])
                if oid not in seen:
                    seen[oid] = {
                        "side": "ask" if side == "asks" else "bid",
                        "price": price,
                        "mid": mid,
                        "first": received,
                        "last": received,
                    }
                else:
                    seen[oid]["last"] = received

    stamps = np.array([int(t["timestamp"]) for t in trades], dtype="int64")
    prices = np.array([float(t["price"]) for t in trades], dtype=float)

    out: list[Order] = []
    for oid, info in seen.items():
        mid = info["mid"]
        if not mid:
            continue
        # Nur die Trades waehrend der beobachteten Lebenszeit der Order. Eine
        # Regel, die auf das ganze Fenster schaut, wuerde jeder Order jede
        # spaetere Bewegung anrechnen.
        lo = int(np.searchsorted(stamps, info["first"], side="left"))
        hi = int(np.searchsorted(stamps, info["last"], side="right"))
        window = prices[lo:hi]
        if window.size == 0:
            through = False
        elif info["side"] == "ask":
            # Eine ruhende Verkaufsorder: "durchgehandelt" heisst, ein Trade
            # druckte OBERHALB ihres Preises.
            through = bool(np.any(window > info["price"]))
        else:
            through = bool(np.any(window < info["price"]))
        out.append(
            Order(
                order_id=oid,
                side=info["side"],
                price=info["price"],
                from_mid_bp=abs(10_000.0 * (info["price"] - mid) / mid),
                first_ms=info["first"],
                last_ms=info["last"],
                proven_filled=oid in traded_ids,
                rule_says_filled=through,
            )
        )
    return out


def rate_with_interval(flags: list[bool], *, level: float) -> tuple[float, float, float]:
    """Anteil mit Block-Bootstrap-Intervall."""
    values = [1.0 if f else 0.0 for f in flags]
    interval = block_bootstrap(values, level=level)
    mean = float(np.mean(values)) if values else float("nan")
    if interval is None:
        return mean, float("nan"), float("nan")
    return mean, interval.low, interval.high


def report_market(symbol: str, *, level: float) -> list[Order] | None:
    books, trades = load(symbol)
    if len(books) < 2 or not trades:  # noqa: PLR2004
        print(f"  {symbol:5s} zu wenig Aufnahme")
        return None
    orders = collect(books, trades)
    if len(orders) < MIN_ORDERS:
        print(f"  {symbol:5s} nur {len(orders):,} Orders -- unter {MIN_ORDERS}")
        return None

    filled = [o for o in orders if o.proven_filled]
    not_filled = [o for o in orders if not o.proven_filled]
    false_flags = [o.rule_says_filled for o in not_filled]
    missed_flags = [not o.rule_says_filled for o in filled]

    false_rate, f_low, f_high = rate_with_interval(false_flags, level=level)
    missed_rate, m_low, m_high = rate_with_interval(missed_flags, level=level)

    print(f"\n{symbol}  {len(orders):,} beobachtete Orders, {len(books):,} Buchaufnahmen")
    print(f"  belegt gefuellt {len(filled):,} ({100 * len(filled) / len(orders):.1f} %), "
          f"nicht gefuellt {len(not_filled):,}")
    print(f"  FALSCHFUELLUNG  {100 * false_rate:>6.1f} %  "
          f"[{100 * f_low:>5.1f}, {100 * f_high:>5.1f}]   "
          f"(unsere Regel sagt ja, die Order wurde nie gehandelt)")
    print(f"  verpasst        {100 * missed_rate:>6.1f} %  "
          f"[{100 * m_low:>5.1f}, {100 * m_high:>5.1f}]   "
          f"(unsere Regel sagt nein, die Order wurde belegt gefuellt)")
    return orders


def by_distance(orders: list[Order]) -> None:
    print(f"\n  {'Abstand vom Mid':>18s} {'n':>8s} {'belegt gefuellt':>16s} "
          f"{'Regel sagt ja':>14s} {'Falschfuellung':>15s}")
    print("  " + "-" * 78)
    for low, high in BUCKETS:
        group = [o for o in orders if low <= o.from_mid_bp < high]
        if not group:
            continue
        not_filled = [o for o in group if not o.proven_filled]
        false_share = (
            100 * sum(o.rule_says_filled for o in not_filled) / len(not_filled)
            if not_filled
            else float("nan")
        )
        label = f"{low:.0f}-{high:.0f} bp" if high < 1e8 else f">{low:.0f} bp"  # noqa: PLR2004
        print(
            f"  {label:>18s} {len(group):>8,} "
            f"{100 * sum(o.proven_filled for o in group) / len(group):>15.1f}% "
            f"{100 * sum(o.rule_says_filled for o in group) / len(group):>13.1f}% "
            f"{false_share:>14.1f}%"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", default="BTC,ETH,SOL")
    parser.add_argument("--level", type=float, default=LEVEL)
    args = parser.parse_args()

    if not TAPE.is_dir():
        raise SystemExit(f"Keine Aufnahme unter {TAPE}.")

    print("=" * 84)
    print("E9 -- Ist unsere Fuell-Annahme realistisch?")
    print("=" * 84)
    print(
        f"\n  Unsere Regel (sim/broker.py, fill_on_touch=false): gefuellt, wenn der\n"
        f"  Preis STRENG durch das Level handelt.\n"
        f"\n  Die Wirklichkeit: eine Kennung, die in einem Trade steht, ist gehandelt\n"
        f"  worden. Kein Modell, ein Id-Join.\n"
        f"\n  Niveau {100 * args.level:.4f}% (Bonferroni auf {COMPARISONS}).\n"
    )

    pooled: list[Order] = []
    for symbol in [s.strip().upper() for s in args.markets.split(",") if s.strip()]:
        got = report_market(symbol, level=args.level)
        if got:
            pooled.extend(got)

    if not pooled:
        print("\n  Keine auswertbare Aufnahme.")
        return 0

    print("\n" + "=" * 84)
    print(f"  GEPOOLT ueber alle Maerkte: {len(pooled):,} Orders")
    print("=" * 84)
    not_filled = [o for o in pooled if not o.proven_filled]
    rate, low, high = rate_with_interval([o.rule_says_filled for o in not_filled], level=args.level)
    print(
        f"\n  Falschfuell-Rate: {100 * rate:.1f} %  [{100 * low:.1f}, {100 * high:.1f}]\n"
        f"  Von {len(not_filled):,} Orders, die nie gehandelt wurden, haette unsere\n"
        f"  Regel {sum(o.rule_says_filled for o in not_filled):,} als gefuellt verbucht."
    )
    by_distance(pooled)
    print(
        "\n  OBERGRENZE, vorab festgelegt: das Buch wird alle 30 s abgetastet, also\n"
        "  sind langlebige Orders ueberrepraesentiert -- und langlebige Orders sind\n"
        "  eher die geduldigen, die storniert werden. Das verzerrt nach oben.\n"
        "\n  UND: es sind die Orders anderer Leute. Dass unsere sich genauso\n"
        "  verhalten wuerden, folgt daraus nicht."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
