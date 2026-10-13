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
from traidingbrain.data.validate import DataQualityError
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


def pull_markets(backfiller: Backfiller, symbols: list[str], args: argparse.Namespace,
                 progress: object) -> tuple[bool, list[str]]:
    """Jeden Markt holen, und einen Ausfall ueberleben.

    Gibt zurueck, ob der Speicher etwas Falsches haelt, und welche Maerkte
    nicht vollstaendig sind.
    """
    fatal = False
    # Ein Markt darf den Lauf nicht killen.
    #
    # Am 12.10.2026 starb ein Lauf ueber 71 Maerkte beim 32. an einem
    # DataQualityError: KNCUSDT H1 hat genau EINE Kerze, deren Schlusskurs
    # ueber ihrem Hoch liegt (2023-11-10 15:00 UTC, open 0.8131, high 0.8239,
    # low 0.8113, close 0.8251 -- der Schluss 0.145 % ueber dem Hoch, so von
    # der Boerse ausgeliefert, eine in 44.000 geprueften Stundenkerzen). Die
    # Pruefung hat recht und darf nicht abgeschwaecht werden -- aber 45
    # unberuehrte Maerkte dafuer liegenzulassen ist auch falsch. Dieselbe
    # Lehre wie beim Replay-Runner.
    #
    # Der Ausfall wird gesammelt, am Ende genannt, und der Exitcode bleibt
    # ungleich Null: "weitergelaufen" heisst nicht "in Ordnung".
    broken: list[str] = []
    for symbol in symbols:
        print(f"\n{symbol}")
        try:
            for result in backfiller.run_many(
                symbol, args.tfs, args.since, args.until, progress=progress
            ):
                print(f"\r  {result.summary()}")
                if result.report.is_fatal:
                    fatal = True
        except DataQualityError as problem:
            print(f"\r  ABGELEHNT: {problem}", flush=True)
            broken.append(f"{symbol}: {problem}")
        except Exception as problem:  # ein Markt faellt aus, der Lauf nicht
            print(f"\r  FEHLER {type(problem).__name__}: {problem}", flush=True)
            broken.append(f"{symbol}: {type(problem).__name__}: {problem}")
    return fatal, broken


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

    fatal, broken = pull_markets(backfiller, symbols, args, progress)

    if args.funding:
        # Auch hier je Markt, und das war gestern vergessen.
        #
        # Die OHLCV-Schleife darueber ueberlebt seit dem 12.10. einen
        # schlechten Markt. Diese Schleife nicht -- und sie hat den naechsten
        # Lauf gekillt, einen Block weiter unten:
        # fetch_funding_rate_history(BCHUSDT) failed after 4 attempts. Ein
        # Netzfehler auf einem von 71 Maerkten, und 43 unberuehrte blieben
        # liegen. Eine Lehre, die man eine Schleife weiter nicht anwendet,
        # ist nicht gelernt.
        #
        # UND DIE REIHENFOLGE KOSTET. Am 13.10.2026 sind in einem Lauf ueber
        # 71 Maerkte ALLE 71 Funding-Abrufe gescheitert, waehrend die
        # OHLCV-Abrufe desselben Laufs durchliefen. Kein Datenproblem: beide
        # Endpunkte antworteten Minuten spaeter direkt mit Daten. Es ist das
        # Anfragebudget -- diese Schleife laeuft NACH allen Kursabrufen, und
        # dann ist es aufgebraucht.
        #
        # Als eigener Lauf mit `--tfs W1`, also fast ohne Kursarbeit, gingen
        # 71 von 71 durch, null Ausfaelle, und damit liegen Funding-Daten
        # fuer alle 83 Maerkte. Wer viele Maerkte neu holt, holt Funding
        # besser in einem zweiten Lauf. Dass der Fehler nach 'vier Versuche
        # gescheitert' aussieht und nicht nach 'zu viele Anfragen', ist der
        # Grund, warum das hier steht.
        funding_store = FundingStore(config.engine.paths.funding_dir)
        print("\nFunding rates:")
        for symbol in symbols:
            try:
                pulled = backfill_funding(
                    source, funding_store, symbol, args.since, args.until
                )
            except Exception as problem:
                print(f"  {symbol}: Funding nicht abrufbar "
                      f"({type(problem).__name__}: {problem})", flush=True)
                broken.append(f"{symbol}: Funding {type(problem).__name__}")
                continue
            print(
                f"  {symbol}: +{len(pulled)} settlements, "
                f"{len(funding_store.read(symbol))} stored"
            )

    if args.verify:
        print("\nVerifying what is on disk:")
        for symbol in symbols:
            for timeframe in args.tfs:
                report = store.report(symbol, timeframe)
                print(f"  {report.summary()}")
                if report.is_fatal:
                    fatal = True

    if broken:
        print(f"\n{len(broken)} von {len(symbols)} Maerkten nicht vollstaendig:",
              file=sys.stderr)
        for line in broken:
            print(f"  {line}", file=sys.stderr)
        print("Der Rest liegt. Ein erneuter Lauf nimmt die fehlenden wieder auf.",
              file=sys.stderr)

    if fatal:
        print("\nFAILED: the store holds data that is wrong in a way we caused.", file=sys.stderr)
        return 1
    if broken:
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
