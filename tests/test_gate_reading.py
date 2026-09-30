"""The gate read out in full, which is what the screen shows between trades.

Most hours have no setup. A dashboard that stays silent through them cannot be
told apart from one whose pipeline has died, so the market view reports every
condition on every poll. That makes the readout a second answer to a question
the backtest already answers -- and two answers to "does this bar qualify" would
drift apart invisibly, each looking plausible on its own.

So the point of this file is mostly one assertion, repeated across shapes: the
reading's first refusal is the counter the gate increments. The rest guards the
two ways a readout goes quietly wrong -- a condition reported as satisfied when
it could not be evaluated, and a label that has drifted from the counter it
describes.
"""

from __future__ import annotations

import threading
import time
from typing import Any, cast

import pytest

from traidingbrain.api.market import GATE_LABELS, MarketAnalysisCache, _Cached, _gate_read
from traidingbrain.brain.trigger import Trigger, TriggerStats, evaluate
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe
from traidingbrain.domain.snapshot import MarketSnapshot

from .factories import make_snapshot, make_timeframe_view


@pytest.fixture
def config() -> AppConfig:
    return load_config()


def _reading(snapshot: MarketSnapshot, config: AppConfig, **overrides: object):
    return evaluate(snapshot, config.engine.trigger.model_copy(update=overrides))


# --------------------------------------------------------------------------- #
# One answer, not two
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "frames",
    [
        pytest.param(None, id="a bar the gate accepts"),
        pytest.param(
            [make_timeframe_view(structure={"sequence": "HH HL", "bos": False, "choch": False})],
            id="no structural event",
        ),
        pytest.param(
            [make_timeframe_view(regime=RegimeKind.UNKNOWN)],
            id="not warmed up",
        ),
        pytest.param(
            [make_timeframe_view(indicators=[])],
            id="nothing taking a side",
        ),
    ],
)
def test_the_readout_refuses_for_the_reason_the_gate_counts(
    config: AppConfig, frames: object
) -> None:
    """The assertion this whole file exists for.

    If these two ever disagree, the screen explains a decision the engine did
    not make -- and it would look entirely reasonable while doing it.
    """
    snapshot = make_snapshot(frames=frames) if frames is not None else make_snapshot()
    trigger = Trigger(config.engine.trigger)

    asked = trigger.should_ask(snapshot, bar_index=100)
    reading = _reading(snapshot, config)

    assert reading.passed is asked
    counted = [
        name
        for name in vars(trigger.stats)
        if name not in {"seen", "fired"} and getattr(trigger.stats, name)
    ]
    assert counted == ([] if asked else [reading.blocking])


def test_looking_at_the_gate_does_not_move_it(config: AppConfig) -> None:
    """The dashboard polls constantly, and the gate has state.

    Spacing is counted in bars since the last call. If reading the panel counted
    as a call, simply watching the screen would suppress the next setup.
    """
    snapshot = make_snapshot()
    trigger = Trigger(config.engine.trigger)

    for _ in range(20):
        trigger.read(snapshot, bar_index=100)

    assert trigger.stats.seen == 0
    assert trigger.should_ask(snapshot, bar_index=100) is True


# --------------------------------------------------------------------------- #
# What the readout must not claim
# --------------------------------------------------------------------------- #


def test_conditions_that_cannot_be_measured_are_left_out_rather_than_passed(
    config: AppConfig,
) -> None:
    """A check reading "satisfied" because nothing could be read is worse than
    its absence: it is reassurance with nothing behind it.

    The signal timeframe is missing entirely here, which is what the first hours
    of a backfill look like. An unread *regime* is a different case -- the view
    exists, so structure and confluence are still real measurements and they
    stay on the list.
    """
    cold = make_snapshot(frames=[make_timeframe_view(timeframe=Timeframe.D1)])

    names = [check.name for check in _reading(cold, config).checks]

    assert names == ["too_soon", "unknown_regime"]


def test_an_unread_regime_still_leaves_the_other_conditions_measured(
    config: AppConfig,
) -> None:
    """The distinction the test above turns on, pinned so it cannot slide.

    A regime needs a long warm-up that structure does not; dropping the rest of
    the panel whenever the regime is unread would blank the screen during the
    hours it is most worth watching.
    """
    warming = make_snapshot(frames=[make_timeframe_view(regime=RegimeKind.UNKNOWN)])

    names = [check.name for check in _reading(warming, config).checks]

    assert "no_structure_event" in names
    assert "too_little_confluence" in names


def test_the_spacing_check_says_so_when_it_has_nothing_to_measure(
    config: AppConfig,
) -> None:
    """The market view has no call history, so spacing cannot refuse there.

    It still appears, because a condition that vanished from the list would read
    as one that had been removed from the engine.
    """
    spacing = next(
        check for check in _reading(make_snapshot(), config).checks if check.name == "too_soon"
    )

    assert spacing.passed is True
    assert "no call yet" in spacing.detail


