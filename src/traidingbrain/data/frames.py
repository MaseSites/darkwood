"""Conversion between candles and DataFrames, and the rule about closed bars.

Everything downstream assumes an OHLCV frame is sorted, gap-annotated, free of
duplicates, and contains *only closed candles*. That last one is the important
one, and it is enforced here rather than left to each caller to remember.

A forming candle is a trap that looks like data. Its high, low and close move
while you read them, so a backtest that includes the last row is quietly using
information from after the decision point -- and it will look better for it.
"""

from __future__ import annotations

import pandas as pd

from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import OHLCV_COLUMNS, Bar

_DTYPES: dict[str, str] = {
    "ts": "int64",
    "open": "float64",
    "high": "float64",
    "low": "float64",
    "close": "float64",
    "volume": "float64",
}


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


def drop_forming(frame: pd.DataFrame, timeframe: Timeframe, now_ms: int) -> pd.DataFrame:
    """Remove any candle that has not finished yet.

    Applied at the boundary of every fetch. If this is ever removed "because the
    exchange already only returns closed candles", the next exchange will not.
    """
    if frame.empty:
        return frame
    keep = frame["ts"] + timeframe_ms(timeframe) <= now_ms
    return frame.loc[keep].reset_index(drop=True)


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in _DTYPES.items()})


def bars_to_frame(bars: list[Bar]) -> pd.DataFrame:
    if not bars:
        return empty_frame()
    frame = pd.DataFrame([bar.model_dump() for bar in bars], columns=list(OHLCV_COLUMNS))
    return normalise(frame)


def frame_to_bars(frame: pd.DataFrame) -> list[Bar]:
    """Columns to objects, via numpy rather than `itertuples`.

    Roughly an order of magnitude faster on the frames this handles, and the
    dtypes are explicit instead of whatever the row tuple happened to carry.
    """
    ts = frame["ts"].to_numpy(dtype="int64")
    opens = frame["open"].to_numpy(dtype="float64")
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    volumes = frame["volume"].to_numpy(dtype="float64")
    return [
        Bar(
            ts=int(ts[i]),
            open=float(opens[i]),
            high=float(highs[i]),
            low=float(lows[i]),
            close=float(closes[i]),
            volume=float(volumes[i]),
        )
        for i in range(len(ts))
    ]


def normalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Canonical form: exact columns, exact dtypes, sorted, deduplicated.

    Deduplication keeps the last occurrence. When a re-fetch overlaps an existing
    range, the fresher copy is the one the exchange most recently affirmed -- and
    for a candle that was still forming at the time of the first fetch, it is also
    the correct one.
    """
    missing = set(OHLCV_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"OHLCV frame is missing columns: {sorted(missing)}")

    out = frame.loc[:, list(OHLCV_COLUMNS)].astype(_DTYPES)
    out = out.sort_values("ts", kind="stable")
    out = out.drop_duplicates(subset="ts", keep="last")
    return out.reset_index(drop=True)


def merge(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Fold a new fetch into what is already stored.

    Order matters: `incoming` goes second so that `keep="last"` prefers it on
    overlap.
    """
    if existing.empty:
        return normalise(incoming)
    if incoming.empty:
        return normalise(existing)
    return normalise(pd.concat([existing, incoming], ignore_index=True))


def slice_until(frame: pd.DataFrame, ts_inclusive: int) -> pd.DataFrame:
    """Everything up to and including a bar -- the only view analysis code may have.

    Analysis functions take this rather than the full frame plus an index, so that
    reaching into the future is awkward rather than a typo away.
    """
    return frame.loc[frame["ts"] <= ts_inclusive].reset_index(drop=True)
