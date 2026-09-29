"""Serve the confirmation dashboard.

    python scripts/run_dashboard.py             # nothing can reach an exchange
    python scripts/run_dashboard.py --demo      # with a sample proposal to look at
    python scripts/run_dashboard.py --execute   # a held confirmation reaches Bybit

Without `--execute` no executor is wired, so confirming a proposal reports what
would have been sent. That is the default, and it is what makes it safe to run
against real account data while the interface is still being shaped.

`--execute` arms the testnet executor, and arming it changes what two other
things have to be true. It needs credentials, and it needs a live price source --
because the drift check that refuses a stale proposal is the difference between
confirming a trade and confirming a trade that no longer exists at that price.
Both are required rather than optional, so there is no configuration in which the
dashboard can trade without being able to check the market first.
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
from traidingbrain.config.settings import load_secrets
from traidingbrain.data.exchange import BybitDataSource
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.execution.diagnose import diagnose
from traidingbrain.execution.intent import IntentLog
from traidingbrain.execution.order import BybitExecutor, UnsafeConfigurationError
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


def _arm(services: Services) -> bool:
    """Connect the executor and the price source, or explain why not.

    Returns False rather than continuing unarmed. Starting up in a weaker mode
    than the one that was asked for is how someone ends up believing a
    confirmation reached the exchange when it did not.
    """
    secrets = load_secrets()
    if not secrets.bybit.is_configured:
        print(
            "  --execute needs TB_BYBIT__API_KEY and TB_BYBIT__API_SECRET in .env "
            "(testnet keys from testnet.bybit.com)",
            file=sys.stderr,
        )
        return False

    config = services.config
    try:
        executor = BybitExecutor(
            secrets.bybit.api_key.get_secret_value(),
            secrets.bybit.api_secret.get_secret_value(),
            IntentLog(config.engine.paths.data_dir / "intents.sqlite"),
            services.kill_switch,
            testnet=secrets.bybit.testnet,
        )
        print(f"  preflight: {executor.preflight().describe()}")
    except UnsafeConfigurationError as exc:
        print(f"  refusing to arm: {exc}", file=sys.stderr)
        return False
    except Exception as exc:
        # A rejected key is a setup problem, and a traceback is indistinguishable
        # from a crash. The dashboard still runs; it just cannot trade.
        print("\n  Could not arm the executor.\n", file=sys.stderr)
        print(diagnose(exc, testnet=secrets.bybit.testnet).render(), file=sys.stderr)
        print(
            "\n  Everything except sending orders works without this: drop --execute\n"
            "  and the dashboard will show proposals and report what confirming\n"
            "  would have sent.\n",
            file=sys.stderr,
        )
        return False

    services.executor = executor
    # Read-only and credential-free: the price this checks against must come from
    # the public market, not from the account that is about to trade.
    services.prices = BybitDataSource(
        testnet=secrets.bybit.testnet, rate_limit_ms=config.engine.exchange.rate_limit_ms
    )
    for symbol in config.engine.symbols.active:
        try:
            services.specs[symbol] = executor.symbol_spec(symbol)
        except Exception as exc:  # one bad symbol must not stop the others
            print(f"  no instrument rules for {symbol}: {exc}", file=sys.stderr)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--demo", action="store_true", help="seed one real proposal to look at")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="arm the testnet executor so a held confirmation reaches the exchange",
    )
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

    if args.execute and not _arm(services):
        return 2

    if args.demo:
        print("Seeding a demo proposal:")
        seed_demo(services)

    print(f"\n  http://{args.host}:{args.port}")
    if services.executor is None:
        print("  no exchange is connected; confirming reports what would have been sent\n")
    else:
        network = "testnet" if load_secrets().bybit.testnet else "MAINNET -- REAL MONEY"
        print(f"  armed against Bybit {network}; a held confirmation places a real order\n")
    uvicorn.run(create_app(services), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
