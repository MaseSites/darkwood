"""Run a backtest and report what it actually established.

    python scripts/run_backtest.py --strategy baseline
    python scripts/run_backtest.py --strategy random --symbol BTCUSDT
    python scripts/run_backtest.py --compare random baseline

The comparison mode is the one that matters. A single strategy's numbers are
uninterpretable on their own -- every backtest produces some expectancy, and
without a yardstick there is no way to tell an edge from a lucky stretch of market.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.config.settings import load_config
from traidingbrain.data.exchange import BybitDataSource
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.sim.engine import BacktestResult, load_engine
from traidingbrain.sim.metrics import compare
from traidingbrain.strategies.baseline import RandomEntry, StructureBaseline

STRATEGIES = {"random": RandomEntry, "baseline": StructureBaseline}

#: Fallback instrument rules, used when running offline. Taken from Bybit's
#: BTCUSDT perpetual; `--live-spec` fetches the real ones.
DEFAULT_SPEC = {
    "price_tick": 0.1,
    "qty_step": 0.001,
    "min_qty": 0.001,
    "min_notional": 5.0,
    "max_leverage": 100.0,
    "taker_fee": 0.00055,
    "maker_fee": 0.0002,
    "maintenance_margin_rate": 0.005,
}


def human(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbol", default=config.engine.symbols.active[0])
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default="baseline")
    parser.add_argument(
        "--compare",
        nargs="+",
        choices=sorted(STRATEGIES),
        help="run several and say whether the difference is real",
    )
    parser.add_argument("--max-bars", type=int, default=None, help="cut the run short")
    parser.add_argument(
        "--live-spec", action="store_true", help="fetch instrument rules from the venue"
    )
    args = parser.parse_args(argv)

    store = ParquetStore(config.engine.paths.parquet_dir)
    frames = {tf: store.read(args.symbol, tf) for tf in config.engine.timeframes.context}
    minutes = store.read(args.symbol, config.engine.timeframes.execution)

    missing = [tf.value for tf, frame in frames.items() if frame.empty]
    if missing or minutes.empty:
        print(
            f"No data for {args.symbol} on {missing or [config.engine.timeframes.execution.value]}."
            f"\nRun: python scripts/backfill.py {args.symbol} --since 2023-01-01",
            file=sys.stderr,
        )
        return 1

    spec = _symbol_spec(args.symbol, use_live=args.live_spec, config=config)
    funding = FundingStore(config.engine.paths.funding_dir).read(args.symbol)

    print(f"{args.symbol}")
    for timeframe, frame in frames.items():
        print(f"  {timeframe.value:<4s} {len(frame):>9,} bars")
    print(f"  {config.engine.timeframes.execution.value:<4s} {len(minutes):>9,} bars")
    if funding:
        print(f"  funding  {len(funding):>9,} settlements")
    else:
        print("  funding  none stored -- holding costs are NOT modelled in this run.")
        print(
            f"           Fix with: python scripts/backfill.py {args.symbol} "
            "--tfs H1 --since 2023-01-01 --funding"
        )

    started = time.perf_counter()
    engine = load_engine(
        args.symbol,
        frames,
        minute_frame=minutes,
        spec=spec,
        config=config,
        funding=funding,
    )
    print(f"\nanalysis ready in {time.perf_counter() - started:.1f}s")

    names = args.compare or [args.strategy]
    results: list[BacktestResult] = []
    for name in names:
        started = time.perf_counter()
        result = engine.run(STRATEGIES[name](), max_bars=args.max_bars)
        print(f"\n{result.summary()}")
        print(f"  window          {human(result.first_ts)} .. {human(result.last_ts)}")
        print(f"  runtime         {time.perf_counter() - started:.1f}s")
        results.append(result)

    if len(results) > 1:
        print("\n" + "=" * 78)
        for other in results[1:]:
            print(compare(results[0].metrics, other.metrics))
            print()

    return 0


def _symbol_spec(symbol: str, *, use_live: bool, config: object) -> SymbolSpec:
    if use_live:
        return BybitDataSource(testnet=False).fetch_symbol_spec(symbol)
    return SymbolSpec(symbol=symbol, **DEFAULT_SPEC)


if __name__ == "__main__":
    raise SystemExit(main())
