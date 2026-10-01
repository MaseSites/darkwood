"""The indicator maths the registry promises, written out.

`analysis/indicators.py` holds the handful the setups themselves need -- ATR,
RSI, EMA, MACD, Bollinger. This holds the rest of the inventory: the twenty-odd
formulas that exist so the score has more than one kind of eye.

Three rules, the same ones the older module holds to:

* **Backward-looking by construction.** No `shift(-n)`, no `center=True`, no
  back-fill. Every one of those pulls a future value into the present and looks
  innocent in a diff.
* **Warm-up is NaN, never a guess.** A reading that does not exist yet must not
  arrive as a number, because the score cannot tell the difference afterwards.
* **Division that cannot be done produces NaN, not infinity.** An infinity
  propagates silently through a mean and poisons a whole family.

A note on what is *not* here. Several of these are recursive and need a Python
loop -- Parabolic SAR, KAMA, Fisher, Supertrend. That is the formula's shape and
not a shortcut; vectorising a path-dependent recursion means changing what it
computes. They are the reason the indicator bank is built lazily.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from traidingbrain.analysis.indicators import ema, rsi, sma, true_range, wilder_smooth

#: Milliseconds in a day, for the calendar groupings below.
_DAY_MS = 86_400_000

#: Epoch day index of the first Monday (1970-01-05). The epoch itself was a
#: Thursday, so week numbering has to be offset or weeks start on the wrong day.
_FIRST_MONDAY = 4

#: Parabolic SAR needs a previous bar to know which way it started.
_MIN_PSAR_BARS = 2


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide, turning an impossible division into NaN rather than infinity."""
    out = numerator / denominator.where(denominator != 0.0)
    return out.replace([np.inf, -np.inf], np.nan)


# --------------------------------------------------------------------------- #
# Momentum
# --------------------------------------------------------------------------- #


def stochastic_k(frame: pd.DataFrame, period: int = 14, smoothing: int = 3) -> pd.Series:
    """Where the close sits in the last `period` bars' range, 0 to 100.

    Smoothed by default, which makes this the "slow" stochastic that charting
    platforms draw. The unsmoothed form is the same number as Williams %R up to
    the sign, and registering both unsmoothed would have put one reading into
    the momentum family twice.
    """
    highest = frame["high"].rolling(period, min_periods=period).max()
    lowest = frame["low"].rolling(period, min_periods=period).min()
    raw = 100.0 * safe_ratio(frame["close"] - lowest, highest - lowest)
    return raw if smoothing <= 1 else sma(raw, smoothing)


def stochastic_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """A stochastic of the RSI: where RSI sits in its own recent range.

    A derivative of a derivative, which is its registered failure mode. Kept
    because it turns early inside a trend -- and because the family machinery
    makes it cost nothing to be wrong alongside RSI.
    """
    values = rsi(close, period)
    highest = values.rolling(period, min_periods=period).max()
    lowest = values.rolling(period, min_periods=period).min()
    return 100.0 * safe_ratio(values - lowest, highest - lowest)


def williams_r(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R, on its native -100..0 scale."""
    highest = frame["high"].rolling(period, min_periods=period).max()
    lowest = frame["low"].rolling(period, min_periods=period).min()
    return -100.0 * safe_ratio(highest - frame["close"], highest - lowest)


def commodity_channel_index(frame: pd.DataFrame, period: int = 20) -> pd.Series:
    """CCI with Lambert's 0.015 constant.

    The constant exists only to put the usual readings near ±100. It is not a
    property of the market, which is why the score normalises CCI against its
    own history rather than against ±100.
    """
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    average = typical.rolling(period, min_periods=period).mean()
    deviation = typical.rolling(period, min_periods=period).apply(
        lambda window: float(np.abs(window - window.mean()).mean()), raw=True
    )
    return safe_ratio(typical - average, 0.015 * deviation)


def chande_momentum(close: pd.Series, period: int = 14) -> pd.Series:
    """Chande momentum oscillator, -100 to 100.

    Sums of gains and losses over a plain window -- no smoothing, which is the
    one thing separating it from RSI. Treated as the same family regardless.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0).rolling(period, min_periods=period).sum()
    loss = (-delta).clip(lower=0.0).rolling(period, min_periods=period).sum()
    return 100.0 * safe_ratio(gain - loss, gain + loss)


