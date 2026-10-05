"""Which side took liquidity, per candle.

In every executed trade there is a buyer and a seller, so counting either tells
you nothing. What carries information is which side crossed the spread to take
what was offered. Binance's candle data answers that directly: alongside total
volume it reports the volume bought by takers, and the rest was sold by takers.

    flow_imbalance = (taker_buy - taker_sell) / total
                   = (2 * taker_buy - total) / total

**Why this is a separate store and not a column on `Bar`.** The OHLCV schema is
shared by twelve markets and six timeframes of multi-year Parquet files, and
adding a column means either re-fetching all of it or carrying two schemas.
Funding is already kept this way -- its own files, read separately, joined by
timestamp -- and the reason is the same: it is an additional observation about a
moment, not a property of the candle. Nothing that reads candles today changes.

**What this is not.** It is measured taker volume, not an estimate. A proxy
that guesses the buy/sell split from candle colour or from where the close sits
in the range is a different thing and must never be reported as order flow;
this project has no such proxy, which was checked rather than assumed.

**The reach of the data.** The per-candle taker volume comes from the klines
endpoint and goes back as far as the candles do. Binance's separate
taker-long/short *ratio* endpoint serves only the last 30 days, which is a
different series and cannot substitute for multi-year tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from traidingbrain.domain.enums import Timeframe

_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64()),
        pa.field("volume", pa.float64()),
        pa.field("taker_buy", pa.float64()),
        pa.field("trades", pa.int64()),
    ]
)


@dataclass(frozen=True)
class Flow:
    """One candle's taker split.

    `ts` is the candle open time, the same key the OHLCV frames use, so the two
    join without any alignment logic.
    """

    ts: int
    volume: float
    taker_buy: float
    trades: int

    @property
    def taker_sell(self) -> float:
        """What takers sold, derived rather than fetched.

        The venue reports total and taker-buy; the remainder is taker-sell by
        construction, which is why only two numbers need storing.
        """
        return max(0.0, self.volume - self.taker_buy)

    @property
    def imbalance(self) -> float:
        """Signed, in [-1, +1]. Zero volume gives zero rather than a division.

        A candle with no trades has no imbalance to report, and returning NaN
        here would quietly poison any feature built on it.
        """
        if self.volume <= 0:
            return 0.0
        return (2.0 * self.taker_buy - self.volume) / self.volume


class FlowStore:
    """One Parquet file per symbol and timeframe."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, symbol: str, timeframe: Timeframe) -> Path:
        return self.root / f"{symbol}-{timeframe.value}.parquet"

    def read(self, symbol: str, timeframe: Timeframe) -> list[Flow]:
        path = self.path(symbol, timeframe)
        if not path.exists():
            return []
        table = pq.read_table(path, schema=_SCHEMA).to_pandas()
        return [
            Flow(
                ts=int(row.ts),
                volume=float(row.volume),
                taker_buy=float(row.taker_buy),
                trades=int(row.trades),
            )
            for row in table.itertuples(index=False)
        ]

    def frame(self, symbol: str, timeframe: Timeframe) -> pd.DataFrame:
        """The same data as a frame, for joining against candles by `ts`."""
        path = self.path(symbol, timeframe)
        if not path.exists():
            return pd.DataFrame(
                {"ts": pd.Series(dtype="int64"), "imbalance": pd.Series(dtype="float64")}
            )
        table = pq.read_table(path, schema=_SCHEMA).to_pandas()
        total = table["volume"].to_numpy()
        buy = table["taker_buy"].to_numpy()
        # Guarded the same way `Flow.imbalance` is: a candle with no volume has
        # no imbalance, and a NaN here would travel into every feature built on
        # it and be blamed on the model.
        imbalance = pd.Series(
            [(2.0 * b - t) / t if t > 0 else 0.0 for t, b in zip(total, buy, strict=True)],
            dtype="float64",
        )
        return pd.DataFrame({"ts": table["ts"].astype("int64"), "imbalance": imbalance})

    def write(self, symbol: str, timeframe: Timeframe, rows: list[Flow]) -> int:
        """Merge and store. Returns how many candles are on disk afterwards."""
        if not rows:
            return len(self.read(symbol, timeframe))

        def to_frame(items: list[Flow]) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "ts": [r.ts for r in items],
                    "volume": [r.volume for r in items],
                    "taker_buy": [r.taker_buy for r in items],
                    "trades": [r.trades for r in items],
                }
            )

        incoming = to_frame(rows)
        existing = self.read(symbol, timeframe)
        if existing:
            incoming = pd.concat([to_frame(existing), incoming], ignore_index=True)

        merged = (
            incoming.astype(
                {"ts": "int64", "volume": "float64", "taker_buy": "float64", "trades": "int64"}
            )
            .sort_values("ts", kind="stable")
            # keep="last" so a refetch corrects a row rather than duplicating
            # it, which matters because the newest candle of any fetch was
            # still forming when an earlier run saw it.
            .drop_duplicates(subset="ts", keep="last")
            .reset_index(drop=True)
        )

        path = self.path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.Table.from_pandas(merged, schema=_SCHEMA, preserve_index=False),
            path,
            compression="zstd",
        )
        return len(merged)

    def last_ts(self, symbol: str, timeframe: Timeframe) -> int | None:
        rows = self.read(symbol, timeframe)
        return rows[-1].ts if rows else None
