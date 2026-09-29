"""Market structure, and the confirmation lag that keeps it honest.

The whole module exists to get one thing right: a swing high is not knowable when
it prints. It becomes knowable once enough bars have passed without exceeding it.
Reporting it at the bar where the price is -- the obvious implementation -- hands
the engine several bars of foresight in the input that carries the most weight.

These tests are built on hand-drawn bar sequences rather than generated data, so
that what each one asserts is visible in the fixture itself.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.fakes import EPOCH
from traidingbrain.analysis.structure import (
    BREAK_RECENCY_BARS,
    StructureTimeline,
    SwingKind,
    find_swings,
)
from traidingbrain.data.frames import bars_to_frame, timeframe_ms
from traidingbrain.domain.enums import Bias, Timeframe
from traidingbrain.domain.market import Bar

H1_MS = timeframe_ms(Timeframe.H1)


def bars(highs: list[float], lows: list[float], closes: list[float] | None = None) -> pd.DataFrame:
    """Build a frame from explicit highs and lows.

    Opens and closes default to the middle of each bar, so a fixture says exactly
    what it is about -- where the extremes are -- and nothing else.
    """
    assert len(highs) == len(lows)
    midpoints = [(h + low) / 2 for h, low in zip(highs, lows, strict=True)]
    resolved = closes if closes is not None else midpoints
    return bars_to_frame(
        [
            Bar(
                ts=EPOCH + i * H1_MS,
                open=(highs[i] + lows[i]) / 2,
                high=highs[i],
                low=lows[i],
                close=resolved[i],
                volume=100.0,
            )
            for i in range(len(highs))
        ]
    )


# --------------------------------------------------------------------------- #
# Confirmation lag
# --------------------------------------------------------------------------- #


def test_a_swing_is_confirmed_lookback_bars_after_it_forms() -> None:
    """The peak is at index 3; it is only knowable at index 6.

    That gap is the entire point. Bars 4, 5 and 6 are what turn "the highest bar so
    far" into "a high the market turned away from".
    """
    frame = bars(
        highs=[10, 11, 12, 20, 13, 12, 11, 10],
        lows=[5, 6, 7, 8, 7, 6, 5, 4],
    )

    swings = [s for s in find_swings(frame, lookback=3) if s.kind is SwingKind.HIGH]

    assert len(swings) == 1
    assert swings[0].index == 3
    assert swings[0].confirmed_index == 6
    assert swings[0].confirmation_lag == 3


def test_an_unconfirmed_swing_is_invisible() -> None:
    frame = bars(
        highs=[10, 11, 12, 20, 13, 12, 11, 10],
        lows=[5, 6, 7, 8, 7, 6, 5, 4],
    )
    timeline = StructureTimeline(frame, lookback=3)

    assert timeline.swings_known_at(5) == []
    known = timeline.swings_known_at(6)
    assert [s.index for s in known if s.kind is SwingKind.HIGH] == [3]


def test_a_flat_top_is_not_a_swing() -> None:
    """Two bars at the same high is a level that has not been rejected yet.

    Calling it a swing would put a confirmed structural anchor where the market
    has not actually turned.
    """
    frame = bars(
        highs=[10, 11, 20, 20, 12, 11, 10, 9],
        lows=[5, 6, 7, 7, 6, 5, 4, 3],
    )

    highs = [s for s in find_swings(frame, lookback=2) if s.kind is SwingKind.HIGH]

    assert highs == []


def test_swing_lows_are_found_the_same_way() -> None:
    frame = bars(
        highs=[20, 19, 18, 17, 18, 19, 20, 21],
        lows=[15, 14, 13, 5, 13, 14, 15, 16],
    )

    lows = [s for s in find_swings(frame, lookback=3) if s.kind is SwingKind.LOW]

    assert len(lows) == 1
    assert lows[0].index == 3
    assert lows[0].confirmed_index == 6
    assert lows[0].price == pytest.approx(5.0)


def test_lookback_must_be_positive() -> None:
    with pytest.raises(ValueError, match="lookback must be"):
        find_swings(bars(highs=[1, 2], lows=[0, 1]), lookback=0)


# --------------------------------------------------------------------------- #
# Break of structure
# --------------------------------------------------------------------------- #


def test_a_break_fires_only_once_per_level() -> None:
    """Closing above a swing high is one event, not one per subsequent bar.

    Without consuming the level, `bars_since_bos` resets every bar and the signal
    becomes "price is above a swing high", which is a different and much weaker
    statement.
    """
    frame = bars(
        highs=[10, 11, 20, 13, 12, 11, 25, 26, 27, 28],
        lows=[5, 6, 15, 8, 7, 6, 20, 21, 22, 23],
        closes=[8, 9, 17, 10, 9, 8, 22, 24, 25, 26],
    )
    timeline = StructureTimeline(frame, lookback=2)

    breaks = [i for i in range(len(frame)) if timeline.state_at(i).bars_since_bos == 0]

    assert len(breaks) == 1, f"expected a single break, got breaks at {breaks}"


def test_a_break_requires_a_close_beyond_the_level_not_a_wick() -> None:
    """A wick through a level is liquidity being taken, not structure breaking.

    Judging on the high would turn every stop hunt into a structural signal.
    """
    frame = bars(
        highs=[10, 11, 20, 13, 12, 11, 25],
        lows=[5, 6, 15, 8, 7, 6, 10],
        # The last bar spikes to 25 but closes at 12, below the swing high of 20.
        closes=[8, 9, 17, 10, 9, 8, 12],
    )
    timeline = StructureTimeline(frame, lookback=2)

    assert timeline.state_at(len(frame) - 1).bars_since_bos is None


def test_change_of_character_needs_a_break_the_other_way() -> None:
    """A second break in the same direction is continuation, not a character change.

    CHoCH is the signal that the side in control has changed hands; firing it on
    every break would make it a synonym for BOS.
    """
    frame = bars(
        highs=[10, 12, 20, 14, 13, 12, 26, 27, 22, 21, 20, 19, 30, 31],
        lows=[5, 7, 15, 9, 8, 7, 21, 22, 17, 16, 15, 14, 25, 26],
        closes=[8, 10, 17, 11, 10, 9, 23, 24, 19, 18, 17, 16, 27, 28],
    )
    timeline = StructureTimeline(frame, lookback=2)

    chochs = [i for i in range(len(frame)) if timeline.state_at(i).bars_since_choch == 0]
    breaks = [i for i in range(len(frame)) if timeline.state_at(i).bars_since_bos == 0]

    assert breaks, "the fixture should produce at least one break"
    assert len(chochs) < len(breaks), (
        "every break was also treated as a change of character, which makes the "
        "second flag meaningless"
    )


def test_the_break_flag_expires_but_the_distance_does_not() -> None:
    """`bos` says "recently", `bars_since_bos` says how long ago.

    Over thousands of bars a break has always happened at some point. A flag
    without a window is true everywhere and tells the model nothing while looking
    like a signal.
    """
    tail = 40
    frame = bars(
        highs=[10, 11, 20, 13, 12, 11, 25] + [24 - i * 0.1 for i in range(tail)],
        lows=[5, 6, 15, 8, 7, 6, 20] + [19 - i * 0.1 for i in range(tail)],
        closes=[8, 9, 17, 10, 9, 8, 22] + [21 - i * 0.1 for i in range(tail)],
    )
    timeline = StructureTimeline(frame, lookback=2, break_recency_bars=BREAK_RECENCY_BARS)

    break_index = next(i for i in range(len(frame)) if timeline.state_at(i).bars_since_bos == 0)

    assert timeline.state_at(break_index).bos is True
    just_inside = timeline.state_at(break_index + BREAK_RECENCY_BARS)
    assert just_inside.bos is True
    well_after = timeline.state_at(break_index + BREAK_RECENCY_BARS + 5)
    assert well_after.bos is False
    assert well_after.bars_since_bos == BREAK_RECENCY_BARS + 5


# --------------------------------------------------------------------------- #
# Sequence and trend
# --------------------------------------------------------------------------- #


def test_rising_swings_read_as_an_uptrend() -> None:
    highs = [10, 12, 20, 14, 13, 15, 24, 18, 17, 19, 28, 22, 21, 23, 32, 26, 25]
    lows = [5, 7, 15, 9, 8, 10, 19, 13, 12, 14, 23, 17, 16, 18, 27, 21, 20]
    timeline = StructureTimeline(bars(highs, lows), lookback=2)

    final = timeline.state_at(len(highs) - 1)

    assert final.trend is Bias.BULLISH, f"sequence was {final.sequence_text()!r}"
    assert "HH" in final.sequence_text()


def test_falling_swings_read_as_a_downtrend() -> None:
    highs = [32, 30, 22, 28, 29, 27, 18, 24, 25, 23, 14, 20, 21, 19, 10]
    lows = [27, 25, 17, 23, 24, 22, 13, 19, 20, 18, 9, 15, 16, 14, 5]
    timeline = StructureTimeline(bars(highs, lows), lookback=2)

    final = timeline.state_at(len(highs) - 1)

    assert final.trend is Bias.BEARISH, f"sequence was {final.sequence_text()!r}"


def test_a_choppy_market_is_called_neutral_rather_than_forced() -> None:
    """Saying "no direction" is more useful than picking one at random."""
    # Swings alternate higher and lower with no net direction: HH then LH then
    # HH again, and the same mix on the lows.
    highs = [20, 14, 25, 13, 20, 14, 22, 13, 20, 14, 26, 13, 20, 14, 23]
    lows = [10, 2, 11, 6, 10, 1, 11, 7, 10, 3, 11, 5, 10, 2, 11]
    timeline = StructureTimeline(bars(highs, lows), lookback=2)

    state = timeline.state_at(len(highs) - 1)

    assert state.trend is Bias.NEUTRAL, f"sequence was {state.sequence_text()!r}"


def test_the_sequence_is_capped() -> None:
    highs = [10 + (i % 5) * 3 + i for i in range(80)]
    lows = [5 + (i % 5) * 3 + i for i in range(80)]
    timeline = StructureTimeline(bars(highs, lows), lookback=2, max_sequence_length=4)

    assert len(timeline.state_at(79).sequence) <= 4


def test_two_swings_are_not_a_trend() -> None:
    """A direction needs more than two comparable points.

    Otherwise the very first pair of swings in any file sets a trend, and the
    weekly frame spends its warm-up period asserting a direction it cannot know.
    """
    frame = bars(
        highs=[10, 12, 20, 14, 13, 12, 18, 11, 10, 9],
        lows=[5, 7, 15, 9, 8, 4, 13, 6, 5, 4],
    )
    timeline = StructureTimeline(frame, lookback=2)

    for index in range(len(frame)):
        state = timeline.state_at(index)
        comparable = [label for label in state.sequence if len(label) == 2]
        if len(comparable) < 3:
            assert state.trend is Bias.NEUTRAL, (
                f"index {index}: called {state.trend} from {state.sequence_text()!r}"
            )


def test_an_empty_history_has_no_structure() -> None:
    frame = bars(highs=[10, 11, 12], lows=[5, 6, 7])
    timeline = StructureTimeline(frame, lookback=3)

    state = timeline.state_at(2)

    assert state.sequence == ()
    assert state.trend is Bias.NEUTRAL
    assert state.bos is False
    assert state.bars_since_bos is None
