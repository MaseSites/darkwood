"""Forward paper trading, and the one property that makes it worth running.

Replay already produces trades. The only thing this module adds is **order**:
the reason is on disk before the outcome exists. Everything else here --
persistence, resumption, not settling a minute twice -- exists to protect that
one claim, because every way of breaking it turns a forward record back into a
replayed one without changing a single number.

Three failure modes get their own test:

* **A reason rebuilt at exit.** It would contain the same figures and prove
  nothing. The test opens a trade, asserts the reason is stored *and* that
  nothing is in the journal yet, and only then lets the market resolve it.
* **A restart as a reset.** The laptop this runs on gets shut down, and a
  four-hour setup holds for days. An account that forgot its position would
  quietly drop exactly the trades that matter most.
* **A minute settled twice.** Funding charged again, a stop hit again. Resumed
  by timestamp rather than by a count of rows read, because the process may
  have been off for a day.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH, aggregate, bars_from_rows, fast_engine_config, synthetic_rows
from traidingbrain.api.paper import build_paper_readout
from traidingbrain.clock import FixedClock
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.frames import bars_to_frame, frame_to_bars, timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import ExitReason, Side, Timeframe
from traidingbrain.domain.market import Bar, FundingRate, SymbolSpec
from traidingbrain.journal.record import Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.paper import PaperTrader
from traidingbrain.live.paperstate import PaperStateStore, Tally
from traidingbrain.sim.plan import TradeIntent

SYMBOL = "BTCUSDT"
M1_BARS = 18_000
"""Twelve and a half days of minutes, which is three hundred hourly candles.

