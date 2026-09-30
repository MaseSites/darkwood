"""Positioning data: how much is open, and which way the crowd leans.

Price says what happened. Open interest says whether it happened because someone
took on risk or because someone got out of it, and those are different markets
wearing the same candle.

The four combinations are the whole reason this is worth fetching:

| price | open interest | what it is                                  |
|-------|---------------|---------------------------------------------|
| up    | up            | new longs -- money arriving, trend supported |
| up    | down          | shorts covering -- a squeeze, not demand     |
| down  | up            | new shorts -- money arriving on the offer    |
| down  | down          | longs closing -- a flush, often exhaustion    |

A rally on falling open interest and a rally on rising open interest look
identical on a chart and are not the same trade. Nothing else in this system can
tell them apart.

**On lookahead.** Both series are timestamped at the close of the interval they
describe, exactly like a candle, and are read through the same
`index_at_or_before` discipline. Bybit serves them back to roughly March 2023,
which covers nearly the whole backfill window -- but not all of it, so a missing
reading has to stay missing rather than become a zero. "No data" and "open
interest did not change" are opposite claims.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from traidingbrain.data.venue import venue

#: Bybit returns at most this many rows per request.
MAX_PAGE = 200

#: Intervals Bybit accepts for these endpoints. Not the same set as for candles,
#: which is why this is spelled out rather than derived from Timeframe.
INTERVALS = {"5min", "15min", "30min", "1h", "4h", "1d"}

_COMPRESSION = "zstd"

_OI_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("open_interest", pa.float64(), nullable=False),
    ]
)

_RATIO_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("buy_ratio", pa.float64(), nullable=False),
        pa.field("sell_ratio", pa.float64(), nullable=False),
    ]
)


class DerivativesUnavailableError(RuntimeError):
    """The venue has no positioning data this far back.

    Raised rather than returning an empty frame, so a backfill that silently
    covered nothing is not mistaken for one that found nothing to add.
    """


@dataclass(frozen=True)
class FetchReport:
    """What a fetch actually retrieved, in terms worth printing."""

    symbol: str
    kind: str
    rows: int
    first_ts: int | None
    last_ts: int | None

    def summary(self) -> str:
        if not self.rows:
            return f"{self.symbol} {self.kind}: nothing returned"
        span = f"{_day(self.first_ts)} to {_day(self.last_ts)}"
        return f"{self.symbol} {self.kind}: {self.rows:,} rows, {span}"


def _day(ts: int | None) -> str:
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts / 1000, tz=UTC).date().isoformat()


class DerivativesSource:
    """Open interest and crowd positioning, read-only and credential-free.

    Through ccxt's unified methods rather than a venue's raw endpoints. The first
    version called Bybit's `/v5/market/open-interest` directly, which worked and
    quietly made the whole positioning factor Bybit-only -- a decision nobody
    made, buried in a URL. Both methods used here exist on Bybit and Binance and
    return the same two fields, which is exactly what unification is for.

    Separate from `MarketData` because these page differently and have a shorter
    history horizon, and folding them together would make one class whose failure
    modes have nothing to do with each other.
    """

    def __init__(self, exchange: Any, venue_name: str = "bybit", *, max_retries: int = 4) -> None:
        self.exchange = exchange
        self.venue = venue(venue_name)
        self.max_retries = max_retries

    def open_interest(
        self, symbol: str, *, interval: str = "1h", since_ms: int, until_ms: int
    ) -> pd.DataFrame:
        """Total contracts outstanding, one row per interval."""
        rows = self._paged(
            "open interest",
            self.exchange.fetch_open_interest_history,
            symbol,
            interval=interval,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        return _tidy(
            pd.DataFrame(
                {
                    "ts": [int(r["timestamp"]) for r in rows],
                    "open_interest": [float(r["openInterestAmount"] or 0.0) for r in rows],
                }
            )
        )

    def account_ratio(
        self, symbol: str, *, interval: str = "1h", since_ms: int, until_ms: int
    ) -> pd.DataFrame:
        """The share of accounts positioned each way.

        Stored as a share rather than the ratio the venues report, because a share
        is bounded and a ratio is not: 0.6 and 1.5 say the same thing, but only one
        of them can be averaged, compared across venues, or shown on a bar.

        Accounts, not size -- a thousand small longs and one large short both read
        as crowded to the long side. That is the intended reading: this is a
        sentiment measure and the crowd is counted by head.
        """
        rows = self._paged(
            "long/short ratio",
            self.exchange.fetch_long_short_ratio_history,
            symbol,
            interval=interval,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        shares = [_share_long(float(r["longShortRatio"] or 1.0)) for r in rows]
        return _tidy(
            pd.DataFrame(
                {
                    "ts": [int(r["timestamp"]) for r in rows],
                    "buy_ratio": shares,
                    "sell_ratio": [1.0 - share for share in shares],
                }
            )
        )

    # -- plumbing ----------------------------------------------------------- #

    def _paged(
        self,
        description: str,
        call: Any,
        symbol: str,
        *,
        interval: str,
        since_ms: int,
        until_ms: int,
    ) -> list[dict[str, Any]]:
        """Walk forward in windows until the range is covered.

        These endpoints stop at their own history horizon without saying so, so
        the loop ends on a page that returns nothing new -- never on a row count,
        which would spin forever once the venue runs out of history.
        """
        if interval not in INTERVALS:
            raise ValueError(f"{interval!r} is not an interval this endpoint accepts: {INTERVALS}")

        step = _interval_ms(interval)
        collected: list[dict[str, Any]] = []
        seen: set[int] = set()
        cursor = since_ms

        while cursor < until_ms:
            page = self._with_retry(
                description, call, self.venue.symbol(symbol), interval, cursor, MAX_PAGE
            )
            fresh = [
                row
                for row in page
                if row.get("timestamp") is not None
                and int(row["timestamp"]) not in seen
                and int(row["timestamp"]) <= until_ms
            ]
            if not fresh:
                break
            for row in fresh:
                seen.add(int(row["timestamp"]))
            collected.extend(fresh)
            newest = max(int(row["timestamp"]) for row in fresh)
            if newest <= cursor:
                break
            cursor = newest + step

        return collected

    def _with_retry(self, description: str, call: Any, *args: Any) -> list[dict[str, Any]]:
        delay = 1.0
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                result: list[dict[str, Any]] = call(*args)
                return result
            except Exception as exc:
                last = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(delay)
                delay *= 2
        raise DerivativesUnavailableError(
            f"{description} failed after {self.max_retries} attempts: {last}"
        )


def _share_long(ratio: float) -> float:
    """Longs-to-shorts, as a share of accounts that are long.

    A ratio of 1.5 means three longs for every two shorts, which is a 0.6 share.
    Clamped, because a venue reporting an absurd ratio should produce a bounded
    number rather than one that fails a model constraint three layers later.
    """
    if ratio <= 0:
        return 0.5
    return max(0.0, min(1.0, ratio / (1.0 + ratio)))


def _interval_ms(interval: str) -> int:
    units = {"min": 60_000, "h": 3_600_000, "d": 86_400_000}
    for suffix, size in units.items():
        if interval.endswith(suffix):
            return int(interval[: -len(suffix)]) * size
    raise ValueError(f"cannot size the interval {interval!r}")


def _tidy(frame: pd.DataFrame) -> pd.DataFrame:
    """Sort, deduplicate and reset. The order these arrive in is not guaranteed."""
    if frame.empty:
        return frame
    return (
        frame.drop_duplicates(subset="ts", keep="last")
        .sort_values("ts")
        .reset_index(drop=True)
        .astype({"ts": "int64"})
    )


class DerivativesStore:
    """Positioning series on disk, one file per symbol and kind.

    One file rather than partitioned by year: an hourly series over three years
    is twenty-six thousand rows, which is small enough that partitioning would
    add directories without saving a single rewrite.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, symbol: str, kind: str) -> Path:
        return self.root / symbol / f"{kind}.parquet"

    def write(self, symbol: str, kind: str, frame: pd.DataFrame) -> int:
        """Merge with whatever is stored and rewrite. Returns the total row count."""
        if frame.empty:
            return 0
        schema = _OI_SCHEMA if kind == "open_interest" else _RATIO_SCHEMA
        path = self.path(symbol, kind)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            stored: pd.DataFrame = pq.read_table(path).to_pandas()
            frame = _tidy(pd.concat([stored, frame], ignore_index=True))

        table = pa.Table.from_pandas(frame[schema.names], schema=schema, preserve_index=False)
        pq.write_table(table, path, compression=_COMPRESSION)
        return len(frame)

    def read(self, symbol: str, kind: str) -> pd.DataFrame:
        path = self.path(symbol, kind)
        if not path.exists():
            schema = _OI_SCHEMA if kind == "open_interest" else _RATIO_SCHEMA
            return pd.DataFrame({name: pd.Series(dtype="float64") for name in schema.names})
        loaded: pd.DataFrame = pq.read_table(path).to_pandas()
        return loaded


