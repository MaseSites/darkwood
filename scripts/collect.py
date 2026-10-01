"""The collector: what a machine that never sleeps writes down.

Runs on the Raspberry Pi, on a systemd timer, and writes into Postgres. The
laptop is off at three in the morning; this is not.

Three things shape it, and all three come from the hardware:

**It is a one-shot, not a daemon.** It starts, fetches, writes and exits. On 426
MB of RAM a Python process holding ccxt resident costs a quarter of the machine
for the 99% of the time it is idle. A timer costs nothing between runs.

**It re-fetches an overlapping window every time.** Not "since my last marker" --
a marker is a claim about a previous run that a crash makes false. It asks
Postgres what the newest row actually is and steps back from there, and every
write upserts. Overlap costs a few redundant rows; a gap costs a hole that only
surfaces months later, in a backtest, as a market that was mysteriously quiet.

**It reuses `MarketData` rather than calling ccxt directly.** That is what keeps
the closed-candle rule and the venue spelling in one place. The alternative --
a collector that decides for itself when a candle is finished -- is two machines
independently answering a question they must answer identically.

Not here yet: open interest and the long/short ratio. Their fetcher in
`data/derivatives.py` returns DataFrames and imports pyarrow at module level, so
it cannot be imported on a machine without either. Splitting its fetching from
its storing is the same move `grid.py` made for `frames.py`, and it is the next
thing rather than a thing to fake tonight.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_config, load_secrets
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.grid import collected_timeframes, timeframe_ms
from traidingbrain.domain.enums import Timeframe
from traidingbrain.storage.postgres import connect

#: How far back to re-fetch beyond what the database already holds.
#:
#: Ten bars, not one. A restart mid-write, a venue that revises a candle, a run
#: killed by the memory limit -- each leaves the newest row correct and the one
#: before it questionable. Ten bars of overlap costs ten upserts and removes the
#: whole class of problem.
OVERLAP_BARS = 10

#: Where to start when a symbol and timeframe have no rows at all.
#:
#: Deliberately short. This is a *collector*, not a backfill: five years of
#: history live in Parquet on the laptop and are not this machine's job. Asking
#: a Pi 1 to page back through 2021 would take days to duplicate work already
#: done.
COLD_START_BARS = 500

#: A day of overlap for funding, which settles every eight hours -- three rows.
FUNDING_OVERLAP_MS = 24 * 3600 * 1000

#: Cold start for funding: a month back.
FUNDING_COLD_START_MS = 30 * 24 * 3600 * 1000


def _newest_ts(cur: Any, symbol: str, timeframe: str) -> int | None:
    cur.execute(
        "SELECT max(ts) FROM ohlcv WHERE symbol = %s AND timeframe = %s",
        (symbol, timeframe),
    )
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _newest_funding_ts(cur: Any, symbol: str) -> int | None:
    cur.execute("SELECT max(ts) FROM funding WHERE symbol = %s", (symbol,))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _note(cur: Any, series: str, rows: int, error: str = "") -> None:
    """Record that this series was attended to, and how it went.

    Written on failure as well as on success. A collector that records only its
    successes leaves a silence that looks exactly like a quiet market.

    `last_ok_ts` advances only when there was no error, so "when did this last
    actually work" survives a run that failed.
    """
    cur.execute(
        """
        INSERT INTO collector_status (series, last_ok_ts, last_rows, last_error, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (series) DO UPDATE SET
            last_ok_ts = CASE WHEN EXCLUDED.last_error = ''
                              THEN EXCLUDED.last_ok_ts
                              ELSE collector_status.last_ok_ts END,
            last_rows  = EXCLUDED.last_rows,
            last_error = EXCLUDED.last_error,
            updated_at = now()
        """,
        (series, int(time.time() * 1000), rows, error),
    )


def collect_ohlcv(market: MarketData, conn: Any, symbol: str, timeframe: Timeframe) -> int:
    """One symbol, one timeframe, from where the database left off."""
    series = f"ohlcv:{symbol}:{timeframe.value}"
    step = timeframe_ms(timeframe)

    with conn.cursor() as cur:
        newest = _newest_ts(cur, symbol, timeframe.value)
    since = (
        newest - OVERLAP_BARS * step
        if newest is not None
        else int(time.time() * 1000) - COLD_START_BARS * step
    )

    try:
        bars = market.fetch_ohlcv(symbol, timeframe, since_ms=since)
    except Exception as error:
        with conn.cursor() as cur:
            _note(cur, series, 0, str(error)[:500])
        conn.commit()
        raise

    if bars:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO ohlcv (symbol, timeframe, ts, open, high, low, close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
                    open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                    close = EXCLUDED.close, volume = EXCLUDED.volume
                """,
                [
                    (symbol, timeframe.value, b.ts, b.open, b.high, b.low, b.close, b.volume)
                    for b in bars
                ],
            )
    with conn.cursor() as cur:
        _note(cur, series, len(bars))
    conn.commit()
    return len(bars)