def fisher_transform(frame: pd.DataFrame, period: int = 9) -> pd.Series:
    """Ehlers' Fisher transform of the median price.

    Recursive in two places -- the smoothed position and the transform itself --
    so it is a loop. The transform exaggerates extremes by construction, which
    is exactly what it is for and exactly its failure mode.
    """
    median = ((frame["high"] + frame["low"]) / 2.0).to_numpy(dtype="float64")
    highest = frame["high"].rolling(period, min_periods=period).max().to_numpy(dtype="float64")
    lowest = frame["low"].rolling(period, min_periods=period).min().to_numpy(dtype="float64")

    out = np.full(median.shape, np.nan, dtype="float64")
    position = 0.0
    smoothed = 0.0
    for i in range(median.size):
        span = highest[i] - lowest[i]
        if not np.isfinite(span) or span <= 0.0:
            continue
        raw = 2.0 * ((median[i] - lowest[i]) / span - 0.5)
        position = 0.33 * raw + 0.67 * position
        # The transform is undefined at ±1, and the recursion can walk there.
        position = float(np.clip(position, -0.999, 0.999))
        smoothed = 0.5 * float(np.log((1.0 + position) / (1.0 - position))) + 0.5 * smoothed
        out[i] = smoothed
    return pd.Series(out, index=frame.index)


def ultimate_oscillator(
    frame: pd.DataFrame, short: int = 7, medium: int = 14, long: int = 28
) -> pd.Series:
    """Williams' ultimate oscillator: three lookbacks, weighted 4:2:1.

    Blending three timescales removes the single-lookback argument that most
    oscillators lose -- and removes any way of saying which timescale is
    speaking, which is its failure mode.
    """
    prev_close = frame["close"].shift(1)
    low_or_close = pd.concat([frame["low"], prev_close], axis=1).min(axis=1)
    buying = frame["close"] - low_or_close
    ranges = true_range(frame)

    def average(period: int) -> pd.Series:
        return safe_ratio(
            buying.rolling(period, min_periods=period).sum(),
            ranges.rolling(period, min_periods=period).sum(),
        )

    return 100.0 * (4.0 * average(short) + 2.0 * average(medium) + average(long)) / 7.0


# --------------------------------------------------------------------------- #
# Trend
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DirectionalMovement:
    adx: pd.Series
    plus_di: pd.Series
    minus_di: pd.Series


def directional_movement(frame: pd.DataFrame, period: int = 14) -> DirectionalMovement:
    """Wilder's ADX and the two directional indicators it is built from.

    ADX measures how *strongly* a market is moving and says nothing about which
    way. That is why it is registered as non-directional: a high ADX read as
    bullish is the single most common misuse of this indicator.
    """
    up = frame["high"].diff()
    down = -frame["low"].diff()

    plus = up.where((up > down) & (up > 0.0), 0.0)
    minus = down.where((down > up) & (down > 0.0), 0.0)
    # The first bar has no previous bar, so it has no directional movement --
    # not zero movement, which is a different claim.
    plus.iloc[0] = np.nan
    minus.iloc[0] = np.nan

    smoothed_range = wilder_smooth(true_range(frame), period)
    plus_di = 100.0 * safe_ratio(wilder_smooth(plus, period), smoothed_range)
    minus_di = 100.0 * safe_ratio(wilder_smooth(minus, period), smoothed_range)
    dx = 100.0 * safe_ratio((plus_di - minus_di).abs(), plus_di + minus_di)
    return DirectionalMovement(adx=wilder_smooth(dx, period), plus_di=plus_di, minus_di=minus_di)


