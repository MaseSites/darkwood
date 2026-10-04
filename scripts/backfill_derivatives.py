"""Fetch open interest and the long/short account ratio.

    python scripts/backfill_derivatives.py
    python scripts/backfill_derivatives.py --symbols BTCUSDT --since 2023-01-01

Price says what happened; open interest says whether it happened because money
arrived or because money left. A rally on rising open interest and a rally on
falling open interest look identical on a chart and are opposite trades.

Bybit serves these back to roughly March 2023 and simply stops there without
saying so, which is earlier than the candles but not as early. A range this
cannot cover stays uncovered: the analysis reads a missing value as unknown, and
turning it into a zero would assert that positioning did not change.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ccxt

from traidingbrain.config.settings import load_config
from traidingbrain.data.derivatives import (
    DerivativesSource,
    DerivativesStore,
    DerivativesUnavailableError,
    FetchReport,
)

KINDS = ("open_interest", "account_ratio")


def parse_date(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbols", nargs="+", default=config.engine.symbols.active)
    parser.add_argument("--since", default="2023-01-01")
    parser.add_argument("--interval", default="1h")
    parser.add_argument(
        "--kinds", nargs="+", default=list(KINDS), choices=list(KINDS), help="what to fetch"
    )
    args = parser.parse_args(argv)

    since = parse_date(args.since)
    until = int(datetime.now(tz=UTC).timestamp() * 1000)

    exchange = ccxt.bybit(
        {
            "enableRateLimit": True,
            "rateLimit": config.engine.exchange.rate_limit_ms,
            "options": {"defaultType": "swap", "defaultSubType": "linear"},
        }
    )
    source = DerivativesSource(exchange)
    store = DerivativesStore(config.engine.paths.data_dir / "derivatives")

    print(f"{args.interval} series from {args.since}, {len(args.symbols)} symbol(s)\n")
    failures = 0

    for symbol in args.symbols:
        for kind in args.kinds:
            try:
                fetch = source.open_interest if kind == "open_interest" else source.account_ratio
                frame = fetch(symbol, interval=args.interval, since_ms=since, until_ms=until)
            except DerivativesUnavailableError as error:
                print(f"  {symbol} {kind}: {error}")
                failures += 1
                continue

            total = store.write(symbol, kind, frame)
            report = FetchReport(
                symbol=symbol,
                kind=kind,
                rows=len(frame),
                first_ts=int(frame["ts"].iloc[0]) if len(frame) else None,
                last_ts=int(frame["ts"].iloc[-1]) if len(frame) else None,
            )
            print(f"  {report.summary()}  ({total:,} on disk)")

    print(f"\nstored under {store.root}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
