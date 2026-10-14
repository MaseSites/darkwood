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
from traidingbrain.journal.signals import SignalStore
from traidingbrain.journal.store import JournalStore
from traidingbrain.journal.version import run_signature
from traidingbrain.live.paper import (
    POLL_SECONDS,
    QUOTE,
    REFRESH_MINUTES,
    PaperTrader,
    state_path,
)
from traidingbrain.storage.singleton import AlreadyRunningError, SingleInstance

#: Damit das Alter eines Fehlschlags in Stunden statt in 300 Minuten steht.
MINUTES_PER_HOUR = 60.0
from traidingbrain.live.book import OpenBook
from traidingbrain.live.paperstate import PaperStateStore
from traidingbrain.risk.limits import KillSwitch, RiskLimits
from traidingbrain.sim.broker import _Ledger

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
    kill_switch = KillSwitch(config.engine.paths.data_dir / "KILL_SWITCH")
    limits = RiskLimits(config.risk.limits, kill_switch)
    shared = shared_ledger(config, states)
    funding_store = FundingStore(config.engine.paths.funding_dir)
    clock = SystemClock()
    # Derselbe Speicher und dieselbe Signatur wie im Replay, damit eine
    # Live-Zeile und eine Replay-Zeile dieselbe Frage beantworten koennen.
    signal_store = SignalStore(config.engine.paths.data_dir / "signals.sqlite")
    signature = run_signature(config)

    source: MarketData | None = None
    if not offline:
        # Mainnet, read-only. Candles and contract specifications are public;
        # only trading touches an account, and this program has no path to one.
        source = MarketData(
            venue_name=config.engine.exchange.name,
            testnet=False,
            rate_limit_ms=config.engine.exchange.rate_limit_ms,
        )

    # Das Buch des gepoolten Kontos. Hier gebaut, weil nur dieser Aufrufer die
    # Liste aller Haendler kennt -- jeder einzelne kennt nur sich selbst, und
    # genau daran konnte die Positionsgrenze nicht ausloesen.
    #
    # Nur bei geteilter Kasse. Unter `account` sind es zwoelf getrennte Konten,
    # und dann ist "wie viele Positionen haelt das Konto" eine Frage ueber
    # eines davon -- die ein Einplatz-Broker strukturell mit 0 oder 1
    # beantwortet, ohne Buch.
    book = OpenBook() if shared is not None else None

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
                # Damit das laufende System aufschreibt, was es erwaegt und
                # ablehnt -- bis zum 08.10.2026 gab es davon keine Zeile.
                signals=signal_store,
                run_signature=signature,
                # Die Kontogrenzen, die bis zum 13.10.2026 auf diesem Pfad
                # nicht existierten: Tagesverlust, Wochenverlust, Abkuehlung
                # nach einer Verlustserie, Zahl offener Positionen. Die
                # Konfiguration fuehrt alle vier, und `RiskLimits.check`
                # wurde hier nie aufgerufen.
                #
                # Der Kill-Switch kommt mit, und er ist der wichtigste Teil:
                # eine Datei, die ein anderer Prozess anlegen kann und die
                # jede weitere Eroeffnung stoppt, ohne den Haendler zu toeten.
                limits=limits,
                ledger=shared,
                # Die vierte Grenze, die bis heute auf diesem Pfad nicht
                # ausloesen konnte: die Zahl gleichzeitig offener Positionen.
                book=book,
            )
        )
    if book is not None:
        for trader in traders:
            book.attach(trader.symbol, trader.broker, trader.spec)
        print(f"  Positionsgrenze portfolioweit: Deckel "
              f"{config.risk.limits.max_open_positions}, "
              f"{len(book)} Symbole im Buch", flush=True)
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


def shared_ledger(config: object, states: PaperStateStore) -> _Ledger | None:
    """Die gemeinsame Kasse, oder None bei Groessenbemessung je Konto.

    **Was der Schalter entscheidet.** Unter `account` fuehrt jedes Symbol
    seine eigenen 1.000 USDT, und 1 % Risiko je Trade sind 0,083 % des
    Gesamtkapitals. Unter `portfolio` ziehen alle zwoelf aus einem Topf, so
    wie ein echtes Boersenkonto, das mehrere Maerkte haelt -- 1 % sind dann
    1 %.

    **Die Umschaltung ist der heikle Teil.** Beim ersten Lauf unter
    `portfolio` gibt es noch keine Portfoliozeile, und die zwoelf
    Kontozeilen halten je ein Zwoelftel. Dann ist der Startwert ihre SUMME.
    Danach steht der geteilte Stand in seiner eigenen Zeile und wird
    gelesen. Ohne diese Trennung waere dieselbe Spalte einmal "ein Zwoelftel"
    und einmal "das Ganze" -- ein Faktor-12-Fehler, der wie eine Zahl
    aussieht.

    Gibt None zurueck, wenn die Konfiguration `account` sagt. Dann baut jeder
    Broker seine eigene Kasse, und nichts aendert sich gegenueber vorher.
    """
    if config.risk.sizing.basis != "portfolio":  # type: ignore[attr-defined]
        return None
    saved = states.load_portfolio()
    if saved is None:
        start = states.equity_sum() or config.engine.simulation.initial_equity  # type: ignore[attr-defined]
        print(f"  Groessenbemessung portfolio: Kasse aus der Summe der Konten, "
              f"{start:,.2f} USDT", flush=True)
        return _Ledger(equity=start, peak_equity=start)
    equity, peak = saved
    print(f"  Groessenbemessung portfolio: Kasse wiederhergestellt, "
          f"{equity:,.2f} USDT (Hoechststand {peak:,.2f})", flush=True)
    return _Ledger(equity=equity, peak_equity=peak)


