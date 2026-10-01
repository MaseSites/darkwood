"""The join: analysed frames in, one score out, across every timeframe.

Two things are worth testing here and the rest is covered elsewhere. The first
is that a reading is refused while any frame is still warming up -- a partial
snapshot is worse than none, because it looks complete and silently reports the
weekly frame as neutral when the truth is that it is unknown. The second is
that the result does not depend on the order the config happens to list its
timeframes in; a score that moved when a YAML list was reordered would be very
hard to believe six months later.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.api.scoring import _headline, build_score_view, signal_index_at
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe
from traidingbrain.score.engine import Score, ScoredFamily
from traidingbrain.score.findings import Evidence, Family, FamilyVerdict
from traidingbrain.score.reading import ScoreReading, score_at

H1_MS = 3_600_000
BARS = 1_400


def walk(bars: int, *, seed: int, step_ms: int, drift: float = 0.0) -> pd.DataFrame:
    """A random walk whose last bar ends at the epoch, whatever the step.

    Ending all frames together is what makes them line up. Starting them
    together instead gives a weekly frame that covers twenty-seven years while
    the hourly one covers two months, so the newest weekly bar that has closed
    by the last hour is bar seven -- still warming up, and nothing is ever
    ready. That cost an afternoon the first time.
    """
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(drift, 0.004, bars)))
    return pd.DataFrame(
        {
            "ts": (np.arange(bars, dtype="int64") - (bars - 1)) * step_ms,
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": close * (1.0 + np.abs(rng.normal(0.0, 0.003, bars))),
            "low": close * (1.0 - np.abs(rng.normal(0.0, 0.003, bars))),
            "close": close,
            "volume": rng.lognormal(3.0, 0.5, bars),
        }
    )


def frames(order: list[Timeframe] | None = None) -> dict[Timeframe, pd.DataFrame]:
    """One frame per context timeframe, each long enough to warm up.

    Built per timeframe rather than sliced out of the hourly series: slicing
    every 168th hourly bar gives a weekly frame of a few dozen rows, the weekly
    indicators never warm up, and nothing is ever ready.
    """
    hours = {Timeframe.W1: 168, Timeframe.D1: 24, Timeframe.H4: 4, Timeframe.H1: 1}
    built = {
        timeframe: walk(BARS, seed=index + 1, step_ms=H1_MS * span)
        for index, (timeframe, span) in enumerate(hours.items())
    }
    built[Timeframe.M15] = walk(BARS * 4, seed=9, step_ms=H1_MS // 4)
    if order is None:
        return built
    return {timeframe: built[timeframe] for timeframe in order}


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


@pytest.fixture(scope="module")
def multi(config: AppConfig) -> MultiFrameAnalysis:
    return MultiFrameAnalysis(frames(), config.engine)


def test_no_score_while_any_frame_is_still_warming_up(multi: MultiFrameAnalysis) -> None:
    """None rather than a partial reading. A snapshot missing its weekly frame
    does not look incomplete -- it looks neutral, which is a different claim."""
    assert score_at(multi, 0) is None


def test_a_ready_bar_produces_a_score_from_every_timeframe(
    multi: MultiFrameAnalysis,
) -> None:
    ready = multi.first_ready_index()
    assert ready is not None

    reading = score_at(multi, len(multi.signal) - 1)

    assert reading is not None
    timeframes = {finding.timeframe for finding in reading.evidence.findings}
    assert len(timeframes) >= 4, "a timeframe contributed nothing at all"


def test_the_same_indicator_on_two_timeframes_is_two_findings(
    multi: MultiFrameAnalysis,
) -> None:
    """Not one finding read twice. The hourly RSI and the daily RSI measure
    different things; the family machinery is what stops them voting twice."""
    reading = score_at(multi, len(multi.signal) - 1)
    assert reading is not None

    keys = {finding.key for finding in reading.evidence.findings}

    assert "rsi_14_h1" in keys
    assert "rsi_14_d1" in keys


def test_the_score_does_not_depend_on_how_the_config_lists_its_timeframes(
    config: AppConfig,
) -> None:
    """A number that moved when a YAML list was reordered would be impossible
    to reproduce later, and the cache key would be lying."""
    forward = MultiFrameAnalysis(
        frames([Timeframe.W1, Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15]),
        config.engine,
    )
    backward = MultiFrameAnalysis(
        frames([Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1, Timeframe.W1]),
        config.engine,
    )
    index = len(forward.signal) - 1

    first = score_at(forward, index)
    second = score_at(backward, index)

    assert first is not None and second is not None
    assert first.score.bullish == second.score.bullish
    assert first.score.bearish == second.score.bearish
    assert [f.key for f in first.evidence.findings] == [
        f.key for f in second.evidence.findings
    ]


def test_the_regime_comes_from_the_timeframe_the_decision_is_taken_on(
    multi: MultiFrameAnalysis,
) -> None:
    """Chapter 12.2's rule has to be answered somewhere, and the signal frame
    is the honest place. Taking the regime from the weekly would tell the
    hourly oscillators they are inside a trend nobody has seen for days."""
    index = len(multi.signal) - 1
    reading = score_at(multi, index)
    assert reading is not None

    assert reading.regime is multi.signal.regime.state_at(index).kind


def test_the_reading_reports_how_many_numbers_went_in(multi: MultiFrameAnalysis) -> None:
    """The gap between this and `breadth` is chapter 12.6's whole argument:
    a hundred readings can still be three pieces of information."""
    reading = score_at(multi, len(multi.signal) - 1)
    assert reading is not None

    assert reading.indicator_count > reading.score.breadth


def test_the_non_directional_readings_come_back_per_timeframe(
    multi: MultiFrameAnalysis,
) -> None:
    """How violent and how choppy are context, and context is per frame: the
    weekly can be calm while the hourly is not."""
    reading = score_at(multi, len(multi.signal) - 1)
    assert reading is not None

    assert Timeframe.H1 in reading.context
    assert "adx_14" in reading.context[Timeframe.H1]


# --------------------------------------------------------------------------- #
# What the screen gets
# --------------------------------------------------------------------------- #


def test_the_view_is_built_for_the_bar_on_screen_not_the_last_one(
    multi: MultiFrameAnalysis,
) -> None:
    """By timestamp, like the setups. The snapshot can be a few bars behind the
    newest stored one -- the builder walks back past bars that are still
    warming up on a higher frame -- and the last index would describe a
    different bar than the one being drawn."""
    index = len(multi.signal) - 1
    ts = multi.signal.ts_at(index)

    assert signal_index_at(multi, ts) == index
    assert signal_index_at(multi, ts + 1) is None
    assert build_score_view("TESTUSDT", multi, ts + 1) is None


def test_the_view_speaks_german(multi: MultiFrameAnalysis) -> None:
    """The labels are a lookup rather than a rename of the enums, for the same
    reason the rest of the screen is: the enum values are what the backtests,
    the history index and the tests assert on."""
    view = build_score_view("TESTUSDT", multi, multi.signal.ts_at(len(multi.signal) - 1))
    assert view is not None

    labels = {family.label for family in view.families}

    assert "Trend" in labels
    assert view.direction in {"aufwärts", "abwärts", "offen"}
    assert view.headline


def test_a_silent_family_says_why_it_is_silent(multi: MultiFrameAnalysis) -> None:
    """Three different things produce a contribution of nothing -- no side, the
    indicators disagreeing, the frames disagreeing -- and they call for three
    different responses. A bare zero says none of them."""
    view = build_score_view("TESTUSDT", multi, multi.signal.ts_at(len(multi.signal) - 1))
    assert view is not None

    for family in view.families:
        if family.silent:
            assert family.reason, family.label


def test_every_family_shows_what_each_timeframe_said(multi: MultiFrameAnalysis) -> None:
    view = build_score_view("TESTUSDT", multi, multi.signal.ts_at(len(multi.signal) - 1))
    assert view is not None

    for family in view.families:
        assert family.frames
        assert all(-1.0 <= frame.lean <= 1.0 for frame in family.frames)


def test_the_headline_counts_the_families_that_agree_not_the_ones_that_spoke(
    multi: MultiFrameAnalysis,
) -> None:
    """The first draft printed the wrong number.

    Four families arguing down and one arguing up came out as "five families
    argue down", because `breadth` counts families with an opinion rather than
    families agreeing with the lean. The table underneath said the opposite of
    the sentence above it.
    """
    view = build_score_view("TESTUSDT", multi, multi.signal.ts_at(len(multi.signal) - 1))
    assert view is not None

    speaking = [family for family in view.families if not family.silent]
    agreeing = sum(
        1
        for family in speaking
        if (family.contribution > 0) is (view.direction == "aufwärts")
    )

    assert view.headline.startswith(f"{agreeing} von {len(speaking)} ")


def test_a_contested_headline_reports_the_share_not_the_conflict_scale() -> None:
    """`conflict` is twice the losing side's share, so that it reaches one when
    the two sides are equal. Printing it as a share claimed "76 % of the
    evidence is against" about a market where 38 % was."""
    score = Score(bullish=0.59, bearish=0.36)
    score.families = [
        ScoredFamily(
            verdict=FamilyVerdict(
                family=Family.STRUCTURE,
                direction=Bias.BULLISH,
                strength=0.6,
                agreement=1.0,
                members=("a",),
            ),
            base_weight=1.0,
            regime_modifier=1.0,
            contribution=0.59,
            split=False,
        )
    ]
    reading = ScoreReading(score=score, regime=RegimeKind.RANGE, evidence=Evidence())

    headline = _headline(reading)

    assert "38 %" in headline.replace("\u00a0", " ") or "38%" in headline
    assert "76" not in headline
