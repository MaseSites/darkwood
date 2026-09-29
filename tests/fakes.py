"""Test doubles for the outside world.

The suite runs with the network switched off, so every external edge has a double
here. `FakeCcxtExchange` deliberately behaves the way a real venue does in the
ways that matter: it returns the candle that is still forming, it caps page size,
and it will happily hand back the same page forever if the caller does not
advance the cursor. All three are things the production code has to survive.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

    from traidingbrain.config.settings import EngineConfig

from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import Bar, FundingRate, SymbolSpec

#: An arbitrary but fixed anchor: 2024-01-01T00:00:00Z.
EPOCH = 1_704_067_200_000


def synthetic_rows(
    start_ts: int, timeframe: Timeframe, count: int, base: float = 42_000.0
) -> list[list[float]]:
    """Deterministic candles in ccxt's list-of-lists shape.

    A slow sine with a small saw on top: enough shape for swings and trends to
    exist, and identical on every run so golden files stay golden.
    """
    step = timeframe_ms(timeframe)
    rows: list[list[float]] = []
    for i in range(count):
        ts = start_ts + i * step
        drift = base * 0.02 * math.sin(i / 40.0)
        wiggle = base * 0.002 * ((i % 7) - 3)
        open_ = base + drift + wiggle
        close = base + drift + wiggle * 0.6 + base * 0.0005 * ((i % 5) - 2)
        high = max(open_, close) + base * 0.0012 * (1 + (i % 3))
        low = min(open_, close) - base * 0.0012 * (1 + ((i + 1) % 3))
        volume = 100.0 + (i % 11) * 3.5
        rows.append([float(ts), open_, high, low, close, volume])
    return rows


class FakeCcxtExchange:
    """Enough of the ccxt surface for `BybitDataSource` to run against."""

    def __init__(
        self,
        rows: list[list[float]],
        timeframe: Timeframe = Timeframe.H1,
        page_cap: int = 1000,
        market: dict[str, Any] | None = None,
        funding: list[dict[str, Any]] | None = None,
    ) -> None:
        self.rows = rows
        self.timeframe = timeframe
        self.page_cap = page_cap
        self.calls: list[tuple[str, str, int, int]] = []
        self.load_markets_calls = 0
        self._market = market or _default_market()
        self._funding = funding or []

    def load_markets(self) -> dict[str, Any]:
        self.load_markets_calls += 1
        return {self._market["symbol"]: self._market}

    def market(self, symbol: str) -> dict[str, Any]:
        return self._market

    def set_sandbox_mode(self, enabled: bool) -> None:  # pragma: no cover - trivial
        self.sandbox = enabled

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> list[list[float]]:
        self.calls.append((symbol, timeframe, since, limit))
        page = [row for row in self.rows if row[0] >= since]
        return page[: min(limit, self.page_cap)]

    def fetch_funding_rate_history(
        self, symbol: str, since: int, limit: int
    ) -> list[dict[str, Any]]:
        return [f for f in self._funding if f["timestamp"] >= since][:limit]


def _default_market() -> dict[str, Any]:
    return {
        "symbol": "BTC/USDT:USDT",
        "precision": {"price": 0.1, "amount": 0.001},
        "limits": {
            "amount": {"min": 0.001},
            "cost": {"min": 5.0},
            "leverage": {"max": 100.0},
        },
        "taker": 0.00055,
        "maker": 0.0002,
        "maintenanceMarginRate": 0.005,
        "info": {},
    }


class FakeDataSource:
    """A `DataSource` backed by a fixed list of bars.

    Pagination is honest -- it slices by `since` and `limit` -- so the backfiller's
    cursor logic is genuinely exercised rather than short-circuited.
    """

    def __init__(
        self,
        bars: list[Bar],
        page_size: int = 1000,
        spec: SymbolSpec | None = None,
        funding: list[FundingRate] | None = None,
    ) -> None:
        self.bars = sorted(bars, key=lambda b: b.ts)
        self.page_size = page_size
        self.spec = spec
        self.funding = funding or []
        self.fetch_calls: list[tuple[str, Timeframe, int, int]] = []

    def fetch_ohlcv(
        self, symbol: str, timeframe: Timeframe, since_ms: int, limit: int
    ) -> list[Bar]:
        self.fetch_calls.append((symbol, timeframe, since_ms, limit))
        window = [bar for bar in self.bars if bar.ts >= since_ms]
        return window[: min(limit, self.page_size)]

    def fetch_funding(self, symbol: str, since_ms: int, limit: int) -> list[FundingRate]:
        return [f for f in self.funding if f.ts >= since_ms][:limit]

    def fetch_symbol_spec(self, symbol: str) -> SymbolSpec:
        if self.spec is None:
            raise LookupError(f"no spec configured for {symbol}")
        return self.spec


class StuckDataSource:
    """A venue that never advances the cursor.

    Real ones do this, usually at the edge of their retention window. A paginating
    client that does not notice spins forever.
    """

    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.calls = 0

    def fetch_ohlcv(
        self, symbol: str, timeframe: Timeframe, since_ms: int, limit: int
    ) -> list[Bar]:
        self.calls += 1
        return list(self.bars)

    def fetch_funding(self, symbol: str, since_ms: int, limit: int) -> list[FundingRate]:
        return []

    def fetch_symbol_spec(self, symbol: str) -> SymbolSpec:
        raise LookupError(symbol)


def bars_from_rows(rows: list[list[float]]) -> list[Bar]:
    return [
        Bar(
            ts=int(r[0]),
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=float(r[5]),
        )
        for r in rows
    ]


def aggregate(frame: pd.DataFrame, to_timeframe: Timeframe) -> pd.DataFrame:
    """Roll a fine frame up to a coarser one, on the correct grid.

    Used to build consistent multi-timeframe fixtures from a single series, so a
    test's weekly candle is genuinely the weekly view of its own hourly candles
    rather than an unrelated random walk that happens to sit beside them.

    The weekly grid is offset by four days: the Unix epoch was a Thursday and
    exchanges open the week on Monday.
    """
    import pandas as pd

    from traidingbrain.data.frames import grid_offset_ms, normalise, timeframe_ms

    step = timeframe_ms(to_timeframe)
    offset = grid_offset_ms(to_timeframe)
    bucket = ((frame["ts"] - offset) // step) * step + offset

    rolled = (
        frame.assign(bucket=bucket)
        .groupby("bucket", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
        .rename(columns={"bucket": "ts"})
    )
    return normalise(pd.DataFrame(rolled))


def multi_frame_fixture(
    m15_bars: int = 3000, start_ts: int = EPOCH
) -> dict[Timeframe, pd.DataFrame]:
    """A consistent set of frames: one series, viewed at five resolutions."""
    from traidingbrain.data.frames import bars_to_frame

    base = bars_to_frame(bars_from_rows(synthetic_rows(start_ts, Timeframe.M15, m15_bars)))
    return {
        Timeframe.M15: base,
        Timeframe.H1: aggregate(base, Timeframe.H1),
        Timeframe.H4: aggregate(base, Timeframe.H4),
        Timeframe.D1: aggregate(base, Timeframe.D1),
        Timeframe.W1: aggregate(base, Timeframe.W1),
    }


def fast_engine_config(context: list[Timeframe] | None = None) -> EngineConfig:
    """An engine config with short warm-up windows, for property tests.

    The shipped config needs roughly a year of history before the weekly frame
    says anything -- `ema_slow` alone is 55 bars, which on W1 is 55 weeks. That is
    the right setting for trading and the wrong one for a test that wants to build
    a few hundred snapshots. Shortening the windows changes how much history is
    needed, not whether the code reaches into the future, which is what these tests
    are about.
    """
    from traidingbrain.config.settings import load_config

    base = load_config().engine
    frames = context or [Timeframe.H4, Timeframe.H1, Timeframe.M15]
    return base.model_copy(
        update={
            "timeframes": base.timeframes.model_copy(
                update={"context": frames, "signal": Timeframe.H1}
            ),
            "indicators": base.indicators.model_copy(
                update={"atr_period": 7, "rsi_period": 7, "ema_fast": 5, "ema_slow": 12}
            ),
            "regime": base.regime.model_copy(update={"volatility_window": 24, "trend_window": 12}),
        }
    )
