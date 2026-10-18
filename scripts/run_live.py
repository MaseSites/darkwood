"""Watch the market and put proposals on the dashboard.

    python scripts/run_live.py                    # analysis only, nothing can trade
    python scripts/run_live.py --execute          # arm the testnet executor
    python scripts/run_live.py --cycles 3         # a few passes, then stop

What this does: every twenty seconds it pulls whatever bars have closed, and when a
new hourly bar appears it runs the same pipeline the backtest runs -- snapshot,
gate, brain, guard, risk -- and, if everything agrees, writes a proposal.

What it does not do: trade. The proposal sits in the store until someone confirms
it from the dashboard. With `--execute` the confirmation reaches Bybit's testnet;
without it, confirming reports what would have been sent.

Reconciliation runs first, before anything else. Starting fresh while an order from
a previous run is still in flight is how a system ends up holding two positions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.brain.cache import DecisionCache
from traidingbrain.brain.factory import BRAIN_NAMES, make_brain
from traidingbrain.clock import SystemClock
from traidingbrain.config.settings import load_config, load_secrets
from traidingbrain.data.derivatives import (
    DerivativesSource,
    DerivativesStore,
    LivePositioning,
)
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.execution.diagnose import diagnose
from traidingbrain.execution.intent import IntentLog
from traidingbrain.execution.order import BybitExecutor, UnsafeConfigurationError
from traidingbrain.execution.reconcile import reconcile
from traidingbrain.execution.watchdog import StopWatchdog
from traidingbrain.history.engine import HistoryEngine
from traidingbrain.journal.history import closed_trades
from traidingbrain.journal.store import JournalStore
from traidingbrain.journal.version import run_signature
from traidingbrain.live.loop import LiveLoop, next_close
from traidingbrain.proposals.builder import ProposalBuilder, describe
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits

OFFLINE_SPEC = {
    "price_tick": 0.1,
    "qty_step": 0.001,
    "min_qty": 0.001,
    "min_notional": 5.0,
    "max_leverage": 100.0,
    "taker_fee": 0.00055,
    "maker_fee": 0.0002,
    "maintenance_margin_rate": 0.005,
}


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbol", default=config.engine.symbols.active[0])
    parser.add_argument("--cycles", type=int, default=None, help="stop after this many passes")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="arm the testnet executor so a confirmation reaches the exchange",
    )
    parser.add_argument("--equity", type=float, default=config.engine.simulation.initial_equity)
    parser.add_argument(
        "--brain",
        choices=BRAIN_NAMES,
        default="subscription",
        help="who interprets the market (default: subscription, no API key needed)",
    )
    args = parser.parse_args(argv)

    secrets = load_secrets()
    kill_switch = KillSwitch(config.engine.paths.data_dir / "KILL_SWITCH")
    limits = RiskLimits(config.risk.limits, kill_switch)
    proposals = ProposalStore(config.engine.paths.db_path)
    intents = IntentLog(config.engine.paths.data_dir / "intents.sqlite")

    # Prices come from mainnet and need no credentials; only trading touches an
    # account, and that one defaults to testnet.
    source = MarketData(
        venue_name=config.engine.exchange.name,
        testnet=False,
        rate_limit_ms=config.engine.exchange.rate_limit_ms,
    )

    executor = _arm_executor(args, config, secrets, intents, kill_switch)
    if executor is False:
        return 1

    if executor is not None:
        outcome = reconcile(intents, executor)
        print(outcome.summary())
        if not outcome.is_clean:
            print(
                "\n  Not starting: something from a previous run is unaccounted for. "
                "Settle it before trading again.",
                file=sys.stderr,
            )
            return 1

    spec = (
        executor.symbol_spec(args.symbol)
        if executor is not None
        else SymbolSpec(symbol=args.symbol, **OFFLINE_SPEC)
    )

    # Dieselbe Datei, die papertrade.py als JOURNAL_NAME fuehrt. Die
    # Konfiguration kennt keinen Journalpfad; er wird im Projekt
    # herumgereicht, und eine Konfigurationsspalte dafuer waere eine
    # groessere Aenderung als dieser Defekt.
    journal = JournalStore(config.engine.paths.data_dir / "journal.sqlite")
    signature = run_signature(config)

    def account() -> AccountState:
        """Der Kontozustand, mit echter Historie statt einer leeren Liste.

        **Was hier vorher stand, und warum es ein Defekt war.** Die drei
        Sicherungen `max_daily_loss_pct`, `max_weekly_loss_pct` und
        `cooldown_after_consecutive_losses` lesen alle `recent_trades`, und
        hier stand `[]`. Sie konnten in keinem Prozess ausloesen. Dazu
        `starting_equity_today=args.equity`, also der Freibetrag gegen das
        AKTUELLE Kapital gemessen -- genau der Fehler, den der Kommentar bei
        der Tagespruefung in `risk/limits.py` beschreibt.

        **Kontoweit, nicht je Symbol.** `run_live.py` faehrt ein Symbol, aber
        gegen EIN Boersenkonto, das mehrere halten kann; die Verlustdeckel
        gelten dem Konto. Deshalb kein `symbol=`-Filter, passend zu
        `executor.open_positions()`, das ebenfalls alles liefert.

        **Gefiltert auf die laufende Signatur.** Ueber alle Zeilen gelesen
        zaehlt die Bremse drei Konfigurationsepochen zusammen -- gemessen am
        12.10.2026 der Unterschied zwischen zwei Konten mit Verlustserie 2
        und keinem einzigen.
        """
        now = SystemClock().now_ms()
        return AccountState.from_history(
            equity=args.equity,
            history=closed_trades(journal, signature=signature),
            now_ms=now,
            open_positions=executor.open_positions() if executor else [],
        )

    loop = LiveLoop(
        args.symbol,
        config,
        source=source,
        store=ParquetStore(config.engine.paths.parquet_dir),
        proposals=proposals,
        builder=ProposalBuilder(config, limits),
        brain=make_brain(
            args.brain, config, cache=DecisionCache(config.engine.paths.cache_db_path)
        ),
        spec=spec,
        clock=SystemClock(),
        history=HistoryEngine(config.engine.history),
        positioning=LivePositioning(
            # Beide mit DERSELBEN Venue, und der Speicher bricht bei
            # fremden Daten ab statt sie zu ueberschreiben. Vorher holte die
            # Quelle von der konfigurierten Boerse und der Speicher schrieb in
            # die Dateien, die `backfill_derivatives.py` mit ccxt.bybit
            # gefuellt hatte -- `drop_duplicates(keep="last")` liess bei
            # Ueberlappung die neue Boerse gewinnen.
            DerivativesSource(source.exchange, config.engine.exchange.name),
            DerivativesStore(
                config.engine.paths.data_dir / "derivatives",
                venue=config.engine.exchange.name,
                on_foreign="raise",
            ),
        ),
        account=account,
    )
    watchdog = (
        StopWatchdog(
            executor,
            deadline_seconds=config.risk.execution.stop_watchdog_deadline_seconds,
        )
        if executor
        else None
    )

    print(f"\n  watching {args.symbol} on {config.engine.timeframes.signal.value}")
    closes_at = next_close(config.engine.timeframes.signal, SystemClock().now_ms())
    print(f"  next bar closes {closes_at:%H:%M UTC}")
    print(f"  execution: {'testnet, armed' if executor else 'not connected'}")
    print("  dashboard: python scripts/run_dashboard.py\n")

    def announce(proposal_id: str) -> None:
        proposal = proposals.get(proposal_id)
        if proposal is not None:
            print(f"\n--- proposal ---\n{describe(proposal)}\n")

    try:
        stats = loop.run(max_cycles=args.cycles, on_proposal=announce)
    except KeyboardInterrupt:
        stats = loop.stats
        print("\n  stopped")

    print(stats.summary())
    print(loop.trigger.stats.summary())
    if watchdog is not None:
        watchdog.sweep()
        print(watchdog.summary())
    for error in stats.errors[-5:]:
        print(f"  ! {error}")
    return 0


def _arm_executor(args, config, secrets, intents, kill_switch):
    """Build the executor, or False if it cannot be armed safely.

    Returns False rather than None on failure so the caller can tell "not asked
    for" apart from "asked for and refused" -- the second has to stop the process.
    """
    if not args.execute:
        return None

    if not secrets.bybit.is_configured:
        print(
            "  --execute needs TB_BYBIT__API_KEY and TB_BYBIT__API_SECRET in .env "
            "(testnet keys from testnet.bybit.com)",
            file=sys.stderr,
        )
        return False

    try:
        executor = BybitExecutor(
            secrets.bybit.api_key.get_secret_value(),
            secrets.bybit.api_secret.get_secret_value(),
            intents,
            kill_switch,
            testnet=secrets.bybit.testnet,
        )
        print(f"  preflight: {executor.preflight().describe()}")
    except UnsafeConfigurationError as exc:
        print(f"  refusing to start: {exc}", file=sys.stderr)
        return False
    except Exception as exc:
        print("\n  Could not connect to the exchange.\n", file=sys.stderr)
        print(diagnose(exc, testnet=secrets.bybit.testnet).render(), file=sys.stderr)
        print("\n  Drop --execute to run the analysis without it.\n", file=sys.stderr)
        return False
    return executor


if __name__ == "__main__":
    raise SystemExit(main())
