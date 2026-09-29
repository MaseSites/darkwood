"""Serve the confirmation dashboard.

    python scripts/run_dashboard.py
    python scripts/run_dashboard.py --demo      # with a sample proposal to look at

No executor is wired in this build, so nothing this serves can place an order.
Confirming a proposal reports what would have been sent. That is what makes it
safe to run against real account data while the interface is still being shaped.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.api.app import Services, build_default_services, create_app
from traidingbrain.brain.fake import FakeBrain
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.proposals.builder import BuildFailure
from traidingbrain.risk.limits import AccountState

DEMO_SPEC = {
    "price_tick": 0.1,
    "qty_step": 0.001,
    "min_qty": 0.001,
    "min_notional": 5.0,
    "max_leverage": 100.0,
    "taker_fee": 0.00055,
    "maker_fee": 0.0002,
    "maintenance_margin_rate": 0.005,
}


def seed_demo(services: Services) -> None:
    """Put one real proposal on the screen, built by the real pipeline.

    Built rather than hand-written, so what is displayed is genuinely what the
    system produces -- a mocked-up ticket would hide exactly the formatting and
    rounding problems this is meant to surface.
    """
    config = services.config
    store = ParquetStore(config.engine.paths.parquet_dir)
    symbol = config.engine.symbols.active[0]
    frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
    if any(frame.empty for frame in frames.values()):
        print(f"  no market data for {symbol}; the dashboard will start empty")
        return

    analysis = MultiFrameAnalysis(frames, config.engine)
    builder = SnapshotBuilder(symbol, analysis, config.engine)
    snapshot = builder.build(len(analysis.signal) - 1)
    if snapshot is None:
        print("  not enough history to build a snapshot")
        return

    spec = SymbolSpec(symbol=symbol, **DEMO_SPEC)
    services.specs[symbol] = spec
    decision = FakeBrain(config).decide(snapshot)
    built = services.builder.build(decision, snapshot, spec, services.account_state())

    if isinstance(built, BuildFailure):
        print(f"  the analysis declined this bar: {built}")
        return
    services.store.put(built)
    print(f"  seeded one proposal: {built.side.value} {symbol} at {built.entry:,.2f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--demo", action="store_true", help="seed one real proposal to look at")
    args = parser.parse_args(argv)

    services = build_default_services()
    services.account = AccountState(
        equity=services.config.engine.simulation.initial_equity,
        starting_equity_today=services.config.engine.simulation.initial_equity,
        starting_equity_this_week=services.config.engine.simulation.initial_equity,
        open_positions=[],
        recent_trades=[],
        now_ms=0,
    )

    if args.demo:
        print("Seeding a demo proposal:")
        seed_demo(services)

    print(f"\n  http://{args.host}:{args.port}")
    print("  no exchange is connected; confirming reports what would have been sent\n")
    uvicorn.run(create_app(services), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
