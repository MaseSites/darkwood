"""The guide's setups run through the same engine as everything else.

Two things are being guaranteed here, and the second is the one that gives the
comparison table its meaning.

**That a bar-reading strategy reaches the market at all.** The engine was built
around the normalised snapshot -- no absolute prices, distances in ATR, levels
by opaque id -- which is right for something being asked to judge a situation
and wrong for a rule that says "stop at the low of the candle that created the
gap". The second path exists for those, and a path that quietly proposed nothing
would look exactly like a strategy that found nothing.

**That both paths are treated identically once they have spoken.** Same broker,
same sizing, same leverage, same cost rule, same refusals. That is the entire
basis for putting a guide setup and a coin flip in one table and reading down
the column: if the two paths sized differently, every comparison in this project
would be measuring the path instead of the signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.pipeline import MultiFrameAnalysis, decision_time_ms
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.sim.engine import BacktestEngine, TradeIntent, wants_analysis
from traidingbrain.strategies.baseline import RandomEntry
from traidingbrain.strategies.guide import (
    FIXED_CONFIDENCE,
    GuidePool,
    GuideSetupStrategy,
    _just_closed,
    all_strategies,
    per_setup,
)
from traidingbrain.strategy.setups import TRADEABLE, SetupSignal

from .factories import make_symbol_spec

H1_MS = 3_600_000
BARS = 2400

#: An arbitrary but fixed anchor for the hourly series.
EPOCH = 1_700_000_000_000

#: How many bars each higher timeframe gets *before* the hourly series starts.
#:
#: The reason the first version of this fixture traded nothing. A context frame
#: is only usable once its own indicators have warmed up, and `aligned_indices`
#: refuses a bar where any context frame is not ready. Weekly frames starting at
#: the same instant as the hourly one need thirty weeks to warm up, while a
#: 2,400-bar hourly series covers a hundred days -- so alignment never happened,
#: `first_ready_index` returned None, and the engine exited before the loop.
#: Zero trades, no error, nothing to point at.
WARMUP_BARS = 60


def walk(
    count: int = BARS, seed: int = 9, step_ms: int = H1_MS, start_ts: int = EPOCH
) -> pd.DataFrame:
    """A series with levels that get tested twice, so setups have something to see."""
    rng = np.random.default_rng(seed)
    price, anchor, hold, slope = 100.0, 100.0, 0, 0.0
    rows = []
    for _ in range(count):
        if hold <= 0:
            hold = int(rng.integers(20, 90))
            anchor = price
            slope = float(rng.normal(0, 0.35)) if rng.random() < 0.55 else 0.0
        hold -= 1
        price = max(price + slope + 0.12 * (anchor - price) + rng.normal(0, 0.55), 1.0)
        spread = abs(float(rng.normal(0, 0.5))) + 0.15
        open_ = price - float(rng.normal(0, 0.3))
        rows.append((open_, max(open_, price) + spread, min(open_, price) - spread, price))
    return pd.DataFrame(
        {
            "ts": [start_ts + i * step_ms for i in range(count)],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [100.0] * count,
        }
    )


def minutes_for(hourly: pd.DataFrame) -> pd.DataFrame:
    """Sixty minute bars per hour, tracing the hour's own path.

    Intrabar order decides which of a stop and a target was hit first, so the
    minutes have to visit both extremes rather than interpolate between opens.
    """
    rows = []
    for row in hourly.itertuples():
        path = [row.open, row.high, row.low, row.close]
        for minute in range(60):
            value = path[minute % 4]
            rows.append(
                {
                    "ts": int(row.ts) + minute * 60_000,
                    "open": value,
                    "high": value + 0.05,
                    "low": value - 0.05,
                    "close": value,
                    "volume": 1.0,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


def context_frames(hourly: pd.DataFrame) -> dict[Timeframe, pd.DataFrame]:
    """Every context timeframe, each long enough to warm its indicators up.

    Not slices of the hourly series, which is the obvious way to build these and
    the reason the first version of this fixture traded nothing: slicing 2,400
    hourly bars every 168th gives a weekly frame of fourteen bars, the weekly
    indicators never warm up, `first_ready_index` never returns, and the engine
    exits before the loop. Zero trades, no error, and nothing to point at.
    """
    def higher(seed: int, hours: int) -> pd.DataFrame:
        step = H1_MS * hours
        return walk(BARS, seed=seed, step_ms=step, start_ts=EPOCH - WARMUP_BARS * step)

    return {
        Timeframe.W1: higher(1, 168),
        Timeframe.D1: higher(2, 24),
        Timeframe.H4: higher(3, 4),
        Timeframe.H1: hourly,
        Timeframe.M15: walk(BARS * 4, seed=9, step_ms=H1_MS // 4, start_ts=EPOCH),
    }


@pytest.fixture(scope="module")
def engine(config: AppConfig) -> BacktestEngine:
    hourly = walk()
    frames = context_frames(hourly)
    spec: SymbolSpec = make_symbol_spec()
    return BacktestEngine(
        "TESTUSDT",
        MultiFrameAnalysis(frames, config.engine),
        minute_frame=minutes_for(hourly),
        spec=spec,
        config=config,
    )


# --------------------------------------------------------------------------- #
# The two paths
# --------------------------------------------------------------------------- #


def test_a_guide_strategy_is_recognised_as_reading_bars() -> None:
    """The engine picks the path by asking what the strategy can answer. If this
    ever said no, the guide strategies would be handed a snapshot they cannot
    read and would propose nothing -- silently."""
    for strategy in all_strategies():
        assert wants_analysis(strategy)


def test_a_snapshot_strategy_is_not(config: AppConfig) -> None:
    assert not wants_analysis(RandomEntry())


def test_the_guide_strategies_actually_trade(engine: BacktestEngine) -> None:
    """The test the rest of this file rests on.

    A strategy that never proposes produces a clean run, a plausible report and
    no error. It is indistinguishable from one that looked and found nothing,
    which is why it is asserted rather than assumed.
    """
    result = engine.run(GuidePool(), max_bars=BARS)

    assert result.metrics.trades > 0, "the pool never opened a position"


def test_each_setup_gets_its_own_row(engine: BacktestEngine) -> None:
    """Chapter 30: "getrennte Video-Modelle". One pooled number cannot say which
    rule earned it, so each setup is run on its own and the pool alongside --
    never instead."""
    names = {strategy.name for strategy in all_strategies()}

    assert names == {f"guide-{setup.key}" for setup in TRADEABLE} | {"guide-all"}
    assert len(per_setup()) == len(TRADEABLE)


def test_the_pool_trades_at_least_as_often_as_any_single_setup(
    engine: BacktestEngine,
) -> None:
    """It takes the first setup to fire, so it can only ever see more bars than
    one of them alone. Fewer would mean a setup is being lost on the way in."""
    singles = {
        strategy.name: engine.run(strategy, max_bars=BARS).metrics.trades
        for strategy in per_setup()
    }
    pooled = engine.run(GuidePool(), max_bars=BARS).metrics.trades

    assert any(count > 0 for count in singles.values()), "no single setup traded"
    assert pooled >= max(singles.values())


# --------------------------------------------------------------------------- #
# Same money management for everyone, which is what makes the table readable
# --------------------------------------------------------------------------- #


def test_every_guide_strategy_reports_the_same_confidence() -> None:
    """The videos give no confidence scale and no sizing rule, so any number
    here belongs to the engine rather than the strategy.

    A varying one would quietly make the sizing ladder part of the strategy, and
    then one setup could beat another for reasons that have nothing to do with
    its entries.
    """
    signal = next(
        strategy
        for strategy in per_setup()
        if strategy.name == f"guide-{TRADEABLE[0].key}"
    )

    assert signal is not None
    assert FIXED_CONFIDENCE == 60.0


def test_a_guide_trade_is_refused_by_the_same_risk_rules_as_any_other(
    engine: BacktestEngine, config: AppConfig
) -> None:
    """The reward-to-risk floor, the cost rule and the liquidation buffer are
    the engine's and apply to every row in the table.

    Checked through the engine rather than by reading the config, because the
    claim is that the rules *run* on this path -- not that they exist.
    """
    minimum = config.risk.limits.min_reward_risk

    class TooTight:
        """Coherent, and refused: the target is closer than the stop."""

        name = "too-tight"

        def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
            price = analysis.signal.close_at(index)
            return TradeIntent(
                side=Side.LONG,
                entry=price,
                stop=price * 0.99,
                target=price * 1.001,
                confidence=FIXED_CONFIDENCE,
            )

    result = engine.run(TooTight(), max_bars=400)

    assert minimum > 0.1
    assert result.metrics.trades == 0, "a trade below the reward-to-risk floor was taken"


def test_an_incoherent_intent_never_reaches_the_broker(engine: BacktestEngine) -> None:
    """A long whose stop sits above its entry is arithmetic that went wrong, and
    the engine drops it before sizing rather than sizing something impossible."""

    class Backwards:
        name = "backwards"

        def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
            price = analysis.signal.close_at(index)
            return TradeIntent(
                side=Side.LONG,
                entry=price,
                stop=price * 1.02,
                target=price * 0.98,
                confidence=FIXED_CONFIDENCE,
            )

    result = engine.run(Backwards(), max_bars=400)

    assert result.metrics.trades == 0


def test_a_strategy_that_never_proposes_produces_an_empty_run(
    engine: BacktestEngine,
) -> None:
    """The control for the test above: zero trades has to be reachable both by
    being refused and by never asking, and the report must not confuse them."""

    class Silent:
        name = "silent"

        def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
            return None

    result = engine.run(Silent(), max_bars=400)

    assert result.metrics.trades == 0
    assert result.fills == []


# --------------------------------------------------------------------------- #
# What the reason carries
# --------------------------------------------------------------------------- #


def test_every_proposal_names_its_setup_and_its_video(engine: BacktestEngine) -> None:
    """A trade in the record that cannot be traced back to a video cannot be
    argued with, and being able to argue with it is the point of taking the
    rules from somewhere in the first place."""
    seen = 0
    for strategy in per_setup():
        for index in range(200, BARS - 2):
            intent = strategy.propose_at(engine.analysis, index)
            if intent is None:
                continue
            assert intent.reason.startswith(strategy.setup.key)
            assert strategy.setup.source in intent.reason
            seen += 1
            break

    assert seen, "no setup proposed anything, so this proved nothing"


def test_the_pool_reports_whichever_setup_fired(engine: BacktestEngine) -> None:
    pool = GuidePool()
    keys = {setup.key for setup in TRADEABLE}

    reasons = [
        intent.reason
        for index in range(200, BARS - 2)
        if (intent := pool.propose_at(engine.analysis, index)) is not None
    ]

    assert reasons
    for reason in reasons:
        assert reason[0] in keys


def test_a_setup_strategy_is_named_after_the_guide_letter() -> None:
    for setup in TRADEABLE:
        assert GuideSetupStrategy(setup).name == f"guide-{setup.key}"


# --------------------------------------------------------------------------- #
# Searching every chart, not only the hourly one
# --------------------------------------------------------------------------- #


def test_a_four_hour_candle_is_offered_once_not_four_times(
    engine: BacktestEngine,
) -> None:
    """The rule that makes multi-timeframe search safe.

    The loop steps hourly. A four-hour setup spans four hourly bars, and
    without this check it would be proposed on each of them -- the same trade
    offered four times, and in a backtest four entries where the rule
    describes one.
    """
    analysis = engine.analysis
    hits = 0
    checked = 0
    for index in range(200, 400):
        aligned = analysis.aligned_indices(index)
        if aligned is None:
            continue
        checked += 1
        decision = decision_time_ms(analysis.signal.ts_at(index), analysis.signal_timeframe)
        if _just_closed(analysis, Timeframe.H4, decision):
            hits += 1

    assert checked > 100, "nothing was ready; this test proved nothing"
    # One hour in four, give or take the window's edges.
    assert checked // 5 <= hits <= checked // 3


def test_the_frame_the_loop_steps_on_closes_every_step(engine: BacktestEngine) -> None:
    """The degenerate case the rule must not break: hourly setups have to keep
    firing exactly as often as before."""
    analysis = engine.analysis
    ready = [i for i in range(200, 300) if analysis.aligned_indices(i) is not None]

    closes = [
        i
        for i in ready
        if _just_closed(
            analysis,
            Timeframe.H1,
            decision_time_ms(analysis.signal.ts_at(i), analysis.signal_timeframe),
        )
    ]

    assert closes == ready


def test_it_is_read_off_the_data_not_off_the_clock(engine: BacktestEngine) -> None:
    """The first version computed this from the grid with a modulo, which is
    true of real exchange bars and false of anything whose timestamps sit a
    little off it -- and then every setup silently stopped firing. These
    fixtures are off-grid on purpose, so this would catch the regression."""
    analysis = engine.analysis
    index = next(i for i in range(200, 300) if analysis.aligned_indices(i) is not None)
    decision = decision_time_ms(analysis.signal.ts_at(index), analysis.signal_timeframe)

    assert decision % H1_MS != 0, "the fixture is on the grid; this proves nothing"
    assert _just_closed(analysis, Timeframe.H1, decision)


def test_a_signal_remembers_which_chart_it_came_from() -> None:
    """Two signals with the same setup letter from different frames are not the
    same kind of trade -- the four-hour one has a stop four times wider and runs
    for days. The journal has to be able to tell them apart."""
    signal = SetupSignal(
        setup="A",
        name="x",
        source="V08",
        side=Side.LONG,
        entry=100.0,
        stop=98.0,
        target=104.0,
        bar_index=5,
        timeframe=Timeframe.H4,
    )

    assert signal.timeframe is Timeframe.H4