class LivePositioning:
    """Keeps a symbol's positioning series current while a live loop runs.

    The backfill fetches years; this fetches the last day and stops. They write to
    the same store, so a long-running session drifts no further from the venue
    than one interval.

    It exists because the staleness rule in `analysis.positioning` is unforgiving
    by design: a reading older than a few hours is reported as unknown rather than
    carried forward, since a venue that stopped reporting is not a market that
    stopped moving. Correct -- and it means that without something topping the
    series up, every reading goes unknown a few hours after the last backfill and
    stays that way. Silent, permanent, and indistinguishable from a period the
    venue genuinely does not cover.
    """

    def __init__(
        self,
        source: DerivativesSource,
        store: DerivativesStore,
        *,
        interval: str = "1h",
        lookback_hours: int = 24,
    ) -> None:
        self.source = source
        self.store = store
        self.interval = interval
        self.lookback_hours = lookback_hours

    def refresh(self, symbol: str, now_ms: int) -> int:
        """Top up both series. Returns how many rows were written."""
        since = now_ms - self.lookback_hours * 3_600_000
        written = 0
        for kind, fetch in (
            ("open_interest", self.source.open_interest),
            ("account_ratio", self.source.account_ratio),
        ):
            frame = fetch(symbol, interval=self.interval, since_ms=since, until_ms=now_ms)
            if not frame.empty:
                written += self.store.write(symbol, kind, frame)
        return written