def account_line(traders: list[PaperTrader]) -> str:
    """Der Kontostand -- einmal, nicht je Markt.

    **Warum eine eigene Zeile.** Vorher trug jede Marktzeile ein
    "Kontostand 12.075,56 CHF", zwoelfmal untereinander. Bei zwoelf getrennten
    Konten war das die Wahrheit; bei einer geteilten Kasse sieht es aus, als
    haette jeder Markt so viel Geld, und genau diese Verwechslung hat das
    Dashboard auf 144.906,72 gebracht.

    Es gibt ein Konto. Also steht es einmal da, mit dem, was gebunden ist und
    was frei ist -- die Zahl, die entscheidet, ob der naechste Trade ueberhaupt
    passt.
    """
    if not traders:
        return ""
    ledger = traders[0].broker.ledger
    shared = not traders[0].broker.owns_ledger
    held = sum(1 for trader in traders if trader.broker.position is not None)
    if not shared:
        return (
            f"Konten: {len(traders)} getrennte à {ledger.equity:,.2f} {QUOTE} "
            f"(Groessenbemessung je Konto)"
        )
    return (
        f"KONTO  {ledger.equity:,.2f} {QUOTE}  |  "
        f"gebunden {ledger.reserved:,.2f}  |  frei {ledger.available:,.2f}  |  "
        f"{held} von {len(traders)} Maerkten offen"
    )


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


#: Ab dieser Fehlerquote im gleitenden Fenster meldet sich der Lauf laut.
#: Nicht bei einzelnen Fehlschlägen: ein einzelner ist normal, das Netz
#: wackelt. Was gemeldet gehört, ist ein ZUSTAND.
FAILURE_ALARM = 0.20

#: Breite des gleitenden Fensters, in Zyklen. Zwanzig Minuten -- lang genug,
#: dass ein einzelner Ausfall nicht alarmiert, kurz genug, dass ein Zustand
#: nicht zwei Stunden unbemerkt bleibt.
FAILURE_WINDOW = 20


class FailureWatch:
    """Meldet eine erhöhte Fehlerquote, solange sie anhält.

    **Anlass, gemessen.** Am 09.10.2026 lief der Papierhandel rund zweieinhalb
    Stunden mit einer Fehlerquote von etwa 47 %: alle zwölf Märkte scheiterten
    wiederholt an `fetch_ohlcv(..., W1)`, dem ersten Abruf jedes Zyklus, mit
    einem ccxt-Timeout. Die Zähler standen danach bei 5.043 Fehlschlägen auf
    46.096 Zyklen -- und **nichts hat das gemeldet**. Gefunden wurde es, weil
    jemand die Datenbank abgefragt hat.

    Verloren ging dabei nichts: ein Fehlschlag wird gefangen statt geworfen,
    und der Broker holt bis zu `REFRESH_MINUTES` Minuten nach, also werden
    Ausstiege höchstens später aufgelöst, nicht übersehen. Aber ein Zustand,
    den man nur durch Nachsehen findet, ist genau der Fall, der dieses Projekt
    schon einmal zwölf Stunden Aufnahme gekostet hat.

    Gemeldet wird der Übergang in beide Richtungen -- auch die Entwarnung.
    Eine Alarmmeldung ohne Entwarnung lässt den Leser im Dunkeln darüber, ob
    der Zustand noch besteht.
    """

    def __init__(self, traders: list[PaperTrader]) -> None:
        self._traders = traders
        self._last = self._totals()
        self._alarming = False

    def _totals(self) -> tuple[int, int]:
        # `stats.tally`, nicht `tally`. Hier lag ein Fehler, der den
        # Papierhandel am 09.10.2026 um 13:37 UTC abgestuerzt hat: meine
        # Test-Vorrichtung trug den Zaehler oben, der echte PaperTrader traegt
        # ihn unter `stats`. Der Test war gruen und der Code falsch -- eine
        # Vorrichtung, die nicht die Form des Echten hat, prueft nichts.
        cycles = sum(t.stats.tally.cycles for t in self._traders)
        failures = sum(t.stats.tally.failures for t in self._traders)
        return cycles, failures

    def check(self) -> None:
        cycles, failures = self._totals()
        spent = cycles - self._last[0]
        if spent < FAILURE_WINDOW * len(self._traders):
            return
        broke = failures - self._last[1]
        share = broke / spent if spent else 0.0
        self._last = (cycles, failures)

        if share >= FAILURE_ALARM and not self._alarming:
            self._alarming = True
            print(
                f"  ! FEHLERQUOTE {100 * share:.0f}% ueber die letzten {spent:,} "
                f"Zyklen ({broke:,} Fehlschlaege).\n"
                f"    Ausstiege werden spaeter aufgeloest, nicht uebersehen -- "
                f"der Broker holt bis zu {REFRESH_MINUTES} Minuten nach.",
                file=sys.stderr,
                flush=True,
            )
        elif share < FAILURE_ALARM and self._alarming:
            self._alarming = False
            print(
                f"  Fehlerquote wieder normal: {100 * share:.0f}% ueber "
                f"{spent:,} Zyklen.",
                file=sys.stderr,
                flush=True,
            )


