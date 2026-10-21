"""The backtest loop.

One rule shapes everything here: a decision taken at the close of bar *i* can
only be acted on from bar *i+1*. The engine asks the strategy at the close of each
signal bar, queues whatever comes back, and then steps through the *next* hour
minute by minute to see what happened to it. Filling within the same bar the
decision was made on is a quiet one-hour head start, and it is enough on its own
to turn a losing strategy into a winning backtest.

The minute loop is the expensive part -- roughly a million and a half iterations
over a couple of years -- so the M1 series is unpacked into numpy arrays once and
indexed positionally, rather than queried per hour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import numpy as np
import pandas as pd

from traidingbrain.analysis.context import load_context
from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.config.settings import AppConfig
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import ExitReason, Timeframe
from traidingbrain.domain.market import FundingRate, SymbolSpec
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.history.engine import HistoryEngine
from traidingbrain.journal.record import Source
from traidingbrain.journal.signals import Action, SignalRecord, SignalStore
from traidingbrain.sim.broker import Fill, PendingEntry, SimBroker
from traidingbrain.sim.metrics import BacktestMetrics, compute_metrics, format_metrics
from traidingbrain.sim.plan import Assessment, TradeIntent, assess, setup_label

#: Re-exported: `TradeIntent` lives below the planner so that `plan` and
#: `engine` do not import each other. Every existing caller imports it from
#: here, and still can.
__all__ = [
    "AnalysisStrategy",
    "BacktestEngine",
    "BacktestResult",
    "MissingMinuteDataError",
    "Strategy",
    "TradeIntent",
    "load_engine",
    "wants_analysis",
]


class MissingMinuteDataError(RuntimeError):
    """The backtest was asked to run where it cannot resolve intrabar order."""


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date().isoformat()


class Strategy(Protocol):
    """Anything that can look at a snapshot and want something."""

    name: str

    def propose(self, snapshot: MarketSnapshot) -> TradeIntent | None: ...


class AnalysisStrategy(Protocol):
    """A strategy that reads the chart directly rather than the snapshot.

    The snapshot is normalised for the model: no absolute prices, distances in
    ATR, levels by opaque id. That is exactly right for something being asked to
    *judge* a situation and exactly wrong for a rule that says "stop at the low
    of the candle that created the gap". Those rules need the bars.

    Both kinds run through the same engine, the same broker, the same sizing and
    the same costs -- which is the only way their results can be put in one
    table. What differs is what they are shown.
    """

    name: str

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None: ...


def wants_analysis(strategy: Strategy | AnalysisStrategy) -> bool:
    """Does this strategy read bars rather than a snapshot?"""
    return hasattr(strategy, "propose_at")


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    metrics: BacktestMetrics
    fills: list[Fill]
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    snapshots_built: int = 0
    intents: int = 0
    intents_rejected_by_risk: int = 0
    #: Signals that existed while the single slot was busy, recorded and
    #: never traded. Zero unless the run asked for them.
    shadow_signals: int = 0
    #: Of those, the ones the risk rules would have accepted. This is the
    #: population the ledger had no record of at all.
    shadow_tradeable: int = 0
    first_ts: int = 0
    last_ts: int = 0
    #: Non-empty when the run covered less than it was asked to. A trim that only
    #: lived in a log would be the same silent no-op this guard exists to catch.
    window_note: str = ""

    def summary(self) -> str:
        head = (
            f"{self.symbol} / {self.strategy}\n"
            f"  snapshots       {self.snapshots_built:,}\n"
            f"  intents         {self.intents:,} "
            f"({self.intents_rejected_by_risk:,} refused by risk rules)"
        )
        if self.shadow_signals:
            head += (
                f"\n  im Schatten     {self.shadow_signals:,} "
                f"({self.shadow_tradeable:,} haette das System genommen)"
            )
        if self.window_note:
            head += f"\n  WINDOW          {self.window_note}"
        return head + "\n" + format_metrics(self.metrics)


class BacktestEngine:
    """Runs one strategy over one symbol."""

    def __init__(
        self,
        symbol: str,
        analysis: MultiFrameAnalysis,
        *,
        minute_frame: pd.DataFrame,
        spec: SymbolSpec,
        config: AppConfig,
        funding: list[FundingRate] | None = None,
        history: HistoryEngine | None = None,
        signals: SignalStore | None = None,
        run_signature: str = "",
        shadow: bool = False,
    ) -> None:
        self.symbol = symbol
        self.analysis = analysis
        self.spec = spec
        self.config = config
        self.funding = funding or []
        self.history = history
        # Optional on purpose: a study comparing two arms over the same period
        # wants one of them writing signals, not both, or the ledger holds the
        # same bar twice under one signature and the counts stop being a
        # population.
        self.signals = signals
        self.run_signature = run_signature
        # Ask the strategy even while the slot is busy, record the answer and
        # never act on it. Off by default because it roughly triples the
        # strategy calls -- about two thirds of hours lie behind an open
        # trade -- and because every number a run already produced was
        # produced without it.
        self.shadow = shadow
        self._fills_seen = 0
        # Positioning and the calendar if they are on disk, nothing if not.
        # A period the venue does not cover is one fewer factor, not a failure.
        self.context = load_context(symbol, analysis.signal.frame, config.engine)
        self.builder = SnapshotBuilder(
            symbol,
            analysis,
            config.engine,
            positioning=self.context.positioning,
            calendar=self.context.calendar,
            sentiment=self.context.sentiment,
        )

        self.minute_ts = minute_frame["ts"].to_numpy(dtype="int64")
        self.minute_open = minute_frame["open"].to_numpy(dtype="float64")
        self.minute_high = minute_frame["high"].to_numpy(dtype="float64")
        self.minute_low = minute_frame["low"].to_numpy(dtype="float64")

    def run(
        self,
        strategy: Strategy | AnalysisStrategy,
        *,
        max_bars: int | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> BacktestResult:
        broker = SimBroker(self.spec, self.config.engine.simulation, self.funding)
        signal = self.analysis.signal
        signal_ms = timeframe_ms(self.config.engine.timeframes.signal)
        expiry_ms = self.config.engine.simulation.entry_expiry_bars * signal_ms

        start = self.analysis.first_ready_index()
        if start is None:
            return self._empty_result(strategy, broker)

        end = len(signal) - 1
        signal_ts = signal.frame["ts"].to_numpy(dtype="int64")
        # When each bar closed. For time bars this is `ts + signal_ms`; for
        # takt bars (E24) it is the stored `close_ts`, and the bars are of
        # uneven length -- so every "next bar" moment below reads this array
        # rather than adding a constant.
        signal_closes = signal.close_times()
        takt = "close_ts" in signal.frame.columns

        start, end, clamp_note = self._resolve_window(
            signal_ts, start, end, start_ts=start_ts, end_ts=end_ts, max_bars=max_bars
        )
        if end <= start:
            return self._empty_result(strategy, broker)

        signal_close = signal.frame["close"].to_numpy(dtype="float64")

        snapshots = 0
        intents = 0
        refused = 0
        # A two-slot list rather than two locals, so the helper that fills
        # it can stay a method instead of returning a tuple nobody reads.
        shadow = [0, 0]
        self._fills_seen = 0
        reads_bars = wants_analysis(strategy)

        for index in range(start, end):
            # Only ask when the answer can be acted on. Asking while a position
            # is open costs milliseconds and changes nothing -- over twenty
            # thousand bars that is most of the runtime.
            #
            # Which question gets asked depends on what the strategy reads. A
            # bar-reading strategy needs no snapshot, and building one for it
            # would be most of the run spent on something never looked at.
            snapshot = None
            intent = None
            # The shadow pass, and the reason it exists: while the slot is busy
            # the strategy is never asked, so no row of any kind is written and
            # `Action.OCCUPIED` had zero rows in the database. Measured on the
            # ledger itself, about two thirds of BTC's four years lies behind a
            # taken signal -- a missing population of the same order as the one
            # every result so far rests on. No bound in either direction could
            # be read from a sample that excludes it.
            #
            # Nothing here reaches the broker. `_record_shadow` assesses and
            # writes a row and returns nothing, so the trades, the equity curve
            # and every metric are identical with the pass on or off. That is
            # asserted directly in tests/test_backtest.py rather than reviewed.
            if self.shadow and not broker.is_flat:
                self._record_shadow(
                    strategy,
                    index,
                    reads_bars=reads_bars,
                    equity=broker.equity,
                    created_ts=int(signal_closes[index]),
                    expires_ts=self._expiry(signal_closes, index, expiry_ms, takt),
                    counts=shadow,
                )
            if broker.is_flat and reads_bars:
                snapshots += 1
                intent = strategy.propose_at(self.analysis, index)  # type: ignore[union-attr]
            elif broker.is_flat:
                snapshot = self.builder.build(index)
                if snapshot is not None and self.history is not None:
                    # Look up from the snapshot just built and fold the answer back
                    # in, rather than building a second one. Two builds per bar
                    # doubled the runtime of a full backtest for no extra
                    # information.
                    stats, _quality = self.history.lookup(snapshot)
                    snapshot = snapshot.model_copy(update={"history": stats})
                if snapshot is not None:
                    snapshots += 1
                    intent = strategy.propose(snapshot)  # type: ignore[union-attr]

            if intent is not None and intent.is_coherent:
                intents += 1
                entry = self._to_entry(
                    intent,
                    snapshot,
                    equity=broker.equity,
                    created_ts=int(signal_closes[index]),
                    expires_ts=self._expiry(signal_closes, index, expiry_ms, takt),
                )
                if entry is None or not broker.submit(entry):
                    refused += 1
                elif self.history is not None and snapshot is not None:
                    # Held aside, not indexed: the outcome does not exist yet.
                    self.history.remember(entry.proposal_id, snapshot)

            # The decision is live from the start of the next bar, never this one.
            self._step_minutes(
                broker,
                from_ms=int(signal_closes[index]),
                to_ms=int(signal_closes[index + 1]),
            )
            self._commit_resolved(broker)
            broker.mark(int(signal_ts[index + 1]), float(signal_close[index + 1]))

        # Anything still open at the end is closed at the last price rather than
        # left out. Dropping open trades from the statistics silently discards the
        # losers a strategy was still sitting in.
        if broker.position is not None:
            broker.close_at(float(signal_close[end]), int(signal_ts[end]), ExitReason.MANUAL)

        return BacktestResult(
            symbol=self.symbol,
            strategy=strategy.name,
            metrics=compute_metrics(
                strategy.name,
                broker.fills,
                broker.equity_curve,
                self.config.engine.simulation.initial_equity,
                expired_entries=broker.expired_entries,
                rejected_entries=broker.rejected_entries,
            ),
            fills=broker.fills,
            equity_curve=broker.equity_curve,
            snapshots_built=snapshots,
            intents=intents,
            intents_rejected_by_risk=refused,
            shadow_signals=shadow[0],
            shadow_tradeable=shadow[1],
            first_ts=int(signal_ts[start]),
            last_ts=int(signal_ts[end]),
            window_note=clamp_note,
        )

    def _resolve_window(
        self,
        signal_ts: np.ndarray,
        start: int,
        end: int,
        *,
        start_ts: int | None,
        end_ts: int | None,
        max_bars: int | None,
    ) -> tuple[int, int, str]:
        """Narrow the run to what was asked for, then to what can be resolved.

        A time window rather than a bar count, so the same period can be asked for
        across symbols and timeframes without translating indices by hand. The
        minute check comes last, because trimming to the minute data before
        applying the caller's window would report a trim the caller never felt.
        """
        if start_ts is not None:
            start = max(start, int(np.searchsorted(signal_ts, start_ts, side="left")))
        if end_ts is not None:
            end = min(end, int(np.searchsorted(signal_ts, end_ts, side="right")) - 1)
        if max_bars is not None:
            end = min(end, start + max_bars)
        if end <= start:
            return start, end, ""
        return self._fit_to_minutes(signal_ts, start, end)

    def _fit_to_minutes(self, signal_ts: np.ndarray, start: int, end: int) -> tuple[int, int, str]:
        """Trim the run to where intrabar order can actually be resolved.

        The minute series decides whether the stop or the target came first inside
        a signal bar. Where it is absent nothing fills, every entry expires unused,
        and the report says "no trades" -- indistinguishable from a strategy that
        found nothing, and the number someone would act on.

        Trimming rather than refusing, because the common case is benign: the
        minute frame is fetched separately and routinely ends an hour or two
        earlier than the hourly one. Aborting a four-year backtest over its last
        afternoon would be the wrong trade. What is not benign is doing it
        silently, so any trim is returned as a sentence and travels into the
        result.

        Refusing is kept for the case where trimming would leave nothing worth
        reporting -- there, a number would be worse than an error.
        """
        if self.minute_ts.size == 0:
            raise MissingMinuteDataError(
                f"{self.symbol}: no minute data at all, so no order could ever fill.\n"
                f"  python scripts/backfill.py {self.symbol} --tfs M1"
            )

        have_from, have_to = int(self.minute_ts[0]), int(self.minute_ts[-1])
        wanted_from, wanted_to = int(signal_ts[start]), int(signal_ts[end])

        fitted_start, fitted_end = start, end
        if wanted_from < have_from:
            fitted_start = int(np.searchsorted(signal_ts, have_from, side="left"))
        if have_to < wanted_to:
            # The threshold is the last bar's *open*, not its close. Minute data
            # routinely stops partway through the newest bar because it is fetched
            # separately, and trimming for that would fire on every ordinary run
            # and make the note worthless. A gap that does not even reach the last
            # bar's open is a different thing.
            fitted_end = int(np.searchsorted(signal_ts, have_to, side="right")) - 1

        fitted_start = max(start, fitted_start)
        fitted_end = min(end, fitted_end)
        if fitted_end <= fitted_start:
            raise MissingMinuteDataError(
                f"{self.symbol}: the requested window {_day(wanted_from)}..{_day(wanted_to)} "
                f"has no minute data at all; minutes cover "
                f"{_day(have_from)}..{_day(have_to)}. Nothing would fill, and the run "
                f"would report no trades rather than an error.\n"
                f"  python scripts/backfill.py {self.symbol} --tfs M1 "
                f"--since {_day(wanted_from)}"
            )

        if (fitted_start, fitted_end) == (start, end):
            return start, end, ""

        lost_days = (
            (int(signal_ts[fitted_start]) - wanted_from) + (wanted_to - int(signal_ts[fitted_end]))
        ) / 86_400_000
        return (
            fitted_start,
            fitted_end,
            f"trimmed to {_day(int(signal_ts[fitted_start]))}.."
            f"{_day(int(signal_ts[fitted_end]))} ({lost_days:.1f} days dropped) "
            f"because minute data covers only {_day(have_from)}..{_day(have_to)}",
        )

    # -- history ------------------------------------------------------------ #

    def _commit_resolved(self, broker: SimBroker) -> None:
        """Move newly closed trades into the index, and drop unfilled entries.

        An entry that expired without filling has no outcome; recording it as a
        zero would put a trade that never happened into the evidence.
        """
        if self.history is None:
            return
        while self._fills_seen < len(broker.fills):
            fill = broker.fills[self._fills_seen]
            self._fills_seen += 1
            self.history.resolve(
                fill.proposal_id, outcome_r=fill.r_multiple, resolved_ts=fill.closed_ts
            )

    # -- internals ---------------------------------------------------------- #

    def _expiry(self, closes: np.ndarray, index: int, expiry_ms: int, takt: bool) -> int:
        """When an entry decided on bar `index` stops waiting for a fill.

        `entry_expiry_bars` is a count of bars. On time bars that is a fixed
        span, and the old arithmetic is kept so the frozen runs stay frozen.
        On takt bars a bar has no fixed span, so the expiry is the close of
        the bar `entry_expiry_bars` later -- the same rule, read off the data.
        """
        if not takt:
            return int(closes[index]) + expiry_ms
        bars = self.config.engine.simulation.entry_expiry_bars
        return int(closes[min(index + bars, closes.size - 1)])

    def _step_minutes(self, broker: SimBroker, from_ms: int, to_ms: int) -> None:
        """Replay one signal bar, minute by minute -- unless there is nothing to replay.

        With no position and no resting order, walking sixty minutes changes
        nothing except the funding cursor, and the broker can move that in one
        step. The broker is flat for most of a backtest, so this is most of the
        minute loop.
        """
        if broker.is_flat:
            broker.skip_to(to_ms)
            return

        lo = int(np.searchsorted(self.minute_ts, from_ms, side="left"))
        hi = int(np.searchsorted(self.minute_ts, to_ms, side="left"))
        for i in range(lo, hi):
            broker.on_minute(
                int(self.minute_ts[i]),
                float(self.minute_open[i]),
                float(self.minute_high[i]),
                float(self.minute_low[i]),
            )

    def _to_entry(
        self,
        intent: TradeIntent,
        snapshot: MarketSnapshot | None,
        *,
        equity: float,
        created_ts: int,
        expires_ts: int,
    ) -> PendingEntry | None:
        """Turn a price plan into an order, or refuse it -- and record either way.

        The rules themselves live in `sim/plan.py`, because the forward paper
        trader applies the same ones and a second copy of them would differ by
        about as much as the effects being measured.

        The refusal used to vanish here into `intents_rejected_by_risk += 1`.
        It is now a row, because the five rules doing the refusing have never
        been tested against outcomes and cannot be while the signals they
        refuse do not exist.
        """
        verdict = assess(
            intent,
            snapshot,
            symbol=self.symbol,
            spec=self.spec,
            config=self.config,
            equity=equity,
            created_ts=created_ts,
            expires_ts=expires_ts,
        )
        if self.signals is not None:
            self.signals.record([self._signal_row(intent, verdict, decided_ts=created_ts)])
        return verdict.entry

    def _record_shadow(
        self,
        strategy: Strategy | AnalysisStrategy,
        index: int,
        *,
        reads_bars: bool,
        equity: float,
        created_ts: int,
        expires_ts: int,
        counts: list[int],
    ) -> None:
        """A signal that existed while the slot was busy. Recorded, never traded.

        The risk rules are still run on it, and the rule that would have
        refused it is still stored, because the decomposition is the whole
        point:

        * OCCUPIED with no rule attached -- the system *would have taken* this
          trade had a slot been free. This is the population nothing has ever
          measured, and the one that decides whether more concurrency is worth
          anything.
        * OCCUPIED with a rule attached -- it would have been refused anyway,
          so the busy slot cost nothing here.

        Without that split, "there were N skipped signals" says nothing: most
        of them may be ones the rules already reject, and the rules are
        measurably right to.

        `history.remember` is deliberately not called. A shadow signal never
        became a trade, so it has no outcome to commit, and recording one would
        put a trade that did not happen into the evidence.
        """
        intent = (
            strategy.propose_at(self.analysis, index)  # type: ignore[union-attr]
            if reads_bars
            else self._shadow_via_snapshot(strategy, index)
        )
        if intent is None or not intent.is_coherent:
            return
        verdict = assess(
            intent,
            None,
            symbol=self.symbol,
            spec=self.spec,
            config=self.config,
            equity=equity,
            created_ts=created_ts,
            expires_ts=expires_ts,
        )
        counts[0] += 1
        if verdict.accepted:
            counts[1] += 1
        if self.signals is not None:
            self.signals.record(
                [
                    self._signal_row(
                        intent,
                        verdict,
                        decided_ts=created_ts,
                        action=Action.OCCUPIED,
                    )
                ]
            )

    def _shadow_via_snapshot(
        self, strategy: Strategy | AnalysisStrategy, index: int
    ) -> TradeIntent | None:
        """The snapshot-reading path, without the history lookup.

        History is skipped on purpose. `lookup` is the expensive half of a
        build, and folding it in here would change nothing that can be acted
        on while also making the shadow pass cost more than the real one. The
        consequence is stated rather than hidden: a shadow intent is produced
        from a snapshot whose `history` block is empty, so a strategy that
        leans on history will propose differently in the shadow than it would
        have in the open. For the rule-based pools in use that block is unread.
        """
        snapshot = self.builder.build(index)
        if snapshot is None:
            return None
        return strategy.propose(snapshot)  # type: ignore[union-attr]

    def _signal_row(
        self,
        intent: TradeIntent,
        verdict: Assessment,
        *,
        decided_ts: int,
        action: Action | None = None,
    ) -> SignalRecord:
        """One signal as the ledger stores it, taken or not.

        `setup_timeframe` is left empty rather than guessed: the pool knows which
        chart it found the setup on and does not pass it out, and a column filled
        with the signal cadence instead would read as an answer. It is the one
        field in this row that still has to be plumbed through.
        """
        return SignalRecord(
            signal_id=f"{self.symbol}-{decided_ts}-{setup_label(intent)}",
            run_signature=self.run_signature,
            decided_ts=decided_ts,
            symbol=self.symbol,
            source=Source.REPLAY,
            # `action` overrides only for the shadow pass. `refused_by` keeps
            # its meaning in both cases -- the rule that said no -- so an
            # OCCUPIED row with it empty is one the rules would have accepted.
            action=action or (Action.TAKEN if verdict.accepted else Action.REFUSED),
            refused_by=verdict.refused_by,
            detail=verdict.detail,
            setup_key=setup_label(intent),
            setup_timeframe="",
            signal_timeframe=self.config.engine.timeframes.signal.value,
            side=intent.side,
            entry=intent.entry,
            stop=intent.stop,
            target=intent.target,
            reward_risk=verdict.reward_risk,
            cost_fraction=verdict.cost_fraction,
            risk_amount=verdict.risk_amount,
            qty=verdict.qty,
            leverage=verdict.leverage,
        )

    def _empty_result(
        self, strategy: Strategy | AnalysisStrategy, broker: SimBroker
    ) -> BacktestResult:
        return BacktestResult(
            symbol=self.symbol,
            strategy=strategy.name,
            metrics=compute_metrics(
                strategy.name, [], [], self.config.engine.simulation.initial_equity
            ),
            fills=[],
        )


def load_engine(
    symbol: str,
    frames: dict[Timeframe, pd.DataFrame],
    *,
    minute_frame: pd.DataFrame,
    spec: SymbolSpec,
    config: AppConfig,
    funding: list[FundingRate] | None = None,
    history: HistoryEngine | None = None,
    signals: SignalStore | None = None,
    run_signature: str = "",
    shadow: bool = False,
) -> BacktestEngine:
    return BacktestEngine(
        symbol,
        MultiFrameAnalysis(frames, config.engine),
        minute_frame=minute_frame,
        spec=spec,
        config=config,
        funding=funding,
        history=history,
        signals=signals,
        run_signature=run_signature,
        shadow=shadow,
    )
