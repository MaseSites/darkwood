"""Download market history into the local store.

    python scripts/backfill.py BTCUSDT --since 2024-01-01
    python scripts/backfill.py BTCUSDT --tfs W1,D1,H4,H1,M15 --since 2023-01-01
    python scripts/backfill.py --all --since 2024-01-01 --verify

Re-running is safe and cheap: it resumes from the newest stored bar, and writing
the same data twice produces identical files.

Prices come from Bybit's public mainnet endpoint. No credentials are used here and
no account is touched -- a testnet's history is too thin to backtest against, and
reading public prices needs no key.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.clock import SystemClock
from traidingbrain.config.settings import load_config
from traidingbrain.data.backfill import Backfiller
from traidingbrain.data.exchange import BybitDataSource
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe


def parse_date(text: str) -> int:
    """Accept a date or a full timestamp, always read as UTC."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=UTC).timestamp() * 1000)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"cannot read {text!r} as a UTC date")


def parse_timeframes(text: str) -> list[Timeframe]:
    return [Timeframe(part.strip().upper()) for part in text.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("symbols", nargs="*", help="e.g. BTCUSDT ETHUSDT")
    parser.add_argument("--all", action="store_true", help="every symbol in settings.yaml")
    parser.add_argument(
        "--tfs",
        type=parse_timeframes,
        default=config.engine.timeframes.all_needed,
        help="comma separated, e.g. W1,D1,H4,H1,M15,M1",
    )
    parser.add_argument("--since", type=parse_date, required=True, help="UTC date, e.g. 2024-01-01")
    parser.add_argument("--until", type=parse_date, default=None)
    parser.add_argument("--verify", action="store_true", help="re-read and report afterwards")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    symbols = (
        config.engine.symbols.available
        if args.all
        else (args.symbols or config.engine.symbols.active)
    )
    unknown = set(symbols) - set(config.engine.symbols.available)
    if unknown:
        parser.error(f"unknown symbols: {sorted(unknown)}")

    store = ParquetStore(config.engine.paths.parquet_dir)
    source = BybitDataSource(testnet=False, rate_limit_ms=config.engine.exchange.rate_limit_ms)
    backfiller = Backfiller(source, store, clock=SystemClock())

    def progress(symbol: str, timeframe: Timeframe, bars: int, newest_ts: int) -> None:
        if args.quiet:
            return
        when = datetime.fromtimestamp(newest_ts / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
        print(f"\r  {symbol} {timeframe.value:<4} {bars:>8,} bars  ->  {when}", end="", flush=True)

    fatal = False
    for symbol in symbols:
        print(f"\n{symbol}")
        for result in backfiller.run_many(
            symbol, args.tfs, args.since, args.until, progress=progress
        ):
            print(f"\r  {result.summary()}")
            if result.report.is_fatal:
                fatal = True

    if args.verify:
        print("\nVerifying what is on disk:")
        for symbol in symbols:
            for timeframe in args.tfs:
                report = store.report(symbol, timeframe)
                print(f"  {report.summary()}")
                if report.is_fatal:
                    fatal = True

    if fatal:
        print("\nFAILED: the store holds data that is wrong in a way we caused.", file=sys.stderr)
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
