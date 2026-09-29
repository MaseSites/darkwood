"""Scheduled events, and the one property that makes them usable.

The plan set the news weight to zero and gave the reason: point-in-time news
history is not honestly obtainable, and weighting something the backtest cannot
see guarantees a divergence between backtest and live. That reasoning stands for
*news*. It does not stand for a *calendar*.

The difference is when the information existed. A headline is known at the moment
it is published, and reconstructing what was known at 14:00 three years ago is
the part nobody can do honestly. A schedule is published months ahead: the Federal
Reserve announces its meeting dates more than a year before they happen, and the
first Friday of the month has been payrolls day for decades. "FOMC in six hours"
was as knowable on the day as it is now.

So this module carries two kinds of event and refuses to mix them:

**Derived** events come from a rule that has always been true -- the first Friday,
the last Friday of a quarter. There is nothing to verify and nothing to fetch.

**Announced** events come from a published schedule and carry `announced_ts`,
the date the schedule itself became public. An event is invisible before then,
which keeps a 2026 meeting date out of a 2023 snapshot even though the file
listing it sits on disk the whole time.

What is deliberately missing: CPI and other releases whose dates follow no rule
and which this module has no authoritative source for. Guessing them would put
unverifiable data into the one place -- the evidence a decision rests on -- where
being approximately right is worse than being absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

#: Events further out than this are not decision-relevant and only add noise.
DEFAULT_HORIZON_HOURS = 72

#: Anything inside this window is close enough that a position taken now will
#: still be open when it lands.
IMMINENT_HOURS = 8

_EASTERN = ZoneInfo("America/New_York")

#: Python numbers weekdays from Monday; Friday is the fourth.
FRIDAY = 4

#: Where the schedule file lives relative to the data directory.
CALENDAR_FILENAME = "macro_calendar.yaml"


@dataclass(frozen=True)
class ScheduledEvent:
    """One dated event, with when it became knowable.

    `announced_ts` is the whole point. Without it a file of future dates is a
    small time machine: every backtest bar would see a schedule that had not been
    published yet, and the effect would be strongest exactly where it matters --
    around the events that move price.
    """

    name: str
    event_ts: int
    impact: str
    announced_ts: int
    source: str = ""

    def is_knowable_at(self, now_ms: int) -> bool:
        return now_ms >= self.announced_ts

    def minutes_until(self, now_ms: int) -> int:
        return int((self.event_ts - now_ms) / 60_000)


def _to_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _eastern(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    """A wall-clock time in New York, converted to UTC.

    Every US release is scheduled in Eastern time, so the UTC hour moves twice a
    year. Pinning a constant UTC hour would put half the events an hour wrong,
    and an hour is the difference between "before the release" and "after".
    """
    return _to_ms(datetime(year, month, day, hour, minute, tzinfo=_EASTERN))


def _first_friday(year: int, month: int) -> datetime:
    day = datetime(year, month, 1, tzinfo=UTC)
    while day.weekday() != FRIDAY:
        day += timedelta(days=1)
    return day


def _last_friday(year: int, month: int) -> datetime:
    day = datetime(year, month, 1, tzinfo=UTC) + timedelta(days=32)
    day = day.replace(day=1) - timedelta(days=1)
    while day.weekday() != FRIDAY:
        day -= timedelta(days=1)
    return day


def derived_events(first_year: int, last_year: int) -> list[ScheduledEvent]:
    """Events that follow a rule which has always been in force.

    `announced_ts` is zero for these: the rule predates any backtest window, so
    there is no moment at which the date was not knowable.
    """
    events: list[ScheduledEvent] = []
    for year in range(first_year, last_year + 1):
        for month in range(1, 13):
            payrolls = _first_friday(year, month)
            events.append(
                ScheduledEvent(
                    name="US non-farm payrolls",
                    # 08:30 in New York, which is 12:30 or 13:30 UTC by season.
                    event_ts=_eastern(payrolls.year, payrolls.month, payrolls.day, 8, 30),
                    impact="high",
                    announced_ts=0,
                    source="rule: first Friday of the month",
                )
            )

            expiry = _last_friday(year, month)
            quarterly = month in (3, 6, 9, 12)
            events.append(
                ScheduledEvent(
                    name=("quarterly" if quarterly else "monthly") + " crypto options expiry",
                    event_ts=_to_ms(
                        datetime(expiry.year, expiry.month, expiry.day, 8, 0, tzinfo=UTC)
                    ),
                    impact="high" if quarterly else "medium",
                    announced_ts=0,
                    source="rule: last Friday, 08:00 UTC",
                )
            )
    return events


class MacroCalendar:
    """The events knowable at a given moment, nearest first.

    Holds everything in memory and answers by scanning. A few thousand events
    over several years is small enough that an index would be machinery without a
    purpose, and a scan is obviously correct.
    """

    def __init__(self, events: list[ScheduledEvent] | None = None) -> None:
        self.events = sorted(events or [], key=lambda event: event.event_ts)

    @classmethod
    def load(
        cls, path: Path | None = None, *, first_year: int = 2022, last_year: int = 2030
    ) -> MacroCalendar:
        """Rule-derived events, plus an announced schedule if one is on disk.

        A missing file is normal and not an error: the derived half stands on its
        own, and the fetched half is an enrichment.
        """
        events = derived_events(first_year, last_year)
        if path is not None and path.exists():
            events.extend(_read_announced(path))
        return cls(events)

    def upcoming(
        self, now_ms: int, *, horizon_hours: int = DEFAULT_HORIZON_HOURS
    ) -> list[ScheduledEvent]:
        """Events ahead of `now_ms` that were already scheduled by then."""
        until = now_ms + horizon_hours * 3_600_000
        return [
            event
            for event in self.events
            if now_ms <= event.event_ts <= until and event.is_knowable_at(now_ms)
        ]

    def imminent(self, now_ms: int) -> list[ScheduledEvent]:
        """Close enough that a position opened now will still be open for it."""
        return self.upcoming(now_ms, horizon_hours=IMMINENT_HOURS)

    def __len__(self) -> int:
        return len(self.events)


def _read_announced(path: Path) -> list[ScheduledEvent]:
    """Load a fetched schedule, skipping anything that does not say when it was known.

    An entry without `announced` is refused rather than defaulted to zero.
    Defaulting would silently readmit the time machine this module exists to
    close, and it would do so for exactly the events worth the most.
    """
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    events: list[ScheduledEvent] = []
    for row in payload.get("events", []):
        if "announced" not in row:
            continue
        events.append(
            ScheduledEvent(
                name=str(row["name"]),
                event_ts=int(row["event_ts"]),
                impact=str(row.get("impact", "medium")),
                announced_ts=int(row["announced"]),
                source=str(row.get("source", "")),
            )
        )
    return events


def write_announced(path: Path, events: list[ScheduledEvent], *, note: str = "") -> int:
    """Persist a fetched schedule in a form a person can read and correct."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "note": note,
        "events": [
            {
                "name": event.name,
                "event_ts": event.event_ts,
                "utc": datetime.fromtimestamp(event.event_ts / 1000, tz=UTC).isoformat(),
                "impact": event.impact,
                "announced": event.announced_ts,
                "source": event.source,
            }
            for event in sorted(events, key=lambda item: item.event_ts)
        ],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return len(events)
