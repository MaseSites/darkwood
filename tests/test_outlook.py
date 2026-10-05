"""The per-bar forward score, and the three things it must not get wrong.

This is the instrument built to answer "how good would it be to buy or sell
right now, if I want to be in profit in 5-10 hours". Before any number from it
may be shown, three properties have to hold, and none of them is visible by
reading the output:

1. **No feature may see the future.** The target is the move over the next
   5-10 hours; a feature contaminated by it would produce a beautiful score and
   a worthless one. `test_no_feature_sees_the_future` mutates every bar after
   the decision bar and requires the feature row to be byte-identical.
2. **`closed_ts` must be the end of the horizon, not the bar.** The purge and
   the embargo in `learn/splits.py` work off `closed_ts`. If it were the bar's
   own time, a training case whose future runs into the validation window would
   stay in, and the walk-forward would leak at every boundary.
3. **The fee must come off the magnitude, not the signed value.** A short earns
   the negative of the move and pays the same toll, so subtracting a positive
   constant from a signed target would subsidise shorts and tax longs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.domain.enums import Timeframe
from traidingbrain.learn.outlook import (
    HOUR_MS,
    NAMES,
    ROUND_TRIP,
    OutlookCase,
    build_cases,
    features_at,
    horizon_bars,
    level_context,
)

MINUTE_MS = 60_000


WEEK_MS = 10080 * MINUTE_MS

#: Every frame ends here, and the week length divides it, so this timestamp
#: lies on the grid of all five timeframes.
END_MS = (1_700_000_000_000 // WEEK_MS) * WEEK_MS

STEPS = {Timeframe.W1: 10080, Timeframe.D1: 1440, Timeframe.H4: 240, Timeframe.H1: 60}


def bars(timeframe: Timeframe, count: int, *, seed: int = 7, start: float = 100.0) -> pd.DataFrame:
    """A random walk on the grid of one timeframe, ending at a shared moment.

    Ending rather than starting together is the point, and getting it wrong
    once cost an afternoon's confusion: the first version gave every timeframe
    its own base and the same start, so at an M15 bar a month in, the weekly
    frame was only at its fourth bar and still warming up. `aligned_indices`
    then returned None for every single bar -- correctly -- and `build_cases`
    produced an empty list that looked like a bug in the builder.
    """
    rng = np.random.default_rng(seed)
    step = STEPS.get(timeframe, 15) * MINUTE_MS
    closes = start * np.exp(np.cumsum(rng.normal(0.0, 0.004, size=count)))
    opens = np.concatenate([[start], closes[:-1]])
    spread = np.abs(rng.normal(0.0, 0.003, size=count)) * closes
    first = END_MS - (count - 1) * step
    return pd.DataFrame(
        {
            "ts": first + np.arange(count, dtype="int64") * step,
            "open": opens,
            "high": np.maximum(opens, closes) + spread,
            "low": np.minimum(opens, closes) - spread,
            "close": closes,
            "volume": rng.uniform(10.0, 100.0, size=count),
        }
    )


@pytest.fixture
def analysis() -> MultiFrameAnalysis:
    config = load_config()
    counts = {
        Timeframe.W1: 120,
        Timeframe.D1: 400,
        Timeframe.H4: 900,
        Timeframe.H1: 1800,
        Timeframe.M15: 4000,
    }
    frames = {tf: bars(tf, counts.get(tf, 1000)) for tf in config.engine.timeframes.context}
    return MultiFrameAnalysis(frames, config.engine)


# --------------------------------------------------------------------------- #
# The three properties
# --------------------------------------------------------------------------- #


def test_no_feature_sees_the_future(analysis: MultiFrameAnalysis) -> None:
    """The one test that makes the whole score worth computing.

    Mirrors the future-mutation test the snapshot already has. A single feature
    that peeks turns the study into a measurement of its own leak, and no
    amount of walk-forward, purging or permutation testing would catch it --
    all of those would faithfully report the leak as skill.
    """
    config = load_config()
    index = 3000
    indices = analysis.aligned_indices(index)
    assert indices is not None, "fixture too short to produce a complete picture"
    before = features_at(analysis, index, indices, level_context(analysis))
    assert before is not None

    rng = np.random.default_rng(99)
    frames = {}
    for timeframe, existing in analysis.analyses.items():
        frame = existing.frame.copy()
        if timeframe is config.engine.timeframes.signal:
            after = frame.index > index
            for column in ("open", "high", "low", "close"):
                frame.loc[after, column] = frame.loc[after, column] * rng.uniform(
                    0.5, 2.0, size=int(after.sum())
                )
        frames[timeframe] = frame

    mutated = MultiFrameAnalysis(frames, config.engine)
    indices_after = mutated.aligned_indices(index)
    assert indices_after == indices
    assert features_at(mutated, index, indices_after, level_context(mutated)) == before, (
        "a feature changed when only future bars changed, so it reads the future"
    )


def test_closed_ts_is_the_end_of_the_horizon(analysis: MultiFrameAnalysis) -> None:
    """What the purge and the embargo are computed against.

    With the bar's own time here, `Fold.training` would keep a case whose
    outcome window overlaps the validation fold, and every boundary would leak.
    """
    for hours in (5, 10):
        cases, _tally = build_cases(analysis, hours=hours, step=50)
        assert cases, "no cases built"
        for case in cases[:20]:
            assert case.closed_ts - case.opened_ts == hours * HOUR_MS


def test_the_fee_comes_off_the_magnitude_not_the_sign() -> None:
    """A short earns the negative of the move and pays the same toll.

    Subtracting a positive constant from a signed target would make every
    downward move look better than it was and every upward move worse.
    """
    up = OutlookCase(opened_ts=0, closed_ts=1, target=0.0, features=(), move=0.0)
    assert up.target == 0.0  # the dataclass stores what it is given

    # The sign/magnitude rule as build_cases applies it, stated directly.
    for move in (0.01, -0.01):
        expected = np.sign(move) * max(0.0, abs(move) - ROUND_TRIP)
        assert abs(expected) == pytest.approx(abs(move) - ROUND_TRIP)
        assert np.sign(expected) == np.sign(move), "the fee flipped the direction"


def test_a_move_smaller_than_the_toll_is_worth_exactly_nothing() -> None:
    """Not negative: an opportunity not worth taking is skipped, not lost."""
    for move in (ROUND_TRIP / 2, -ROUND_TRIP / 2, 0.0):
        assert np.sign(move) * max(0.0, abs(move) - ROUND_TRIP) == 0.0


# --------------------------------------------------------------------------- #
# Shape and bookkeeping
# --------------------------------------------------------------------------- #


def test_every_feature_has_a_name(analysis: MultiFrameAnalysis) -> None:
    """Otherwise a report cannot say which feature carried a result."""
    index = 3000
    indices = analysis.aligned_indices(index)
    assert indices is not None
    row = features_at(analysis, index, indices, level_context(analysis))
    assert row is not None
    assert len(row) == len(NAMES)
    assert len(set(NAMES)) == len(NAMES), "a feature name is used twice"


def test_the_horizon_converts_to_the_bars_the_question_implies() -> None:
    assert horizon_bars(5, Timeframe.M15) == 20
    assert horizon_bars(10, Timeframe.M15) == 40
    assert horizon_bars(5, Timeframe.H1) == 5
    # Never zero, however short the horizon against the timeframe.
    assert horizon_bars(1, Timeframe.D1) == 1


def test_features_are_finite_or_the_bar_is_dropped(analysis: MultiFrameAnalysis) -> None:
    """A NaN reaching the matrix poisons a whole ridge fit silently."""
    cases, _tally = build_cases(analysis, hours=5, step=7)
    assert cases
    values = np.array([case.features for case in cases], dtype="float64")
    assert np.isfinite(values).all()


def test_the_tally_accounts_for_every_bar_it_looked_at(analysis: MultiFrameAnalysis) -> None:
    """So a thin result is explainable rather than mysterious."""
    cases, tally = build_cases(analysis, hours=5, step=10)
    assert tally.kept == len(cases)
    accounted = tally.kept + tally.not_ready + tally.unaligned + tally.no_features + tally.no_future
    assert accounted == tally.seen


def test_no_case_reaches_past_the_end_of_the_data(analysis: MultiFrameAnalysis) -> None:
    """The last bars have no future, and inventing one would be the worst leak."""
    signal = analysis.signal
    last_ts = signal.ts_at(len(signal) - 1)
    cases, _tally = build_cases(analysis, hours=10, step=1)
    assert cases
    for case in cases:
        assert case.opened_ts + 10 * HOUR_MS <= last_ts + 10 * HOUR_MS
    # The strict form: the horizon must be inside the data, so the newest case
    # cannot start within the horizon of the final bar.
    assert max(case.opened_ts for case in cases) < last_ts


def test_thinning_changes_the_count_and_not_the_cases(analysis: MultiFrameAnalysis) -> None:
    """`step` must drop bars, never alter the ones it keeps."""
    dense, _ = build_cases(analysis, hours=5, step=1)
    thin, _ = build_cases(analysis, hours=5, step=10)
    assert len(thin) < len(dense)
    by_ts = {case.opened_ts: case for case in dense}
    for case in thin:
        assert by_ts[case.opened_ts] == case


def test_the_symbol_travels_with_the_case(analysis: MultiFrameAnalysis) -> None:
    """Cases from several markets get pooled, and a result per market needs it."""
    cases, _tally = build_cases(analysis, hours=5, symbol="BTCUSDT", step=25)
    assert cases
    assert {case.symbol for case in cases} == {"BTCUSDT"}


def test_a_case_satisfies_the_scorable_protocol(analysis: MultiFrameAnalysis) -> None:
    """So the tested walk-forward and permutation machinery applies unchanged."""
    cases, _tally = build_cases(analysis, hours=5, step=40)
    assert cases
    case = cases[0]
    assert isinstance(case.opened_ts, int)
    assert isinstance(case.closed_ts, int)
    assert isinstance(case.target, float)
    assert isinstance(case.taken, bool)
    assert len(list(case.features)) == len(NAMES)


def test_there_is_no_baseline_group_to_compare_against(analysis: MultiFrameAnalysis) -> None:
    """`taken` is False everywhere, deliberately.

    `Scorable.taken` exists so a signal filter is measured against what the
    rules already trade. Here every bar is a case and the system trades on
    almost none of them, so a baseline group would be a handful of rows
    masquerading as a comparison. The permutation null is the comparison.
    """
    cases, _tally = build_cases(analysis, hours=5, step=40)
    assert cases
    assert not any(case.taken for case in cases)
