"""Crowd sentiment, and the rule that makes it usable in a backtest.

The plan set the news weight to zero because you cannot reconstruct what anyone
knew on a past afternoon. This index is the exception: published once a day,
never revised, so the value for a past day is the value that existed then.

That exception holds only while the one-day rule does. A value stamped at
midnight on day D describes day D, and how much of day D it already knows is
undocumented -- so a decision on day D may see D-1 and no later. Without that,
every bar would quietly know its own day's mood, and the effect would be
strongest exactly where sentiment moves, which is where it would look most like
a finding.
"""

from __future__ import annotations

import httpx
import pandas as pd
import pytest

from traidingbrain.data.sentiment import (
    LOOKBACK_HOURS,
    SentimentStore,
    SentimentTimeline,
    SentimentUnavailableError,
    classify,
    fetch,
)

DAY = 86_400_000
START = 1_700_000_000_000 // DAY * DAY  # midnight UTC


def daily(values: list[int], *, start: int = START) -> pd.DataFrame:
    return pd.DataFrame(
        {"ts": [start + i * DAY for i in range(len(values))], "value": values}
    )


# --------------------------------------------------------------------------- #
# The one-day rule
# --------------------------------------------------------------------------- #


def test_a_decision_never_sees_its_own_day() -> None:
    """The rule the whole exception rests on."""
    timeline = SentimentTimeline(daily([10, 20, 30, 40]))
    # Midday on the day stamped 30 -- that value describes today and is off limits.
    decision = START + 2 * DAY + 12 * 3_600_000

    reading = timeline.at(decision)

    assert reading.value == 20, "it read today's value instead of yesterday's"
    assert reading.age_hours >= LOOKBACK_HOURS


def test_the_reading_is_never_fresher_than_the_lookback() -> None:
    timeline = SentimentTimeline(daily(list(range(10, 100, 10))))

    for offset in range(3, 9):
        decision = START + offset * DAY + 6 * 3_600_000
        assert timeline.at(decision).age_hours >= LOOKBACK_HOURS


def test_rewriting_later_values_does_not_change_an_earlier_reading() -> None:
    """The same guarantee every other series here is held to."""
    original = daily([10, 20, 30, 40, 50])
    decision = START + 2 * DAY + 12 * 3_600_000
    before = SentimentTimeline(original).at(decision)

    mutated = original.copy()
    mutated.loc[3:, "value"] = [99, 1]
    after = SentimentTimeline(mutated).at(decision)

    assert before == after


# --------------------------------------------------------------------------- #
# Absence
# --------------------------------------------------------------------------- #


def test_no_data_reports_unknown_rather_than_neutral() -> None:
    """Fifty is the middle of the scale and would read as a calm market."""
    reading = SentimentTimeline(daily([])).at(START)

    assert reading.known is False
    assert "no reading" in reading.describe()


def test_a_date_before_the_index_began_is_unknown() -> None:
    """It starts in 2018; some candle history starts earlier."""
    timeline = SentimentTimeline(daily([50, 60]))

    assert timeline.at(START - 10 * DAY).known is False


def test_a_long_publication_gap_is_not_papered_over() -> None:
    """A stopped feed is not a market that stopped having a mood."""
    timeline = SentimentTimeline(daily([50]))

    assert timeline.at(START + 30 * DAY).known is False


# --------------------------------------------------------------------------- #
# Reading it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "label"),
    [(5, "extreme fear"), (30, "fear"), (50, "neutral"), (65, "greed"), (90, "extreme greed")],
)
def test_the_published_bands_are_kept_as_published(value: int, label: str) -> None:
    assert classify(value) == label


@pytest.mark.parametrize("value", [10, 15, 85, 95])
def test_the_tails_are_marked_unusual(value: int) -> None:
    timeline = SentimentTimeline(daily([value, value, value]))

    assert timeline.at(START + 2 * DAY + 3_600_000).is_extreme is True


@pytest.mark.parametrize("value", [40, 50, 60])
def test_the_middle_is_not(value: int) -> None:
    timeline = SentimentTimeline(daily([value, value, value]))

    assert timeline.at(START + 2 * DAY + 3_600_000).is_extreme is False


# --------------------------------------------------------------------------- #
# Fetching and storing
# --------------------------------------------------------------------------- #


def test_the_fetch_sorts_oldest_first_whatever_the_api_returns() -> None:
    """The API answers newest first; every consumer here expects the opposite."""
    payload = {
        "data": [
            {"timestamp": "1700086400", "value": "70"},
            {"timestamp": "1700000000", "value": "60"},
        ]
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    with httpx.Client(transport=transport) as client:
        frame = fetch(client=client)

    assert list(frame["value"]) == [60, 70]
    assert frame["ts"].is_monotonic_increasing


def test_an_empty_response_is_an_error_not_an_empty_frame() -> None:
    """A backfill that covered nothing must not look like one that found nothing."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))

    with httpx.Client(transport=transport) as client, pytest.raises(SentimentUnavailableError):
        fetch(client=client)


def test_a_failed_request_is_an_error(tmp_path: object) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))

    with httpx.Client(transport=transport) as client, pytest.raises(SentimentUnavailableError):
        fetch(client=client)


def test_writing_twice_merges_rather_than_duplicating(tmp_path: object) -> None:
    store = SentimentStore(tmp_path / "sentiment.parquet")  # type: ignore[operator]
    store.write(daily([10, 20, 30]))
    total = store.write(daily([30, 40], start=START + 2 * DAY))

    assert total == 4
    assert store.read()["ts"].is_unique


def test_a_missing_file_reads_as_empty_rather_than_failing(tmp_path: object) -> None:
    store = SentimentStore(tmp_path / "nothing.parquet")  # type: ignore[operator]

    assert store.read().empty
