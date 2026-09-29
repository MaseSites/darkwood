"""Technical indicators, written here rather than imported.

Two reasons for owning these. `pandas-ta` is unmaintained and does not install
cleanly on current Python, and -- more importantly -- an indicator library is a
place where lookahead hides. Every function in this module is backward-looking by
construction, and the tests compare each one against an independent naive
implementation to 1e-9 rather than trusting that claim.

The rules this module holds to:

* No `shift(-n)`, no `center=True`, no `bfill`. Each of those pulls a future value
  into the present, and each looks perfectly innocent in a diff.
* Warm-up produces NaN, not a filled-in guess. A 14-period average does not exist
  on bar 3, and pretending otherwise puts a number into the snapshot that the
  market never supported.
* Wilder's smoothing where Wilder specified it. RSI and ATR computed with a simple
  mean are a different indicator that happens to share a name, and the difference
  is large enough to change which setups trigger.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

#: A rolling statistic needs at least two observations to mean anything.
MIN_WINDOW = 2


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average with the conventional 2/(n+1) smoothing."""
    if span < 1:
        raise ValueError(f"span must be >= 1, got {span}")
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing, seeded the way Wilder specified it.

    Also called RMA. The recursion is `avg[i] = (avg[i-1] * (n-1) + x[i]) / n`,
    which is an EMA with alpha = 1/n rather than the usual 2/(n+1). Substituting a
    normal EMA gives a visibly different line.

    The seed matters as much as the recursion, and this is where a one-line
    `ewm(alpha=1/n, adjust=False)` quietly goes wrong. Pandas starts the recursion
    at the very first observation, so the whole series carries the weight of one
    early value. Wilder seeds with the simple average of the first `n`
    observations and recurses from there, which is also what every charting
    platform draws. Since the whole point of RSI and ATR here is to mean the same
    thing they mean on the user's chart, this follows Wilder.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    values = series.to_numpy(dtype="float64")
    out = np.full(values.shape, np.nan, dtype="float64")

    valid = np.nonzero(~np.isnan(values))[0]
    if valid.size < period:
        return pd.Series(out, index=series.index, name=series.name)

    start = int(valid[0]) + period - 1
    if start >= values.size or np.isnan(values[int(valid[0]) : start + 1]).any():
        return pd.Series(out, index=series.index, name=series.name)

    out[start] = values[int(valid[0]) : start + 1].mean()
    for i in range(start + 1, values.size):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period

    return pd.Series(out, index=series.index, name=series.name)


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def true_range(frame: pd.DataFrame) -> pd.Series:
    """The greater of this bar's range and its gap from the previous close.

    The first bar has no previous close, so its true range is undefined rather
    than simply its own high minus low.
    """
    prev_close = frame["close"].shift(1)
    spans = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    tr = spans.max(axis=1)
    tr.iloc[0] = np.nan
    return tr


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average true range, Wilder-smoothed.

    The scale unit of the whole system: distances reach the model in ATR, position
    size is derived from the stop distance in ATR, and volatility buckets are
    percentiles of it.
    """
    return wilder_smooth(true_range(frame), period)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative strength index, Wilder-smoothed.

    A flat stretch with no losses gives an infinite relative strength; the
    conventional reading there is 100, and that is what this returns rather than
    an inf that would poison everything downstream.
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = wilder_smooth(gain, period)
    avg_loss = wilder_smooth(loss, period)

    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss != 0.0, 100.0)
    out = out.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    return out.where(avg_gain.notna() & avg_loss.notna())


@dataclass(frozen=True)
class Macd:
    line: pd.Series
    signal: pd.Series
    histogram: pd.Series


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Macd:
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be shorter than slow ({slow})")
    line = ema(series, fast) - ema(series, slow)
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return Macd(line=line, signal=signal_line, histogram=line - signal_line)


@dataclass(frozen=True)
class Bollinger:
    middle: pd.Series
    upper: pd.Series
    lower: pd.Series
    _upper_cache: np.ndarray | None = None
    _lower_cache: np.ndarray | None = None

    def percent_b(self, close: pd.Series) -> pd.Series:
        """Where price sits in the band: 0 at the lower edge, 1 at the upper.

        Scale-free, which is what makes it safe to hand to the model.
        """
        width = self.upper - self.lower
        return ((close - self.lower) / width).where(width != 0.0)

    def percent_b_at(self, close: float, index: int) -> float:
        """The same thing for one bar, without building the whole series.

        The series form was being called once per bar and indexed once -- O(n) work
        for a single number, repeated n times. On a two-year backtest that was a
        third of the total runtime on its own.
        """
        upper = float(self._upper_values[index])
        lower = float(self._lower_values[index])
        width = upper - lower
        if width == 0.0 or math.isnan(width):
            return float("nan")
        return (close - lower) / width

    @property
    def _upper_values(self) -> np.ndarray:
        if self.__dict__.get("_upper_cache") is None:
            object.__setattr__(self, "_upper_cache", self.upper.to_numpy(dtype="float64"))
        return self.__dict__["_upper_cache"]  # type: ignore[no-any-return]

    @property
    def _lower_values(self) -> np.ndarray:
        if self.__dict__.get("_lower_cache") is None:
            object.__setattr__(self, "_lower_cache", self.lower.to_numpy(dtype="float64"))
        return self.__dict__["_lower_cache"]  # type: ignore[no-any-return]


def bollinger(series: pd.Series, period: int = 20, std: float = 2.0) -> Bollinger:
    """Bollinger bands using the population standard deviation.

    `ddof=0` on purpose: the band is a description of the window, not an estimate
    of a wider population, and every charting package computes it this way.
    """
    middle = sma(series, period)
    deviation = series.rolling(period, min_periods=period).std(ddof=0)
    return Bollinger(middle=middle, upper=middle + std * deviation, lower=middle - std * deviation)


def rolling_percentile_rank(series: pd.Series, window: int) -> pd.Series:
    """Where the current value sits within its own recent history, in [0, 1].

    Rolling, never global. A percentile computed over the whole dataset tells the
    model on every bar how this moment compares to years it has not lived through
    yet -- lookahead that no amount of careful indexing elsewhere can undo.
    """
    if window < MIN_WINDOW:
        raise ValueError(f"window must be >= {MIN_WINDOW}, got {window}")

    def rank(values: np.ndarray) -> float:
        current = values[-1]
        if np.isnan(current):
            return float("nan")
        history = values[:-1]
        history = history[~np.isnan(history)]
        if history.size == 0:
            return float("nan")
        return float((history <= current).sum()) / float(history.size)

    return series.rolling(window, min_periods=max(MIN_WINDOW, window // 4)).apply(rank, raw=True)


def slope(series: pd.Series, window: int) -> pd.Series:
    """Least-squares slope over a trailing window, normalised by the mean level.

    Normalising makes it comparable across symbols and price regimes, which is
    what lets a read learned on BTC mean the same thing on XRP.
    """
    if window < MIN_WINDOW:
        raise ValueError(f"window must be >= {MIN_WINDOW}, got {window}")
    x = np.arange(window, dtype="float64")
    x_centred = x - x.mean()
    denominator = float((x_centred**2).sum())

    def fit(values: np.ndarray) -> float:
        if np.isnan(values).any():
            return float("nan")
        beta = float((x_centred * (values - values.mean())).sum()) / denominator
        level = float(np.abs(values).mean())
        return beta / level if level else float("nan")

    return series.rolling(window, min_periods=window).apply(fit, raw=True)


#: Series that must all carry a value before a snapshot may be built.
_READY_SERIES = (
    "atr",
    "rsi",
    "ema_fast",
    "ema_slow",
    "macd_line",
    "macd_signal",
    "bb_middle",
    "volume_ma",
)


@dataclass
class IndicatorSet:
    """Every indicator for one timeframe, aligned to the same index."""

    atr: pd.Series
    rsi: pd.Series
    ema_fast: pd.Series
    ema_slow: pd.Series
    macd: Macd
    bollinger: Bollinger
    volume_ma: pd.Series

    #: Series as numpy arrays, built once.
    #:
    #: Reading indicators is a per-bar operation and `Series.iloc` costs about a
    #: microsecond each time. Over twenty thousand bars and six readings per frame
    #: across five frames that was seconds of pure indexing overhead.
    _arrays: dict[str, np.ndarray] = field(default_factory=dict, compare=False)

    def _by_name(self) -> dict[str, pd.Series]:
        """Flat names onto the nested structure.

        Written out rather than resolved with `getattr`: a typo in a name should be
        a KeyError here, not an AttributeError three frames away.
        """
        return {
            "atr": self.atr,
            "rsi": self.rsi,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "macd_line": self.macd.line,
            "macd_signal": self.macd.signal,
            "macd_histogram": self.macd.histogram,
            "bb_middle": self.bollinger.middle,
            "bb_upper": self.bollinger.upper,
            "bb_lower": self.bollinger.lower,
            "volume_ma": self.volume_ma,
        }

    def values(self, name: str) -> np.ndarray:
        cached = self._arrays.get(name)
        if cached is None:
            cached = self._by_name()[name].to_numpy(dtype="float64")
            self._arrays[name] = cached
        return cached

    def at(self, name: str, index: int) -> float:
        return float(self.values(name)[index])

    def warmup_bars(self) -> int:
        """How many bars must pass before every series carries a value."""
        return int(max((s.isna().sum() for s in self._series()), default=0))

    def _series(self) -> list[pd.Series]:
        return [
            self.atr,
            self.rsi,
            self.ema_fast,
            self.ema_slow,
            self.macd.line,
            self.macd.signal,
            self.bollinger.middle,
            self.volume_ma,
        ]

    def is_ready(self, index: int) -> bool:
        """Is every indicator defined at this bar?

        The snapshot builder refuses to emit before this is true. A half-warmed
        indicator set produces readings the market never actually supported.
        """
        return all(not np.isnan(self.values(name)[index]) for name in _READY_SERIES)


def compute_all(
    frame: pd.DataFrame,
    *,
    atr_period: int = 14,
    rsi_period: int = 14,
    ema_fast: int = 21,
    ema_slow: int = 55,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    bb_period: int = 20,
    bb_std: float = 2.0,
    volume_ma: int = 20,
) -> IndicatorSet:
    """Compute the full set for one OHLCV frame."""
    close = frame["close"]
    return IndicatorSet(
        atr=atr(frame, atr_period),
        rsi=rsi(close, rsi_period),
        ema_fast=ema(close, ema_fast),
        ema_slow=ema(close, ema_slow),
        macd=macd(close, macd_fast, macd_slow, macd_signal),
        bollinger=bollinger(close, bb_period, bb_std),
        volume_ma=sma(frame["volume"], volume_ma),
    )