Sized to the warm-up and no larger. The score is ready at roughly the hundred
and thirty-fifth hourly bar under the shortened test windows, so this leaves
about a week of tape to trade forward through -- enough for a dozen trades,
cheap enough that the file runs in under a minute."""

#: Where the venue's clock starts: past the warm-up, with the rest ahead.
START_BAR = 160


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def tape() -> dict[Timeframe, pd.DataFrame]:
    """One minute series, viewed at every resolution the trader needs.

    Built from M1 upwards rather than down from M15, because here the minutes
    are not decoration: they are what the exits are resolved against, and a
    minute series that disagreed with its own hourly candles would make every
    fill in this file a fiction.
    """
    base = bars_to_frame(bars_from_rows(synthetic_rows(EPOCH, Timeframe.M1, M1_BARS)))
    return {
        Timeframe.M1: base,
        Timeframe.M15: aggregate(base, Timeframe.M15),
        Timeframe.H1: aggregate(base, Timeframe.H1),
        Timeframe.H4: aggregate(base, Timeframe.H4),
    }


@pytest.fixture(scope="module")
def config() -> AppConfig:
    """The engine this file exercises, with the cost rule pinned.

    The cost cap is pinned rather than inherited because these tests check
    *mechanics* -- that an exit comes from the simulator, that a gap is closed
    before a trade resolves, that a replay cannot overwrite a forward trade.
    All of them need some trade to open, and none of them is about how strict
    the risk layer happens to be today.

    Inheriting it broke all six on 05.10.2026, when the production cap moved
    from 0.15 to 0.08 and the synthetic signals stopped clearing it. The tests
    were right to fail -- behaviour had changed -- but they were failing for a
    reason none of them is about, which makes them a tripwire on an unrelated
    tuning knob rather than a check on the thing they name.
    """
    engine = fast_engine_config([Timeframe.H4, Timeframe.H1, Timeframe.M15])
    base = load_config()
    limits = base.risk.limits.model_copy(update={"max_cost_fraction_of_risk": 0.15})
    risk = base.risk.model_copy(update={"limits": limits})
    return base.model_copy(update={"engine": engine, "risk": risk})


class TapeSource:
    """Serves the fixture up to a moving cutoff, like a venue would.

    The cutoff is the point of it: a forward trader must only ever see closed
    bars up to now, and a source that handed over the whole series would let
    every test here read the future and pass.
    """

    def __init__(self, tape: dict[Timeframe, pd.DataFrame], now_ms: int) -> None:
        self.bars = {tf: frame_to_bars(frame) for tf, frame in tape.items()}
        self.now_ms = now_ms
        self.fail_next = False
        self.calls = 0

    def fetch_ohlcv(
        self, symbol: str, timeframe: Timeframe, since_ms: int, limit: int
    ) -> list[Bar]:
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("exchange unreachable")
        window = [
            bar
            for bar in self.bars.get(timeframe, [])
            if since_ms <= bar.ts and bar.ts + timeframe_ms(timeframe) <= self.now_ms
        ]
        # The *first* `limit` from `since`, which is what ccxt does. Taking the
        # last would make paging impossible to test: every page would end at
        # now, so a loop walking forward would appear to finish in one request
        # and the gap-filling path would never run.
        return window[:limit]

    def fetch_funding(self, symbol: str, since_ms: int, limit: int = 200) -> list[FundingRate]:
        return []

    def fetch_symbol_spec(self, symbol: str) -> SymbolSpec:
        return make_symbol_spec()


class FixedIntent:
    """A strategy that always wants the same trade, in prices off the bar.

    A real setup fires on a handful of bars in a fixture and on none in some,
    which makes "did the account open a position" a test of the fixture rather
    than of the trader. The guide's setups have their own measured tests; this
    file is about what happens to a trade once one exists.
    """

    name = "fixed-for-test"

    def __init__(self, *, side: Side = Side.LONG, stop_atr: float = 0.012) -> None:
        self.side = side
        self.stop_atr = stop_atr
        self.asked = 0

    def propose_at(self, analysis: object, index: int) -> TradeIntent | None:
        self.asked += 1
        close = analysis.signal.close_at(index)  # type: ignore[attr-defined]
        width = close * self.stop_atr
        if self.side is Side.LONG:
            return TradeIntent(
                side=Side.LONG,
                entry=close,
                stop=close - width,
                target=close + width * 3,
                confidence=60.0,
            )
        return TradeIntent(
            side=Side.SHORT,
            entry=close,
            stop=close + width,
            target=close - width * 3,
            confidence=60.0,
        )


def build(
    tmp_path: Path,
    config: AppConfig,
    tape: dict[Timeframe, pd.DataFrame],
    *,
    now_ms: int,
    strategy: object | None = None,
    funding: list[FundingRate] | None = None,
) -> tuple[PaperTrader, TapeSource, PaperStateStore, JournalStore]:
    source = TapeSource(tape, now_ms)
    store = ParquetStore(tmp_path / "ohlcv")
    # Seed the archive with the history that exists up to now, which is what a
    # backfilled deployment has. Without it the store holds only the two dozen
    # bars a cycle refetches, the score never warms up, and every test here
    # would be testing the warm-up guard instead.
    for timeframe, frame in tape.items():
        closed = frame[frame["ts"] + timeframe_ms(timeframe) <= now_ms]
        if not closed.empty:
            store.write(SYMBOL, timeframe, closed)
    states = PaperStateStore(tmp_path / "paper.sqlite")
    journal = JournalStore(tmp_path / "journal.sqlite")
    trader = PaperTrader(
        SYMBOL,
        config,
        source=source,
        store=store,
        state=states,
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(now_ms),
        funding=funding,
        strategy=strategy or FixedIntent(),  # type: ignore[arg-type]
    )
    return trader, source, states, journal


def advance(trader: PaperTrader, source: TapeSource, *, hours: int) -> list:
    """Move the venue's clock forward an hour at a time and run a cycle each.

    An hour per cycle rather than a minute, because that is the resolution the
    decision runs at and a test that stepped minute by minute would spend its
    time re-reading parquet rather than exercising anything.
    """
    closed = []
    for _ in range(hours):
        source.now_ms += timeframe_ms(Timeframe.H1)
        trader.clock = FixedClock(source.now_ms)
        closed.extend(trader.step())
    return closed


def advance_until_open(trader: PaperTrader, source: TapeSource, *, limit: int = 24) -> bool:
    """Step until an order or a position exists. True if one does.

    Needed because these tests are about what happens *to* a trade, and a fixed
    number of hours either has not opened one yet or has already closed it. The
    moment of opening is the moment the central claim is about.
    """
    for _ in range(limit):
        source.now_ms += timeframe_ms(Timeframe.H1)
        trader.clock = FixedClock(source.now_ms)
        trader.step()
        if not trader.broker.is_flat:
            return True
    return False


#: A stop wide enough that the fixture never reaches it.
#:
#: The synthetic series swings about two percent, so a five percent stop and a
#: fifteen percent target are both out of reach and the trade stays open for as
#: long as a test needs it. Used only where the question is what happens while
#: a trade is live.
UNREACHABLE_STOP = 0.05


# --------------------------------------------------------------------------- #
# The claim
# --------------------------------------------------------------------------- #


def test_the_reason_is_on_disk_before_the_outcome_exists(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The only thing this module adds over replay.

    A reason recomputed when the trade closes would hold the same figures and
    prove nothing about when they were known. So: a stored reason and an empty
    journal, checked at the moment the order is placed and before the market is
    allowed to resolve anything.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, journal = build(
        tmp_path, config, tape, now_ms=start, strategy=FixedIntent(stop_atr=UNREACHABLE_STOP)
    )

    assert advance_until_open(trader, source), "nothing ever opened"

    saved = states.load(SYMBOL)
    assert saved is not None
    assert saved.reason is not None, "an order was placed with no case written down"
    assert saved.reason.score_direction, "the score was not captured at the decision bar"
    assert journal.count() == 0, "an outcome was recorded before one existed"


def test_the_stored_reason_is_the_one_the_journal_gets(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Not a second one built at exit, which is the same bug in a nicer shape."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, journal = build(tmp_path, config, tape, now_ms=start)

    assert advance_until_open(trader, source), "nothing ever opened"
    opened = states.load(SYMBOL)
    assert opened is not None and opened.reason is not None
    at_entry = opened.reason

    closed = advance(trader, source, hours=20)
    assert closed, "nothing resolved in twenty hours; this test proved nothing"

    entry = closed[0]
    assert entry.reason.rating == at_entry.rating
    assert entry.reason.score_bullish == at_entry.score_bullish
    assert entry.reason.score_bearish == at_entry.score_bearish
    assert entry.reason.setup_timeframe == at_entry.setup_timeframe
    assert journal.count(source=Source.LIVE) >= 1


def test_forward_trades_are_stored_as_live_and_never_as_replay(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Mixing the two produces an average that describes neither."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, _states, journal = build(tmp_path, config, tape, now_ms=start)

    advance(trader, source, hours=14)

    assert journal.count(source=Source.LIVE) > 0
    assert journal.count(source=Source.REPLAY) == 0
    assert all(entry.source is Source.LIVE for entry in journal.all())


# --------------------------------------------------------------------------- #
# Surviving the machine it runs on
# --------------------------------------------------------------------------- #


def test_a_restart_keeps_the_position_and_its_reason(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """A four-hour setup holds for days and the laptop gets shut down.

    An account that started over on restart would drop exactly the trades whose
    length is the reason for running this at all.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    first, source, states, journal = build(tmp_path, config, tape, now_ms=start)
    assert advance_until_open(first, source), "nothing ever opened"

    before = first.broker.position or first.broker.pending
    assert before is not None, "nothing was working, so there was nothing to resume"
    saved_reason = states.load(SYMBOL)
    assert saved_reason is not None and saved_reason.reason is not None

    # A fresh process, same files.
    second = PaperTrader(
        SYMBOL,
        config,
        source=source,
        store=ParquetStore(tmp_path / "ohlcv"),
        state=states,
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(source.now_ms),
        strategy=FixedIntent(),  # type: ignore[arg-type]
    )
    after = second.broker.position or second.broker.pending
    assert after is not None
    assert after.side is before.side
    assert after.stop == pytest.approx(before.stop)
    assert after.target == pytest.approx(before.target)
    assert second.broker.equity == pytest.approx(first.broker.equity)

    closed = advance(second, source, hours=14)
    assert closed, "the resumed trade never ended"
    assert closed[0].reason.rating == saved_reason.reason.rating


