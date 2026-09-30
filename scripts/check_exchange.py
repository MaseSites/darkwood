"""Check the exchange connection before anything depends on it.

    python scripts/check_exchange.py
    python scripts/check_exchange.py --venue binance --live

Runs in two halves, and the split is the point.

The public half needs no account at all and proves the venue is reachable, the
symbols exist, and candles, funding, open interest and the crowd ratio all
arrive. That half works today and is what the backtest and the live analysis
actually depend on.

The private half runs only when credentials are present. It never places an
order and never cancels one: it reads the clock, the balance, the positions and
-- where the venue offers it -- the key's own permissions. The first order this
system ever sends should be one a person confirmed on the dashboard, not one a
setup script sent to see whether it could.

`--live` points at real money instead of the sandbox. It reads only, but it is
opt-in anyway, because a script that silently touches the live account once will
do it again when someone copies the command.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.config.settings import load_config, load_secrets
from traidingbrain.data.derivatives import DerivativesSource
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.venue import SUPPORTED, venue
from traidingbrain.domain.enums import Timeframe
from traidingbrain.execution.diagnose import diagnose
from traidingbrain.execution.intent import IntentLog
from traidingbrain.execution.order import BybitExecutor, UnsafeConfigurationError
from traidingbrain.risk.limits import KillSwitch

OK = "  ok   "
BAD = "  FAIL "
SKIP = "  --   "


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--venue", choices=list(SUPPORTED), default=config.engine.exchange.name)
    parser.add_argument("--symbol", default=config.engine.symbols.active[0])
    parser.add_argument(
        "--live",
        action="store_true",
        help="read the real account instead of the sandbox; still places no orders",
    )
    args = parser.parse_args(argv)

    chosen = venue(args.venue)
    testnet = not args.live
    where = "testnet" if testnet else "LIVE (real money -- reading only)"
    print(f"venue {chosen.name} ({chosen.ccxt_id}), {where}")
    print(f"symbol {args.symbol} -> {chosen.symbol(args.symbol)}\n")

    failures = _public_checks(args, config)
    failures += _private_checks(args, config, chosen, testnet)

    print()
    if failures:
        print(f"{failures} check(s) failed. Nothing was sent to the exchange.")
        return 1
    print("Everything answered. Nothing was sent to the exchange.")
    return 0


def _public_checks(args: argparse.Namespace, config: object) -> int:
    """No credentials, no account. This is what the analysis actually needs.

    Always against the real venue, never the practice one, because that is what
    the system does: prices, candles and open interest are identical either way,
    and the practice hosts serve a thinner set of them. Reading market data from
    a sandbox would test a path nothing uses.
    """
    print("public data (real venue, no account, no credentials)")
    failures = 0
    rate = config.engine.exchange.rate_limit_ms  # type: ignore[attr-defined]
    data = MarketData(venue_name=args.venue, testnet=False, rate_limit_ms=rate)

    try:
        recent = int(datetime.now(tz=UTC).timestamp() * 1000) - 12 * 3_600_000
        bars = data.fetch_ohlcv(args.symbol, Timeframe.H1, recent, 5)
        newest = datetime.fromtimestamp(bars[-1].ts / 1000, tz=UTC)
        print(f"{OK} candles          {len(bars)} bars, newest {newest:%Y-%m-%d %H:%M} UTC")
    except Exception as error:
        print(f"{BAD} candles          {_short(error)}")
        failures += 1

    try:
        spec = data.fetch_symbol_spec(args.symbol)
        print(
            f"{OK} instrument rules tick {spec.price_tick}, step {spec.qty_step}, "
            f"max leverage {spec.max_leverage:g}x"
        )
    except Exception as error:
        print(f"{BAD} instrument rules {_short(error)}")
        failures += 1

    try:
        price = data.last_price(args.symbol)
        print(f"{OK} last price       {price:,.2f}" if price else f"{BAD} last price       none")
        failures += 0 if price else 1
    except Exception as error:
        print(f"{BAD} last price       {_short(error)}")
        failures += 1

    now = int(datetime.now(tz=UTC).timestamp() * 1000)
    derivatives = DerivativesSource(data.exchange, args.venue)
    for label, fetch in (
        ("open interest", derivatives.open_interest),
        ("crowd ratio", derivatives.account_ratio),
    ):
        try:
            frame = fetch(args.symbol, since_ms=now - 6 * 3_600_000, until_ms=now)
            if frame.empty:
                print(f"{BAD} {label:<16s} no rows returned")
                failures += 1
            else:
                print(f"{OK} {label:<16s} {len(frame)} rows")
        except Exception as error:
            print(f"{BAD} {label:<16s} {_short(error)}")
            failures += 1

    return failures


def _private_checks(
    args: argparse.Namespace, config: object, chosen: object, testnet: bool
) -> int:
    """Read-only account checks. Skipped entirely when there are no credentials."""
    print("\naccount (read-only -- no order is placed, nothing is cancelled)")
    secrets = load_secrets()
    if not secrets.bybit.is_configured:
        print(f"{SKIP} credentials      none in .env, so the account is not checked")
        print("        Everything above works without them; only sending orders needs an account.")
        return 0

    data_dir = config.engine.paths.data_dir  # type: ignore[attr-defined]
    try:
        executor = BybitExecutor(
            secrets.bybit.api_key.get_secret_value(),
            secrets.bybit.api_secret.get_secret_value(),
            IntentLog(data_dir / "intents.sqlite"),
            KillSwitch(data_dir / "KILL_SWITCH"),
            testnet=testnet,
            venue_name=args.venue,
        )
        report = executor.preflight()
    except UnsafeConfigurationError as error:
        print(f"{BAD} preflight        {error}")
        return 1
    except Exception as error:
        print(f"{BAD} connection\n")
        print(diagnose(error, testnet=testnet).render(indent="        "))
        return 1

    print(f"{OK} preflight        {report.describe()}")
    if not chosen.reports_key_rights:  # type: ignore[attr-defined]
        print(f"{SKIP} key permissions  {chosen.name} has no endpoint for this; not checked")  # type: ignore[attr-defined]
    else:
        print(f"{OK} key permissions  may trade, may not withdraw")
    return 0


def _short(error: Exception) -> str:
    return f"{type(error).__name__}: {str(error)[:70]}"


if __name__ == "__main__":
    raise SystemExit(main())
