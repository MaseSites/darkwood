"""Does it matter which side took liquidity -- continuation or exhaustion?

    python scripts/study_flow.py --symbols BTCUSDT,ETHUSDT --timeframe H1

Run `scripts/backfill_flow.py` first; this reads the store it fills.

The test plan's second priority, and the two readings it asks to be separated
rather than assumed:

* **continuation** -- heavy aggressive buying together with a clear price rise
  might signal more strength;
* **exhaustion** -- heavy aggressive buying with a weak price response might
  signal the opposite.

Both are interpretations, not rules, and they make opposite predictions about
the same observation. That is exactly why the plan asks for a grid: price move
against flow imbalance, with the cell boundaries fixed on earlier data, and the
number of opportunities reported next to the average so nobody reads a verdict
off eleven candles.

**The accounting identity that must not be mistaken for an edge.** Imbalance
correlates +0.50 with the return of its *own* candle, measured on BTC H1 --
necessarily, since takers buying is what moves the price while they do it. That
says nothing about the next candle, and a study that reported it would be
reporting arithmetic. Everything here is measured on what happens *after* the
candle closes, entered at the next open.

**What this cannot do.** Flow is per candle, so it says who crossed the spread
during an hour, not where resting liquidity sat. Real order-book imbalance would
be a different measurement needing data nobody kept -- the plan says so, and
today's snapshots cannot stand in for history.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from traidingbrain.config.settings import load_config
from traidingbrain.data.flow import FlowStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC
from traidingbrain.reporting.intervals import block_bootstrap

#: Candles ahead to measure. One is the plan's question; the rest are here
#: because the ratio of movement to toll decides everything and it grows with
#: the horizon.
HORIZONS: tuple[int, ...] = (1, 4, 8)

#: Cell edges as quantiles, so "strong" means strong for this market and era.
#:
#: Fixed on the first 60% of the data and applied to the rest, which is the
#: plan's requirement: boundaries chosen on the data they are then tested on is
#: how a grid finds a cell that was always going to look good.
TERCILES = (0.0, 0.33, 0.67, 1.0)
FIT_SHARE = 0.6

#: Fewest observations in a cell before it is reported with a number.
MIN_CELL = 100

#: Index of the top band. The last cell has no upper edge to compare
#: against, so it takes everything from its lower edge upward.
TOP = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--timeframe", default="H1")
    return parser.parse_args()


def round_trip(slippage_bps: float) -> float:
    fees = float(DEFAULT_SPEC["taker_fee"]) + float(DEFAULT_SPEC["maker_fee"])
    return fees + 2.0 * slippage_bps / 10_000.0


def joined(symbol: str, timeframe: Timeframe, ahead: int) -> pd.DataFrame | None:
    """Candles and their taker split, with the forward move after each.

    Joined on `ts` -- the candle open time both stores key on -- and the forward
    move is open-to-open starting one candle later, so the entry is a price a
    decision taken at the close could reach.
    """
    config = load_config()
    candles = ParquetStore(config.engine.paths.parquet_dir).read(symbol, timeframe)
    flow = FlowStore(config.engine.paths.data_dir / "flow").frame(symbol, timeframe)
    if candles.empty or flow.empty:
        return None

    frame = candles.copy()
    frame["ts"] = frame["ts"].astype("int64")
    merged = frame.merge(flow, on="ts", how="inner").sort_values("ts").reset_index(drop=True)
    if len(merged) < ahead + 4:
        return None

    opens = merged["open"].to_numpy(dtype="float64")
    closes = merged["close"].to_numpy(dtype="float64")
    n = len(merged)
    # Explicit indices, because slice arithmetic hid an off-by-one in the
    # reversal study that made the signal and the outcome the same candle.
    at = np.arange(1, n - 1 - ahead)
    out = merged.iloc[at].copy()
    out["own_return"] = closes[at] / closes[at - 1] - 1.0
    out["forward"] = opens[at + 1 + ahead] / opens[at + 1] - 1.0
    return out.reset_index(drop=True)


def cell_line(name: str, values: np.ndarray, cost: float) -> str:
    if values.size < MIN_CELL:
        return f"      {name:30s} n={values.size:5d}  zu wenige"
    net = values - cost
    interval = block_bootstrap(net * 100.0)
    bounds = interval.labelled() if interval is not None else "zu wenige"
    return (
        f"      {name:30s} n={values.size:5d}  brutto {100 * values.mean():+.4f}%  "
        f"netto {100 * net.mean():+.4f}%  {bounds}"
    )


def main() -> int:
    args = parse_args()
    config = load_config()
    timeframe = Timeframe(args.timeframe)
    cost = round_trip(config.engine.simulation.slippage_bps)
    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    print(f"Runde Fahrt {100 * cost:.4f}% des Preises. Einstieg zur naechsten Eroeffnung.")
    print(
        "Zellgrenzen auf den ersten 60% der Daten festgelegt und auf den Rest\n"
        "angewandt -- Grenzen auf denselben Daten zu waehlen, auf denen man dann\n"
        "prueft, findet immer eine Zelle, die gut aussieht.\n"
    )

    for ahead in HORIZONS:
        pooled: list[pd.DataFrame] = []
        for symbol in symbols:
            frame = joined(symbol, timeframe, ahead)
            if frame is None:
                print(f"  {symbol}: keine verbundenen Daten -- backfill_flow.py zuerst")
                continue
            pooled.append(frame)
        if not pooled:
            continue
        data = pd.concat(pooled, ignore_index=True)

        cut = int(FIT_SHARE * len(data))
        fit, test = data.iloc[:cut], data.iloc[cut:]
        if len(test) < MIN_CELL:
            print(f"  {timeframe.value}, {ahead} voraus: zu wenig Pruefdaten")
            continue
        move_edges = np.quantile(fit["own_return"].to_numpy(), TERCILES)
        flow_edges = np.quantile(fit["imbalance"].to_numpy(), TERCILES)

        print(f"  {timeframe.value}, {ahead} Kerzen voraus  ({len(test)} Pruefbeobachtungen)")
        forward = test["forward"].to_numpy(dtype="float64")
        print(cell_line("alle (nur long gehalten)", forward, cost))

        move = test["own_return"].to_numpy(dtype="float64")
        flow = test["imbalance"].to_numpy(dtype="float64")
        labels = ("schwach", "mittel", "stark")
        for i in range(TOP + 1):
            for j in range(TOP + 1):
                mask = (
                    (move >= move_edges[i])
                    & ((move < move_edges[i + 1]) | (i == TOP))
                    & (flow >= flow_edges[j])
                    & ((flow < flow_edges[j + 1]) | (j == TOP))
                )
                name = f"Bewegung {labels[i]}, Fluss {labels[j]}"
                print(cell_line(name, forward[mask], cost))
        print()

    print(
        "Imbalance korreliert +0.50 mit der Rendite ihrer EIGENEN Kerze, notwendig\n"
        "und ohne Aussagekraft: Takerkaeufe sind, was den Kurs waehrenddessen\n"
        "bewegt. Alles hier ist gemessen, was NACH dem Schluss passiert.\n\n"
        "Und was Kerzen-Fluss nicht ist: er sagt, wer in einer Stunde den Spread\n"
        "genommen hat, nicht wo ruhende Liquiditaet lag. Echte Orderbuch-\n"
        "Ungleichgewichte brauchen Daten, die niemand aufbewahrt hat."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
