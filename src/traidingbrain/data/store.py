"""On-disk market data: Parquet partitions, read through DuckDB.

Layout is `data/ohlcv/{SYMBOL}/{TIMEFRAME}/{YEAR}.parquet`. Partitioning by year
keeps re-fetching a recent stretch from rewriting a million M1 rows, and it makes
the store inspectable with any Parquet tool.

Two properties this module is built around:

* **Writes are idempotent.** Running the same backfill twice produces
  byte-identical files. Without that there is no way to tell a real data change
  from write-order noise, and "the backtest result moved" becomes unanswerable.
* **Bad data does not get written.** Every write runs the validator first and
  refuses on anything that indicates a pipeline fault. Gaps are the exception --
  exchanges do go down -- and those are reported, not hidden.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from traidingbrain.data.frames import empty_frame, merge, normalise
from traidingbrain.data.validate import (
    DataQualityError,
    ValidationReport,
    validate_ohlcv,
)
from traidingbrain.domain.enums import Timeframe

#: Fixed so that two runs of the same backfill produce identical bytes.
_COMPRESSION = "zstd"
_ROW_GROUP_SIZE = 50_000

_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.float64(), nullable=False),
    ]
)


def year_of(ts_ms: int) -> int:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).year


class ParquetStore:
    """Market data on disk, one directory per symbol and timeframe."""

    def __init__(self, root: Path) -> None:
        self.root = root

    # -- layout ------------------------------------------------------------- #

    def directory(self, symbol: str, timeframe: Timeframe) -> Path:
        return self.root / symbol / timeframe.value

    def partition_path(self, symbol: str, timeframe: Timeframe, year: int) -> Path:
        return self.directory(symbol, timeframe) / f"{year}.parquet"

    def partitions(self, symbol: str, timeframe: Timeframe) -> list[Path]:
        directory = self.directory(symbol, timeframe)
        if not directory.exists():
            return []
        return sorted(directory.glob("*.parquet"))

    # -- reading ------------------------------------------------------------ #

    def read(
        self,
        symbol: str,
        timeframe: Timeframe,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> pd.DataFrame:
        """Read a range. Returns an empty, correctly typed frame when nothing is stored."""
        files = self.partitions(symbol, timeframe)
        if not files:
            return empty_frame()

        frames = [pq.read_table(path, schema=_SCHEMA).to_pandas() for path in files]
        combined = normalise(pd.concat(frames, ignore_index=True))
        if since_ms is not None:
            combined = combined.loc[combined["ts"] >= since_ms]
        if until_ms is not None:
            combined = combined.loc[combined["ts"] <= until_ms]
        return combined.reset_index(drop=True)

    def last_ts(self, symbol: str, timeframe: Timeframe) -> int | None:
        """Newest stored candle, for resuming an incremental backfill."""
        files = self.partitions(symbol, timeframe)
        if not files:
            return None
        newest = files[-1]
        table = pq.read_table(newest, columns=["ts"], schema=pa.schema([_SCHEMA.field("ts")]))
        if table.num_rows == 0:
            return None
        return int(max(table.column("ts").to_pylist()))

    def first_ts(self, symbol: str, timeframe: Timeframe) -> int | None:
        """Oldest stored candle.

        The mirror of `last_ts`, and needed for the same reason in the other
        direction: a backfill asked to reach further back has to know where the
        existing data starts, or it computes a resume point that is already
        covered and fetches nothing while reporting success.
        """
        files = self.partitions(symbol, timeframe)
        if not files:
            return None
        oldest = files[0]
        table = pq.read_table(oldest, columns=["ts"], schema=pa.schema([_SCHEMA.field("ts")]))
        if table.num_rows == 0:
            return None
        return int(min(table.column("ts").to_pylist()))

    def query(self, sql: str) -> pd.DataFrame:
        """Run SQL over the Parquet tree.

        DuckDB reads the partitions directly, so ad-hoc analysis does not need a
        loading step and does not go through pandas twice.
        """
        with duckdb.connect() as conn:
            return conn.execute(sql).fetch_df()

    def glob(self, symbol: str, timeframe: Timeframe) -> str:
        """A DuckDB-friendly path pattern for `read_parquet`."""
        return str(self.directory(symbol, timeframe) / "*.parquet").replace("\\", "/")

    # -- writing ------------------------------------------------------------ #

    def write(
        self,
        symbol: str,
        timeframe: Timeframe,
        frame: pd.DataFrame,
        *,
        validate: bool = True,
    ) -> ValidationReport:
        """Merge a frame into the store and return what the validator saw.

        Existing partitions are read, merged and rewritten, so an overlapping
        re-fetch corrects whatever was there rather than appending a second copy.
        """
        incoming = normalise(frame)
        if incoming.empty:
            return validate_ohlcv(incoming, symbol, timeframe)

        touched_years = sorted({year_of(ts) for ts in incoming["ts"]})
        merged_parts: list[pd.DataFrame] = []

        for year in touched_years:
            path = self.partition_path(symbol, timeframe, year)
            existing = (
                pq.read_table(path, schema=_SCHEMA).to_pandas() if path.exists() else empty_frame()
            )
            slice_ = incoming.loc[incoming["ts"].map(year_of) == year]
            merged_parts.append(merge(existing, slice_))

        combined = normalise(pd.concat(merged_parts, ignore_index=True))
        report = validate_ohlcv(combined, symbol, timeframe)
        if validate and report.is_fatal:
            raise DataQualityError(report)

        for year, part in zip(touched_years, merged_parts, strict=True):
            self._write_partition(symbol, timeframe, year, normalise(part))

        return report

    def _write_partition(
        self, symbol: str, timeframe: Timeframe, year: int, frame: pd.DataFrame
    ) -> None:
        path = self.partition_path(symbol, timeframe, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(frame, schema=_SCHEMA, preserve_index=False)
        pq.write_table(
            table,
            path,
            compression=_COMPRESSION,
            row_group_size=_ROW_GROUP_SIZE,
            write_statistics=True,
            store_schema=True,
            version="2.6",
        )

    # -- reporting ---------------------------------------------------------- #

    def report(self, symbol: str, timeframe: Timeframe) -> ValidationReport:
        return validate_ohlcv(self.read(symbol, timeframe), symbol, timeframe)

    def coverage(self, symbol: str, timeframe: Timeframe) -> tuple[int, int] | None:
        frame = self.read(symbol, timeframe)
        if frame.empty:
            return None
        return int(frame["ts"].iloc[0]), int(frame["ts"].iloc[-1])
