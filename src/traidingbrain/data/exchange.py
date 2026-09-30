"""Bybit market data through ccxt.

This is one of only two modules allowed to import `ccxt` -- the boundary is
checked by a test -- so that "what can reach the exchange" stays a one-line
answer.

Venue choice: Binance's futures testnet does not resolve, Bybit's does, and
Bybit's public API serves all four target symbols. Everything sits behind the
`DataSource` protocol, so moving venue later is a configuration change rather
than a rewrite.

**History comes from mainnet, trading goes to testnet.** These are separate
decisions and the default reflects that. A testnet's price history is thin and
partly synthetic -- backtesting against it would measure a market that does not
exist. The public kline endpoint needs no credentials, so reading mainnet prices
carries no risk; only `execution` touches an account, and that one defaults to
testnet.
"""

from __future__ import annotations

import time
from typing import Any

import ccxt

from traidingbrain.clock import SystemClock
from traidingbrain.data.grid import is_closed
from traidingbrain.data.venue import venue
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import Bar, FundingRate, SymbolSpec
from traidingbrain.domain.protocols import Clock

#: Bybit v5 caps a kline page at 1000.
MAX_PAGE = 1000

#: Fallback when the exchange does not publish a maintenance margin rate for a
#: symbol. Deliberately conservative: overstating it moves the computed
#: liquidation price closer to entry, which makes the sizing more cautious, not
#: less.
DEFAULT_MAINTENANCE_MARGIN_RATE = 0.005

_RETRYABLE = (
    ccxt.NetworkError,
    ccxt.ExchangeNotAvailable,
    ccxt.RequestTimeout,
    ccxt.DDoSProtection,
    ccxt.RateLimitExceeded,
    ccxt.OnMaintenance,
)

#: Bybit reports its own transient faults as ordinary exchange errors. Retrying
#: every `ExchangeError` would also retry a bad symbol forever, so only the
#: server-side ones are matched -- 10016 is Bybit's generic internal failure and
#: shows up several times in a two-thousand-request minute backfill.
_RETRYABLE_MESSAGES = ("10016", "svc error", "system error", "server error", "10002")


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, _RETRYABLE):
        return True
    if isinstance(exc, ccxt.ExchangeError):
        text = str(exc).lower()
        return any(marker in text for marker in _RETRYABLE_MESSAGES)
    return False


def to_ccxt_symbol(symbol: str) -> str:
    """`BTCUSDT` -> `BTC/USDT:USDT`, the ccxt name for a USDT-margined perpetual."""
    if "/" in symbol:
        return symbol
    if not symbol.endswith("USDT"):
        raise ValueError(f"only USDT-quoted perpetuals are supported, got {symbol!r}")
    base = symbol[: -len("USDT")]
    return f"{base}/USDT:USDT"


