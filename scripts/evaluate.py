"""Ask whether a backtest result means anything.

    python scripts/evaluate.py --split
    python scripts/evaluate.py --split --symbols BTCUSDT ETHUSDT SOLUSDT XRPUSDT
    python scripts/evaluate.py --walk-forward 4

A single backtest number is in-sample until proven otherwise. This script does the
proving, or -- more often, and more usefully -- fails to.

Three things it does that a plain backtest does not:

* Splits chronologically and reports how much of the in-sample result survived.
* Pools several symbols. One symbol over two and a half years gives about a
  hundred and fifty trades, which cannot distinguish a small edge from nothing.
  Results are measured in R, so they combine across instruments.
* Uses a block bootstrap, which keeps the clustering of trades instead of
  pretending each one is an independent draw.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.brain.fake import FakeBrain
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.history.engine import HistoryEngine
from traidingbrain.sim.engine import BacktestEngine, load_engine
from traidingbrain.sim.evaluate import (
    PooledResult,
    Window,
    compare_out_of_sample,
    evaluate,
    split,
    walk_forward,
)
from traidingbrain.strategies.baseline import RandomEntry, StructureBaseline
from traidingbrain.strategies.brain_strategy import BrainStrategy

#: Offline instrument rules. Close enough to Bybit's majors that the cost model is
#: realistic; `scripts/run_backtest.py --live-spec` fetches the real ones.
DEFAULT_SPEC = {
    "price_tick": 0.01,
    "qty_step": 0.001,
    "min_qty": 0.001,
    "min_notional": 5.0,
    "max_leverage": 100.0,
    "taker_fee": 0.00055,
    "maker_fee": 0.0002,
    "maintenance_margin_rate": 0.005,
}

STRATEGY_NAMES = ["random", "baseline", "fake-brain"]


def maker(name: str, config: AppConfig):
    """A factory, not an instance.

    Each window gets a fresh strategy, so a carried random seed or trigger
    cooldown cannot let one window influence the next.
    """

    def build():
        if name == "random":
            return RandomEntry()
        if name == "baseline":
            return StructureBaseline()
        if name == "fake-brain":
            return BrainStrategy(FakeBrain(config), config.engine.trigger, name="fake-brain")
        raise ValueError(f"unknown strategy {name!r}")

    return build


def build_engine(
    symbol: str, config: AppConfig, history: HistoryEngine | None = None
) -> BacktestEngine | None:
    store = ParquetStore(config.engine.paths.parquet_dir)
    frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
    minutes = store.read(symbol, config.engine.timeframes.execution)
    if any(frame.empty for frame in frames.values()) or minutes.empty:
        return None
    return load_engine(
        symbol,
        frames,
        minute_frame=minutes,
        spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
        config=config,
        funding=FundingStore(config.engine.paths.funding_dir).read(symbol),
        history=history,
    )


def usable_window(engine: BacktestEngine) -> Window | None:
    first = engine.analysis.first_ready_index()
    if first is None:
        return None
    signal = engine.analysis.signal
    return Window("all", signal.ts_at(first), signal.ts_at(len(signal) - 1))


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=config.engine.symbols.active,
        help="pool several symbols; results are in R, so they combine across instruments",
    )
    parser.add_argument("--strategies", nargs="+", choices=STRATEGY_NAMES, default=STRATEGY_NAMES)
    parser.add_argument(
        "--split", action="store_true", help="fit on the first half, report on the second"
    )
    parser.add_argument("--walk-forward", type=int, default=0, metavar="FOLDS")
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="run without the similarity index, to see what it is contributing",
    )
    parser.add_argument("--train-fraction", type=float, default=0.5)
    args = parser.parse_args(argv)

    if not args.split and not args.walk_forward:
        args.split = True

    # One index across every symbol, because one symbol does not reach the
    # threshold a win rate may be quoted at and four pooled do.
    #
    # Running the symbols one after another is safe despite the shared index: a
    # case is only admissible once its outcome resolved before the embargo window
    # preceding the bar being decided, so BTC's 2026 trades are invisible while
    # ETH is at 2024. The time filter does the work, not the loop order.
    history = None if args.no_history else HistoryEngine(config.engine.history)

    engines: dict[str, BacktestEngine] = {}
    windows: dict[str, Window] = {}
    for symbol in args.symbols:
        engine = build_engine(symbol, config, history)
        if engine is None:
            print(f"  {symbol}: no data, skipping", file=sys.stderr)
            continue
        window = usable_window(engine)
        if window is None:
            print(f"  {symbol}: not enough history to warm up, skipping", file=sys.stderr)
            continue
        engines[symbol] = engine
        windows[symbol] = window
        print(f"{symbol}: {window}")

    if not engines:
        print(
            "\nNothing to evaluate. Run:\n"
            "  python scripts/backfill.py --all --since 2023-01-01 --funding",
            file=sys.stderr,
        )
        return 1

    # The common window, so every symbol is judged on the same period. Without it
    # a symbol with a shorter history quietly contributes a different market.
    common = Window(
        "common",
        max(w.start_ts for w in windows.values()),
        min(w.end_ts for w in windows.values()),
    )
    if len(engines) > 1:
        print(f"\ncommon window across all symbols: {common}")

    if args.split:
        _report_split(engines, common, args, config)

    if args.walk_forward:
        _report_walk_forward(engines, common, args, config)

    if history is not None:
        print(
            f"\nhistory index: {history.cases:,} resolved cases, "
            f"{history.lookups:,} lookups, "
            f"{history.lookups_with_sample:,} of them with enough comparable cases "
            f"to quote a rate"
        )

    return 0


def _report_split(
    engines: dict[str, BacktestEngine],
    window: Window,
    args: argparse.Namespace,
    config: AppConfig,
) -> None:
    print("\n" + "=" * 78)
    print("SINGLE SPLIT -- how much of the in-sample result survives")
    print("=" * 78)
    train, test = split(window.start_ts, window.end_ts, args.train_fraction)
    print(f"  {train}\n  {test}\n")

    for name in args.strategies:
        build = maker(name, config)
        in_sample = {
            symbol: engine.run(build(), start_ts=train.start_ts, end_ts=train.end_ts)
            for symbol, engine in engines.items()
        }
        out_sample = {
            symbol: engine.run(build(), start_ts=test.start_ts, end_ts=test.end_ts)
            for symbol, engine in engines.items()
        }

        print(PooledResult(f"{name} -- in-sample", in_sample).report())
        print(PooledResult(f"{name} -- out-of-sample", out_sample).report())

        if len(engines) == 1:
            symbol = next(iter(engines))
            print(compare_out_of_sample(in_sample[symbol], out_sample[symbol]))
        print()


def _report_walk_forward(
    engines: dict[str, BacktestEngine],
    window: Window,
    args: argparse.Namespace,
    config: AppConfig,
) -> None:
    print("=" * 78)
    print(f"WALK FORWARD ({args.walk_forward} folds) -- does it hold across periods")
    print("=" * 78)
    tests = [test for _, test in walk_forward(window.start_ts, window.end_ts, args.walk_forward)]

    for name in args.strategies:
        build = maker(name, config)
        for symbol, engine in engines.items():
            label = f"{name} / {symbol}" if len(engines) > 1 else name
            print(evaluate(engine, build, tests, label).report())
        print()


if __name__ == "__main__":
    raise SystemExit(main())
