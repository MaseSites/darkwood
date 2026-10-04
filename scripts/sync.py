"""Empty the collector's landing zone forward into the Parquet archive.

The Pi gathers into Postgres while the laptop is off; the dashboard and the
backtest read Parquet. This is the step between, and until it existed the
collector had been writing into a table nobody drained.

    python scripts/sync.py                 # copy everything new, delete nothing
    python scripts/sync.py --prune         # also empty what the archive now holds
    python scripts/sync.py --dry-run       # say what would move, touch nothing

Nothing is deleted unless `--prune` is given, and then only rows the archive
has been re-read and confirms it holds. The exit code is non-zero when any
series failed, so a timer that runs this shows up in `systemctl --failed`
rather than failing quietly -- the same mechanism `health.py` uses, for the
same reason.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import EngineConfig, load_config, load_secrets
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.grid import collected_timeframes, timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.data.sync import OVERLAP_BARS, SyncReport, drain
from traidingbrain.domain.enums import Timeframe
from traidingbrain.storage.landing import PostgresLandingZone
from traidingbrain.storage.postgres import PostgresUnavailableError, close_pools


def _report(report: SyncReport, *, quiet: bool) -> None:
    for result in report.results:
        if result.error or not quiet or result.read:
            print(result.describe())
    print(report.describe())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete landing-zone rows the archive has been confirmed to hold",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read and report, write nothing",
    )
    parser.add_argument("--symbol", action="append", help="limit to these symbols")
    parser.add_argument("--quiet", action="store_true", help="print only what moved or failed")
    args = parser.parse_args()

    config = load_config().engine
    secrets = load_secrets()
    url = secrets.postgres_url.get_secret_value()

    symbols = args.symbol or config.symbols.active
    # Exactly what the collector writes -- one definition, so the two cannot
    # drift. They did: the first draft drained the context frames only, which
    # left M1 accumulating in the landing zone with nothing to empty it.
    timeframes = collected_timeframes(config.timeframes.context, config.timeframes.execution)

    if args.dry_run:
        # Counting without writing, so that "how far behind is the archive?"
        # can be asked before anything moves. Deliberately a separate path
        # rather than a flag threaded through the drain: a write guarded by a
        # boolean is a write that happens the day the boolean is wrong.
        return _dry_run(url, config, symbols, timeframes)

    zone = PostgresLandingZone(url)
    try:
        report = drain(
            zone,
            ParquetStore(config.paths.parquet_dir),
            FundingStore(config.paths.funding_dir),
            symbols=symbols,
            timeframes=timeframes,
            prune=args.prune,
        )
    except PostgresUnavailableError as error:
        print(f"keine Datenbank: {error}", file=sys.stderr)
        return 2
    finally:
        close_pools()

    _report(report, quiet=args.quiet)
    return 1 if report.failures else 0


def _dry_run(
    url: str, config: EngineConfig, symbols: list[str], timeframes: list[Timeframe]
) -> int:
    """How much is waiting, without touching either store."""
    store = ParquetStore(config.paths.parquet_dir)
    zone = PostgresLandingZone(url)
    try:
        total = 0
        for symbol in symbols:
            for timeframe in timeframes:
                held = store.last_ts(symbol, timeframe)
                since = 0 if held is None else held - OVERLAP_BARS * timeframe_ms(timeframe)
                waiting = len(zone.ohlcv_since(symbol, timeframe, max(0, since)))
                total += waiting
                if waiting:
                    print(f"ohlcv:{symbol}:{timeframe.value}: {waiting} Zeilen würden folgen")
        print(f"{total} Zeilen insgesamt, nichts geschrieben")
    except PostgresUnavailableError as error:
        print(f"keine Datenbank: {error}", file=sys.stderr)
        return 2
    finally:
        close_pools()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
