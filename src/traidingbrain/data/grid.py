"""Where a candle sits on the clock, and when it is finished.

Pure arithmetic over timestamps -- no pandas, no DataFrame, nothing that has to
be installed. That is the entire reason this is its own module: the rule about
closed candles has to hold on every machine that touches market data, and the
collector runs on a Raspberry Pi where pandas costs more memory than the whole
job is allowed to use.

Previously this lived in `frames.py`, which imports pandas at module level for
DataFrame helpers a collector never calls. Importing `is_closed` therefore
dragged in a hundred megabytes to answer a question that is one addition and one
comparison -- and the alternative, letting the collector reimplement it, is how
two machines end up disagreeing about whether a candle is done.

`frames.py` re-exports everything here, so every existing caller is unchanged.
"""

from __future__ import annotations

from traidingbrain.domain.enums import Timeframe

#: The Unix epoch fell on a Thursday, but exchanges open the weekly candle on
#: Monday. So the weekly grid is offset by four days; every other frame divides
#: the epoch evenly because 1970-01-01 was midnight UTC.
#: 1970-01-05T00:00:00Z, the first Monday.
_WEEKLY_GRID_OFFSET_MS = 4 * 24 * 60 * 60 * 1000


def timeframe_ms(timeframe: Timeframe) -> int:
    return timeframe.minutes * 60_000


def grid_offset_ms(timeframe: Timeframe) -> int:
    """Where this timeframe's grid starts, relative to the epoch."""
    return _WEEKLY_GRID_OFFSET_MS if timeframe is Timeframe.W1 else 0


def is_aligned(ts: int, timeframe: Timeframe) -> bool:
    """Does this timestamp sit on a candle boundary for the timeframe?

    A misaligned timestamp means the pipeline mixed frames or mangled a value --
    worth refusing a write over, which is why it has to be right for every frame
    rather than only the convenient ones.
    """
    return (ts - grid_offset_ms(timeframe)) % timeframe_ms(timeframe) == 0


def close_time_ms(open_ts: int, timeframe: Timeframe) -> int:
    """When the candle that opened at `open_ts` finishes."""
    return open_ts + timeframe_ms(timeframe)


def is_closed(open_ts: int, timeframe: Timeframe, now_ms: int) -> bool:
    """A candle is usable only once its close time has passed.

    Strictly `<=`: at exactly the close time the candle is complete, and the next
    one has just opened.
    """
    return close_time_ms(open_ts, timeframe) <= now_ms
