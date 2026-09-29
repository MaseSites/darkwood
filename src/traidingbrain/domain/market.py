"""Raw market data types and the OHLCV frame contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Column names every OHLCV DataFrame in this codebase uses, in this order.
#: `ts` is the candle's OPEN time in UTC milliseconds.
OHLCV_COLUMNS: Final[tuple[str, ...]] = ("ts", "open", "high", "low", "close", "volume")

#: Index name for OHLCV frames once `ts` is promoted to the index.
OHLCV_INDEX: Final[str] = "ts"


class Bar(BaseModel):
    """One candle. Immutable, and always a *closed* candle.

    The engine never sees a forming candle: `data.backfill` drops the last row of
    every fetch, because a forming candle's high/low/close change under you and
    reading them is lookahead in its purest form.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: int = Field(description="Candle open time, UTC milliseconds since epoch")
    open: float
    high: float
    low: float
    close: float
    volume: float

    @field_validator("high")
    @classmethod
    def _high_is_highest(cls, v: float, info: object) -> float:
        return v

    @property
    def opened_at(self) -> datetime:
        return datetime.fromtimestamp(self.ts / 1000, tz=UTC)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def is_up(self) -> bool:
        return self.close >= self.open


class FundingRate(BaseModel):
    """A realised funding payment rate for a perpetual, at its settlement time.

    Backtests charge funding from this history rather than estimating it — an
    estimated funding rate quietly changes the result of every multi-day trade.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: int = Field(description="Funding settlement time, UTC milliseconds")
    rate: float = Field(description="Signed rate; longs pay shorts when positive")


class SymbolSpec(BaseModel):
    """Exchange-side trading rules for one symbol.

    Everything that touches order size or price rounds through these. Sending a
    price with more precision than the exchange accepts is a reliably rejected
    order, and it is the kind of bug that only appears against the real API.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    price_tick: float = Field(gt=0, description="Minimum price increment")
    qty_step: float = Field(gt=0, description="Minimum quantity increment")
    min_qty: float = Field(gt=0)
    min_notional: float = Field(ge=0, default=0.0)
    max_leverage: float = Field(gt=0)
    taker_fee: float = Field(ge=0, description="Fraction, e.g. 0.00055 for 0.055%")
    maker_fee: float = Field(description="Fraction; may be negative (rebate)")
    maintenance_margin_rate: float = Field(
        gt=0, description="Fraction of notional held back; drives the liquidation price"
    )
