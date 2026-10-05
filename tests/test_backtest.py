"""The backtest loop end to end.

Two things are checked here that no unit test reaches.

**Nothing fills in the bar it was decided on.** A decision taken at the close of an
hour can only be acted on from the next hour. Filling within the same bar is a
silent one-hour head start, and it is enough on its own to turn a losing strategy
into a winning backtest -- because the bar the signal fired on is, by construction,
a bar that moved.

**The whole run is frozen.** A golden hash over the fills and the equity curve
means any change to the simulation, the sizing or the strategy shows up as a
deliberate decision rather than as a quietly different number in a report nobody
diffed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

import pandas as pd
import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH, aggregate, fast_engine_config, multi_frame_fixture
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import ExitReason, Timeframe
from traidingbrain.domain.market import FundingRate
from traidingbrain.journal.signals import Action, SignalStore
from traidingbrain.sim.engine import BacktestResult, MissingMinuteDataError, load_engine
from traidingbrain.sim.metrics import compare
from traidingbrain.strategies.baseline import RandomEntry, StructureBaseline

H1_MS = timeframe_ms(Timeframe.H1)


#: Starting equity the frozen run is measured at.
#:
#: Pinned rather than read from the configuration. `initial_equity` is a
#: preference -- Severin moved it from ten thousand to one thousand because the
#: smaller number is what he will actually have -- and position size is risk
#: divided by stop distance, so every fill price and the whole equity curve move
#: with it. Inheriting it meant the golden file failed on a change that was not
#: about the engine at all, and the only ways out were to regenerate the golden
#: (which hides whatever else moved with it) or to leave a red test standing.
#:
#: The guard is about the simulator, the sizing rules and the strategy. The
#: account they run on is an input, and an input a test depends on belongs in
#: the test.
GOLDEN_EQUITY = 10_000.0


@pytest.fixture(scope="module")
def config() -> AppConfig:
    """Shipped risk rules, short analysis warm-up, pinned starting equity.

    The risk side is deliberately the real thing: a golden run that used toy sizing
    would not protect the numbers anyone actually looks at.
    """
    base = load_config()
    engine = fast_engine_config()
    return base.model_copy(
        update={
            "engine": engine.model_copy(
                update={
                    "simulation": engine.simulation.model_copy(
                        update={"initial_equity": GOLDEN_EQUITY}
                    )
                }
            )
        }
    )


@pytest.fixture(scope="module")
def frames() -> dict[Timeframe, pd.DataFrame]:
    return multi_frame_fixture(8000)


@pytest.fixture(scope="module")
def minutes(frames: dict[Timeframe, pd.DataFrame]) -> pd.DataFrame:
    """M1 built from the same series, so intrabar resolution is self-consistent.

    A fixture whose minutes disagreed with its hours would let a bug in the exit
    logic pass unnoticed.
    """
    return aggregate(frames[Timeframe.M15], Timeframe.M1)


@pytest.fixture(scope="module")
def engine(config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame):
    return load_engine(
        "TESTUSDT",
        frames,
        minute_frame=minutes,
        spec=make_symbol_spec(),
        config=config,
        funding=[],
    )


@pytest.fixture(scope="module")
def baseline_run(engine) -> BacktestResult:
    return engine.run(StructureBaseline())


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


def test_the_run_produces_trades(baseline_run: BacktestResult) -> None:
    """Guard against a suite that passes because nothing ever happens."""
    assert baseline_run.snapshots_built > 100
    assert baseline_run.intents > 0
    assert baseline_run.metrics.trades > 0


def test_nothing_fills_before_the_bar_after_the_decision(baseline_run: BacktestResult) -> None:
    """The head start that makes a backtest lie.

    The bar a signal fires on is by construction a bar that moved. Allowing a fill
    inside it hands the strategy the move it was reacting to.
    """
    for fill in baseline_run.fills:
        assert fill.opened_ts >= baseline_run.first_ts + H1_MS, (
            f"a position opened at {fill.opened_ts}, before the next bar had begun"
        )


def test_every_exit_comes_after_its_entry(baseline_run: BacktestResult) -> None:
    for fill in baseline_run.fills:
        assert fill.closed_ts >= fill.opened_ts


def test_the_equity_curve_is_marked_every_bar(baseline_run: BacktestResult) -> None:
    curve = baseline_run.equity_curve
    assert len(curve) > 100
    stamps = [ts for ts, _ in curve]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


def test_no_position_survives_the_end_of_the_run(baseline_run: BacktestResult) -> None:
    """Anything still open is closed at the last price rather than dropped.

    Dropping open trades quietly discards the losers a strategy was still sitting
    in, which is the most flattering possible way to end a backtest.
    """
    assert baseline_run.metrics.trades == len(baseline_run.fills)


def test_risk_per_trade_never_exceeds_the_configured_ceiling(
    baseline_run: BacktestResult, config: AppConfig
) -> None:
    """The cap is enforced on every trade, not on average."""
    ceiling = config.risk.sizing.absolute_max_risk_pct
    equity = config.engine.simulation.initial_equity
    for fill in baseline_run.fills:
        # Equity only falls in a losing run, so the starting value is the loosest
        # possible bound and still holds.
        assert fill.risk_amount <= equity * ceiling * 1.01


def test_no_trade_is_liquidated(baseline_run: BacktestResult) -> None:
    """Leverage is derived so that the stop is always reached first.

    A liquidation here means that derivation is wrong, and the account would have
    lost its whole margin on a trade that was supposed to risk one percent.
    """
    assert baseline_run.metrics.liquidations == 0


def test_running_the_same_backtest_twice_gives_the_same_answer(engine) -> None:
    first = engine.run(StructureBaseline())
    second = engine.run(StructureBaseline())

    assert first.metrics.trades == second.metrics.trades
    assert first.metrics.final_equity == pytest.approx(second.metrics.final_equity)


def test_max_bars_shortens_the_run(engine) -> None:
    short = engine.run(StructureBaseline(), max_bars=200)
    assert short.snapshots_built <= 200


# --------------------------------------------------------------------------- #
# Strategies against each other
# --------------------------------------------------------------------------- #


def test_random_entry_trades_in_both_directions(engine) -> None:
    """The null hypothesis has to actually be a coin flip."""
    result = engine.run(RandomEntry(seed=3, trade_probability=0.1))
    sides = {fill.side for fill in result.fills}
    assert len(sides) == 2, f"random entry only ever went {sides}"


def test_the_comparison_refuses_to_overclaim(engine) -> None:
    """Overlapping intervals mean the data did not distinguish the two.

    Reporting the larger point estimate as a winner is how a strategy gets adopted
    on the strength of sampling noise.
    """
    baseline = engine.run(StructureBaseline())
    random = engine.run(RandomEntry(seed=5, trade_probability=0.05))

    text = compare(random.metrics, baseline.metrics)

    assert "expectancy" in text
    if not (baseline.metrics.has_enough_trades and random.metrics.has_enough_trades):
        assert "Too few trades" in text
    else:
        overlap = not (
            baseline.metrics.expectancy_r.low > random.metrics.expectancy_r.high
            or baseline.metrics.expectancy_r.high < random.metrics.expectancy_r.low
        )
        assert ("does not distinguish" in text) is overlap


# --------------------------------------------------------------------------- #
# Frozen
# --------------------------------------------------------------------------- #


def fingerprint(result: BacktestResult) -> dict[str, object]:
    """A compact, stable description of an entire run."""
    trades = [
        {
            "side": fill.side.value,
            "reason": fill.reason.value,
            "opened": fill.opened_ts,
            "closed": fill.closed_ts,
            "entry": round(fill.entry_price, 6),
            "exit": round(fill.exit_price, 6),
            "qty": round(fill.qty, 8),
            "leverage": fill.leverage,
            "r": round(fill.r_multiple, 6),
        }
        for fill in result.fills
    ]
    curve = hashlib.sha256(
        json.dumps([[ts, round(v, 6)] for ts, v in result.equity_curve]).encode()
    ).hexdigest()
    return {
        "strategy": result.strategy,
        "snapshots": result.snapshots_built,
        "intents": result.intents,
        "trades": trades,
        "equity_curve_sha256": curve,
        "final_equity": round(result.metrics.final_equity, 6),
    }


def test_the_baseline_run_is_frozen(
    baseline_run: BacktestResult, golden: Callable[[str, object], None]
) -> None:
    """Every trade, every fill price, and a hash of the equity curve.

    This fails on any change to the simulator, the sizing or the strategy. That is
    the point: those changes move every number in every report, and they should be
    noticed when they are made rather than wondered about later.

    **Re-frozen 05.10.2026**, when `max_cost_fraction_of_risk` moved from 0.15
    to 0.08 (`scripts/study_costcap.py`, `config/risk.yaml`). The run now
    refuses one more signal on cost: 7 trades and 8 risk rejections instead of
    8 and 7. The file did its job -- it noticed -- and the change was intended,
    so the reference moved with a reason recorded here rather than quietly.
    """
    golden("backtest_baseline", fingerprint(baseline_run))


#: Seed whose run exits through the target as often as through the stop.
#:
#: The baseline run above is 7 stops and 1 forced close -- not one take profit
#: in it. So the frozen guard covered only the losing path, and the change that
#: made a target exit earn the maker fee instead of the taker one moved real
#: money through code no golden file was watching. It was caught by a unit test
#: that happened to assert the old rate; had that test not existed, nothing
#: would have failed.
#:
#: 6 targets against 4 stops and one forced close, which is the mix the guard
#: was missing.
#:
#: It was 31 against 23 until 05.10.2026, when `max_cost_fraction_of_risk` went
#: from 0.15 to 0.08 and the cost rule refused four fifths of this run. The
#: property that matters survived the cut and was checked rather than assumed:
#: targets still outnumber stops, so the winning path is still covered. Had
#: they dropped to zero, re-freezing would have gutted the one thing this guard
#: exists for, and the right move would have been a new seed instead.
TARGET_SEED = 1


@pytest.fixture(scope="module")
def target_run(engine) -> BacktestResult:
    return engine.run(RandomEntry(seed=TARGET_SEED, trade_probability=0.1))


def test_the_fixture_still_exits_through_the_target(target_run: BacktestResult) -> None:
    """Guard on the guard below.

    The run exists only for its take profits, and it reaches them through the
    strategy's own entries rather than by construction. A change elsewhere could
    leave it passing with nothing but stops in it -- a frozen file over the wrong
    mix, which is worse than no file because it looks like coverage.
    """
    reasons = {fill.reason for fill in target_run.fills}

    assert ExitReason.TARGET in reasons, f"no take profit left in the run, only {reasons}"
    assert ExitReason.STOP in reasons, "both paths belong in one frozen run"


def test_the_winning_path_is_frozen(
    target_run: BacktestResult, golden: Callable[[str, object], None]
) -> None:
    """The same freeze as the baseline, over a run that actually wins.

    Fees differ by exit route -- a target rests in the book and earns maker, a
    stop leaves at market and pays taker -- so the two paths are separate code
    with separate arithmetic, and one frozen run cannot speak for both.
    """
    golden("backtest_target_exits", fingerprint(target_run))


def test_funding_changes_the_result(
    config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    """Holding costs are small per settlement and not small in aggregate.

    If they made no difference the simulator would be ignoring them, which is the
    normal state of affairs in backtests and the reason live results disappoint.
    """
    rates = [FundingRate(ts=EPOCH + i * 8 * 60 * 60_000, rate=0.0005) for i in range(1, 400)]
    with_funding = load_engine(
        "TESTUSDT",
        frames,
        minute_frame=minutes,
        spec=make_symbol_spec(),
        config=config,
        funding=rates,
    ).run(StructureBaseline())
    without = load_engine(
        "TESTUSDT",
        frames,
        minute_frame=minutes,
        spec=make_symbol_spec(),
        config=config,
        funding=[],
    ).run(StructureBaseline())

    assert with_funding.metrics.funding != 0.0
    assert with_funding.metrics.final_equity != pytest.approx(without.metrics.final_equity)


# --------------------------------------------------------------------------- #
# Minute coverage
# --------------------------------------------------------------------------- #


def test_a_window_the_minutes_do_not_reach_is_trimmed_and_reported(
    config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    """Missing minute data must stop the run, not quietly empty it.

    The minute series decides whether the stop or the target came first inside an
    hour. Where it is absent nothing fills, every entry expires, and the report
    reads "no trades" -- indistinguishable from a strategy that found nothing,
    and the number someone would act on.

    This is reachable by ordinary use: extending the candle history further back
    without extending the minute history produces exactly this state.
    """
    half = minutes.loc[minutes["ts"] >= minutes["ts"].quantile(0.6)].reset_index(drop=True)
    engine = load_engine(
        "TESTUSDT",
        frames,
        minute_frame=half,
        spec=make_symbol_spec(),
        config=config,
        funding=[],
    )

    result = engine.run(StructureBaseline())

    assert result.window_note, "the run was trimmed and said nothing about it"
    assert "minute data covers" in result.window_note
    assert "WINDOW" in result.summary()


def test_a_trim_at_the_head_moves_the_reported_window(
    config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    late = minutes.loc[minutes["ts"] >= minutes["ts"].quantile(0.6)].reset_index(drop=True)
    engine = load_engine(
        "TESTUSDT", frames, minute_frame=late, spec=make_symbol_spec(), config=config, funding=[]
    )

    result = engine.run(StructureBaseline())

    # Trimmed at the head, so the reported window starts later than asked.
    assert result.first_ts >= int(late["ts"].min())
    assert "days dropped" in result.window_note


def test_no_minute_data_at_all_is_refused(
    config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    engine = load_engine(
        "TESTUSDT",
        frames,
        minute_frame=minutes.iloc[0:0],
        spec=make_symbol_spec(),
        config=config,
        funding=[],
    )

    with pytest.raises(MissingMinuteDataError, match="no minute data at all"):
        engine.run(StructureBaseline())


def test_minutes_ending_inside_the_last_signal_bar_are_tolerated(
    config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    """The newest hour's minutes may still be forming. That is normal, not a hole.

    Trimmed by time rather than by row count: this fixture's "minutes" are
    fifteen-minute bars, so dropping thirty rows removes seven and a half hours
    and is a real gap, which is what the first version of this test accidentally
    asserted was fine.
    """
    signal_ms = timeframe_ms(config.engine.timeframes.signal)
    cutoff = int(minutes["ts"].max()) - signal_ms // 2
    trimmed = minutes.loc[minutes["ts"] <= cutoff].reset_index(drop=True)
    engine = load_engine(
        "TESTUSDT",
        frames,
        minute_frame=trimmed,
        spec=make_symbol_spec(),
        config=config,
        funding=[],
    )

    engine.run(StructureBaseline())


# --------------------------------------------------------------------------- #
# The signals the run did not trade
# --------------------------------------------------------------------------- #


def test_the_run_records_the_signals_the_risk_rules_refused(
    tmp_path, config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    """A refusal is a row, not an increment.

    `intents_rejected_by_risk` counts them and nothing more, so the five rules
    doing the refusing have never been checked against outcomes -- there was
    nothing to check. The ledger is what makes that question askable, and this
    test is what proves the ledger is actually being filled by a real run
    rather than only by its own unit tests.
    """
    store = SignalStore(tmp_path / "signals.sqlite")
    result = load_engine(
        "TESTUSDT",
        frames,
        minute_frame=minutes,
        spec=make_symbol_spec(),
        config=config,
        funding=[],
        signals=store,
        run_signature="test",
    ).run(StructureBaseline())

    recorded = store.all()
    assert recorded, "the run wrote no signals at all"

    # Every intent the engine assessed is one row, taken or refused.
    assert len(recorded) == result.intents
    taken = store.count(action=Action.TAKEN)
    refused = store.count(action=Action.REFUSED)
    assert taken + refused == result.intents
    assert refused == result.intents_rejected_by_risk, (
        "the ledger and the counter disagree about how many were refused"
    )

    # And a refusal names its rule and keeps the plan, so it can be labelled.
    for signal in store.all(action=Action.REFUSED):
        assert signal.refused_by is not None
        assert signal.detail
        assert signal.entry > 0 and signal.stop > 0 and signal.target > 0
        assert signal.symbol == "TESTUSDT"

    for signal in store.all(action=Action.TAKEN):
        assert signal.refused_by is None
        assert signal.qty > 0 and signal.leverage > 0


def test_a_rerun_of_the_same_period_does_not_double_the_ledger(
    tmp_path, config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    """Replaying the same bars under the same settings is a no-op.

    Without this the population would grow every time a study was re-run, and
    the counts would describe how often somebody pressed enter.
    """
    store = SignalStore(tmp_path / "signals.sqlite")

    def once() -> int:
        load_engine(
            "TESTUSDT",
            frames,
            minute_frame=minutes,
            spec=make_symbol_spec(),
            config=config,
            funding=[],
            signals=store,
            run_signature="same",
        ).run(StructureBaseline())
        return store.count()

    first = once()
    assert first > 0
    assert once() == first, "the second run added rows"


def test_the_shadow_pass_changes_nothing_that_trades(
    tmp_path, config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    """The property that makes the shadow pass free to turn on.

    It asks the strategy while the single slot is busy and records the answer.
    If a single one of those answers reached the broker, every number the
    project has measured would change and the comparison between arms would be
    meaningless. So the trades, the equity curve and the metrics must be
    identical with the pass on and off -- not close, identical.
    """
    def run(shadow: bool):
        return load_engine(
            "TESTUSDT",
            frames,
            minute_frame=minutes,
            spec=make_symbol_spec(),
            config=config,
            funding=[],
            signals=SignalStore(tmp_path / f"signals-{shadow}.sqlite"),
            run_signature="test",
            shadow=shadow,
        ).run(StructureBaseline())

    plain = run(shadow=False)
    shadowed = run(shadow=True)

    assert [f.exit_price for f in shadowed.fills] == [f.exit_price for f in plain.fills]
    assert [f.reason for f in shadowed.fills] == [f.reason for f in plain.fills]
    assert shadowed.equity_curve == plain.equity_curve
    assert shadowed.intents == plain.intents
    assert shadowed.intents_rejected_by_risk == plain.intents_rejected_by_risk
    assert plain.shadow_signals == 0, "the pass ran when it was not asked for"


def test_the_shadow_pass_records_what_the_slot_hid(
    tmp_path, config: AppConfig, frames: dict[Timeframe, pd.DataFrame], minutes: pd.DataFrame
) -> None:
    """And splits it by whether the rules would have taken it anyway.

    "There were N skipped signals" says nothing on its own: most may be ones
    the risk rules already refuse, and those rules are measurably right to.
    The row that matters is OCCUPIED with no rule attached -- a trade the
    system would have taken had a slot been free.
    """
    store = SignalStore(tmp_path / "signals.sqlite")
    result = load_engine(
        "TESTUSDT",
        frames,
        minute_frame=minutes,
        spec=make_symbol_spec(),
        config=config,
        funding=[],
        signals=store,
        run_signature="test",
        shadow=True,
    ).run(StructureBaseline())

    occupied = store.all(action=Action.OCCUPIED)
    assert len(occupied) == result.shadow_signals
    assert result.shadow_signals > 0, "no bar was ever reached with the slot busy"

    # The decomposition, and it has to agree with the counter.
    would_trade = [signal for signal in occupied if signal.refused_by is None]
    assert len(would_trade) == result.shadow_tradeable

    # A shadow row is a plan, so it can be labelled against minute data later.
    for signal in occupied:
        assert signal.entry > 0 and signal.stop > 0 and signal.target > 0
        assert signal.symbol == "TESTUSDT"

    # And it is not counted as something the run did.
    assert store.count(action=Action.TAKEN) + store.count(action=Action.REFUSED) == result.intents