def supertrend(
    frame: pd.DataFrame, atr_values: pd.Series, period: int = 10, multiplier: float = 3.0
) -> pd.Series:
    """The Supertrend line itself, not the flag.

    Deliberately the line: the flag is +1 or -1, and a binary series normalised
    against its own history reads as neutral for as long as the trend lasts --
    which is precisely when it has the most to say. The distance from price to
    the line keeps the information the flag throws away.
    """
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    band = atr_values.to_numpy(dtype="float64") * multiplier
    middle = (highs + lows) / 2.0

    line = np.full(closes.shape, np.nan, dtype="float64")
    upper = np.nan
    lower = np.nan
    rising = True
    for i in range(period, closes.size):
        if not np.isfinite(band[i]):
            continue
        upper_basic = middle[i] + band[i]
        lower_basic = middle[i] - band[i]
        upper = (
            min(upper_basic, upper)
            if np.isfinite(upper) and closes[i - 1] <= upper
            else upper_basic
        )
        lower = (
            max(lower_basic, lower)
            if np.isfinite(lower) and closes[i - 1] >= lower
            else lower_basic
        )
        if rising and closes[i] < lower:
            rising = False
        elif not rising and closes[i] > upper:
            rising = True
        line[i] = lower if rising else upper
    return pd.Series(line, index=frame.index)


def parabolic_sar(
    frame: pd.DataFrame, step: float = 0.02, maximum: float = 0.2
) -> pd.Series:
    """Wilder's parabolic stop and reverse.

    Path-dependent by definition: today's stop is yesterday's stop plus an
    acceleration that itself depends on every extreme since the last reversal.
    A loop is the formula, not an implementation shortcut.
    """
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    out = np.full(highs.shape, np.nan, dtype="float64")
    if highs.size < _MIN_PSAR_BARS:
        return pd.Series(out, index=frame.index)

    rising = highs[1] >= highs[0]
    stop = lows[0] if rising else highs[0]
    extreme = highs[1] if rising else lows[1]
    acceleration = step

    for i in range(1, highs.size):
        stop = stop + acceleration * (extreme - stop)
        if rising:
            # The stop may never move into the last two bars' range.
            stop = min(stop, lows[i - 1], lows[max(0, i - 2)])
            if lows[i] < stop:
                rising = False
                stop = extreme
                extreme = lows[i]
                acceleration = step
            elif highs[i] > extreme:
                extreme = highs[i]
                acceleration = min(acceleration + step, maximum)
        else:
            stop = max(stop, highs[i - 1], highs[max(0, i - 2)])
            if highs[i] > stop:
                rising = True
                stop = extreme
                extreme = highs[i]
                acceleration = step
            elif lows[i] < extreme:
                extreme = lows[i]
                acceleration = min(acceleration + step, maximum)
        out[i] = stop
    return pd.Series(out, index=frame.index)


def aroon_oscillator(frame: pd.DataFrame, period: int = 25) -> pd.Series:
    """Aroon up minus Aroon down, -100 to 100.

    Measures how recently the extremes happened, not how large the move was --
    a market can post a fresh high by a tick and read +100.
    """

    def bars_since_max(window: np.ndarray) -> float:
        return float(len(window) - 1 - int(np.argmax(window)))

    def bars_since_min(window: np.ndarray) -> float:
        return float(len(window) - 1 - int(np.argmin(window)))

    span = period + 1
    since_high = frame["high"].rolling(span, min_periods=span).apply(bars_since_max, raw=True)
    since_low = frame["low"].rolling(span, min_periods=span).apply(bars_since_min, raw=True)
    return 100.0 * (since_low - since_high) / period


