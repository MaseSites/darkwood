"""Clocks, injected rather than read.

Code that calls `datetime.now()` directly cannot be replayed: the backtest needs
simulated time, and anything that lands in a prompt needs to be stable or the
prompt cache silently never hits. So time arrives as a dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    """Wall clock, for live operation."""

    def now_ms(self) -> int:
        return int(datetime.now(tz=UTC).timestamp() * 1000)


class FixedClock:
    """A clock that stays put, for tests.

    Also what makes the forming-candle rule testable: pin the time, and whether a
    candle counts as closed becomes a property of the data rather than of when the
    test happened to run.
    """

    def __init__(self, now_ms: int) -> None:
        self._now = now_ms

    def now_ms(self) -> int:
        return self._now

    def set(self, now_ms: int) -> None:
        self._now = now_ms

    def advance(self, delta_ms: int) -> None:
        self._now += delta_ms
