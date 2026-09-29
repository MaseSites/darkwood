"""Read the Federal Reserve's own meeting calendar into a file you can check.

    python scripts/fetch_fomc.py
    python scripts/fetch_fomc.py --show

Run once, not per backtest. The output is a YAML file that the analysis reads;
nothing here runs while a decision is being made. That is deliberate: a schedule
fetched live would make every backtest depend on a web page still existing and
still being laid out the same way, and a page that changes shape would quietly
change results rather than fail.

**On announcement dates.** Each meeting is recorded with when its date became
public, so a 2026 meeting cannot appear in a 2023 snapshot. The Fed publishes a
calendar roughly eighteen months out, so the announcement is estimated as
eighteen months before the meeting -- conservative in the right direction, since
being late makes an event invisible for longer rather than visible too early.
Erring the other way would be a time machine.

**On parsing a web page.** The markup will change eventually. It fails loudly
with what it found rather than writing a short file, because a calendar missing
half its meetings is worse than no calendar: the gaps look like quiet periods.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx

from traidingbrain.config.settings import load_config
from traidingbrain.data.calendar import (
    CALENDAR_FILENAME,
    ScheduledEvent,
    _eastern,
    write_announced,
)

URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

#: How far ahead the Fed publishes. Used to estimate when a date became public.
ANNOUNCE_LEAD_DAYS = 548

#: The statement lands at 14:00 in New York. Eastern, not UTC: the offset moves
#: twice a year and an hour is the difference between before and after.
STATEMENT_HOUR_ET = 14

#: A year with fewer than this many meetings means the parse missed some. The
#: FOMC has held eight scheduled meetings a year for decades.
MIN_MEETINGS_PER_YEAR = 6

_YEAR_PANEL = re.compile(r'<a id="\d+">(\d{4}) FOMC Meetings</a>')
_MEETING = re.compile(
    r'fomc-meeting__month[^"]*"><strong>([A-Za-z]+)(?:/([A-Za-z]+))?</strong>.*?'
    r'fomc-meeting__date[^"]*">\s*([\d\u2013-]+)',
    re.DOTALL,
)

_FULL_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

#: Both spellings, because the page uses the full name for a single-month meeting
#: and a three-letter abbreviation when one spans two months -- "Apr/May". Taking
#: only the full names silently dropped every cross-month meeting, which is four
#: or five a year and includes some of the most consequential.
MONTHS: dict[str, int] = {}
for _number, _name in enumerate(_FULL_MONTHS, start=1):
    MONTHS[_name] = _number
    MONTHS[_name[:3]] = _number


def parse(html: str) -> list[ScheduledEvent]:
    """Pull every meeting out of the page, one year panel at a time.

    Meetings run over two days and the decision lands on the second, so a range
    like "27-28" resolves to the 28th. A meeting spanning a month boundary is
    written "January/February", and there the second day belongs to the second
    month -- the one case where taking the first month silently misdates it.
    """
    panels = list(_YEAR_PANEL.finditer(html))
    if not panels:
        raise SystemExit("no year panels found: the page layout has changed")

    events: list[ScheduledEvent] = []
    per_year: dict[int, int] = {}

    for index, panel in enumerate(panels):
        year = int(panel.group(1))
        end = panels[index + 1].start() if index + 1 < len(panels) else len(html)
        body = html[panel.end() : end]

        for match in _MEETING.finditer(body):
            first_month, second_month, days = match.groups()
            month_name = second_month or first_month
            month = MONTHS.get(month_name)
            if month is None:
                continue
            day = int(re.split(r"[\u2013-]", days.strip())[-1])
            # A meeting written "December/January" decides in the next year.
            starts_in = MONTHS.get(first_month, month)
            # "Dec/Jan" decides in the following year; every other pair does not.
            meeting_year = year + 1 if second_month and starts_in > month else year

            event_ts = _eastern(meeting_year, month, day, STATEMENT_HOUR_ET)
            events.append(
                ScheduledEvent(
                    name="FOMC rate decision",
                    event_ts=event_ts,
                    impact="high",
                    announced_ts=event_ts - ANNOUNCE_LEAD_DAYS * 86_400_000,
                    source=URL,
                )
            )
            per_year[meeting_year] = per_year.get(meeting_year, 0) + 1

    thin = {year: count for year, count in per_year.items() if count < MIN_MEETINGS_PER_YEAR}
    if thin:
        raise SystemExit(
            f"only found {thin} meetings in those years; the FOMC holds eight.\n"
            "The page layout has probably changed. Refusing to write a calendar with\n"
            "holes in it -- a missing meeting reads as a quiet day, which is the one\n"
            "thing it is not."
        )
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--show", action="store_true", help="print what was found")
    args = parser.parse_args(argv)

    config = load_config()
    path = config.engine.paths.data_dir / CALENDAR_FILENAME

    print(f"reading {URL}")
    response = httpx.get(
        URL, timeout=30, follow_redirects=True, headers={"User-Agent": "traidingBrain/0.1"}
    )
    response.raise_for_status()

    events = parse(response.text)
    written = write_announced(
        path,
        events,
        note=(
            "Fetched from the Federal Reserve. Announcement dates are estimated at "
            f"{ANNOUNCE_LEAD_DAYS} days before each meeting, which is how far ahead the "
            "calendar is published. Statement time is 14:00 America/New_York."
        ),
    )

    years = sorted({datetime.fromtimestamp(e.event_ts / 1000, tz=UTC).year for e in events})
    print(f"  {written} meetings, {years[0]}-{years[-1]}")
    print(f"  written to {path}")

    if args.show:
        for event in sorted(events, key=lambda item: item.event_ts):
            when = datetime.fromtimestamp(event.event_ts / 1000, tz=UTC)
            print(f"    {when:%Y-%m-%d %H:%M} UTC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