class MarketData:
    """Read-only market data. Holds no credentials and places no orders.

    The venue comes from configuration rather than being built in. It used to be
    `ccxt.bybit` here and again in the executor, while settings.yaml carried an
    `exchange.name` nothing read -- so the config described a choice the code did
    not offer.
    """

    def __init__(
        self,
        *,
        venue_name: str = "bybit",
        testnet: bool = False,
        rate_limit_ms: int = 120,
        clock: Clock | None = None,
        max_retries: int = 4,
        exchange: Any | None = None,
    ) -> None:
        self.clock: Clock = clock or SystemClock()
        self.max_retries = max_retries
        self._markets_loaded = False
        self.venue = venue(venue_name)

        if exchange is not None:
            self.exchange = exchange
        else:
            self.exchange = self.venue.build(testnet=testnet, rate_limit_ms=rate_limit_ms)

    # -- plumbing ----------------------------------------------------------- #

    def _load_markets(self) -> None:
        if not self._markets_loaded:
            self.exchange.load_markets()
            self._markets_loaded = True

    def _with_retry(self, description: str, call: Any, *args: Any, **kwargs: Any) -> Any:
        """Retry the failures that are about the network, not about the request.

        A bad symbol or a malformed parameter is not going to succeed on the third
        attempt, so only transport-level errors are retried.
        """
        delay = 1.0
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return call(*args, **kwargs)
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                last = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(delay)
                delay *= 2
        raise RuntimeError(
            f"{description} failed after {self.max_retries} attempts: {last}"
        ) from last

    # -- DataSource --------------------------------------------------------- #

    def fetch_ohlcv(
        self, symbol: str, timeframe: Timeframe, since_ms: int, limit: int = MAX_PAGE
    ) -> list[Bar]:
        """One page of candles, oldest first, forming candle removed.

        The exchange happily returns the candle currently being built. Including it
        is the most effective way to make a backtest look good and a live system
        disappoint, so it is dropped here, at the boundary, once.
        """
        self._load_markets()
        raw = self._with_retry(
            f"fetch_ohlcv({symbol}, {timeframe})",
            self.exchange.fetch_ohlcv,
            self.venue.symbol(symbol),
            timeframe.ccxt_timeframe,
            since_ms,
            min(limit, MAX_PAGE),
        )
        now = self.clock.now_ms()
        bars: list[Bar] = []
        for row in raw:
            ts = int(row[0])
            if not is_closed(ts, timeframe, now):
                continue
            bars.append(
                Bar(
                    ts=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
        return bars

    def last_price(self, symbol: str) -> float | None:
        """The current mark price, or None if it cannot be had.

        This is what the confirmation path checks a proposal against. None means
        unknown, and the caller must treat unknown as "refuse", never as "no drift"
        -- a proposal priced twenty minutes ago is a trade nobody agreed to.
        """
        self._load_markets()
        try:
            ticker = self._with_retry(
                f"ticker for {symbol}", self.exchange.fetch_ticker, self.venue.symbol(symbol)
            )
        except Exception:
            return None
        for field in ("last", "close", "mark", "markPrice"):
            value = ticker.get(field) if isinstance(ticker, dict) else None
            if value:
                return float(value)
        return None

    def fetch_funding(self, symbol: str, since_ms: int, limit: int = 200) -> list[FundingRate]:
        """Realised funding rates.

        Charged from history rather than estimated: a guessed funding rate quietly
        changes the outcome of every trade held across a settlement.
        """
        self._load_markets()
        raw = self._with_retry(
            f"fetch_funding_rate_history({symbol})",
            self.exchange.fetch_funding_rate_history,
            self.venue.symbol(symbol),
            since_ms,
            limit,
        )
        return [
            FundingRate(ts=int(entry["timestamp"]), rate=float(entry["fundingRate"]))
            for entry in raw
            if entry.get("timestamp") is not None and entry.get("fundingRate") is not None
        ]

    def fetch_symbol_spec(self, symbol: str) -> SymbolSpec:
        """Tick size, step size, fees and maintenance margin, straight from the venue.

        Hardcoding these is how orders get rejected in production for reasons that
        never showed up in a test.
        """
        self._load_markets()
        market = self.exchange.market(self.venue.symbol(symbol))
        limits = market.get("limits") or {}
        precision = market.get("precision") or {}
        amount_limits = limits.get("amount") or {}
        cost_limits = limits.get("cost") or {}
        leverage_limits = limits.get("leverage") or {}

        return SymbolSpec(
            symbol=symbol,
            price_tick=float(precision.get("price") or 0.01),
            qty_step=float(precision.get("amount") or 0.001),
            min_qty=float(amount_limits.get("min") or 0.001),
            min_notional=float(cost_limits.get("min") or 0.0),
            max_leverage=float(leverage_limits.get("max") or 25.0),
            taker_fee=float(market.get("taker") or 0.00055),
            maker_fee=float(market.get("maker") or 0.0002),
            maintenance_margin_rate=_maintenance_margin_rate(market),
        )


def _maintenance_margin_rate(market: dict[str, Any]) -> float:
    """Dig the maintenance margin out of wherever the venue put it."""
    for key in ("maintenanceMarginRate", "maintenance_margin_rate"):
        value = market.get(key)
        if value:
            return float(value)
    info = market.get("info") or {}
    for key in ("maintenanceMargin", "mmr", "maintenanceMarginRate"):
        value = info.get(key)
        if value:
            return float(value)
    return DEFAULT_MAINTENANCE_MARGIN_RATE
