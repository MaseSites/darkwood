"""Fetch the taker buy/sell split per candle, which ccxt throws away.

    python scripts/backfill_flow.py --symbols BTCUSDT,ETHUSDT --timeframe H1
    python scripts/backfill_flow.py --symbols BTCUSDT --timeframe H1 --days 400

The test plan ranks order flow as its second priority and the data was simply
missing: our candles are (ts, open, high, low, close, volume) because
`DataSource.fetch_ohlcv` goes through ccxt, and ccxt normalises Binance's
twelve-field kline to six. Field ten -- taker buy base volume -- is discarded
before our code ever sees it.

So this calls the kline endpoint directly and keeps the two numbers that matter.
Verified against one live candle before any of it was built: BTCUSDT 1h showed
volume 3322.009 with taker_buy_base 1626.267, so the split is real and the field
is where the documentation says.

**Written to its own store.** `data/flow/`, one file per symbol and timeframe,
joined to candles by `ts`. Nothing that reads OHLCV today changes, and no
multi-year Parquet file needs refetching -- the same arrangement funding already
uses, for the same reason.

**The forming candle is dropped, and that is the whole correctness argument.**
A candle still being built has a volume and a taker split that are both
partial, and they grow for the rest of the hour. Storing one would put a
half-finished observation into the feature set, where it would read as a real
imbalance and be impossible to spot later. The last row of every fetch is
therefore removed, which is the same rule `ExchangeSource.fetch_ohlcv` applies
to candles.

**Only what is needed.** Default is one timeframe and the markets named, not
twelve markets and six timeframes: the plan says to test 1h first, and
refetching everything to answer a question nobody has asked yet is hours of
requests for nothing. Resumable -- it starts after the newest stored candle.
"""

from __future__ import annotations

import argparse
import sys
import time
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ccxt

from traidingbrain.config.settings import load_config
from traidingbrain.data.flow import Flow, FlowStore
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.domain.enums import Timeframe

#: Candles per request. Binance futures klines allows 1500.
PAGE = 1500

#: Index of each field in Binance's kline row, from the public documentation.
#:
#: Named rather than inlined because the row has twelve positional fields and a
#: wrong index here is a silent data error: `quote_volume` at index 7 is a
#: plausible-looking number that is not volume, and `taker_buy_quote` at 10 is
#: a plausible-looking number that is not base volume.
TS, VOLUME, TRADES, TAKER_BUY_BASE = 0, 5, 8, 9

#: Cells in the grid, named so the loop bound is not a bare number.
LAST_BAND = 2

#: ccxt's interval strings, which differ from our timeframe names.
INTERVALS = {
    Timeframe.M1: "1m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1w",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument(
        "--refill",
        action="store_true",
        help=(
            "Start at the beginning of history even when newer candles are "
            "already stored. Needed because resuming only moves forward: a "
            "short recent fetch leaves the older history unreachable, which is "
            "exactly what happened to BTC after a 60-day transport check. "
            "Merging is by timestamp, so refilling cannot duplicate anything."
        ),
    )
    parser.add_argument(
        "--days",
        type=float,
        help="How far back to start when nothing is stored yet. Default: all of it.",
    )
    return parser.parse_args()


def fetch_page(exchange: object, symbol: str, interval: str, since_ms: int) -> list[list[object]]:
    rows: list[list[object]] = exchange.fapiPublicGetKlines(  # type: ignore[attr-defined]
        {"symbol": symbol, "interval": interval, "startTime": since_ms, "limit": PAGE}
    )
    return rows


def report_gaps(
    store: FlowStore, symbol: str, timeframe: Timeframe, step: int, added: int
) -> None:
    """Say what is on disk and where it is missing.

    A gap report rather than a count, because resuming only ever moves
    forward: a short recent fetch leaves the older history unreachable and
    the next run reports "0 neu" as though the data were complete. That
    happened here -- a 60-day transport check on BTC made its full history
    unfetchable, and only a count was printed. `--refill` is the cure and
    this is how anyone finds out it is needed.
    """
    rows = store.read(symbol, timeframe)
    if not rows:
        print(f"{symbol} {timeframe.value}: nichts auf Platte", flush=True)
        return
    stamps = [row.ts for row in rows]
    holes = [(a, b) for a, b in pairwise(stamps) if b - a > step]
    missing = sum((b - a) // step - 1 for a, b in holes)
    span = (stamps[-1] - stamps[0]) / 86_400_000
    note = f", {len(holes)} Luecken ueber {missing} Kerzen" if holes else ", keine Luecken"
    print(
        f"{symbol} {timeframe.value}: {added} neu, {len(rows)} auf Platte, "
        f"{span:.0f} Tage{note}",
        flush=True,
    )
    if holes:
        print(
            "  -> mit --refill schliessen; Fortsetzen allein geht nur vorwaerts.",
            flush=True,
        )


def main() -> int:
    args = parse_args()
    config = load_config()
    timeframe = Timeframe(args.timeframe)
    interval = INTERVALS.get(timeframe)
    if interval is None:
        print(f"Keine Intervall-Zuordnung fuer {timeframe.value}")
        return 1

    store = FlowStore(config.engine.paths.data_dir / "flow")
    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    step = timeframe_ms(timeframe)
    now_ms = int(time.time() * 1000)
    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    for symbol in symbols:
        last = store.last_ts(symbol, timeframe)
        if args.refill:
            cursor = 0
            print(f"{symbol} {timeframe.value}: Neubefuellung ab Anfang", flush=True)
        elif last is not None:
            cursor = last + step
            print(f"{symbol} {timeframe.value}: fortsetzen ab {cursor}", flush=True)
        elif args.days:
            cursor = now_ms - int(args.days * 86_400_000)
            print(f"{symbol} {timeframe.value}: Start {args.days:.0f} Tage zurueck", flush=True)
        else:
            cursor = 0
            print(f"{symbol} {timeframe.value}: Start am Anfang der Historie", flush=True)

        added = 0
        pages = 0
        while cursor < now_ms:
            rows = fetch_page(exchange, symbol, interval, cursor)
            if not rows:
                break
            pages += 1

            # The newest row of any fetch may be the candle currently forming.
            # Its volume and taker split are both partial and will keep growing,
            # so it is dropped rather than stored -- the same rule the candle
            # fetch applies, and for the same reason.
            closed = [row for row in rows if int(row[TS]) + step <= now_ms]
            if not closed:
                break

            batch = [
                Flow(
                    ts=int(row[TS]),
                    volume=float(row[VOLUME]),
                    taker_buy=float(row[TAKER_BUY_BASE]),
                    trades=int(row[TRADES]),
                )
                for row in closed
            ]
            store.write(symbol, timeframe, batch)
            added += len(batch)
            newest = int(closed[-1][TS])
            if newest + step <= cursor:
                # No forward progress: stop rather than loop on the same page.
                break
            cursor = newest + step
            if pages % 10 == 0:
                print(f"  {added} Kerzen, bis {newest}", flush=True)

        report_gaps(store, symbol, timeframe, step, added)

    print(
        "\nIn data/flow/, nach Symbol und Zeitebene. Die OHLCV-Dateien sind\n"
        "unberuehrt; verbunden wird ueber `ts`, genau wie bei den Funding-Raten."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
