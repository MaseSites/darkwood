"""Which trading session a bar falls in, and what that session has done so far.

Crypto never closes, so a "session" here is not an opening bell. It is the hours
when the desks in a region are staffed, and the difference shows up as liquidity
rather than as a gap: the same setup at 03:00 UTC and at 14:00 UTC is the same
picture drawn by very different numbers of participants.

**Defined in local time, converted here.** London is UTC+0 in winter and UTC+1 in
summer; New York is UTC-5 and UTC-4. A session pinned to a fixed UTC hour is an
hour wrong for half the year, and that hour is exactly the one around an open --
which is the part anyone cares about.

**The overlap is its own thing.** London and New York both staffed, roughly
13:00-16:00 UTC, is where most of the day's volume lands. It is not a fourth
region; it is a property of two, and it is reported as one.

What this does not do is say whether a session is good to trade. That is a rule,
rules belong in configuration, and this is the measurement they bind to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Session:
    """One region's staffed hours, in that region's own clock."""

    name: str
    zone: str
    open_hour: int
    close_hour: int

    def covers(self, moment: datetime) -> bool:
        """Is this session staffed at that instant?

        Converted into the region's own time first, so the answer stays correct
        across both daylight-saving changes without a table of exceptions.
        """
        local = moment.astimezone(ZoneInfo(self.zone))
        if self.open_hour <= self.close_hour:
            return self.open_hour <= local.hour < self.close_hour
        # A session that wraps midnight, which Sydney does.
        return local.hour >= self.open_hour or local.hour < self.close_hour


#: The four desks, in their own clocks. Hours are the staffed span rather than
#: an exchange's official session, because for crypto the exchange never closes
#: and what matters is who is at a desk.
SESSIONS: tuple[Session, ...] = (
    Session("sydney", "Australia/Sydney", 8, 17),
    Session("tokyo", "Asia/Tokyo", 9, 18),
    Session("london", "Europe/London", 8, 17),
    Session("new_york", "America/New_York", 8, 17),
)

#: The pair whose overlap carries most of the day's volume.
OVERLAP = ("london", "new_york")


@dataclass(frozen=True)
class SessionView:
    """Which desks are staffed at one bar, and what has happened since they opened."""

    active: tuple[str, ...]
    is_overlap: bool = False
    #: Bars since the newest active session opened, or None when none is active.
    bars_since_open: int | None = None
    #: Where price sits inside the range the active sessions have made so far,
    #: 0 at the low and 1 at the high. None until there is a range to speak of.
    position_in_range: float | None = None

    @property
    def is_quiet(self) -> bool:
        """No desk staffed. Common in crypto and worth saying out loud.

        Thin books move further on the same order, so a break at 03:00 UTC and
        the same break at 14:00 are not equally believable.
        """
        return not self.active

    def describe(self) -> str:
        if self.is_quiet:
            return "session: none staffed"
        names = " + ".join(self.active)
        return f"session: {names}{' (overlap)' if self.is_overlap else ''}"


def sessions_at(ts_ms: int) -> tuple[str, ...]:
    """Which desks are staffed at this instant."""
    moment = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    return tuple(session.name for session in SESSIONS if session.covers(moment))


class SessionTimeline:
    """Session state per bar, computed once in a forward pass.

    Built like the other timelines: everything at index `i` uses only bars at or
    before `i`, so it is safe to read inside a backtest loop without further
    guarding. The session range in particular is a running high and low of the
    current session, never the whole session's eventual range -- that would be
    the most ordinary kind of lookahead, and it would look like a working
    feature.
    """

    def __init__(self, frame: pd.DataFrame) -> None:
        self.ts = frame["ts"].to_numpy(dtype="int64")
        highs = frame["high"].to_numpy(dtype="float64")
        lows = frame["low"].to_numpy(dtype="float64")
        closes = frame["close"].to_numpy(dtype="float64")

        count = len(self.ts)
        self._active: list[tuple[str, ...]] = []
        self._since_open = np.full(count, -1, dtype="int64")
        self._position = np.full(count, np.nan)

        running_high = -np.inf
        running_low = np.inf
        opened_at: int | None = None
        previous: tuple[str, ...] = ()

        for index in range(count):
            active = sessions_at(int(self.ts[index]))
            self._active.append(active)

            if active != previous:
                # The staffed set changed, so the range starts again. Treated as
                # a new session even when one desk carries over: what the range
                # measures is "since this configuration of participants began".
                running_high, running_low = -np.inf, np.inf
                opened_at = index if active else None
                previous = active

            if not active:
                continue

            running_high = max(running_high, highs[index])
            running_low = min(running_low, lows[index])
            if opened_at is not None:
                self._since_open[index] = index - opened_at

            span = running_high - running_low
            if span > 0:
                self._position[index] = (closes[index] - running_low) / span

    def __len__(self) -> int:
        return len(self.ts)

    def at(self, index: int) -> SessionView:
        if index < 0 or index >= len(self.ts):
            return SessionView(active=())
        active = self._active[index]
        since = int(self._since_open[index])
        position = float(self._position[index])
        return SessionView(
            active=active,
            is_overlap=all(name in active for name in OVERLAP),
            bars_since_open=since if since >= 0 else None,
            position_in_range=round(position, 4) if np.isfinite(position) else None,
        )
