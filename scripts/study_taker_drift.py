"""Was ein Taker über die Gebühr hinaus zahlt -- und was das mit dem 22x macht.

    python scripts/study_taker_drift.py --markets BTC,ETH

**Warum diese Zahl gebraucht wird.** Die neue Venue wurde interessant, weil
ihre Taker-Runde auf BTC **0,0005 %** kostet -- 0,05 bp gegen eine
Obergrenze des gemessenen Einstiegsvorsprungs von 0,0106 % = 1,06 bp. Faktor
**22**, und das war die einzige Grösse, die sich in diesem Projekt je
zugunsten des Systems bewegt hat.

Diese 0,05 bp sind die **Gebühr plus der gelaufene Spread**. Sie enthalten
nicht, was *nach* dem Trade passiert.

`study_tape_fills.py` hat gemessen, dass der Markout auf belegten
Maker-Fills bei allen vier Horizonten **zugunsten des Makers** liegt
(-0,195 bp bei 1 s, repliziert über zwei Fenster mit 1,18x). Die Kehrseite
davon ist eine Kostenposition des Takers -- und dieses System handelt als
Taker.

**Nicht aus Symmetrie gefolgert, sondern gemessen.** Man könnte sagen "der
Maker gewinnt 0,195 bp, also verliert der Taker 0,195 bp" und hätte eine
Zahl aus einer Annahme. `is_maker_ask` sagt je Trade, auf welcher Seite der
Aggressor stand, also lässt sich die Drift **gegen den Taker** direkt
rechnen. Die beiden müssen sich nicht genau entsprechen: Fills, die ich im
Buch beobachtet habe, sind eine andere Stichprobe als alle Trades.

**Vorzeichen:** positiv heisst **gegen den Taker**. Ein Taker, der kauft
(`is_maker_ask == true`, also lief der Trade am Ask), verliert, wenn der
Preis danach fällt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.reporting.intervals import block_bootstrap

TAPE = ROOT / "data" / "quarantine" / "venue_tape"

#: Dieselben vier Horizonte wie in E0 Punkt 7.
HORIZONS = ((1_000, "1s"), (5_000, "5s"), (30_000, "30s"), (300_000, "5min"))

#: Die gemessene Taker-Runde auf BTC, in bp. Aus audit/VENUE_KOSTEN_REPORT.md.
ROUND_TRIP_BP = 0.05

#: Der Horizont, auf dem der Faktor neu gerechnet wird.
ONE_SECOND_MS = 1_000

#: Obergrenze des gemessenen Einstiegsvorsprungs, in bp (0,0106 %).
EDGE_BOUND_BP = 1.06

#: Unter so vielen Ereignissen keine Schätzung.
MIN_EVENTS = 500


def load(symbol: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Zeit, Preis und Aggressor-Richtung je Trade.

    `is_maker_ask == True` heisst: der Maker stand auf der Ask-Seite, also
    hat der Taker GEKAUFT. `+1` für einen Taker-Kauf, `-1` für einen
    Taker-Verkauf.
    """
    stamps: list[int] = []
    prices: list[float] = []
    sides: list[int] = []
    folder = TAPE / symbol
    for path in sorted(folder.glob("trades-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for row in json.loads(line)["trades"]:
                stamps.append(int(row["timestamp"]))
                prices.append(float(row["price"]))
                sides.append(1 if row["is_maker_ask"] else -1)
    order = np.argsort(np.array(stamps, dtype="int64"), kind="stable")
    return (
        np.array(stamps, dtype="int64")[order],
        np.array(prices, dtype=float)[order],
        np.array(sides, dtype=int)[order],
    )


def mid_from_tape(prices: np.ndarray, sides: np.ndarray) -> np.ndarray:
    """Laufendes Mid aus dem Tape, ohne Buch.

    Ein Trade am Ask setzt die Ask-Seite, einer am Bid die Bid-Seite; das
    Mid ist der Mittelwert der jeweils letzten bekannten. Ohne diesen
    Schritt messen die Zahlen unten den Bid-Ask-Bounce, und auf den dünnen
    Maerkten (DOGE, LINK: Spread 0,038 %) wuerde der jedes Ergebnis
    dominieren.
    """
    ask = np.where(sides > 0, prices, np.nan)
    bid = np.where(sides < 0, prices, np.nan)
    for series in (ask, bid):
        seen = np.nan
        for i in range(series.size):
            if np.isnan(series[i]):
                series[i] = seen
            else:
                seen = series[i]
    both = ~np.isnan(ask) & ~np.isnan(bid)
    return np.where(both, 0.5 * (ask + bid), prices)


def drift(
    stamps: np.ndarray, prices: np.ndarray, sides: np.ndarray, mid: np.ndarray, *, lag_ms: int
) -> tuple[int, float, float, float]:
    """Mid-Bewegung nach jedem Taker-Trade, Vorzeichen gegen den Taker."""
    moves: list[float] = []
    for i in range(stamps.size):
        j = int(np.searchsorted(stamps, stamps[i] + lag_ms, side="right")) - 1
        if j <= i:
            continue
        # Taker-Kauf (side +1): er verliert, wenn das Mid FAELLT.
        signed = -sides[i] * (mid[j] - prices[i])
        moves.append(10_000.0 * signed / prices[i])
    if len(moves) < 2:  # noqa: PLR2004
        return len(moves), float("nan"), float("nan"), float("nan")
    interval = block_bootstrap(moves, level=0.95)
    low = interval.low if interval is not None else float("nan")
    high = interval.high if interval is not None else float("nan")
    return len(moves), float(np.mean(moves)), low, high


def one_market(symbol: str) -> float | None:
    stamps, prices, sides = load(symbol)
    if stamps.size < MIN_EVENTS:
        print(f"  {symbol:5s} nur {stamps.size:,} Trades -- unter {MIN_EVENTS}")
        return None
    mid = mid_from_tape(prices, sides)
    buys = int(np.sum(sides > 0))

    print(f"\n{symbol}  {stamps.size:,} Trades, davon {buys:,} Taker-Kaeufe "
          f"({100 * buys / stamps.size:.1f} %)")
    print("  Drift nach dem Trade, positiv = GEGEN den Taker:")
    at_one_second = None
    for lag_ms, label in HORIZONS:
        n, mean, low, high = drift(stamps, prices, sides, mid, lag_ms=lag_ms)
        if n < MIN_EVENTS:
            print(f"    {label:>5s}  nur {n:,} Ereignisse")
            continue
        print(f"    {label:>5s}  {mean:>+7.3f} bp  [{low:>+7.3f}, {high:>+7.3f}]  n={n:,}")
        if lag_ms == ONE_SECOND_MS:
            at_one_second = mean
    return at_one_second


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markets", default="BTC,ETH,SOL")
    args = parser.parse_args()

    if not TAPE.is_dir():
        raise SystemExit(f"Keine Aufnahme unter {TAPE}.")

    print("=" * 82)
    print("Was ein Taker ueber die Gebuehr hinaus zahlt")
    print("=" * 82)
    print(
        f"\n  Gemessene Taker-Runde auf BTC: {ROUND_TRIP_BP:.2f} bp\n"
        f"  Obergrenze des Einstiegsvorsprungs: {EDGE_BOUND_BP:.2f} bp\n"
        f"  Daraus der Faktor, mit dem diese Venue interessant wurde: "
        f"{EDGE_BOUND_BP / ROUND_TRIP_BP:.0f}x\n"
        f"\n  Diese {ROUND_TRIP_BP:.2f} bp sind Gebuehr plus gelaufener Spread. Was NACH\n"
        f"  dem Trade passiert, stehen sie nicht.\n"
    )

    found: dict[str, float] = {}
    for symbol in [s.strip().upper() for s in args.markets.split(",") if s.strip()]:
        value = one_market(symbol)
        if value is not None:
            found[symbol] = value

    if "BTC" not in found:
        print("\n  Ohne BTC keine Neurechnung des Faktors.")
        return 0

    one_way = found["BTC"]
    print("\n" + "=" * 82)
    print("  Was das mit dem Faktor macht")
    print("=" * 82)
    if one_way <= 0:
        print(
            f"\n  Die Drift auf BTC liegt bei {one_way:+.3f} bp, also NICHT gegen den\n"
            f"  Taker. Dann gibt es hier nichts abzuziehen, und der Faktor bleibt.\n"
            f"  Das waere allerdings schwer mit dem Maker-Befund zu vereinbaren und\n"
            f"  gehoert nachgesehen, nicht gefeiert."
        )
        return 0

    full = ROUND_TRIP_BP + 2 * one_way
    print(
        f"\n  Drift gegen den Taker, eine Seite, 1s:        {one_way:+.3f} bp\n"
        f"  Eine Runde sind zwei Seiten:                  {2 * one_way:+.3f} bp\n"
        f"  Dazu die gemessene Maut:                      {ROUND_TRIP_BP:+.3f} bp\n"
        f"  ------------------------------------------------------\n"
        f"  Volle Runde inklusive Drift:                  {full:+.3f} bp\n"
        f"\n  Der Faktor war {EDGE_BOUND_BP / ROUND_TRIP_BP:.0f}x. Mit der Drift ist er "
        f"**{EDGE_BOUND_BP / full:.1f}x**."
    )
    print(
        f"\n  ABER: diese Rechnung unterstellt, dass die Drift BLEIBT. Die Tabelle\n"
        f"  oben sagt etwas anderes -- sie revertiert. Bei 1s laeuft sie gegen den\n"
        f"  Taker, bei 30s spannt ihr Intervall ueber die Null, bei 5min liegt sie\n"
        f"  darunter. Eine transiente Drift ist fuer einen Scalper eine Kosten-\n"
        f"  position und fuer einen Halter von 14 Stunden womoeglich keine: wenn\n"
        f"  sie zurueckkommt, gibt sie sich selbst wieder her.\n"
        f"\n  Darum stehen hier ZWEI Lesarten, und ich habe keine:\n"
        f"    permanent gedacht (1s):    Faktor {EDGE_BOUND_BP / full:.1f}x\n"
        f"    revertierend (30s, Null):  Faktor bleibt "
        f"{EDGE_BOUND_BP / ROUND_TRIP_BP:.0f}x\n"
        f"\n  Welche gilt, haengt an der Haltedauer und daran, ob die Reversion den\n"
        f"  EIGENEN Trade betrifft oder nur den Durchschnitt aller. Das entscheidet\n"
        f"  diese Aufnahme nicht, und eine der beiden Zahlen als die Zahl zu\n"
        f"  berichten waere eine Wahl, die ich nicht belegen kann."
    )
    print(
        "\n  Und die 1.06 bp, gegen die alles gerechnet wird, sind selbst die\n"
        "  OBERGRENZE einer Zelle von vier -- der einzigen, die ein Intervall ohne\n"
        "  Null hatte. Wer den Faktor zitiert, stellt eine Obergrenze gegen eine\n"
        "  Untergrenze."
    )
    print(
        "\n  Was hier NICHT behauptet wird: dass diese Drift genau der Gewinn des\n"
        "  Makers ist. Das waere Symmetrie statt Messung. Die beobachteten\n"
        "  Maker-Fills sind eine andere Stichprobe als alle Trades -- darum steht\n"
        "  hier die direkt gerechnete Zahl und nicht die umgedrehte."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