def run(traders: list[PaperTrader], source: MarketData | None, *, cycles: int | None) -> int:
    symbols = [trader.symbol for trader in traders]
    print(f"Papertrading läuft: {', '.join(symbols)}")
    print(
        f"Kein Konto, keine Börse, kein Geld. Takt {POLL_SECONDS}s, "
        f"Entscheidungen auf {traders[0].config.engine.timeframes.signal.value}-Schluss.\n"
    )
    print(account_line(traders))
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
    watch = FailureWatch(traders)
    try:
        while cycles is None or done < cycles:
            if done % 20 == 0:
                top_up_funding(source, traders)
            watch.check()
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
    print(account_line(traders))
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

    print("Papertrading-Konto\n")
    print(account_line(traders))
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
            # Das ALTER daneben, nicht nur der Zeitstempel. Der Zaehler ist
            # kumulativ und ueberlebt jeden Neustart, also sieht ein
            # historisches Problem fuer immer wie ein laufendes aus. Am
            # 07.10.2026 standen hier 58 Fehlschlaege, und erst der Vergleich
            # des Zeitstempels mit der Uhr zeigte, dass der letzte 68 Minuten
            # alt war -- die Ursache (zwei gleichzeitig laufende Haendler,
            # also doppelte Anfragerate) war bereits behoben. Eine Zahl, fuer
            # deren Deutung man rechnen muss, wird falsch gedeutet.
            age = ""
            if tally.last_failure_ts:
                minutes = (int(time.time() * 1000) - tally.last_failure_ts) / 60_000
                age = (
                    f", vor {minutes / MINUTES_PER_HOUR:.1f}h"
                    if minutes >= MINUTES_PER_HOUR
                    else f", vor {minutes:.0f} min"
                )
            print(
                f"      ! {tally.failures} gescheiterte Zyklen insgesamt, "
                f"zuletzt {when} UTC{age}: {reason}"
            )

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
        # Die Marktzeilen UND die Kasse.
        #
        # Bis zum 14.10.2026 loeschte `--reset` nur die Zeilen in `accounts`
        # und liess die `portfolio`-Zeile stehen. Das sah nach einem
        # Zuruecksetzen aus und war keines: die Marktzeilen waren weg, das
        # Geld stand noch da, und der naechste Start las es wieder ein. Wer
        # "von vorn" sagte, bekam alte 12.075,56 mit leeren Zaehlern -- die
        # schlechteste der drei moeglichen Lagen, weil sie wie ein frischer
        # Anfang aussieht.
        states = PaperStateStore(state_path(config))
        full = set(symbols) == set(config.engine.symbols.active)
        for symbol in symbols:
            states.forget(symbol)
        print(f"Arbeitsstand gelöscht: {', '.join(symbols)}")
        if full and config.risk.sizing.basis == "portfolio":
            start = config.engine.simulation.initial_equity * len(symbols)
            states.save_portfolio(start, start)
            print(f"Konto zurückgesetzt auf {start:,.2f} {QUOTE}")
        elif config.risk.sizing.basis == "portfolio":
            equity, _peak = states.load_portfolio() or (0.0, 0.0)
            print(
                f"Konto NICHT angefasst ({equity:,.2f} {QUOTE}) -- es gehört allen "
                f"Märkten, und zurückgesetzt wurden nur {len(symbols)} davon. "
                "Für das ganze Konto: ohne --symbol aufrufen."
            )
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

    # Ein Händler je Datenverzeichnis, vom Betriebssystem erzwungen.
    #
    # Am 07.10.2026 liefen zwei davon gleichzeitig. Sie verdoppelten die
    # Anfragerate gegen dieselbe IP, liefen ins Rate-Limit und erzeugten 58
    # fehlgeschlagene Zyklen -- und keiner von beiden merkte etwas, weil ein
    # fehlgeschlagener Zyklus für sich normal aussieht. Die Sperre sitzt hier
    # und nicht am Anfang von `main`, damit `--status`, `--reset` und
    # `--close-out` neben einem laufenden Händler weiter benutzbar bleiben.
    try:
        with SingleInstance("papertrade", directory=config.engine.paths.data_dir):
            return run(traders, source, cycles=args.cycles)
    except AlreadyRunningError as refusal:
        print(f"\nStart abgelehnt: {refusal}", file=sys.stderr, flush=True)
        print(
            "  Ein zweiter Händler würde die Anfragerate verdoppeln und beide\n"
            "  ins Rate-Limit treiben. Beende zuerst den laufenden.",
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
