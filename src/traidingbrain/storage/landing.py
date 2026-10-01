"""The landing zone, read over the wire.

Four statements and a connection. Everything that decides anything lives in
`data/sync.py`, where it can be tested without a database -- see the note on
`LandingZone` there for why the split is that way round.

The connection comes from the shared pool rather than a fresh one per call. The
sync runs twenty-odd series back to back, and twenty connections to a server
allowing twenty total is how the proposal tests learned this lesson.
"""

from __future__ import annotations

import pandas as pd

from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import FundingRate
from traidingbrain.storage.postgres import pool_for

#: Columns the archive expects, in the order it expects them.
_OHLCV_COLUMNS = ("ts", "open", "high", "low", "close", "volume")


class PostgresLandingZone:
    """`data.sync.LandingZone`, backed by the collector's database."""

    def __init__(self, url: str) -> None:
        self.url = url

    def ohlcv_since(self, symbol: str, timeframe: Timeframe, since_ms: int) -> pd.DataFrame:
        """Every stored bar at or after `since_ms`, oldest first.

        Read whole rather than in batches, and that is a decision about what
        this table is for: the landing zone holds what has not been filed yet,
        which on a daily sync is hours of bars. A landing zone big enough to
        need paging is itself the problem, and it shows up here as memory
        rather than as a silent partial drain.
        """
        with pool_for(self.url).connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ts, open, high, low, close, volume FROM ohlcv "
                "WHERE symbol = %s AND timeframe = %s AND ts >= %s ORDER BY ts",
                (symbol, timeframe.value, since_ms),
            )
            rows = cur.fetchall()
        if not rows:
            return pd.DataFrame({name: pd.Series(dtype="float64") for name in _OHLCV_COLUMNS})
        frame = pd.DataFrame(rows, columns=list(_OHLCV_COLUMNS))
        return frame.astype({"ts": "int64"})

    def funding_since(self, symbol: str, since_ms: int) -> list[FundingRate]:
        with pool_for(self.url).connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ts, rate FROM funding WHERE symbol = %s AND ts >= %s ORDER BY ts",
                (symbol, since_ms),
            )
            return [FundingRate(ts=int(ts), rate=float(rate)) for ts, rate in cur.fetchall()]

    def prune_ohlcv(self, symbol: str, timeframe: Timeframe, through_ms: int) -> int:
        """Delete bars the archive has been confirmed to hold.

        `<=` rather than `<`: the caller passes the newest timestamp the
        archive actually contains, re-read after writing, so that bar is one of
        the filed ones.
        """
        with pool_for(self.url).connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ohlcv WHERE symbol = %s AND timeframe = %s AND ts <= %s",
                (symbol, timeframe.value, through_ms),
            )
            return int(cur.rowcount)

    def prune_funding(self, symbol: str, through_ms: int) -> int:
        with pool_for(self.url).connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM funding WHERE symbol = %s AND ts <= %s", (symbol, through_ms)
            )
            return int(cur.rowcount)
