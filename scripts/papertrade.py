"""Let the system trade itself forward, with fake money.

    python scripts/papertrade.py                   # run until stopped
    python scripts/papertrade.py --cycles 4        # a few passes, then stop
    python scripts/papertrade.py --status          # what the accounts look like
    python scripts/papertrade.py --close-out       # close everything open, journal it
    python scripts/papertrade.py --reset           # forget the accounts and start over

This is the one thing in the project that produces evidence replay cannot. Every
number measured so far came from running the engine over bars that had already
happened; the decisions inside that are sound -- the no-lookahead tests cover
them -- but the *choice of period* was made by somebody who already knew how it
went, and no test can cover that. Here the reason is written to disk and the
outcome arrives afterwards. That is the whole point, and it is why these trades
are stored as `live` and never averaged with the replayed ones.

No exchange, no account, no key, no order. Prices come from the venue's public
candle endpoint, which needs no credentials; nothing in this path can reach a
trading endpoint, and the confirmation rule that governs real orders is
untouched.

It is slow on purpose. A four-hour setup rests its stop on four-hour structure,
so the trade is roughly four times wider than an hourly one and runs for days.
Expect a handful of trades a day across four symbols, not a screen full.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.clock import SystemClock
from traidingbrain.config.settings import load_config
from traidingbrain.data.exchange import MarketData
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.record import JournalEntry, Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.paper import POLL_SECONDS, QUOTE, PaperTrader, state_path
from traidingbrain.live.paperstate import PaperStateStore

JOURNAL_NAME = "journal.sqlite"

#: How much funding history to top up each time, in days.
#:
#: Funding settles every eight hours and is charged against anything held
#: across one. Topping it up is not optional bookkeeping: a long held two days
#: in a positive-funding market pays for it, and a run that never fetched the
#: rates would report a profit the account did not make.
FUNDING_DAYS = 7
DAY_MS = 86_400_000

#: Spare bars on top of the longest indicator window.
#:
#: The warm-up itself is derived from the configuration rather than guessed --
#: see `bars_needed`. The margin exists because the regime and structure windows
#: sit on top of the indicator ones, and because a frame that only just reaches
#: the threshold reports a reading from its very first usable bar.
WARMUP_MARGIN = 40


def clock_text(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%d.%m %H:%M")


def build_traders(
    symbols: list[str], *, offline: bool
) -> tuple[list[PaperTrader], MarketData | None]:
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    states = PaperStateStore(state_path(config))
    journal = JournalStore(config.engine.paths.data_dir / JOURNAL_NAME)
    funding_store = FundingStore(config.engine.paths.funding_dir)
    clock = SystemClock()

    source: MarketData | None = None
    if not offline:
        # Mainnet, read-only. Candles and contract specifications are public;
        # only trading touches an account, and this program has no path to one.
        source = MarketData(
            venue_name=config.engine.exchange.name,
            testnet=False,
            rate_limit_ms=config.engine.exchange.rate_limit_ms,
        )

    traders: list[PaperTrader] = []
    for symbol in symbols:
        spec = _spec(source, symbol)
        traders.append(
            PaperTrader(
                symbol,
                config,
                source=source,
                store=store,
                state=states,
                journal=journal,
                spec=spec,
                clock=clock,
                funding=funding_store.read(symbol),
            )
        )
    return traders, source


def _spec(source: MarketData | None, symbol: str) -> SymbolSpec:
    """The venue's own contract rules, or the documented fallback.

    Fetched rather than assumed, because the tick size and the minimum notional
    decide whether a position is placeable at all, and a wrong minimum silently
    refuses every trade in the cheapest symbol.
    """
    if source is None:
        return SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
    try:
        return source.fetch_symbol_spec(symbol)
    except Exception as exc:
        print(f"  {symbol}: Spezifikation nicht abrufbar ({exc}), Standardwerte", file=sys.stderr)
        return SymbolSpec(symbol=symbol, **DEFAULT_SPEC)


def top_up_funding(source: MarketData | None, traders: list[PaperTrader]) -> None:
    """Fetch the funding rates that settled since the last run, and hand them over.

    Writing them to disk was only half the job, and the missing half was
    silent. Each broker took its schedule once, in its constructor, so every
    settlement falling due after the process started was charged against the
    end of that list -- charged as zero. A position held across two days of
    positive funding paid nothing, and the forward journal recorded a profit
    the account did not make. This function fetched the rates faithfully every
    twenty cycles and nothing ever read them.

    The whole series is read back from the store rather than only the rates
    that just arrived: the broker wants a complete schedule, and it places its
    own cursor from the account clock. Handed over even when the fetch brought
    nothing, because the list the constructor was given may already have been
    stale.
    """
    if source is None:
        return
    config = load_config()
    store = FundingStore(config.engine.paths.funding_dir)
    now = SystemClock().now_ms()
    for trader in traders:
        symbol = trader.symbol
        last = store.last_ts(symbol)
        since = (last + 1) if last else now - FUNDING_DAYS * DAY_MS
        try:
            rates = source.fetch_funding(symbol, since)
        except Exception as exc:
            print(f"  {symbol}: Funding nicht abrufbar ({exc})", file=sys.stderr)
            rates = []
        if rates:
            store.write(symbol, rates)
        trader.refresh_funding(store.read(symbol))


def bars_needed(config: object) -> int:
    """How many bars a frame needs before every indicator carries a value.

    Read off the configuration instead of guessed. The first version of this
    check used a flat three hundred bars per frame and refused to start,
    because the weekly frame has 259 candles -- five years, which is every week
    these contracts have existed. A threshold that cannot be met by all the
    data there is, is a threshold about the wrong thing.
    """
    indicators = config.engine.indicators  # type: ignore[attr-defined]
    regime = config.engine.regime  # type: ignore[attr-defined]
    return (
        max(
            indicators.ema_slow,
            indicators.ema_fast,
            indicators.atr_period,
            indicators.rsi_period,
            indicators.bb.period,
            indicators.volume_ma,
            indicators.macd.slow + indicators.macd.signal,
            regime.volatility_window,
            regime.trend_window,
        )
        + WARMUP_MARGIN
    )


def report_history(traders: list[PaperTrader]) -> bool:
    """Say how much history each frame has, and refuse to start without enough.

    The score needs every indicator warm on every context frame before it says
    anything, and a setup that fires where the score is silent is not traded --
    the reason has to exist before the order does. A fresh install therefore
    runs, proposes, declines, and looks broken. This says so instead.
    """
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    need = bars_needed(config)
    ready = True
    print(f"Vorhandene Historie (mindestens {need} Kerzen pro Zeitebene):")
    for trader in traders:
        counts = []
        thin = []
        for timeframe in config.engine.timeframes.context:
            frame = store.read(trader.symbol, timeframe)
            counts.append(f"{timeframe.value} {len(frame)}")
            if len(frame) < need:
                thin.append(timeframe.value)
        mark = "  " if not thin else "! "
        print(f"{mark}{trader.symbol:9s} {', '.join(counts)}")
        if thin:
            ready = False
            print(f"      zu wenig auf {', '.join(thin)} -- erst backfill.py laufen lassen")
    return ready


def announce(entry: JournalEntry) -> None:
    """One line per closed trade, with the sentence that explains it."""
    verdict = entry.post_mortem.verdict
    print(
        f"\n  [{clock_text(entry.closed_ts)}] {entry.symbol} "
        f"{entry.reason.setup_key} auf {entry.reason.setup_timeframe} "
        f"{entry.reason.side}: {entry.r_multiple:+.2f} R "
        f"({entry.exit_reason.value}, {entry.post_mortem.bars_held} Kerzen)"
    )
    # Womit der Trade eingegangen wurde, zum EINSTIEGSPREIS. Beim
    # Ausstiegspreis gerechnet waere es die Groesse, mit der er verlassen
    # wurde -- bei einem Gewinner eine groessere Zahl und eine andere Frage.
    print(
        f"      eingesetzt {entry.notional:,.2f} {QUOTE} @ {entry.entry_price:,.4f}  |  "
        f"Hebel {entry.leverage:g}x  |  Margin {entry.margin:,.2f} {QUOTE}  |  "
        f"Risiko {entry.risk_amount:,.2f} {QUOTE}  ->  "
        f"netto {entry.net_pnl:+,.2f} {QUOTE}"
    )
    # flush, weil der Haendler als Dauerprozess mit umgeleiteter Ausgabe
    # laeuft. Diese Meldung existierte vorher schon und war aus genau diesem
    # Grund nie zu sehen.
    print(f"      {verdict}", flush=True)


def tend_open_positions(traders: list[PaperTrader]) -> None:
    """Settle whatever is open, even when the run is about to give up.

    Section 14 of the masterplan says it outright: missing or stale data stops
    new entries, never the management of a position that is already open. The
    thin-history exit below used to return before a single settle() ran, which
    left a live stop unwatched for as long as the data stayed thin -- and there
    were open positions when this was found.
    """
    for trader in traders:
        if trader.broker.is_flat:
            continue
        for entry in trader.settle():
            announce(entry)
        print(f"  {trader.status()}")


def run(traders: list[PaperTrader], source: MarketData | None, *, cycles: int | None) -> int:
    symbols = [trader.symbol for trader in traders]
    print(f"Papertrading läuft: {', '.join(symbols)}")
    print(
        f"Kein Konto, keine Börse, kein Geld. Takt {POLL_SECONDS}s, "
        f"Entscheidungen auf {traders[0].config.engine.timeframes.signal.value}-Schluss.\n"
    )
    for trader in traders:
        print(f"  {trader.status()}")

    if not report_history(traders):
        print(
            "\nKeine neuen Einstiege: ohne Historie kann die Bewertung nicht gelesen\n"
            "werden, und ohne Bewertung wird kein Trade eröffnet.",
            file=sys.stderr,
        )
        tend_open_positions(traders)
        return 1

    done = 0
    try:
        while cycles is None or done < cycles:
            if done % 20 == 0:
                top_up_funding(source, traders)
            # Two passes, and the order is the point. Settling is what an
            # open position depends on and costs a fetch; deciding costs ten
            # to fifteen seconds of analysis per market. Interleaved, one
            # market's analysis delays eleven other markets' exits.
            for trader in traders:
                for entry in trader.settle():
                    announce(entry)
            for trader in traders:
                trader.decide()
            done += 1
            if cycles is None or done < cycles:
                time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nangehalten. Offene Trades bleiben offen und laufen beim nächsten Start weiter.")

    print("\n" + "-" * 70)
    for trader in traders:
        print(f"  {trader.status()}")
        print(f"      {trader.stats.summary()}")
        for error in trader.stats.errors[-3:]:
            print(f"      ! {error}")
    return 0


def show_status(traders: list[PaperTrader]) -> int:
    config = load_config()
    journal = JournalStore(config.engine.paths.data_dir / JOURNAL_NAME)
    live = journal.all(source=Source.LIVE)

    print("Papertrading-Konten\n")
    for trader in traders:
        tally = trader.state.tally
        print(f"  {trader.status()}")
        print(f"      letzte Minute verbucht: {clock_text(trader.state.last_minute_ts)} UTC")
        # The count alone cannot be acted on, and it is the part that survives a
        # restart. Printing the stored reason next to it is what makes "one
        # failure per account" answerable instead of merely alarming.
        if tally.failures:
            when = clock_text(tally.last_failure_ts) if tally.last_failure_ts else "unbekannt"
            reason = tally.last_failure or "kein Text gespeichert (vor dieser Version)"
            print(f"      ! {tally.failures} gescheiterte Zyklen, zuletzt {when} UTC: {reason}")

    print(f"\nVorwärts-Trades im Journal: {len(live)}")
    if live:
        rs = [entry.r_multiple for entry in live]
        wins = sum(1 for entry in live if entry.won)
        print(
            f"  Mittel {sum(rs) / len(rs):+.3f} R, Treffer {100 * wins / len(live):.0f}%, "
            f"von {clock_text(live[0].opened_ts)} bis {clock_text(live[-1].closed_ts)}"
        )
        print(f"\n  Die letzten fünf — Einsatz, Hebel und Ergebnis je Trade ({QUOTE}):")
        print(
            f"    {'wann':12s} {'Markt':9s} {'Setup':6s} {'Einsatz':>10s} {'Hebel':>6s} "
            f"{'Margin':>9s} {'Risiko':>8s} {'netto':>9s} {'R':>7s}  Grund"
        )
        for entry in live[-5:]:
            print(
                f"    {clock_text(entry.closed_ts):12s} {entry.symbol:9s} "
                f"{entry.reason.setup_key} {entry.reason.setup_timeframe:3s} "
                f"{entry.notional:>10,.2f} {entry.leverage:>5g}x "
                f"{entry.margin:>9,.2f} {entry.risk_amount:>8,.2f} "
                f"{entry.net_pnl:>+9,.2f} {entry.r_multiple:>+7.2f}  "
                f"{entry.exit_reason.value}"
            )
        # Die Summe daneben, weil fuenf Einzelbetraege nicht sagen, wie viel
        # Kapital das System insgesamt bewegt hat.
        total_notional = sum(e.notional for e in live)
        total_risk = sum(e.risk_amount for e in live)
        print(
            f"\n    Über alle {len(live)} Vorwärts-Trades: {total_notional:,.2f} {QUOTE} "
            f"Notional bewegt, {total_risk:,.2f} {QUOTE} insgesamt riskiert, "
            f"Hebel {min(e.leverage for e in live):g}x bis "
            f"{max(e.leverage for e in live):g}x"
        )
    else:
        print("  noch keiner. Die ersten brauchen Stunden bis Tage -- das ist die Idee.")
    return 0


def main() -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbol", action="append", help="repeatable; default: all active")
    parser.add_argument("--cycles", type=int, default=None, help="stop after this many passes")
    parser.add_argument("--status", action="store_true", help="read the accounts, change nothing")
    parser.add_argument("--close-out", action="store_true", help="close everything open now")
    parser.add_argument("--reset", action="store_true", help="forget the accounts and start over")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="no venue; works off whatever bars are already stored",
    )
    args = parser.parse_args()

    symbols = args.symbol or list(config.engine.symbols.active)

    if args.reset:
        states = PaperStateStore(state_path(config))
        for symbol in symbols:
            states.forget(symbol)
        print(f"Konten zurückgesetzt: {', '.join(symbols)}")
        print("Journal-Einträge bleiben -- was passiert ist, ist passiert.")
        return 0

    traders, source = build_traders(symbols, offline=args.offline or args.status)

    if args.status:
        return show_status(traders)

    if args.close_out:
        for trader in traders:
            entry = trader.close_out()
            if entry is not None:
                announce(entry)
            else:
                print(f"  {trader.symbol}: nichts offen")
        return 0

    return run(traders, source, cycles=args.cycles)


if __name__ == "__main__":
    raise SystemExit(main())
