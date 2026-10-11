"""Download market history into the local store.

    python scripts/backfill.py BTCUSDT --since 2024-01-01
    python scripts/backfill.py BTCUSDT --tfs W1,D1,H4,H1,M15 --since 2023-01-01
    python scripts/backfill.py --all --since 2024-01-01 --verify

Re-running is safe and cheap: it resumes from the newest stored bar, and writing
the same data twice produces identical files.

Prices come from whichever venue `exchange.name` in config/settings.yaml names,
through its public mainnet endpoint -- today `binance`, so Binance USD-M. The
line above said "Bybit" long after that stopped being true: this script reads
the config and always did. A wrong provenance note already blocked a research
axis in this project for a day, because nobody re-measures a comment.

No credentials are used here and no account is touched -- a testnet's history is
too thin to backtest against, and reading public prices needs no key.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.clock import SystemClock
from traidingbrain.config.settings import load_config
from traidingbrain.data.backfill import Backfiller
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.funding import FundingStore, backfill_funding
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


def resolve_symbols(args: argparse.Namespace, *, config: object,
                    parser: argparse.ArgumentParser) -> list[str]:
    """Welche Maerkte geholt werden, und woran die Liste geprueft wird.

    `available` heisst "wir haben die Daten und koennten das handeln". Fuer
    eine Datenerweiterung ist das zirkulaer: der Markt kommt erst dort hinein,
    wenn seine Daten liegen, und die holt genau dieses Skript.

    Die Pruefung gegen `available` bleibt der Normalfall -- sie faengt
    Tippfehler, und das ist sie wert. Fuer die Erweiterung tritt die vorab
    erzeugte Liste aus `scripts/universe_for_backfill.py` an ihre Stelle: eine
    Regel statt einer Tastatureingabe, damit die Marktauswahl nicht die
    Auswahl nach Ergebnis ist, gegen die das ganze Register steht.
    """
    if args.from_universe:
        universe = config.engine.paths.data_dir / "universe_for_backfill.json"  # type: ignore[attr-defined]
        if not universe.exists():
            parser.error(f"{universe} fehlt -- erst scripts/universe_for_backfill.py --write")
        declared = json.loads(universe.read_text(encoding="utf-8"))
        chosen = list(args.symbols) or list(declared["to_backfill"])
        unknown = set(chosen) - set(declared["eligible"])
        if unknown:
            parser.error(f"nicht in der vorab erzeugten Liste: {sorted(unknown)}")
        if not args.quiet:
            print(f"  Regel: {declared['rule']}")
            print(f"  {len(chosen)} Maerkte aus {universe.name}\n")
        return chosen

    available = config.engine.symbols.available  # type: ignore[attr-defined]
    chosen = (
        list(available)
        if args.all
        else list(args.symbols or config.engine.symbols.active)  # type: ignore[attr-defined]
    )
    unknown = set(chosen) - set(available)
    if unknown:
        parser.error(f"unknown symbols: {sorted(unknown)}")
    return chosen


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
    parser.add_argument(
        "--funding",
        action="store_true",
        help="also pull funding rate history (needed for realistic holding costs)",
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--from-universe",
        action="store_true",
        help="die Liste aus data/universe_for_backfill.json holen (Datenerweiterung)",
    )
    args = parser.parse_args(argv)

    symbols = resolve_symbols(args, config=config, parser=parser)

    store = ParquetStore(config.engine.paths.parquet_dir)
    source = MarketData(
        venue_name=config.engine.exchange.name,
        testnet=False,
        rate_limit_ms=config.engine.exchange.rate_limit_ms,
    )
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

    if args.funding:
        funding_store = FundingStore(config.engine.paths.funding_dir)
        print("\nFunding rates:")
        for symbol in symbols:
            pulled = backfill_funding(source, funding_store, symbol, args.since, args.until)
            print(
                f"  {symbol}: +{len(pulled)} settlements, {len(funding_store.read(symbol))} stored"
            )

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
