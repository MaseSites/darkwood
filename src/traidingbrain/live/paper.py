"""Forward paper trading: the system takes its own trades, with no money.

Every number this project has produced so far came from replay -- the engine run
over bars that had already happened. Replay is honest about its own decisions
(the no-lookahead tests cover those) but not about its *selection*: the stretch
of history was chosen by somebody who knows how it went. Nothing can test that
away. The only cure is to decide first and find out afterwards, which is what
this module does.

**The record is written before the outcome exists.** When a setup fires, the
order and the whole case for it -- score, families, rating, which chart it came
from -- are persisted in the same breath. The outcome arrives minutes or days
later and is appended. There is no point at which the reasoning could have been
informed by the result, because the reasoning was on disk first. That is the
entire difference between this and `scripts/paper.py --replay`, and it is why
these trades are stored as `Source.LIVE` and never averaged with the others.

**The exits are the simulator's.** `SimBroker` resolves stop, target,
liquidation, fees, funding and gaps, minute by minute, exactly as in the
backtests. A forward trader with its own fill logic would be a second answer to
the same question, differing by about as much as the effects being measured.

**It still cannot trade.** It does reach the venue -- for candles and contract
rules, both public and needing no credentials. What it never touches is an
account: nothing here imports `execution`, builds an order, or holds a key, so
there is no code path from this module to a trading endpoint. The rule that a
real order needs a held human confirmation is untouched by it.

**Each symbol keeps its own account.** The backtests size every symbol against
the same starting equity, so a forward run that pooled them would not be
comparable with anything already measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from traidingbrain.analysis.pipeline import MultiFrameAnalysis, decision_time_ms
from traidingbrain.config.settings import AppConfig
from traidingbrain.data.frames import bars_to_frame
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import ExitReason, Timeframe
from traidingbrain.domain.market import FundingRate, SymbolSpec
from traidingbrain.domain.protocols import Clock, DataSource
from traidingbrain.journal.build import reason_at
from traidingbrain.journal.postmortem import examine
from traidingbrain.journal.record import JournalEntry, Source, TradeReason
from traidingbrain.journal.signals import Action, SignalRecord, SignalStore
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.paperstate import PaperState, PaperStateStore, Tally
from traidingbrain.sim.broker import Fill, OpenPosition, SimBroker
from traidingbrain.sim.engine import AnalysisStrategy
from traidingbrain.sim.plan import Assessment, assess, setup_label
from traidingbrain.strategies.guide import GuidePool

#: Bars refetched per timeframe each cycle.
#:
#: Enough to repair a gap from a short outage without re-downloading history.
#: Larger for minutes than the hourly loop needs, because the minutes are what
#: the exits are resolved against: a cycle that missed them would resolve the
#: trade against the next minute it did see, and a stop that was hit two minutes
#: ago has to be found when the process comes back.
REFRESH_BARS = 24
REFRESH_MINUTES = 240

#: Die Waehrung, in der Notional, Margin und Risiko wirklich anfallen.
#:
#: Und hier liegt ein Defekt, der hingeschrieben gehoert statt mitgeschleppt
#: zu werden: `status()` weiter unten meldet den Kontostand in **CHF**, und
#: `config/risk.yaml` rechnet in CHF. Die Preise sind aber durchgaengig
#: USDT-Quotes -- `data/venue.py` laesst ueberhaupt nur USDT-quotierte
#: Maerkte zu -- und eine Umrechnung existiert nirgends im Code. Geprueft am
#: 07.10.2026: kein FX-Kurs, kein Konversionsschritt, nichts.
#:
#: Das System setzt also stillschweigend 1 USDT = 1 CHF. Bei einem Kurs um
#: 0,8 sind "12'000 CHF" real etwa 9'600 CHF. Fuer eine ZIELQUOTE (1,25x)
#: aendert das nichts, weil sich der Faktor herauskuerzt. Fuer jeden
#: absoluten Betrag aendert es ein Fuenftel.
#:
#: Die Betraege hier tragen darum das Zeichen, das nachweisbar stimmt. Das
#: Konto umzubenennen ist eine Entscheidung des Nutzers und nicht die eines
#: Anzeige-Patches.
QUOTE = "USDT"

#: Most bars per context frame the analysis is built over.
#:
#: The archive holds four years -- 175,000 fifteen-minute candles for one symbol
#: -- and building the full analysis over that takes minutes, per symbol, every
#: hour. Measured on this machine, BTCUSDT, four context frames: 146 seconds to
#: build the analysis and 12.8 to read one bar's score over the whole archive,
#: against 8.5 and 1.2 over the last five thousand bars of each frame. Fifteen
#: times, and the difference between a loop that keeps up and one that does not.
#:
#: Five thousand is twelve times the longest lookback anything in the analysis
#: declares (trendlines drop a line after 400 bars, which is the largest), so
#: every structure, level and indicator sees its whole window. What it does cut
#: off is an unmitigated zone older than that -- fifty-two days on the
#: fifteen-minute frame, seven months on the hourly. The backtests read the
#: whole archive, so a forward reading and a replayed one are not bit-identical
#: for a zone that old, and that is the price of running at all.
HISTORY_BARS = 5000

#: What a forward trade's journal id starts with.
#:
#: The journal keys on the proposal id, which is `{symbol}-{decision close}`,
#: and replaces a row that already has that id -- which is right, because
#: re-running a replay over a period should correct it rather than double it.
#: But a replay of this week would then have exactly the ids of this week's
#: forward trades and would overwrite them. The forward record is the only
#: evidence here that replay cannot produce, and it would be destroyed by a
#: routine command. The prefix makes the collision impossible and says in the
#: id itself which kind of trade it is.
LIVE_PREFIX = "live-"

#: Pages of minutes fetched to close a gap, at a thousand bars each.
#:
#: A laptop closed overnight comes back sixteen hours behind, which is one page.
#: Four covers a long weekend; beyond that the trade is stale enough that
#: resolving it minute by minute is not the interesting part.
MAX_CATCHUP_PAGES = 4

#: Minutes per catch-up page. The venue's own page size.
CATCHUP_PAGE = 1000

#: How often a cycle looks for new bars, in seconds.
#:
#: Well inside a minute. The exits are resolved on closed minute bars, so this
#: is the resolution of the whole thing: a stop touched at 14:03:20 is found at
#: 14:04 at the earliest, whatever this is set to.
POLL_SECONDS = 30

#: How often one signal bar may throw before the loop gives up on it.
#:
#: Three, because the failures this guards against are transient -- a
#: timed-out fetch, a frame that arrived short -- and three cycles is a
#: minute and a half at the poll interval. Retrying for ever would let one
#: unreadable bar stop an account from deciding again; not retrying at all
#: loses the signal, which at roughly two signals a day is expensive.
MAX_DECISION_ATTEMPTS = 3


@dataclass
class PaperStats:
    """What a run did, for a status line worth reading.

    The counters themselves live in `Tally` and are written to disk every
    cycle, because the case they exist for is a trader that has run for three
    days and traded nothing: "still flat" cannot say whether no setup fired,
    whether the risk layer refused every one, or whether the score was never
    ready. Held only in memory they were invisible for exactly as long as they
    mattered.

    The errors are not persisted. They are about this process -- a failed
    fetch, a bad cycle -- and carrying yesterday's forward would make the list
    grow for ever and describe nothing.
    """

    tally: Tally = field(default_factory=Tally)
    errors: list[str] = field(default_factory=list)

    @property
    def cycles(self) -> int:
        return self.tally.cycles

    def summary(self) -> str:
        t = self.tally
        return (
            f"Zyklen {t.cycles}, Kerzen {t.bars_seen}, "
            f"Vorschläge {t.proposed}, abgelehnt {t.refused_by_risk}, "
            f"ohne Bewertung {t.not_ready}, eröffnet {t.opened}, "
            f"geschlossen {t.closed}, verfallen {t.expired}"
            + (f", {len(self.errors)} Fehler" if self.errors else "")
        )


class PaperTrader:
    """One symbol, one paper account, trading itself forward.

    The loop is deliberately the same shape as the backtest's: resolve what is
    open against the minutes that have arrived, then -- only when flat -- ask
    the strategy about the newest closed signal bar. Asking while a position is
    open would propose trades the account cannot take and record refusals that
    say nothing about the rules.
    """

    def __init__(
        self,
        symbol: str,
        config: AppConfig,
        *,
        source: DataSource | None,
        store: ParquetStore,
        state: PaperStateStore,
        journal: JournalStore,
        spec: SymbolSpec,
        clock: Clock,
        funding: list[FundingRate] | None = None,
        strategy: AnalysisStrategy | None = None,
        signals: SignalStore | None = None,
        run_signature: str = "",
    ) -> None:
        self.symbol = symbol
        self.config = config
        self.source = source
        self.store = store
        self.state_store = state
        self.journal = journal
        self.spec = spec
        self.clock = clock
        self.strategy = strategy or GuidePool.for_config(config)
        # Optional, damit jeder bestehende Aufruf unveraendert weiterlaeuft.
        # Ohne Speicher wird nichts aufgezeichnet und nichts bricht.
        self.signals = signals
        self.run_signature = run_signature
        self.stats = PaperStats()

        self.broker = SimBroker(spec, config.engine.simulation, funding)
        self.state = state.load(symbol) or PaperState(
            symbol=symbol, equity=config.engine.simulation.initial_equity
        )
        self.state.restore_into(self.broker)
        # The counters carry over, so a restart continues the tally rather than
        # resetting it. An account that has been flat for three days should say
        # three days, not "since I was last started".
        self.stats.tally = self.state.tally
        self._reason: TradeReason | None = self.state.reason
        #: (bar, attempts) for the signal bar currently being retried.
        #:
        #: In memory on purpose. A restart retrying a bar once more is the
        #: right behaviour -- the thing that failed was usually the fetch --
        #: and persisting the count would make a restart the way to get past
        #: a genuinely unreadable bar, which is worse.
        self._attempts: tuple[int, int] = (0, 0)
        #: Newest closed signal bar seen by the last refresh. Carried between
        #: the two halves of a cycle so deciding does not have to re-fetch.
        self._newest = 0

    # -- data --------------------------------------------------------------- #

    def refresh_data(self) -> tuple[int, pd.DataFrame]:
        """Pull recent closed bars for every frame.

        Returns the newest signal bar and the minute bars just fetched. The
        minutes are handed back rather than re-read from the archive because
        this runs twice a minute and the archive holds millions of them: a
        cycle that reloaded the whole M1 history to settle four hours of it
        would spend all its time in parquet.

        The adapter drops the forming candle, so only finished bars land here --
        the same guarantee the backtest had, enforced at the boundary once.

        No source is a legitimate state, not a half-built one: `--status` reads
        the accounts and must not touch the network to do it.
        """
        if self.source is None:
            return 0, bars_to_frame([])
        newest = 0
        minutes = bars_to_frame([])
        for timeframe in self.config.engine.timeframes.all_needed:
            is_execution = timeframe is self.config.engine.timeframes.execution
            count = REFRESH_MINUTES if is_execution else REFRESH_BARS
            step = timeframe_ms(timeframe)
            since = self.clock.now_ms() - step * count
            bars = self.source.fetch_ohlcv(self.symbol, timeframe, since, count)
            if not bars:
                continue
            frame = bars_to_frame(bars)
            if is_execution:
                minutes = frame
            if timeframe is self.config.engine.timeframes.signal:
                newest = max(newest, bars[-1].ts)

            # Minutes are never archived from here. They are used in memory to
            # settle the open position and nothing else reads them, while the
            # M1 table is the largest by far -- 2.6 million rows per symbol --
            # and every write merges, revalidates and rewrites a whole year
            # partition. Doing that once a minute, four times over, would be
            # most of what this program does. The collector and the sync keep
            # that table; this one borrows from it.
            if is_execution:
                continue

            # For the rest, write only what the archive does not already hold.
            # The hourly frames gain a bar once an hour while this runs twice a
            # minute, so without the guard most of a cycle is spent revalidating
            # candles that did not change.
            last = self.store.last_ts(self.symbol, timeframe)
            fresh = frame if last is None else frame.loc[frame["ts"] > last]
            if not fresh.empty:
                self.store.write(self.symbol, timeframe, fresh)
        return newest, minutes

    # -- the cycle ---------------------------------------------------------- #

    def step(self) -> list[JournalEntry]:
        """One whole cycle for one market: settle, then decide.

        Kept for callers that drive a single market, and for the tests. The
        runner uses `settle` and `decide` separately so that a dozen markets all
        settle before any of them spends ten seconds on an analysis.

        Every failure is caught and recorded rather than raised. A loop that
        dies on one bad API response stops watching its own open position,
        which is worse than missing a cycle.

        **The two halves do not share a fate.** Settling is what an open
        position depends on; deciding is what a flat account does with a spare
        moment. They were under one `try` with one `return` on failure, so a
        decision that raised would have discarded minutes that had already been
        settled -- the open position's own record thrown away by a failure in
        the part that was not about it. Not observed, found by reading; the
        shape of it is wrong whether or not it has fired yet.
        """
        closed = self.settle()
        self.decide()
        return closed

    def settle(self) -> list[JournalEntry]:
        """Pull fresh bars and resolve whatever is open. The cheap half.

        Separated from deciding so a runner with a dozen markets can settle all
        of them before any of the expensive analysis begins. Deciding costs ten
        to fifteen seconds a market; settling costs a fetch and a walk over a
        few minutes, and it is what an open position depends on.

        Late settling does not change a recorded outcome, because the minutes
        are replayed: a stop hit at 14:01 and noticed at 14:03 is still resolved
        at 14:01, at that minute's price. What it delays is only when the
        journal entry appears and when the account is free again.
        """
        self.stats.tally.cycles += 1
        try:
            newest, minutes = self.refresh_data()
        except Exception as exc:  # broad on purpose: a bad cycle must not end the run
            self._failed(f"Daten holen fehlgeschlagen: {exc}")
            return []
        self._newest = newest

        closed: list[JournalEntry] = []
        try:
            closed = self._settle(minutes)
        except Exception as exc:
            self._failed(f"Abrechnen fehlgeschlagen: {exc}")

        # Always. Whatever was settled happened, and a record that is only
        # written when the whole cycle succeeded is a record that disappears
        # exactly when something is wrong.
        self._persist()
        return closed

    def decide(self) -> None:
        """Ask the setups about the bar that just closed. The expensive half.

        Does nothing unless a signal bar has closed since the last decision, so
        most cycles cost nothing at all -- at a fifteen-minute cadence that is
        twenty-nine cycles in thirty.
        """
        newest = self._newest
        # GRÖSSER, nicht bloss UNGLEICH. Der Unterschied ist ein Defekt, der
        # erst sichtbar wird, wenn eine Antwort veraltet ist statt zu fehlen.
        #
        # Der Fehlschlag-Pfad ist sicher: `self._newest` wird in `settle()`
        # erst nach einem vollständig gelungenen `refresh_data()` gesetzt, also
        # bleibt der Zeiger bei einem Abruffehler stehen und hier passiert
        # nichts. Was nicht sicher war: eine Abfrage, die GELINGT und einen
        # alten Balken zurückgibt -- eine zwischengespeicherte oder
        # gespiegelte Antwort. Dass das kein Hirngespinst ist, zeigt der
        # Befund vom 09.10.2026 zu `stream.binancefuture.com`: Preise auf den
        # Cent richtig, Kennraum um Faktor 11 falsch. Eine Antwort kann
        # richtig aussehen und alt sein.
        #
        # Mit `!=` hätte ein solcher Rückschritt zwei Dinge getan: einen längst
        # entschiedenen Balken erneut entscheiden, und den Zeiger unten
        # RÜCKWÄRTS setzen -- womit alle Balken dazwischen zum zweiten Mal
        # entschieden würden. Mit `>` passiert nichts, und es wird vermerkt.
        if not newest:
            return
        if newest <= self.state.last_decided_ts:
            if newest < self.state.last_decided_ts:
                self.stats.tally.stale_bars += 1
                self._failed(
                    f"Veralteter Signalbalken verworfen: {newest} liegt vor dem "
                    f"zuletzt entschiedenen {self.state.last_decided_ts}"
                )
                self._persist()
            return
        try:
            self._maybe_open(newest)
        except Exception as exc:
            # The cursor stays where it is, so the bar is read again next cycle.
            # Marking it decided here -- which is what this method used to do,
            # before `_maybe_open` -- burned the bar permanently: the persist
            # below runs after the except too, so one timed-out fetch silently
            # destroyed that signal and nothing in the record said so. Forward
            # evidence is the only kind the plan calls decisive, and it arrives
            # at about two signals a day.
            self._attempts = (newest, self._attempts[1] + 1 if self._attempts[0] == newest else 1)
            self._failed(f"Entscheiden fehlgeschlagen: {exc}")
            if self._attempts[1] < MAX_DECISION_ATTEMPTS:
                self._persist()
                return
            # Retrying for ever would let one unreadable bar stop this account
            # from ever deciding again. Giving up is the lesser harm, but it is
            # a loss of evidence either way, so it is counted rather than
            # quietly skipped.
            self.stats.tally.abandoned_bars += 1
            self._failed(
                f"Signalbalken aufgegeben nach {MAX_DECISION_ATTEMPTS} Versuchen: {newest}"
            )

        # Only now, and only once, is the bar actually decided.
        self.stats.tally.bars_seen += 1
        self.state.last_decided_ts = newest
        self._persist()

    def refresh_funding(self, rates: list[FundingRate]) -> int:
        """Hand the broker funding rates that settled after it was built.

        The broker took its schedule once, in the constructor. Everything due
        after that was charged against the end of that list, which is to say
        charged as nothing.
        """
        return self.broker.refresh_funding(rates)

    @property
    def wants_decision(self) -> bool:
        """Has a signal bar closed that has not been acted on?

        Let a runner see the expensive work coming before it starts it.
        """
        return bool(self._newest) and self._newest > self.state.last_decided_ts

    def _failed(self, message: str) -> None:
        """Record a failed cycle where somebody will see it.

        Counted as well as listed, because the list lives in this process and
        prints at shutdown. A loop failing every cycle for an hour reads on the
        screen exactly like a quiet market, and "say why nothing is happening"
        is not worth much if "everything is throwing" is not one of the answers
        it can give.
        """
        self.stats.tally.failures += 1
        # Persisted as well as listed. The list dies with the process, and a
        # trader that is killed and restarted keeps the count while losing the
        # reason -- which is how twelve accounts came to show one unexplainable
        # failure each. The clock is the injected one, so a replay stamps these
        # with simulated time like everything else.
        self.stats.tally.last_failure = message[:500]
        self.stats.tally.last_failure_ts = self.clock.now_ms()
        self.stats.errors.append(message)

    def _settle(self, minutes: pd.DataFrame) -> list[JournalEntry]:
        """Walk the minutes that arrived since the last cycle.

        Resumable by timestamp rather than by position in a file: the process
        may have been off for a day, and what matters is which minutes have
        already been charged against the account, not how many rows were read.

        A cycle that crashes half way leaves the account advanced in memory and
        not on disk, so the next start replays those minutes. That is safe
        rather than lucky: the journal keys on the proposal id and upserts, so a
        trade written twice is written once.
        """
        minutes = self._fill_gap(minutes)
        if minutes.empty:
            return []

        stamps = minutes["ts"].to_numpy(dtype="int64")
        opens = minutes["open"].to_numpy(dtype="float64")
        highs = minutes["high"].to_numpy(dtype="float64")
        lows = minutes["low"].to_numpy(dtype="float64")
        closes = minutes["close"].to_numpy(dtype="float64")

        begin = int(stamps.searchsorted(self.state.last_minute_ts + 1, side="left"))
        out: list[JournalEntry] = []
        for i in range(begin, len(stamps)):
            ts = int(stamps[i])
            if self.broker.is_flat:
                # Nothing working: the only effect of a minute is the funding
                # cursor, and the broker moves that in one step.
                self.broker.skip_to(ts)
            else:
                before = self.broker.expired_entries
                fill = self.broker.on_minute(ts, float(opens[i]), float(highs[i]), float(lows[i]))
                if self.broker.expired_entries > before:
                    self.stats.tally.expired += 1
                    self._reason = None
                if fill is not None:
                    entry = self._record(fill)
                    if entry is not None:
                        out.append(entry)
                elif self.broker.position is not None and self.state.opened_ts == 0:
                    # The entry just filled. Noted so a restart knows the order
                    # became a position rather than still resting.
                    self.state.opened_ts = self.broker.position.opened_ts
                    # Und genau hier ist die Antwort auf "mit wie viel Geld bin
                    # ich in den Trade gegangen": der tatsaechliche Fill. Die
                    # `margin` kommt aus dem Broker, nicht nachgerechnet -- sie
                    # ist der Betrag, der wirklich blockiert wurde.
                    self._announce_fill(self.broker.position)
            self.state.last_minute_ts = ts
            self.state.last_price = float(closes[i])
        return out

    def _fill_gap(self, minutes: pd.DataFrame) -> pd.DataFrame:
        """The fetched minutes, extended back over a gap the cycle left.

        Pulled from the venue rather than the archive, because the archive's
        minute table is maintained by the collector and may itself be behind --
        and because the venue is the authority on what happened in a window
        nobody was watching.

        It matters more than it looks. The trade's exit is decided minute by
        minute; resolving it against the first minute this cycle happens to see
        would put the exit hours late, at a price the market never offered, and
        in the direction that flatters the account.
        """
        if self.state.last_minute_ts == 0 or minutes.empty or self.source is None:
            return minutes
        step = timeframe_ms(Timeframe.M1)
        first = int(minutes["ts"].to_numpy(dtype="int64")[0])
        if first <= self.state.last_minute_ts + step:
            return minutes

        pages: list[pd.DataFrame] = []
        since = self.state.last_minute_ts + 1
        for _ in range(MAX_CATCHUP_PAGES):
            bars = self.source.fetch_ohlcv(
                self.symbol, self.config.engine.timeframes.execution, since, CATCHUP_PAGE
            )
            if not bars:
                break
            pages.append(bars_to_frame(bars))
            since = bars[-1].ts + 1
            if since >= first:
                break
        if not pages:
            return minutes
        joined = pd.concat([*pages, minutes], ignore_index=True)
        joined = joined.drop_duplicates(subset="ts").sort_values("ts")
        return joined.reset_index(drop=True)

    def _maybe_open(self, bar_ts: int) -> None:
        """Ask the setups about the bar that just closed, and size what they say."""
        if not self.broker.is_flat:
            return

        frames = {
            timeframe: self.store.read(self.symbol, timeframe)
            .tail(HISTORY_BARS)
            .reset_index(drop=True)
            for timeframe in self.config.engine.timeframes.context
        }
        if any(frame.empty for frame in frames.values()):
            return

        analysis = MultiFrameAnalysis(frames, self.config.engine)
        index = _index_of(analysis.signal.frame, bar_ts)
        if index is None:
            return

        intent = self.strategy.propose_at(analysis, index)
        if intent is None or not intent.is_coherent:
            return
        self.stats.tally.proposed += 1

        # The case for the trade, built *before* the order exists. If it cannot
        # be built the trade does not happen: an order placed now and explained
        # later is a replayed trade wearing a forward label, which is the one
        # thing this module exists to rule out.
        #
        # In practice this is the warm-up. The score needs a few hundred bars on
        # every frame, and a fresh install has none -- so without this counter a
        # new deployment would propose, refuse, and never say why.
        reason = reason_at(analysis, index, intent.side)
        if reason is None:
            self.stats.tally.not_ready += 1
            return

        signal_ms = timeframe_ms(self.config.engine.timeframes.signal)
        created = decision_time_ms(bar_ts, self.config.engine.timeframes.signal)
        # `assess` statt `plan_entry`: dieselbe Rechnung, aber mit dem Urteil
        # daneben statt nur der Order.
        #
        # Bis zum 08.10.2026 warf der Papierhaendler das Urteil weg und
        # behielt nur die Order. Folge: `signals.sqlite` enthielt 67'786
        # Replay-Signale und **null** Live-Signale. Das Projekt misst
        # abgelehnte Signale im Replay ausgiebig (study_refused.py, zwoelf
        # Maerkte, 34'699 Ablehnungen) und hatte vom LAUFENDEN System keinen
        # einzigen -- weder was es erwogen noch was es verworfen hat.
        #
        # Das blockierte auch E0 Punkt 3: "Teste Signale, die auf der
        # bisherigen Venue ENTSTEHEN, mit einer Ausfuehrung auf der neuen"
        # braucht Signale aus dem Aufnahmefenster, und die gab es nicht.
        verdict = assess(
            intent,
            None,
            symbol=self.symbol,
            spec=self.spec,
            config=self.config,
            equity=self.broker.equity,
            created_ts=created,
            expires_ts=created + self.config.engine.simulation.entry_expiry_bars * signal_ms,
        )
        entry = verdict.entry
        self._record_signal(intent, verdict, decided_ts=created)
        if entry is None or not self.broker.submit(entry):
            self.stats.tally.refused_by_risk += 1
            return

        self._reason = reason
        self.state.opened_ts = 0
        self.stats.tally.opened += 1
        # Was eingereicht wurde, in Geld. GEPLANT, nicht gefuellt: eine Order
        # fuellt nicht zwingend zum Limit und vielleicht nie. Der Fill meldet
        # sich unten mit den echten Zahlen, und die beiden Zeilen sind
        # absichtlich verschieden beschriftet.
        # `flush=True`, und das ist kein Detail: Python puffert stdout, sobald
        # es in eine Datei oder Pipe geht, und der Haendler laeuft als
        # Dauerprozess mit umgeleiteter Ausgabe. Ohne flush landet jede Zeile
        # im Puffer und erscheint erst, wenn der Prozess endet -- also genau
        # dann nicht, wenn man sie braucht. Dasselbe galt fuer die schon
        # vorhandene Abschlussmeldung, die darum nie zu sehen war.
        print(
            f"  [{self.symbol}] Order eingereicht: {entry.side.value} "
            f"{entry.qty:g} @ {entry.limit_price:,.4f} = "
            f"{entry.planned_notional:,.2f} {QUOTE} geplant  |  "
            f"Hebel {entry.leverage:g}x  |  Margin {entry.planned_margin:,.2f} {QUOTE}  |  "
            f"Risiko {entry.risk_amount:,.2f} {QUOTE} bei Stop {entry.stop:,.4f}",
            flush=True,
        )
        # Persisted immediately rather than at the end of the cycle. The gap
        # between placing the order and saving its reason is the window in
        # which a crash would produce an unexplained trade, and it costs one
        # write per trade to close it.
        self._persist()

    # -- the record --------------------------------------------------------- #

    def _record(self, fill: Fill) -> JournalEntry | None:
        """Append the outcome to the reason that was already written down.

        A fill whose reason is missing is dropped rather than journalled with a
        blank one. It can only happen if the state file was lost mid-trade, and
        a row saying "lost 1 R" for reasons unknown is what this whole package
        exists to avoid.
        """
        self.stats.tally.closed += 1
        reason = self._reason
        self._reason = None
        self.state.opened_ts = 0
        if reason is None:
            self.stats.errors.append(f"{fill.proposal_id}: Begründung fehlt, nicht journalisiert")
            return None

        signal = (
            self.store.read(self.symbol, self.config.engine.timeframes.signal)
            .tail(HISTORY_BARS)
            .reset_index(drop=True)
        )
        entry = JournalEntry(
            trade_id=f"{LIVE_PREFIX}{fill.proposal_id}",
            source=Source.LIVE,
            symbol=self.symbol,
            strategy=self.strategy.name,
            opened_ts=fill.opened_ts,
            closed_ts=fill.closed_ts,
            exit_reason=fill.reason,
            entry_price=fill.entry_price,
            exit_price=fill.exit_price,
            qty=fill.qty,
            leverage=fill.leverage,
            risk_amount=fill.risk_amount,
            gross_pnl=round(fill.gross_pnl, 4),
            fees=round(fill.fees, 4),
            funding=round(fill.funding, 4),
            net_pnl=round(fill.net_pnl, 4),
            r_multiple=round(fill.r_multiple, 4),
            reason=reason,
            post_mortem=examine(
                signal,
                side=fill.side,
                entry=fill.entry_price,
                stop=reason.stop,
                opened_ts=fill.opened_ts,
                closed_ts=fill.closed_ts,
                exit_price=fill.exit_price,
                exit_reason=fill.reason,
                r_multiple=fill.r_multiple,
            ),
        )
        self.journal.record([entry])
        return entry

    def _record_signal(
        self, intent: object, verdict: Assessment, *, decided_ts: int
    ) -> None:
        """Jedes erwogene Signal aufschreiben, genommen wie abgelehnt.

        Spiegelt `sim/engine.py:586` -- dieselben Felder, dieselbe Bedeutung,
        nur `source=LIVE`. Dass die beiden sich gleichen, ist der Punkt: eine
        Live-Zeile und eine Replay-Zeile muessen dieselbe Frage beantworten
        koennen, sonst ist der Vergleich der beiden Populationen keiner.

        Ein Fehler beim Schreiben darf den Handel nicht anhalten. Die
        Aufzeichnung ist Beobachtung, nicht Betrieb -- wer die Reihenfolge
        umdreht, hat einen Haendler, den sein Notizbuch stoppen kann.
        """
        if self.signals is None:
            return
        try:
            self.signals.record((
                SignalRecord(
                    signal_id=f"{self.symbol}-{decided_ts}-{setup_label(intent)}",
                    run_signature=self.run_signature,
                    decided_ts=decided_ts,
                    symbol=self.symbol,
                    source=Source.LIVE,
                    action=Action.TAKEN if verdict.entry is not None else Action.REFUSED,
                    refused_by=verdict.refused_by,
                    detail=verdict.detail,
                    setup_key=setup_label(intent),
                    setup_timeframe="",
                    signal_timeframe=self.config.engine.timeframes.signal.value,
                    side=intent.side,  # type: ignore[attr-defined]
                    entry=intent.entry,  # type: ignore[attr-defined]
                    stop=intent.stop,  # type: ignore[attr-defined]
                    target=intent.target,  # type: ignore[attr-defined]
                    reward_risk=verdict.reward_risk,
                    cost_fraction=verdict.cost_fraction,
                    risk_amount=verdict.risk_amount,
                    qty=verdict.qty,
                    leverage=verdict.leverage,
                ),
            ))
        except Exception as problem:
            self.stats.errors.append(f"Signal nicht aufgezeichnet: {problem}")

    def _announce_fill(self, position: OpenPosition) -> None:
        """Was wirklich in den Trade gegangen ist, zum echten Fill-Preis.

        Drei Betraege, und sie sind drei verschiedene Dinge:

        * **Notional** -- die Positionsgroesse. Das Geld, das im Trade steckt.
        * **Margin** -- was davon auf dem Konto blockiert ist. Kommt aus
          `position.margin`, also aus dem Broker selbst, nicht hier
          nachgerechnet.
        * **Risiko** -- was verloren geht, wenn der Stop greift.

        Die ersten ersten Zeilen von `config/risk.yaml` erklaeren, warum diese
        Trennung Geld wert ist: eine 5'000er Position mit 3% Stop riskiert
        150, nicht 5'000. Wer die drei in einer Zahl zusammenfasst, hat
        entweder das Risiko aufgeblasen oder die Groesse verkleinert.
        """
        print(
            f"  [{self.symbol}] GEFUELLT: {position.side.value} {position.qty:g} @ "
            f"{position.entry_price:,.4f}  ->  {position.notional:,.2f} {QUOTE} im Trade  |  "
            f"Hebel {position.leverage:g}x  |  Margin {position.margin:,.2f} {QUOTE} gebunden  |  "
            f"Risiko {position.risk_amount:,.2f} {QUOTE}"
        )
        print(
            f"      Stop {position.stop:,.4f}  Ziel {position.target:,.4f}  "
            f"Liquidation {position.liq_price:,.4f}",
            flush=True,
        )

    def _persist(self) -> None:
        self.state.capture_from(self.broker, reason=self._reason)
        self.state.tally = self.stats.tally
        self.state_store.save(self.state)

    # -- reading ------------------------------------------------------------ #

    def status(self) -> str:
        position = self.broker.position
        if position is not None:
            move = position.unrealised(self.state.last_price)
            # Geld und Hebel gehoeren auch hier hin, nicht nur in die
            # Fill-Meldung: eine offene Position ist der Zustand, den man
            # ansieht, wenn man wissen will, was gerade im Feuer steht. Die
            # Fill-Meldung ist schon durchgescrollt.
            return (
                f"{self.symbol}: {position.side.value} {position.qty:g} @ "
                f"{position.entry_price:,.2f} = {position.notional:,.2f} {QUOTE}, "
                f"Hebel {position.leverage:g}x, Margin {position.margin:,.2f} {QUOTE}, "
                f"Risiko {position.risk_amount:,.2f} {QUOTE}, "
                f"Stop {position.stop:,.2f}, Ziel {position.target:,.2f}, "
                f"offen {move:+,.2f} {QUOTE}"
            )
        if self.broker.pending is not None:
            pending = self.broker.pending
            return (
                f"{self.symbol}: Order liegt bei {pending.limit_price:,.2f} "
                f"({pending.side.value}) = {pending.planned_notional:,.2f} {QUOTE} geplant, "
                f"Hebel {pending.leverage:g}x, Margin {pending.planned_margin:,.2f} {QUOTE}, "
                f"Risiko {pending.risk_amount:,.2f} {QUOTE}, verfällt {pending.expires_ts}"
            )
        return (
            f"{self.symbol}: flach, Kontostand {self.broker.equity:,.2f} CHF"
            f" -- {self.stats.tally.sentence()}"
        )

    def close_out(self) -> JournalEntry | None:
        """Close an open position at the last price and journal it.

        For stopping deliberately. An open trade dropped on shutdown is a loser
        the statistics never see, which is the same hole the backtest closes at
        the end of its window.
        """
        fill = self.broker.close_at(
            self.state.last_price, self.state.last_minute_ts, ExitReason.MANUAL
        )
        if fill is None:
            self.broker.cancel_pending()
            self._persist()
            return None
        entry = self._record(fill)
        self._persist()
        return entry


def _index_of(frame: pd.DataFrame, ts: int) -> int | None:
    """Where a bar with this timestamp sits, or None if it is not there."""
    stamps = frame["ts"].to_numpy(dtype="int64")
    found = stamps.searchsorted(ts, side="left")
    if found >= len(stamps) or int(stamps[found]) != ts:
        return None
    return int(found)


def state_path(config: AppConfig) -> Path:
    """Where the paper accounts live.

    Beside the journal rather than in it: the journal is what happened and is
    appended forever, this is the current state of an account and is rewritten
    every cycle.
    """
    return config.engine.paths.data_dir / "paper.sqlite"
