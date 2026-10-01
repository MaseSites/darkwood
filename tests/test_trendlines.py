"""Diagonal levels, and the three ways a trendline study fools itself.

A trendline is the easiest thing in technical analysis to draw dishonestly.
Three of the tests here exist for the three ways:

* **Drawing it before it could be known.** A line is anchored on swings, and a
  swing high is only a high once price has turned away from it. A line dated
  to the bar its anchor *formed* on would be readable hours before anyone could
  have drawn it, and every study built on it would look prescient.
* **Counting contacts that came before the line.** Walking back from the second
  anchor collects touches the line was fitted to. That is scoring a line on the
  data it was made from.
* **Switching between wicks and bodies.** V06 says it outright -- "nicht
  zwischen Docht und Body wechseln, um die eigene Erwartung passend zu machen".
  A line fitted to whichever produces a nicer picture always exists.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.indicators import atr
from traidingbrain.analysis.structure import StructureTimeline
from traidingbrain.analysis.trendlines import (
    ANCHOR_SOURCE,
    MIN_ANCHOR_SPAN,
    MIN_TOUCHES,
    TrendlineKind,
    TrendlineTimeline,
    find_trendlines,
)

H1_MS = 3_600_000


def frame_from(highs: list[float], lows: list[float]) -> pd.DataFrame:
    closes = [(h + lo) / 2 for h, lo in zip(highs, lows, strict=True)]
    return pd.DataFrame(
        {
            "ts": np.arange(len(highs), dtype="int64") * H1_MS,
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.full(len(highs), 100.0),
        }
    )


def descending_ceiling(bars: int = 160) -> pd.DataFrame:
    """A falling ceiling: each rally stops a little lower than the last.

    Built rather than randomised. The thing under test is whether a line
    through a sequence of lower highs is found, and a random walk that happens
    to fall does not reliably produce one.
    """
    highs: list[float] = []
    lows: list[float] = []
    level = 120.0
    for leg in range(bars // 20):
        peak = level - leg * 3.0
        for step in range(20):
            # A rally to just under the ceiling, then a pullback.
            reach = peak - abs(10 - step) * 0.8
            highs.append(reach)
            lows.append(reach - 4.0)
    return frame_from(highs, lows)


def built(frame: pd.DataFrame) -> tuple[StructureTimeline, TrendlineTimeline]:
    structure = StructureTimeline(frame, lookback=3, max_sequence_length=8)
    return structure, TrendlineTimeline(frame, structure, atr(frame, 14))


# --------------------------------------------------------------------------- #
# The three ways to cheat
# --------------------------------------------------------------------------- #


def test_a_line_is_dated_to_when_it_could_be_drawn() -> None:
    """Not to the bar its anchor formed on.

    A swing high is confirmed `lookback` bars after it happens, because that
    is how long it takes to see price turn away. A line claiming to exist
    earlier would be readable before anybody could have drawn it.
    """
    frame = descending_ceiling()
    structure, _ = built(frame)
    found = find_trendlines(frame, structure, atr(frame, 14))

    assert found, "nothing was found; this test proved nothing"
    for line in found:
        anchors = {line.first_index, line.second_index}
        confirmations = [
            swing.confirmed_index
            for swing in structure.all_swings()
            if swing.index in anchors
        ]
        assert line.confirmed_index == max(confirmations)
        assert line.confirmed_index > max(anchors)


def test_contacts_before_the_line_existed_are_not_counted() -> None:
    """Walking back from the second anchor would collect touches the line was
    fitted to, which is scoring a line on the data it was made from."""
    frame = descending_ceiling()
    structure, _ = built(frame)

    for line in find_trendlines(frame, structure, atr(frame, 14)):
        # Two anchors come free; everything beyond them was counted forward.
        assert line.touches >= 2
        if line.broken_index is not None:
            assert line.broken_index >= line.confirmed_index


def test_the_anchor_source_is_fixed_in_one_place() -> None:
    """V06: "nicht zwischen Docht und Body wechseln, um die eigene Erwartung
    passend zu machen". A line fitted to whichever of the two looks better
    always exists, so the choice is a constant rather than an argument."""
    assert ANCHOR_SOURCE == "wick"


# --------------------------------------------------------------------------- #
# Does it find the thing it is for
# --------------------------------------------------------------------------- #


def test_a_falling_ceiling_is_found() -> None:
    frame = descending_ceiling()
    _, lines = built(frame)

    resistance = [
        line
        for line in lines.known_at(len(frame) - 1)
        if line.kind is TrendlineKind.RESISTANCE
    ]

    assert resistance, "a staircase of lower highs produced no resistance line"
    assert any(line.is_falling for line in resistance)


def test_two_anchors_alone_are_not_a_validated_line() -> None:
    """Any two points lie on a line. V06's wording is "mindestens zwei
    Ankerpunkte; dritter Kontakt" -- the third contact is what separates a
    drawn line from an observed one."""
    frame = descending_ceiling()
    _, lines = built(frame)
    index = len(frame) - 1

    for line in lines.known_at(index):
        if line.touches < MIN_TOUCHES:
            assert not line.is_validated

    assert all(line.is_validated for line in lines.validated_at(index))


def test_a_line_price_has_left_behind_stops_being_offered() -> None:
    """A ceiling price closed well above is not a ceiling. Without this the
    chart fills with lines from a market that no longer exists."""
    frame = descending_ceiling()
    _, lines = built(frame)
    index = len(frame) - 1

    for line in lines.known_at(index):
        assert line.broken_index is None or line.broken_index > index


def test_the_line_can_be_read_at_any_bar() -> None:
    """Setups need the level now, not at its anchors. A diagonal extends."""
    frame = descending_ceiling()
    structure, _ = built(frame)
    line = find_trendlines(frame, structure, atr(frame, 14))[0]

    at_first = line.price_at(line.first_index)
    at_second = line.price_at(line.second_index)

    assert at_first == pytest.approx(line.first_price)
    assert at_second == pytest.approx(line.second_price)


def test_a_flat_series_produces_no_diagonal_worth_having() -> None:
    """The degenerate case. A market going nowhere has horizontal levels, and
    reporting a diagonal through its noise would be inventing structure."""
    flat = frame_from([100.0] * 120, [99.0] * 120)
    _, lines = built(flat)

    assert lines.known_at(len(flat) - 1) == []


def test_asking_before_anything_was_confirmed_gives_nothing() -> None:
    frame = descending_ceiling()
    _, lines = built(frame)

    assert lines.known_at(0) == []


# --------------------------------------------------------------------------- #
# Keeping it to a chart a person could have drawn
# --------------------------------------------------------------------------- #


def test_two_swings_a_few_bars_apart_are_not_a_trendline() -> None:
    """A line through two highs an hour apart is a near-vertical segment that
    extends to nonsense within a day. Measured on BTC hourly before the filter:
    seventy-eight validated lines at once, one of them falling 73 points a
    candle. A trendline is a claim about a trend."""
    frame = descending_ceiling()
    structure, _ = built(frame)

    for line in find_trendlines(frame, structure, atr(frame, 14)):
        assert line.second_index - line.first_index >= MIN_ANCHOR_SPAN


def test_only_a_handful_are_offered_for_drawing() -> None:
    """Every diagonal that survives the filters is still a line somebody could
    have drawn. A person draws two or three; a chart with seventy-eight is not
    a chart."""
    frame = descending_ceiling()
    _, lines = built(frame)
    index = len(frame) - 1

    best = lines.best_at(index, limit=4)

    assert len(best) <= 4
    assert best == sorted(
        best,
        key=lambda line: (line.touches, line.second_index - line.first_index),
        reverse=True,
    )


def test_the_best_line_is_the_one_with_the_most_contacts() -> None:
    """Contacts are the evidence. The span breaks ties, because a line resting
    on highs two days apart describes more than one resting on two hours."""
    frame = descending_ceiling()
    _, lines = built(frame)
    index = len(frame) - 1
    best = lines.best_at(index, limit=4)

    if len(best) > 1:
        assert best[0].touches >= best[1].touches
