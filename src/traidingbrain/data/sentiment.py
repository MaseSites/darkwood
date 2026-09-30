"""Crowd sentiment, as a number with a date on it.

The plan set the news weight to zero and gave a reason that still holds: you
cannot honestly reconstruct what a headline said, or when anyone read it, three
years after the fact. Anything built on that is a backtest measuring hindsight.

This is the exception, for the same reason the calendar was. The Fear & Greed
index is published once a day and never revised, so the value for a past day is
the value that existed on that day. There is nothing to reconstruct.

**The one-day rule.** A value stamped 00:00 on day D describes day D, and how
much of day D it already knows is not documented. So a decision on day D may
only see day D-1. That costs a day of freshness and removes the entire question
-- which is the right trade when the alternative is a signal that looks good in
a backtest for reasons nobody can name.

**What it is not.** A contrarian signal. Extreme fear is not a buy and extreme
greed is not a sell; crowds are right for most of a trend and wrong at the ends,
and a number cannot tell you which you are in. It goes into the snapshot as a
reading, and what to make of it is the model's problem, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

#: Free, no key, and it serves the whole history in one request.
FNG_URL = "https://api.alternative.me/fng/"

#: How stale a reading may be before it is treated as absent. The index is daily,
#: so two days of slack covers a missed publication without letting a week-old
#: number pass as current.
MAX_AGE_HOURS = 48

#: A decision may only see values stamped at least this far back. The index does
#: not document how much of its own day it already knows, and one day of delay
#: removes the question entirely.
LOOKBACK_HOURS = 24

DAY_MS = 86_400_000

#: The published band boundaries, kept exactly as the index publishes them. They
#: are named rather than inlined because they appear twice -- once for the label
#: and once for the extremes -- and two copies of a threshold drift apart.
EXTREME_FEAR_MAX = 24
FEAR_MAX = 44
NEUTRAL_MAX = 55
GREED_MAX = 74

#: Where a reading counts as unusual rather than ordinary. Wider than the
#: published extremes on purpose: this marks "worth mentioning", not "act".
UNUSUALLY_LOW = 25
UNUSUALLY_HIGH = 75

_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("value", pa.int64(), nullable=False),
    ]
)


class SentimentUnavailableError(RuntimeError):
    """The index could not be fetched.

    Raised rather than returning an empty frame, so a backfill that covered
    nothing is not mistaken for one that found nothing to add.
    """


@dataclass(frozen=True)
class SentimentReading:
    """One day's crowd mood, or the absence of one.

    `known` is a field rather than the object being absent because "no data" has
    to survive into the prompt. The index starts in 2018 and the candles start
    earlier for some venues; a model shown neutral where the truth is silence
    will weight the silence.
    """

    known: bool
    value: int = 50
    label: str = "unknown"
    age_hours: float = 0.0

    @property
    def is_extreme(self) -> bool:
        """The tails, where the reading is at least unusual.

        Not a signal. Crowds are right for most of a trend and wrong at its ends,
        and this cannot tell you which one you are looking at.
        """
        return self.known and (self.value <= UNUSUALLY_LOW or self.value >= UNUSUALLY_HIGH)

    def describe(self) -> str:
        if not self.known:
            return "sentiment: no reading for this date"
        return f"sentiment: {self.value}/100 ({self.label})"


def classify(value: int) -> str:
    """The published bands, kept as published rather than renamed."""
    if value <= EXTREME_FEAR_MAX:
        return "extreme fear"
    if value <= FEAR_MAX:
        return "fear"
    if value <= NEUTRAL_MAX:
        return "neutral"
    if value <= GREED_MAX:
        return "greed"
    return "extreme greed"


def fetch(limit: int = 0, *, client: httpx.Client | None = None) -> pd.DataFrame:
    """The whole index, newest first from the API and oldest first on return.

    `limit=0` means everything, which is a few thousand rows -- small enough that
    paging would be machinery without a purpose.
    """
    owned = client is None
    http = client or httpx.Client(timeout=30)
    try:
        response = http.get(FNG_URL, params={"limit": limit, "format": "json"})
        response.raise_for_status()
        rows = response.json().get("data", [])
    except (httpx.HTTPError, ValueError) as error:
        raise SentimentUnavailableError(f"could not fetch the index: {error}") from error
    finally:
        if owned:
            http.close()

    if not rows:
        raise SentimentUnavailableError("the index returned no rows")

    frame = pd.DataFrame(
        {
            "ts": [int(row["timestamp"]) * 1000 for row in rows],
            "value": [int(row["value"]) for row in rows],
        }
    )
    return frame.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)


class SentimentStore:
    """The index on disk, one file. A few thousand rows needs nothing more."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            stored: pd.DataFrame = pq.read_table(self.path).to_pandas()
            frame = (
                pd.concat([stored, frame], ignore_index=True)
                .drop_duplicates("ts", keep="last")
                .sort_values("ts")
                .reset_index(drop=True)
            )
        pq.write_table(
            pa.Table.from_pandas(frame[_SCHEMA.names], schema=_SCHEMA, preserve_index=False),
            self.path,
            compression="zstd",
        )
        return len(frame)

    def read(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame({"ts": pd.Series(dtype="int64"), "value": pd.Series(dtype="int64")})
        loaded: pd.DataFrame = pq.read_table(self.path).to_pandas()
        return loaded


class SentimentTimeline:
    """Readings aligned to decision times, with the one-day rule enforced here.

    Enforced in one place on purpose. A caller that forgets it would produce a
    backtest that quietly knows today's mood before today ended -- and the effect
    would be strongest exactly where sentiment moves, which is where it would
    look most like a finding.
    """

    def __init__(self, frame: pd.DataFrame, *, lookback_hours: int = LOOKBACK_HOURS) -> None:
        self.lookback_ms = lookback_hours * 3_600_000
        if frame.empty:
            self.ts = self.values = None
        else:
            ordered = frame.sort_values("ts")
            self.ts = ordered["ts"].to_numpy(dtype="int64")
            self.values = ordered["value"].to_numpy(dtype="int64")

    def at(self, decision_ts: int) -> SentimentReading:
        """The newest reading a decision at this moment was allowed to see."""
        if self.ts is None or self.values is None:
            return SentimentReading(known=False)

        cutoff = decision_ts - self.lookback_ms
        eligible = self.ts <= cutoff
        if not eligible.any():
            return SentimentReading(known=False)

        index = int(eligible.nonzero()[0][-1])
        age_hours = (decision_ts - int(self.ts[index])) / 3_600_000
        if age_hours > MAX_AGE_HOURS + LOOKBACK_HOURS:
            # A gap in publication, not a market that stopped having a mood.
            return SentimentReading(known=False)

        value = int(self.values[index])
        return SentimentReading(
            known=True, value=value, label=classify(value), age_hours=round(age_hours, 1)
        )


def day_of(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date().isoformat()
