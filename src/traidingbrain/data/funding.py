"""Funding rate history.

Perpetual futures have no expiry, so the venue keeps them tethered to spot by
making one side pay the other every eight hours. Over a trade held for days this
is a real, one-directional cost, and it is the one people leave out of backtests
because it is small per settlement and invisible per trade.

It is not small in aggregate. A trend-following strategy is long during rallies,
which is exactly when funding is most positive and longs pay most. Estimating a
constant rate would systematically understate the cost of the trades the strategy
takes most often -- which is worse than leaving it out, because it looks like it
has been handled.

So: fetched from the venue, stored, and charged at its own settlement times.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from traidingbrain.domain.market import FundingRate
from traidingbrain.domain.protocols import DataSource

_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("rate", pa.float64(), nullable=False),
    ]
)

#: Bybit pages funding history 200 at a time.
PAGE_SIZE = 200


class FundingStore:
    """One Parquet file per symbol."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, symbol: str) -> Path:
        return self.root / f"{symbol}.parquet"

    def read(self, symbol: str) -> list[FundingRate]:
        path = self.path(symbol)
        if not path.exists():
            return []
        table = pq.read_table(path, schema=_SCHEMA).to_pandas()
        return [
            FundingRate(ts=int(row.ts), rate=float(row.rate))
            for row in table.itertuples(index=False)
        ]

    def write(self, symbol: str, rates: list[FundingRate]) -> int:
        """Merge and store. Returns how many settlements are on disk afterwards."""
        if not rates:
            return len(self.read(symbol))

        incoming = pd.DataFrame(
            {"ts": [r.ts for r in rates], "rate": [r.rate for r in rates]}
        )
        existing = self.read(symbol)
        if existing:
            incoming = pd.concat(
                [
                    pd.DataFrame(
                        {"ts": [r.ts for r in existing], "rate": [r.rate for r in existing]}
                    ),
                    incoming,
                ],
                ignore_index=True,
            )

        merged = (
            incoming.astype({"ts": "int64", "rate": "float64"})
            .sort_values("ts", kind="stable")
            .drop_duplicates(subset="ts", keep="last")
            .reset_index(drop=True)
        )

        path = self.path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.Table.from_pandas(merged, schema=_SCHEMA, preserve_index=False),
            path,
            compression="zstd",
        )
        return len(merged)

    def last_ts(self, symbol: str) -> int | None:
        rates = self.read(symbol)
        return rates[-1].ts if rates else None


def backfill_funding(
    source: DataSource,
    store: FundingStore,
    symbol: str,
    since_ms: int,
    until_ms: int | None = None,
    *,
    resume: bool = True,
    max_pages: int = 200,
) -> list[FundingRate]:
    """Page through funding history and store it.

    Bounded by `max_pages` rather than trusting the venue to stop returning data.
    A paginating loop against an endpoint that repeats its last page is one of the
    standard ways a data job never finishes.
    """
    cursor = since_ms
    if resume:
        stored = store.last_ts(symbol)
        if stored is not None:
            cursor = max(cursor, stored + 1)

    collected: list[FundingRate] = []
    for _ in range(max_pages):
        page = source.fetch_funding(symbol, cursor, PAGE_SIZE)
        if not page:
            break
        if until_ms is not None:
            page = [rate for rate in page if rate.ts <= until_ms]
            if not page:
                break
        collected.extend(page)
        newest = max(rate.ts for rate in page)
        if newest <= cursor:
            break
        cursor = newest + 1

    if collected:
        store.write(symbol, collected)
    return collected