def vortex(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """VI+ minus VI-: which direction is winning the bar-to-bar swing."""
    prev_close = frame["close"].shift(1)
    plus = (frame["high"] - frame["low"].shift(1)).abs()
    minus = (frame["low"] - frame["high"].shift(1)).abs()
    ranges = true_range(frame).rolling(period, min_periods=period).sum()
    del prev_close
    return safe_ratio(
        plus.rolling(period, min_periods=period).sum()
        - minus.rolling(period, min_periods=period).sum(),
        ranges,
    )


def trix(close: pd.Series, period: int = 15) -> pd.Series:
    """Rate of change of a triple-smoothed EMA, in percent.

    Three smoothings make it very late, which is the trade it offers: almost no
    false flips, and no chance of being early.
    """
    smoothed = ema(ema(ema(close, period), period), period)
    return 100.0 * smoothed.pct_change()


def percentage_price_oscillator(
    close: pd.Series, fast: int = 12, slow: int = 26
) -> pd.Series:
    """MACD expressed as a percentage of the slow average.

    The same information as MACD, scaled -- registered with that failure mode
    and sharing MACD's family so the two cannot vote twice.
    """
    fast_line = ema(close, fast)
    slow_line = ema(close, slow)
    return 100.0 * safe_ratio(fast_line - slow_line, slow_line)


def hull_moving_average(close: pd.Series, period: int = 21) -> pd.Series:
    """Hull's average: weighted averages arranged to cancel most of the lag.

    Less lag is not more information -- chapter 12.7 is blunt that new
    smoothing is not a new source -- but less lag does change *when* the same
    information arrives, and that is worth one entry.
    """

    def weighted(series: pd.Series, window: int) -> pd.Series:
        weights = np.arange(1, window + 1, dtype="float64")
        return series.rolling(window, min_periods=window).apply(
            lambda values: float(np.dot(values, weights) / weights.sum()), raw=True
        )

    half = max(1, period // 2)
    root = max(1, int(np.sqrt(period)))
    raw = 2.0 * weighted(close, half) - weighted(close, period)
    return weighted(raw, root)


def kaufman_adaptive(
    close: pd.Series, period: int = 20, fast: int = 2, slow: int = 30
) -> pd.Series:
    """Kaufman's adaptive moving average.

    Smooths hard when price is noisy and barely at all when it is directional,
    which means its lag is a function of the market. The `lag_bars` field in its
    registration is therefore an estimate and says so.
    """
    values = close.to_numpy(dtype="float64")
    out = np.full(values.shape, np.nan, dtype="float64")
    if values.size <= period:
        return pd.Series(out, index=close.index)

    change = np.abs(values[period:] - values[:-period])
    volatility = (
        pd.Series(np.abs(np.diff(values, prepend=np.nan)))
        .rolling(period, min_periods=period)
        .sum()
        .to_numpy(dtype="float64")[period:]
    )
    fast_alpha = 2.0 / (fast + 1.0)
    slow_alpha = 2.0 / (slow + 1.0)

    current = values[period - 1]
    for offset, i in enumerate(range(period, values.size)):
        spread = volatility[offset]
        efficiency = 0.0 if not np.isfinite(spread) or spread == 0.0 else change[offset] / spread
        alpha = (efficiency * (fast_alpha - slow_alpha) + slow_alpha) ** 2
        current = current + alpha * (values[i] - current)
        out[i] = current
    return pd.Series(out, index=close.index)


# --------------------------------------------------------------------------- #
# Volatility and location
# --------------------------------------------------------------------------- #


def keltner_position(
    frame: pd.DataFrame, atr_values: pd.Series, period: int = 20, multiplier: float = 2.0
) -> pd.Series:
    """Where price sits between the Keltner mid-line and its band, -1 to 1."""
    middle = ema(frame["close"], period)
    return safe_ratio(frame["close"] - middle, multiplier * atr_values)


def donchian_position(frame: pd.DataFrame, period: int = 20) -> pd.Series:
    """Where price sits in the last `period` bars' channel, -1 at the low."""
    highest = frame["high"].rolling(period, min_periods=period).max()
    lowest = frame["low"].rolling(period, min_periods=period).min()
    return 2.0 * safe_ratio(frame["close"] - lowest, highest - lowest) - 1.0


def historical_volatility(close: pd.Series, period: int = 30) -> pd.Series:
    """Standard deviation of log returns over the window.

    Past dispersion. It does not price the gap that has not happened yet, which
    is the only kind that matters for a stop.
    """
    logs = pd.Series(np.log(close.to_numpy(dtype="float64")), index=close.index)
    return logs.diff().rolling(period, min_periods=period).std(ddof=0)


def choppiness(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """How much of the range was spent going nowhere, 0 to 100.

    High means the bar-by-bar travel greatly exceeds the net move -- a range.
    It describes trendiness and never which way, so it is non-directional.
    """
    ranges = true_range(frame).rolling(period, min_periods=period).sum()
    highest = frame["high"].rolling(period, min_periods=period).max()
    lowest = frame["low"].rolling(period, min_periods=period).min()
    ratio = safe_ratio(ranges, highest - lowest).where(lambda value: value > 0.0)
    logs = pd.Series(np.log10(ratio.to_numpy(dtype="float64")), index=ratio.index)
    return 100.0 * logs / float(np.log10(period))


# --------------------------------------------------------------------------- #
# Volume
# --------------------------------------------------------------------------- #


def on_balance_volume(frame: pd.DataFrame) -> pd.Series:
    """Running total of volume, signed by the bar's direction.

    Assigns a whole bar's volume to one side, which is a crude claim about a
    bar that traded both ways. The score reads its change, never its level: a
    cumulative total's absolute value depends on where the file starts.
    """
    direction = pd.Series(
        np.sign(frame["close"].diff().to_numpy(dtype="float64")), index=frame.index
    )
    return (direction * frame["volume"]).fillna(0.0).cumsum()


def accumulation_distribution(frame: pd.DataFrame) -> pd.Series:
    """Running total of volume weighted by where in the bar the close landed."""
    span = frame["high"] - frame["low"]
    multiplier = safe_ratio(
        (frame["close"] - frame["low"]) - (frame["high"] - frame["close"]), span
    )
    return (multiplier.fillna(0.0) * frame["volume"]).cumsum()


def chaikin_money_flow(frame: pd.DataFrame, period: int = 20) -> pd.Series:
    """Accumulation/distribution over a window, as a share of volume. -1 to 1.

    Close position inside the bar is a proxy for pressure, not order flow. The
    knowledge base is explicit that no chart series identifies who traded.
    """
    span = frame["high"] - frame["low"]
    multiplier = safe_ratio(
        (frame["close"] - frame["low"]) - (frame["high"] - frame["close"]), span
    )
    flow = (multiplier * frame["volume"]).rolling(period, min_periods=period).sum()
    return safe_ratio(flow, frame["volume"].rolling(period, min_periods=period).sum())


def accumulation_divergence(frame: pd.DataFrame, period: int = 50) -> pd.Series:
    """Where the A/D line sits in its own range, against where price sits. -1..1.

    Positive means accumulation is holding up better than price -- the classic
    bullish divergence. Written this way because the A/D line summed over a
    window is *literally* Chaikin money flow, so reading the sum would register
    one number under two names in the same family.

    A divergence is a disagreement, not a timing signal. It can persist for a
    very long time without resolving, which is its registered failure mode.
    """
    line = accumulation_distribution(frame)
    return _range_position(line, period) - _range_position(frame["close"], period)


def _range_position(series: pd.Series, period: int) -> pd.Series:
    """Where a series sits in its own trailing range, -1 at the bottom."""
    highest = series.rolling(period, min_periods=period).max()
    lowest = series.rolling(period, min_periods=period).min()
    return 2.0 * safe_ratio(series - lowest, highest - lowest) - 1.0


def close_range_position(close: pd.Series, period: int = 20) -> pd.Series:
    """Where the close sits in the range of the last `period` closes.

    The range through the closes rather than through the wicks. Every rejected
    spike is excluded, so this says where value settled rather than how far
    price was briefly pushed.
    """
    return _range_position(close, period)


def money_flow_index(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI of money flow: typical price times volume, split by direction."""
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    raw = typical * frame["volume"]
    rising = typical.diff() > 0.0
    falling = typical.diff() < 0.0
    positive = raw.where(rising, 0.0).rolling(period, min_periods=period).sum()
    negative = raw.where(falling, 0.0).rolling(period, min_periods=period).sum()
    return 100.0 * safe_ratio(positive, positive + negative)


def force_index(frame: pd.DataFrame, period: int = 13) -> pd.Series:
    """Price change times volume, smoothed. Dominated by gaps, as registered."""
    return ema(frame["close"].diff() * frame["volume"], period)


def session_vwap(frame: pd.DataFrame) -> pd.Series:
    """Volume-weighted average price, re-anchored each UTC day.

    The anchor is a choice, and a different one gives a different number -- the
    registered failure mode. UTC midnight is used because it is the only session
    boundary a 24-hour crypto market actually has.
    """
    day = frame["ts"].to_numpy(dtype="int64") // _DAY_MS
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    grouped = pd.Series(day, index=frame.index)
    turnover = (typical * frame["volume"]).groupby(grouped).cumsum()
    traded = frame["volume"].groupby(grouped).cumsum()
    return safe_ratio(turnover, traded)


# --------------------------------------------------------------------------- #
# Calendar levels
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PeriodLevels:
    """The previous calendar period's extremes, aligned to every bar."""

    high: pd.Series
    low: pd.Series
    close: pd.Series


def previous_period_levels(frame: pd.DataFrame, *, weekly: bool = False) -> PeriodLevels:
    """Yesterday's -- or last week's -- high, low and close, on every bar.

    The previous period is used rather than the current one, and that is the
    whole no-lookahead argument: the current day's high is still being written
    by the bar asking the question.
    """
    day = frame["ts"].to_numpy(dtype="int64") // _DAY_MS
    key = pd.Series((day - _FIRST_MONDAY) // 7 if weekly else day, index=frame.index)

    def previous(series: pd.Series, how: str) -> pd.Series:
        aggregated = getattr(series.groupby(key), how)()
        return key.map(aggregated.shift(1))

    return PeriodLevels(
        high=previous(frame["high"], "max"),
        low=previous(frame["low"], "min"),
        close=previous(frame["close"], "last"),
    )


def classic_pivot(frame: pd.DataFrame) -> pd.Series:
    """The floor-trader pivot from the previous day: (H + L + C) / 3.

    One formula among many -- Camarilla, Woodie and Fibonacci pivots all put
    the line somewhere else. No level here is guaranteed to matter; what it
    offers is a line a great many people are looking at.
    """
    levels = previous_period_levels(frame)
    return (levels.high + levels.low + levels.close) / 3.0


__all__ = [
    "DirectionalMovement",
    "PeriodLevels",
    "accumulation_distribution",
    "accumulation_divergence",
    "aroon_oscillator",
    "chaikin_money_flow",
    "chande_momentum",
    "choppiness",
    "classic_pivot",
    "close_range_position",
    "commodity_channel_index",
    "directional_movement",
    "donchian_position",
    "ema",
    "fisher_transform",
    "force_index",
    "historical_volatility",
    "hull_moving_average",
    "kaufman_adaptive",
    "keltner_position",
    "money_flow_index",
    "on_balance_volume",
    "parabolic_sar",
    "percentage_price_oscillator",
    "previous_period_levels",
    "safe_ratio",
    "session_vwap",
    "sma",
    "stochastic_k",
    "stochastic_rsi",
    "supertrend",
    "trix",
    "ultimate_oscillator",
    "vortex",
    "williams_r",
]
