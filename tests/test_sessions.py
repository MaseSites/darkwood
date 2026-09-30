"""Which desks are staffed, and the two ways that gets quietly wrong.

Crypto never closes, so a session here is not an opening bell -- it is how many
people are watching, and it shows up as liquidity rather than as a gap. The same
break at 03:00 UTC and at 14:00 is the same picture drawn by very different
numbers of participants.

Two failures this pins. The first is daylight saving: London is UTC+0 in winter
and UTC+1 in summer, New York is UTC-5 and UTC-4, so a session pinned to a fixed
UTC hour is an hour wrong for half the year -- and that hour is the one around an
open, which is the part anyone cares about. The second is the session range,
which is the most ordinary lookahead available here: measured over the whole
session it would tell a bar at 09:00 what the day's high would be.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.sessions import OVERLAP, SessionTimeline, sessions_at

HOUR = 3_600_000


def at(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=UTC).timestamp() * 1000)


def hourly(start_iso: str, closes: list[float]) -> pd.DataFrame:
    start = at(start_iso)
    return pd.DataFrame(
        {
            "ts": [start + i * HOUR for i in range(len(closes))],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1.0] * len(closes),
        }
    )


# --------------------------------------------------------------------------- #
# Daylight saving
# --------------------------------------------------------------------------- #


def test_london_opens_an_hour_earlier_in_utc_during_summer() -> None:
    """08:00 London is 08:00 UTC in winter and 07:00 UTC in summer.

    A fixed UTC hour is wrong for half the year, and wrong exactly around the
    open -- which is the hour a session rule would be written about.
    """
    assert "london" not in sessions_at(at("2026-01-15T07:30:00"))
    assert "london" in sessions_at(at("2026-07-15T07:30:00"))


def test_new_york_shifts_too() -> None:
    assert "new_york" not in sessions_at(at("2026-01-15T12:30:00"))
    assert "new_york" in sessions_at(at("2026-07-15T12:30:00"))


def test_tokyo_does_not_shift_because_japan_has_no_daylight_saving() -> None:
    """The control. If this moved, the conversion itself would be wrong."""
    for iso in ("2026-01-15T02:00:00", "2026-07-15T02:00:00"):
        assert "tokyo" in sessions_at(at(iso))


def test_the_overlap_is_when_both_western_desks_are_staffed() -> None:
    active = sessions_at(at("2026-07-15T14:00:00"))

    assert all(name in active for name in OVERLAP)


def test_there_is_an_hour_with_nobody_staffed() -> None:
    """Between New York closing and Sydney opening, and it really is one hour.

    Worth pinning as a number rather than a vibe: if the definitions drifted so
    that the desks covered the clock, "quiet hour" would silently stop meaning
    anything and every bar would read as staffed.
    """
    quiet = [
        hour
        for hour in range(24)
        if not sessions_at(at(f"2026-07-15T{hour:02d}:30:00"))
    ]

    assert quiet == [21]


# --------------------------------------------------------------------------- #
# The session range
# --------------------------------------------------------------------------- #


def test_the_range_only_knows_bars_that_have_happened() -> None:
    """The most ordinary lookahead available here, and the most convincing.

    Measured over the whole session, a bar at the open would be told where the
    session would close relative to its eventual high -- and the feature would
    look excellent.
    """
    # No wicks, so a rising close is exactly the running high and the position
    # is exactly 1. With wicks the arithmetic is still right but the number is
    # not obviously right, and a test nobody can check by hand is weaker.
    # 12:00 to 15:00 UTC in July is London and New York throughout, so the
    # staffed set never changes and the range never restarts. Crossing a change
    # would be testing the restart instead, which has its own test.
    rising = hourly("2026-07-15T12:00:00", [100, 101, 102, 103])
    rising["high"] = rising["close"]
    rising["low"] = rising["close"]
    timeline = SessionTimeline(rising)

    # The first bar has no range yet; every later one is its own running high.
    positions = [timeline.at(i).position_in_range for i in range(1, 4)]

    assert positions == [1.0, 1.0, 1.0], positions


def test_rewriting_later_bars_does_not_move_an_earlier_reading() -> None:
    frame = hourly("2026-07-15T08:00:00", [100, 101, 102, 103, 104, 105])
    before = SessionTimeline(frame).at(2)

    mutated = frame.copy()
    mutated.loc[3:, ["open", "high", "low", "close"]] = 999.0
    after = SessionTimeline(mutated).at(2)

    assert before == after


def test_the_range_restarts_when_the_staffed_set_changes() -> None:
    """A new configuration of participants is a new range.

    Carrying it across means a London reading measured against Tokyo's night,
    which is not what "where are we in the session" is asking.
    """
    # 05:00 to 12:00 UTC in July crosses Tokyo-only into London.
    frame = hourly("2026-07-15T05:00:00", [100, 110, 120, 130, 90, 95, 100, 105])
    timeline = SessionTimeline(frame)

    opens = [timeline.at(i).bars_since_open for i in range(len(frame))]

    assert 0 in opens[1:], f"no session ever restarted: {opens}"


def test_a_quiet_bar_reports_no_session_rather_than_a_stale_one() -> None:
    frame = hourly("2026-07-15T21:00:00", [100, 101, 102, 103])
    timeline = SessionTimeline(frame)

    quiet = [timeline.at(i) for i in range(len(frame)) if timeline.at(i).is_quiet]

    assert quiet, "the fixture never reached a quiet hour"
    for view in quiet:
        assert view.active == ()
        assert view.bars_since_open is None
        assert "none staffed" in view.describe()


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("index", [-1, 999])
def test_an_index_outside_the_frame_is_quiet_rather_than_an_error(index: int) -> None:
    timeline = SessionTimeline(hourly("2026-07-15T08:00:00", [100, 101]))

    assert timeline.at(index).is_quiet is True


def test_a_flat_session_has_no_position_rather_than_a_made_up_one() -> None:
    """Zero range cannot be divided, and 0.5 would be an invention."""
    flat = hourly("2026-07-15T08:00:00", [100.0, 100.0])
    flat[["high", "low"]] = 100.0
    timeline = SessionTimeline(flat)

    assert timeline.at(1).position_in_range is None


def test_the_position_stays_inside_its_bounds() -> None:
    rng = np.random.default_rng(3)
    closes = [float(rng.uniform(90, 110)) for _ in range(40)]
    timeline = SessionTimeline(hourly("2026-07-15T06:00:00", closes))

    for index in range(len(closes)):
        position = timeline.at(index).position_in_range
        assert position is None or 0.0 <= position <= 1.0
