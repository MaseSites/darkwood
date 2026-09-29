"""Scheduled events, and the two ways a calendar becomes a time machine.

The plan set the news weight to zero for a good reason: point-in-time news
history is not honestly obtainable. A calendar is the exception, and it is only
an exception while these tests pass.

The first way it breaks is announcement dates. A file of future meeting dates
sits on disk during the whole backtest, so without a knowability check every
2023 bar can see the 2026 schedule. The second is daylight saving. Every US
release is scheduled in Eastern time, so a constant UTC hour is wrong for half
the year -- and an hour is exactly the difference between before and after.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from traidingbrain.data.calendar import (
    IMMINENT_HOURS,
    MacroCalendar,
    ScheduledEvent,
    derived_events,
    write_announced,
)


def ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp() * 1000)


def utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts / 1000, tz=UTC)


# --------------------------------------------------------------------------- #
# Knowability
# --------------------------------------------------------------------------- #


def test_an_event_is_invisible_before_its_schedule_was_published() -> None:
    """The check that keeps a file of future dates from being a time machine."""
    event = ScheduledEvent(
        name="FOMC rate decision",
        event_ts=ms("2026-09-17T18:00:00"),
        impact="high",
        announced_ts=ms("2025-06-01T00:00:00"),
    )

    assert event.is_knowable_at(ms("2025-01-01T00:00:00")) is False
    assert event.is_knowable_at(ms("2025-06-01T00:00:00")) is True


def test_a_calendar_standing_in_the_past_does_not_see_a_later_schedule() -> None:
    """The same rule, exercised the way a backtest exercises it.

    Every bar of a three-year backtest reads the same file, so this is not an
    edge case -- it is the normal path, and getting it wrong would leak hardest
    around the events that move price most.
    """
    calendar = MacroCalendar(
        [
            ScheduledEvent(
                name="announced late",
                event_ts=ms("2024-03-20T18:00:00"),
                impact="high",
                announced_ts=ms("2024-03-01T00:00:00"),
            )
        ]
    )

    assert calendar.upcoming(ms("2024-02-01T00:00:00"), horizon_hours=24 * 90) == []
    assert len(calendar.upcoming(ms("2024-03-15T00:00:00"), horizon_hours=24 * 10)) == 1


def test_an_entry_without_an_announcement_date_is_refused_not_defaulted(tmp_path: Path) -> None:
    """Defaulting to zero would readmit the leak silently, and for the best events."""
    path = tmp_path / "calendar.yaml"
    path.write_text(
        "events:\n"
        "- name: has one\n"
        "  event_ts: 1700000000000\n"
        "  announced: 1600000000000\n"
        "- name: missing one\n"
        "  event_ts: 1700000000000\n",
        encoding="utf-8",
    )

    calendar = MacroCalendar.load(path, first_year=2100, last_year=2100)
    names = {event.name for event in calendar.events}

    assert "has one" in names
    assert "missing one" not in names


def test_events_already_past_are_not_upcoming() -> None:
    calendar = MacroCalendar(
        [
            ScheduledEvent(
                name="gone",
                event_ts=ms("2024-01-01T00:00:00"),
                impact="high",
                announced_ts=0,
            )
        ]
    )

    assert calendar.upcoming(ms("2024-01-02T00:00:00")) == []


# --------------------------------------------------------------------------- #
# Daylight saving
# --------------------------------------------------------------------------- #


def test_payrolls_lands_an_hour_apart_in_summer_and_winter() -> None:
    """08:30 in New York is 13:30 UTC in winter and 12:30 in summer.

    A fixed UTC hour would put half the year's releases an hour wrong, and an
    hour is the difference between a position taken before one and after it.
    """
    events = {
        utc(event.event_ts).date().isoformat(): utc(event.event_ts)
        for event in derived_events(2024, 2024)
        if event.name == "US non-farm payrolls"
    }

    january = next(when for date, when in events.items() if date.startswith("2024-01"))
    july = next(when for date, when in events.items() if date.startswith("2024-07"))

    assert january.hour == 13, "winter: 08:30 EST is 13:30 UTC"
    assert july.hour == 12, "summer: 08:30 EDT is 12:30 UTC"


def test_payrolls_is_always_a_friday() -> None:
    fridays = {
        utc(event.event_ts).weekday()
        for event in derived_events(2023, 2026)
        if event.name == "US non-farm payrolls"
    }

    assert fridays == {4}


def test_there_is_one_payrolls_release_per_month() -> None:
    releases = [
        event for event in derived_events(2025, 2025) if event.name == "US non-farm payrolls"
    ]

    assert len(releases) == 12


# --------------------------------------------------------------------------- #
# Expiries
# --------------------------------------------------------------------------- #


def test_quarterly_expiries_are_marked_higher_impact_than_monthly() -> None:
    """Quarterly expiry carries most of the open interest, and it shows in price."""
    expiries = [event for event in derived_events(2025, 2025) if "expiry" in event.name]
    quarterly = [event for event in expiries if event.impact == "high"]

    assert len(expiries) == 12
    assert len(quarterly) == 4
    assert {utc(event.event_ts).month for event in quarterly} == {3, 6, 9, 12}


def test_every_expiry_is_the_last_friday_of_its_month() -> None:
    for event in derived_events(2024, 2024):
        if "expiry" not in event.name:
            continue
        when = utc(event.event_ts)
        assert when.weekday() == 4
        assert (when.day + 7) > _days_in_month(when.year, when.month)


def _days_in_month(year: int, month: int) -> int:
    from calendar import monthrange

    return monthrange(year, month)[1]


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #


def test_imminent_is_a_tighter_window_than_upcoming() -> None:
    """Different questions: "is one coming" and "will I still be in this trade"."""
    now = ms("2025-05-01T00:00:00")
    calendar = MacroCalendar(
        [
            ScheduledEvent("soon", now + 2 * 3_600_000, "high", 0),
            ScheduledEvent("later", now + (IMMINENT_HOURS + 10) * 3_600_000, "high", 0),
        ]
    )

    assert [event.name for event in calendar.imminent(now)] == ["soon"]
    assert len(calendar.upcoming(now)) == 2


def test_upcoming_is_ordered_nearest_first() -> None:
    now = ms("2025-05-01T00:00:00")
    calendar = MacroCalendar(
        [
            ScheduledEvent("third", now + 30 * 3_600_000, "low", 0),
            ScheduledEvent("first", now + 1 * 3_600_000, "low", 0),
            ScheduledEvent("second", now + 5 * 3_600_000, "low", 0),
        ]
    )

    assert [event.name for event in calendar.upcoming(now)] == ["first", "second", "third"]


def test_a_missing_file_still_gives_the_derived_half(tmp_path: Path) -> None:
    """The rules stand alone; a fetched schedule is an enrichment, not a dependency."""
    calendar = MacroCalendar.load(tmp_path / "nothing.yaml", first_year=2025, last_year=2025)

    assert len(calendar) == 24  # twelve payrolls, twelve expiries


def test_a_written_calendar_reads_back_identically(tmp_path: Path) -> None:
    """The file is meant to be inspected and corrected by hand, so it round-trips."""
    path = tmp_path / "calendar.yaml"
    original = [
        ScheduledEvent("FOMC rate decision", ms("2026-01-28T19:00:00"), "high", ms("2024-08-01")),
    ]
    write_announced(path, original, note="test")

    reloaded = [
        event
        for event in MacroCalendar.load(path, first_year=2100, last_year=2100).events
        if event.name == "FOMC rate decision"
    ]

    assert len(reloaded) == 1
    assert reloaded[0].event_ts == original[0].event_ts
    assert reloaded[0].announced_ts == original[0].announced_ts