def test_the_restored_side_is_an_enum_not_a_string(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """`StrEnum` compares equal to its text, so a string would work until the
    first `is` -- and the broker decides every exit with `side is Side.LONG`.
    A stop that silently stopped firing would look like a market that never
    reached it."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, _journal = build(
        tmp_path, config, tape, now_ms=start, strategy=FixedIntent(stop_atr=UNREACHABLE_STOP)
    )
    assert advance_until_open(trader, source), "nothing ever opened"

    saved = states.load(SYMBOL)
    assert saved is not None
    working = saved.position or saved.pending
    assert working is not None
    assert type(working.side) is Side


def test_a_minute_is_never_settled_twice(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Funding charged again, a stop hit again. Resumed by timestamp rather
    than by how many rows were read, because the process may have been off for
    a day."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, _journal = build(tmp_path, config, tape, now_ms=start)
    advance(trader, source, hours=6)

    mark = states.load(SYMBOL)
    assert mark is not None
    equity = trader.broker.equity

    # Same cycle again with no new bars: nothing may move.
    trader.step()
    trader.step()

    again = states.load(SYMBOL)
    assert again is not None
    assert again.last_minute_ts == mark.last_minute_ts
    assert trader.broker.equity == pytest.approx(equity)


def test_funding_is_not_charged_twice_across_a_restart(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The funding cursor is advanced to the last settled minute on resume.

    Without it, a trade held across a restart pays for every settlement since
    the beginning of the rate history -- a cost that grows with how long the
    file is, which is the kind of bug that gets worse quietly.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    rates = [FundingRate(ts=EPOCH + i * 8 * 3_600_000, rate=0.0001) for i in range(1, 400)]
    trader, source, states, journal = build(
        tmp_path,
        config,
        tape,
        now_ms=start,
        funding=rates,
        strategy=FixedIntent(stop_atr=UNREACHABLE_STOP),
    )
    assert advance_until_open(trader, source), "nothing ever opened"
    advance(trader, source, hours=10)
    assert trader.broker.position is not None, "the order never filled"
    paid = trader.broker.position.funding_paid

    resumed = PaperTrader(
        SYMBOL,
        config,
        source=source,
        store=ParquetStore(tmp_path / "ohlcv"),
        state=states,
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(source.now_ms),
        funding=rates,
        strategy=FixedIntent(stop_atr=UNREACHABLE_STOP),  # type: ignore[arg-type]
    )
    resumed.step()
    if resumed.broker.position is not None:
        # One cycle adds at most the settlements inside it, never the history.
        assert abs(resumed.broker.position.funding_paid - paid) < abs(paid) + 1.0


# --------------------------------------------------------------------------- #
# Behaving like the backtest it has to stay comparable with
# --------------------------------------------------------------------------- #


def test_nothing_is_proposed_while_a_position_is_open(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """One position per symbol, same as the broker and same as the backtest.

    Asking anyway would record refusals that say nothing about the rules and
    make the live refusal count incomparable with the measured one. Run with a
    stop the fixture cannot reach, so the trade is still open on every cycle
    after the first -- otherwise a strategy asked again after one closed looks
    like a violation and is not.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    strategy = FixedIntent(stop_atr=UNREACHABLE_STOP)
    trader, source, _states, _journal = build(
        tmp_path, config, tape, now_ms=start, strategy=strategy
    )

    assert advance_until_open(trader, source), "nothing ever opened"
    asked = strategy.asked

    advance(trader, source, hours=6)
    assert not trader.broker.is_flat, "the unreachable stop was reached; fixture changed"
    assert strategy.asked == asked, "the strategy was asked while a trade was open"


def test_the_exit_comes_from_the_simulator(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """A long stopped out exits at or below its stop, never above it.

    The point is not the inequality but where it comes from: `SimBroker`
    resolves it, slippage and gaps included. A forward trader with its own fill
    logic would be a second answer to the same question, differing by about as
    much as the effects being measured.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, _states, _journal = build(tmp_path, config, tape, now_ms=start)
    closed = advance(trader, source, hours=20)

    assert closed, "nothing resolved in five days"
    for entry in closed:
        if entry.exit_reason is ExitReason.STOP:
            assert entry.exit_price <= entry.reason.stop
        if entry.exit_reason is ExitReason.TARGET:
            assert entry.exit_price >= entry.reason.target


def test_a_gap_is_closed_from_the_venue_before_the_trade_is_resolved(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The laptop-closed-overnight case, and it decides the exit price.

    A cycle fetches four hours of minutes. Come back sixteen hours behind and
    the stop was hit in the part nobody fetched -- so resolving the trade
    against the oldest minute this cycle happens to see would place the exit
    hours late, at a price the market never offered, and in the direction that
    flatters the account. The missing minutes are pulled from the venue first.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, _journal = build(tmp_path, config, tape, now_ms=start)
    assert advance_until_open(trader, source), "nothing ever opened"
    settled = states.load(SYMBOL)
    assert settled is not None
    mark = settled.last_minute_ts

    # The process was off for ten hours: the clock moved, no cycle ran.
    source.now_ms += 10 * timeframe_ms(Timeframe.H1)
    trader.clock = FixedClock(source.now_ms)
    trader.step()

    after = states.load(SYMBOL)
    assert after is not None
    # Every minute in the gap was walked, not skipped: the account's clock lands
    # on the newest minute and the trade that resolved inside the gap resolved
    # at the minute it actually happened on.
    assert after.last_minute_ts > mark + 9 * timeframe_ms(Timeframe.H1)
    closed = [fill for fill in trader.broker.fills]
    if closed:
        assert closed[0].closed_ts <= source.now_ms
        assert closed[0].closed_ts > mark


def test_a_failed_refresh_costs_a_cycle_not_the_run(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """A loop that dies on one bad API response stops watching its own open
    position, which is worse than missing a cycle."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, _states, _journal = build(tmp_path, config, tape, now_ms=start)
    advance(trader, source, hours=2)

    source.fail_next = True
    assert trader.step() == []
    assert trader.stats.errors, "a failure passed silently"

    source.now_ms += timeframe_ms(Timeframe.H1)
    trader.clock = FixedClock(source.now_ms)
    trader.step()
    assert trader.stats.cycles >= 4


def test_closing_out_journals_the_open_trade(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """An open trade dropped on shutdown is a loser the statistics never see --
    the same hole the backtest closes at the end of its window."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, _states, journal = build(
        tmp_path, config, tape, now_ms=start, strategy=FixedIntent(stop_atr=UNREACHABLE_STOP)
    )
    assert advance_until_open(trader, source), "nothing ever opened"
    advance(trader, source, hours=2)
    if trader.broker.position is None:
        pytest.skip("the order never filled, so there was nothing to close out")
    before = journal.count()

    entry = trader.close_out()

    assert entry is not None
    assert entry.exit_reason is ExitReason.MANUAL
    assert journal.count() == before + 1
    assert trader.broker.is_flat


def test_a_fill_with_no_reason_is_not_journalled(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """It can only happen if the state file was lost mid-trade, and a row saying
    "lost 1 R" for reasons unknown is what the journal exists to prevent.
    Dropped and counted, never written blank."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, _states, journal = build(
        tmp_path, config, tape, now_ms=start, strategy=FixedIntent(stop_atr=UNREACHABLE_STOP)
    )
    assert advance_until_open(trader, source), "nothing ever opened"
    advance(trader, source, hours=2)
    if trader.broker.position is None:
        pytest.skip("the order never filled")
    before = journal.count()

    trader._reason = None
    entry = trader.close_out()

    assert entry is None
    assert journal.count() == before
    assert any("fehlt" in error for error in trader.stats.errors)


def test_the_account_can_be_started_over(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Deliberately, and without touching the journal: what happened happened."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, journal = build(tmp_path, config, tape, now_ms=start)
    advance(trader, source, hours=14)
    recorded = journal.count()
    assert recorded > 0

    states.forget(SYMBOL)
    assert states.load(SYMBOL) is None
    assert journal.count() == recorded


# --------------------------------------------------------------------------- #
# What the screen is told
# --------------------------------------------------------------------------- #


def test_the_screen_is_never_shown_replayed_trades_as_forward_ones(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The journal holds thousands of replayed trades beside the forward ones.

    A panel headed "Papertrading" that averaged both would be reporting an edge
    measured on a stretch of history somebody chose knowing how it went. The
    filter is not a display preference.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, journal = build(tmp_path, config, tape, now_ms=start)
    closed = advance(trader, source, hours=20)
    assert closed, "nothing resolved"

    # Smuggle in a replayed trade with an impossible result.
    faked = dataclasses.replace(closed[0], trade_id="fake-1", source=Source.REPLAY, r_multiple=99.0)
    journal.record([faked])

    readout = build_paper_readout(states.path, journal.path, now_ms=source.now_ms, symbols=[SYMBOL])

    assert readout.trades == len(journal.all(source=Source.LIVE))
    assert readout.mean_r < 1.0, "a replayed trade leaked into the forward average"
    assert all(trade.r_multiple != 99.0 for trade in readout.recent)


def test_a_stopped_trader_does_not_look_like_a_working_one(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The failure that cost an hour on the score panel, in a new place.

    A screen showing an account whose last settled minute is hours old renders
    identically to one showing a live system unless the age is part of the
    payload.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, journal = build(tmp_path, config, tape, now_ms=start)
    advance(trader, source, hours=3)

    fresh = build_paper_readout(
        states.path, journal.path, now_ms=source.now_ms + 60_000, symbols=[SYMBOL]
    )
    assert not fresh.accounts[0].stale
    assert fresh.running

    later = build_paper_readout(
        states.path, journal.path, now_ms=source.now_ms + 6 * 3_600_000, symbols=[SYMBOL]
    )
    assert later.accounts[0].stale
    assert later.accounts[0].behind_minutes >= 300
    assert not later.running


def test_an_open_position_reaches_the_screen_with_its_plan(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Entry, stop, target, open profit and which setup it came from.

    Without the setup and its timeframe the panel says a position exists; with
    them it says what the system thought it was doing, which is the only part
    worth reading twice.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, journal = build(
        tmp_path, config, tape, now_ms=start, strategy=FixedIntent(stop_atr=UNREACHABLE_STOP)
    )
    assert advance_until_open(trader, source), "nothing ever opened"
    advance(trader, source, hours=3)
    if trader.broker.position is None:
        pytest.skip("the order never filled")

    readout = build_paper_readout(states.path, journal.path, now_ms=source.now_ms, symbols=[SYMBOL])
    account = readout.accounts[0]

    assert account.position is not None
    assert account.position.entry > 0
    assert account.position.stop < account.position.entry  # the long it was told to take
    assert account.position.target > account.position.entry
    assert account.setup_timeframe, "the panel cannot say which chart this came from"
    assert account.rating is not None


def test_a_replay_cannot_overwrite_a_forward_trade(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The journal replaces a row that already has the same id.

    That is right for replay -- re-running a period should correct it rather
    than double it -- and it was almost fatal here: a replay of this week would
    have carried exactly the ids of this week's forward trades and silently
    overwritten the only evidence in the project that replay cannot produce.
    `python scripts/paper.py --replay` is a routine command.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, _states, journal = build(tmp_path, config, tape, now_ms=start)
    closed = advance(trader, source, hours=20)
    assert closed, "nothing resolved"

    live = closed[0]
    assert live.trade_id.startswith("live-")

    # The replay path would have produced this id for the same decision bar.
    collided = dataclasses.replace(
        live,
        trade_id=live.trade_id.removeprefix("live-"),
        source=Source.REPLAY,
        r_multiple=-99.0,
    )
    journal.record([collided])

    survived = [
        entry for entry in journal.all(source=Source.LIVE) if entry.trade_id == live.trade_id
    ]
    assert len(survived) == 1
    assert survived[0].r_multiple == live.r_multiple


# --------------------------------------------------------------------------- #
# Why nothing is happening
# --------------------------------------------------------------------------- #


def test_the_counters_survive_a_restart(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """An account flat for three days should say three days.

    Held only in memory the counters were printed at shutdown, which is exactly
    when they stop being useful: the case they exist for is a trader that has
    been running a long time and traded nothing.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    first, source, states, journal = build(tmp_path, config, tape, now_ms=start)
    advance(first, source, hours=5)
    seen = first.stats.tally.bars_seen
    assert seen >= 3

    second = PaperTrader(
        SYMBOL,
        config,
        source=source,
        store=ParquetStore(tmp_path / "ohlcv"),
        state=states,
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(source.now_ms),
        strategy=FixedIntent(),  # type: ignore[arg-type]
    )
    assert second.stats.tally.bars_seen == seen
    advance(second, source, hours=2)
    assert second.stats.tally.bars_seen > seen


def test_the_sentence_separates_no_setup_from_every_setup_refused(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Two different problems with two different answers.

    A market that offered nothing wants patience; a risk layer that refused
    every setup wants the stop width looked at. "Flach" says neither.
    """
    quiet = Tally(cycles=400, bars_seen=72, proposed=0)
    assert "kein Setup" in quiet.sentence()

    refused = Tally(cycles=400, bars_seen=72, proposed=9, refused_by_risk=9)
    assert "Risikoschicht" in refused.sentence()

    cold = Tally(cycles=4, bars_seen=0)
    assert "keine Kerze" in cold.sentence()

    working = Tally(cycles=400, bars_seen=72, proposed=9, opened=3, closed=2)
    assert "eröffnet" in working.sentence()


def test_an_account_file_from_before_the_counters_still_opens(
    tmp_path: Path, config: AppConfig
) -> None:
    """`CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it was.

    So a column added later is missing from every file already in use, and
    every read of it fails -- on a file that may be holding an open position.
    Four accounts were already running when this column was added.
    """
    path = tmp_path / "paper.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE accounts (symbol TEXT PRIMARY KEY, equity REAL NOT NULL, "
            "last_minute_ts INTEGER NOT NULL, last_decided_ts INTEGER NOT NULL, "
            "last_price REAL NOT NULL, opened_ts INTEGER NOT NULL, "
            "pending TEXT, position TEXT, reason TEXT)"
        )
        conn.execute(
            "INSERT INTO accounts VALUES ('BTCUSDT', 9876.5, 17, 16, 42.0, 0, NULL, NULL, NULL)"
        )
        conn.commit()

    store = PaperStateStore(path)
    restored = store.load("BTCUSDT")

    assert restored is not None
    assert restored.equity == pytest.approx(9876.5)
    assert restored.tally == Tally()
    store.save(restored)


def test_a_broken_loop_does_not_read_as_a_quiet_market(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The sentence has to be able to say "everything is throwing".

    Otherwise "say why nothing is happening" answers every question except the
    one where something is actually wrong, and a loop failing every cycle for
    an hour looks exactly like a market that offered no setup.
    """
    broken = Tally(cycles=40, failures=39, bars_seen=0)
    assert broken.mostly_failing
    assert "scheitern" in broken.sentence()

    # One bad response in a long run is not a broken loop.
    flaky = Tally(cycles=400, failures=3, bars_seen=70, proposed=0)
    assert not flaky.mostly_failing
    assert "kein Setup" in flaky.sentence()


def test_a_failed_decision_does_not_discard_settled_minutes(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Settling is what an open position depends on; deciding is not.

    Under one try/except a decision that raised took the settled minutes with
    it -- the position's own record thrown away by a failure in the half that
    was not about it.
    """

    class Exploding:
        name = "exploding"

        def propose_at(self, analysis: object, index: int) -> None:
            raise RuntimeError("boom")

    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, _journal = build(
        tmp_path, config, tape, now_ms=start, strategy=Exploding()
    )

    advance(trader, source, hours=3)

    saved = states.load(SYMBOL)
    assert saved is not None
    assert saved.last_minute_ts > 0, "the settled minutes were thrown away with the decision"
    assert saved.tally.failures >= 1
    assert any("Entscheiden" in error for error in trader.stats.errors)


def test_settling_every_market_comes_before_deciding_for_any(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """With a dozen markets, interleaving costs an open position its exits.

    Deciding builds the analysis -- ten to fifteen seconds a market. Settling is
    a fetch and a walk over a few minutes, and it is the half an open position
    depends on. Done market by market, one market's analysis delays every other
    market's exit by as long as it takes.

    The split is what lets a runner settle all of them first. Here it is checked
    directly: settling must not ask the strategy anything.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    strategy = FixedIntent(stop_atr=UNREACHABLE_STOP)
    trader, source, _states, _journal = build(
        tmp_path, config, tape, now_ms=start, strategy=strategy
    )

    source.now_ms += timeframe_ms(Timeframe.H1)
    trader.clock = FixedClock(source.now_ms)

    trader.settle()
    assert strategy.asked == 0, "settling reached the strategy; the halves are not separate"
    assert trader.wants_decision, "a new bar closed and nothing noticed"

    trader.decide()
    assert strategy.asked == 1
    assert not trader.wants_decision, "the decision was not marked as taken"


def test_deciding_twice_on_one_bar_does_nothing_the_second_time(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The runner calls decide once per cycle whether or not a bar closed.

    Without the guard a flat market would rebuild its analysis every thirty
    seconds -- fifteen seconds of work, twice a minute, per market -- and the
    loop would never finish a pass.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    strategy = FixedIntent(stop_atr=UNREACHABLE_STOP)
    trader, source, _states, _journal = build(
        tmp_path, config, tape, now_ms=start, strategy=strategy
    )

    source.now_ms += timeframe_ms(Timeframe.H1)
    trader.clock = FixedClock(source.now_ms)
    trader.settle()
    trader.decide()
    asked = strategy.asked

    trader.decide()
    trader.decide()

    assert strategy.asked == asked, "the same bar was decided more than once"


# --------------------------------------------------------------------------- #
# A cycle that throws must not spend the bar
# --------------------------------------------------------------------------- #


class ThrowingIntent(FixedIntent):
    """A strategy that fails the first `fails` times it is asked.

    Standing in for what actually goes wrong on the forward path: a fetch that
    timed out, a frame that arrived one bar short. The failure is transient, and
    what mattered was whether the signal survived it.
    """

    def __init__(self, *, fails: int) -> None:
        super().__init__()
        self.fails = fails
        self.thrown = 0

    def propose_at(self, analysis: object, index: int) -> TradeIntent | None:
        if self.thrown < self.fails:
            self.thrown += 1
            raise RuntimeError("Rahmen unvollständig")
        return super().propose_at(analysis, index)


def test_a_cycle_that_throws_does_not_burn_the_signal_bar(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """The bar is read again next cycle, because the signal is the scarce thing.

    `decide` used to mark the bar decided *before* asking the setups, and
    persisted afterwards even from the except branch -- so one timed-out fetch
    destroyed that signal permanently and nothing in the record said so. At
    roughly two signals a day across twelve markets, and with forward evidence
    the only kind section 9 calls decisive, that is the most expensive silent
    loss in the loop.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    strategy = ThrowingIntent(fails=1)
    trader, _source, states, _journal = build(
        tmp_path, config, tape, now_ms=start, strategy=strategy
    )

    trader.step()
    assert strategy.thrown == 1, "the strategy was never asked"
    assert trader.stats.tally.failures == 1
    assert trader.wants_decision, "the bar was marked decided although the cycle threw"
    assert trader.stats.tally.bars_seen == 0, "a bar nobody decided was counted as seen"

    # The same bar, asked again, now succeeds -- and the signal is not lost.
    trader.step()
    assert not trader.wants_decision
    assert trader.stats.tally.bars_seen == 1
    saved = states.load(SYMBOL)
    assert saved is not None
    assert saved.pending is not None or saved.position is not None, "the signal was lost"


def test_an_unreadable_bar_is_given_up_on_and_counted(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Retrying for ever would stop the account deciding anything again.

    So the bar is abandoned -- but it is still evidence that was lost rather
    than measured, and `abandoned_bars` is separate from `failures` for exactly
    that reason: a cycle that threw and then succeeded cost nothing.
    """
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    strategy = ThrowingIntent(fails=99)
    trader, _source, _states, _journal = build(
        tmp_path, config, tape, now_ms=start, strategy=strategy
    )

    for _ in range(3):
        trader.step()

    assert trader.stats.tally.abandoned_bars == 1
    assert not trader.wants_decision, "the loop is still stuck on one bar"
    assert trader.stats.tally.bars_seen == 1
    # And it moves on: the next bar gets its own attempts rather than inheriting
    # the exhausted count.
    assert trader.stats.tally.failures >= 3


def test_the_abandoned_counter_survives_a_restart(
    tmp_path: Path, config: AppConfig, tape: dict[Timeframe, pd.DataFrame]
) -> None:
    """Lost evidence has to stay visible, or the loop looks like a quiet market."""
    start = EPOCH + timeframe_ms(Timeframe.H1) * START_BAR
    trader, source, states, journal = build(
        tmp_path, config, tape, now_ms=start, strategy=ThrowingIntent(fails=99)
    )
    for _ in range(3):
        trader.step()
    assert trader.stats.tally.abandoned_bars == 1

    resumed = PaperTrader(
        SYMBOL,
        config,
        source=source,
        store=ParquetStore(tmp_path / "ohlcv"),
        state=states,
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(source.now_ms),
        strategy=FixedIntent(),  # type: ignore[arg-type]
    )
    assert resumed.stats.tally.abandoned_bars == 1