def test_every_detail_carries_its_measurement(config: AppConfig) -> None:
    """The teaching part. "Too little confluence" says which rule refused;
    "1 of 2 indicators taking a side" says how far off the market is."""
    thin = make_snapshot(
        frames=[
            make_timeframe_view(
                indicators=[
                    {"name": "rsi", "value": 50.0, "bias": Bias.NEUTRAL, "strength": 0.1},
                ]
            )
        ]
    )

    confluence = next(
        check
        for check in _reading(thin, config).checks
        if check.name == "too_little_confluence"
    )

    assert confluence.passed is False
    assert f"of {config.engine.trigger.min_indicator_confluence}" in confluence.detail


# --------------------------------------------------------------------------- #
# The panel
# --------------------------------------------------------------------------- #


def test_every_condition_the_gate_can_report_has_a_label() -> None:
    """The counter name is the identifier and the label is what is read. A label
    missing here would surface the raw counter name on screen, which is exactly
    where nobody would notice it."""
    reportable = {name for name in vars(TriggerStats()) if name not in {"seen", "fired"}}

    assert reportable == set(GATE_LABELS)


def test_the_headline_names_the_first_refusal_only(config: AppConfig) -> None:
    """A bar that misses on three conditions is not three times further from a
    setup. The gate stops at the first, and the sentence says the same."""
    blocked = make_snapshot(
        frames=[
            make_timeframe_view(
                regime=RegimeKind.UNKNOWN,
                structure={"sequence": "", "bos": False, "choch": False},
                indicators=[],
            )
        ]
    )

    panel = _gate_read(_reading(blocked, config))

    assert panel.would_ask is False
    assert panel.blocking == "unknown_regime"
    assert panel.headline.lower().startswith("no setup: regime")


def test_a_passing_bar_says_it_would_be_put_to_the_model(config: AppConfig) -> None:
    """Deliberately not "would trade". The gate decides what earns the model's
    attention; the model still answers WAIT on most of it."""
    panel = _gate_read(_reading(make_snapshot(), config))

    assert panel.would_ask is True
    assert "model" in panel.headline
    assert all(check.passed for check in panel.checks)


# --------------------------------------------------------------------------- #
# The cache the panel is served from
# --------------------------------------------------------------------------- #


def test_a_cold_cache_under_polling_builds_once(config: AppConfig) -> None:
    """The failure this guards is the worst kind: nothing reports an error.

    The screen polls every four seconds and a cold build takes about twenty. Six
    overlapping builds start before the first finishes, each slowing the rest,
    and the page simply never arrives -- while every request is still
    legitimately working, so nothing anywhere says anything is wrong.

    The build itself is stubbed out. What is under test is the serialisation,
    and driving it through a real multi-timeframe analysis would make a
    concurrency test take a minute to say something it can say in a tenth of a
    second.
    """
    class Store:
        def last_ts(self, symbol: str, timeframe: object) -> int:
            return 1

    cache = MarketAnalysisCache(Store(), config.engine)
    builds = 0
    counted = threading.Lock()

    def slow_build(symbol: str) -> _Cached:
        nonlocal builds
        with counted:
            builds += 1
        time.sleep(0.05)
        built = _Cached(cast(Any, None), cast(Any, None), 1, time.monotonic())
        cache._cache[symbol] = built
        return built

    cache._build = slow_build  # type: ignore[method-assign]

    threads = [threading.Thread(target=cache.for_symbol, args=("BTCUSDT",)) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert builds == 1, f"{builds} builds ran where one would have served all six"


def test_a_second_symbol_is_not_held_up_by_the_first(config: AppConfig) -> None:
    """One lock per symbol. A shared one would make the four followed symbols
    build in series, which is the same stall wearing a different hat."""
    class Store:
        def last_ts(self, symbol: str, timeframe: object) -> int:
            return 1

    cache = MarketAnalysisCache(Store(), config.engine)
    inside = threading.Barrier(2, timeout=5)

    def blocking_build(symbol: str) -> _Cached:
        # Both builds must be inside at once, or the barrier times out.
        inside.wait()
        built = _Cached(cast(Any, None), cast(Any, None), 1, time.monotonic())
        cache._cache[symbol] = built
        return built

    cache._build = blocking_build  # type: ignore[method-assign]

    threads = [
        threading.Thread(target=cache.for_symbol, args=(symbol,))
        for symbol in ("BTCUSDT", "ETHUSDT")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=6)

    assert not any(thread.is_alive() for thread in threads), "the two symbols serialised"