def collect_funding(market: MarketData, conn: Any, symbol: str) -> int:
    """Realised funding settlements, from where the database left off."""
    series = f"funding:{symbol}"

    with conn.cursor() as cur:
        newest = _newest_funding_ts(cur, symbol)
    now_ms = int(time.time() * 1000)
    since = newest - FUNDING_OVERLAP_MS if newest is not None else now_ms - FUNDING_COLD_START_MS

    try:
        rates = market.fetch_funding(symbol, since_ms=since)
    except Exception as error:
        with conn.cursor() as cur:
            _note(cur, series, 0, str(error)[:500])
        conn.commit()
        raise

    if rates:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO funding (symbol, ts, rate) VALUES (%s, %s, %s)
                ON CONFLICT (symbol, ts) DO UPDATE SET rate = EXCLUDED.rate
                """,
                [(symbol, r.ts, r.rate) for r in rates],
            )
    with conn.cursor() as cur:
        _note(cur, series, len(rates))
    conn.commit()
    return len(rates)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect market data into Postgres.")
    parser.add_argument(
        "--timeframes",
        default="",
        help="comma-separated, e.g. M1,M15. Default: every configured frame.",
    )
    parser.add_argument("--symbols", default="", help="comma-separated. Default: config.")
    parser.add_argument("--funding", action="store_true", help="also collect funding rates")
    args = parser.parse_args()

    config = load_config()
    url = load_secrets().postgres_url.get_secret_value()
    if not url:
        print("no TB_POSTGRES_URL -- nothing to collect into", file=sys.stderr)
        return 2

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] or list(
        config.engine.symbols.active
    )
    if args.timeframes:
        frames = [Timeframe(t.strip()) for t in args.timeframes.split(",") if t.strip()]
    else:
        frames = collected_timeframes(
            config.engine.timeframes.context, config.engine.timeframes.execution
        )

    market = MarketData(
        venue_name=config.engine.exchange.name,
        # Candles from mainnet even when trading is on testnet. Two separate
        # decisions: a testnet price history is too thin to be worth storing,
        # and the public candle endpoint needs no key.
        testnet=False,
        rate_limit_ms=config.engine.exchange.rate_limit_ms,
    )

    failures = 0
    with connect(url) as conn:
        for symbol in symbols:
            for frame in frames:
                try:
                    count = collect_ohlcv(market, conn, symbol, frame)
                    print(f"ohlcv   {symbol:9s} {frame.value:4s} {count:5d} bars")
                except Exception as error:
                    failures += 1
                    print(
                        f"ohlcv   {symbol:9s} {frame.value:4s} FAILED: {error}",
                        file=sys.stderr,
                    )
            if args.funding:
                try:
                    count = collect_funding(market, conn, symbol)
                    print(f"funding {symbol:9s}      {count:5d} settlements")
                except Exception as error:
                    failures += 1
                    print(f"funding {symbol:9s}      FAILED: {error}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
