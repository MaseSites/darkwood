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

from traidingbrain.brain.cache import DecisionCache
from traidingbrain.brain.factory import BRAIN_NAMES, make_brain
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.history.engine import HistoryEngine
from traidingbrain.sim.engine import BacktestResult, load_engine
from traidingbrain.sim.metrics import compare
from traidingbrain.strategies.baseline import RandomEntry, StructureBaseline
from traidingbrain.strategies.brain_strategy import BrainStrategy
from traidingbrain.strategies.guide import GuidePool, GuideSetupStrategy
from traidingbrain.strategy.setups import TRADEABLE


def _make(name: str, config, *, kind: str = "fake"):
    """Build a strategy by name.

    `fake-brain` is the sharpest of the three yardsticks: identical gate,
    identical factors, identical sizing, with the judgement replaced by
    arithmetic. The gap between it and the real model is the value of the
    judgement alone.
    """
    if name.startswith("guide-"):
        key = name.removeprefix("guide-")
        if key == "all":
            return GuidePool.for_config(config)
        setup = next((item for item in TRADEABLE if item.key == key), None)
        if setup is None:
            raise ValueError(
                f"unknown guide setup {key!r}; this build trades "
                f"{', '.join(item.key for item in TRADEABLE)}"
            )
        return GuideSetupStrategy(setup)
    if name == "random":
        return RandomEntry()
    if name == "baseline":
        return StructureBaseline()
    if name == "fake-brain":
        return BrainStrategy(make_brain("fake", config), config.engine.trigger, name="fake-brain")
    if name == "brain":
        # The cache is what makes a repeat run free and reproducible. Without
        # sampling parameters it is the only reproducibility guarantee there is.
        cache = DecisionCache(config.engine.paths.cache_db_path)
        return BrainStrategy(
            make_brain(kind, config, cache=cache), config.engine.trigger, name=f"brain-{kind}"
        )
    raise ValueError(f"unknown strategy {name!r}")


#: Every strategy the comparison can run.
#:
#: The guide setups are listed one by one rather than only as a pool, because
#: chapter 30 of the guide asks for them to be measured apart -- a single pooled
#: number cannot say which rule earned it.
STRATEGY_NAMES = [
    "random",
    "baseline",
    "fake-brain",
    "brain",
    *(f"guide-{setup.key}" for setup in TRADEABLE),
    "guide-all",
]


#: Fallback instrument rules, used when running offline. Taken from Bybit's
#: BTCUSDT perpetual; `--live-spec` fetches the real ones.
def human(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbol", default=config.engine.symbols.active[0])
    parser.add_argument("--strategy", choices=STRATEGY_NAMES, default="baseline")
    parser.add_argument(
        "--compare",
        nargs="+",
        choices=STRATEGY_NAMES,
        help="run several and say whether the difference is real",
    )
    parser.add_argument(
        "--brain",
        choices=BRAIN_NAMES,
        default="subscription",
        help="who answers when --strategy brain is used (default: subscription)",
    )
    parser.add_argument("--max-bars", type=int, default=None, help="cut the run short")
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="run without the similarity index, to see what it is contributing",
    )
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
    # The index fills as the run proceeds and starts empty, so this is the same
    # walk-forward behaviour a live system would have -- not a training pass.
    history = None if args.no_history else HistoryEngine(config.engine.history)
    engine = load_engine(
        args.symbol,
        frames,
        minute_frame=minutes,
        spec=spec,
        config=config,
        funding=funding,
        history=history,
    )
    print(f"\nanalysis ready in {time.perf_counter() - started:.1f}s")

    names = args.compare or [args.strategy]
    results: list[BacktestResult] = []
    for name in names:
        started = time.perf_counter()
        strategy = _make(name, config, kind=args.brain)
        result = engine.run(strategy, max_bars=args.max_bars)
        print(f"\n{result.summary()}")
        print(f"  window          {human(result.first_ts)} .. {human(result.last_ts)}")
        if hasattr(strategy, "summary"):
            print(strategy.summary())
        print(f"  runtime         {time.perf_counter() - started:.1f}s")
        results.append(result)

    if len(results) > 1:
        print("\n" + "=" * 78)
        for other in results[1:]:
            print(compare(results[0].metrics, other.metrics))
            print()

    return 0


def _symbol_spec(symbol: str, *, use_live: bool, config: AppConfig) -> SymbolSpec:
    if use_live:
        return MarketData(venue_name=config.engine.exchange.name, testnet=False).fetch_symbol_spec(
            symbol
        )
    return SymbolSpec(symbol=symbol, **DEFAULT_SPEC)


if __name__ == "__main__":
    raise SystemExit(main())
