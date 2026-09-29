"""Indicators, checked against independent implementations and against arithmetic.

Two kinds of test here, and they catch different mistakes.

The *oracle* tests re-implement each indicator as a plain Python loop and demand
agreement to 1e-9. Those catch vectorisation errors -- an off-by-one in a shift, a
window that is one bar too long.

The *definition* tests use tiny hand-computed series. Those catch the more
dangerous error, where the vectorised code faithfully computes the wrong thing.
Wilder's smoothing is the example: seeding the recursion at the first observation
instead of the average of the first n is a one-character difference that produces
a plausible line which does not match any chart the user will ever look at.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tests.fakes import EPOCH, bars_from_rows, synthetic_rows
from traidingbrain.analysis.indicators import (
    atr,
    bollinger,
    compute_all,
    ema,
    macd,
    rolling_percentile_rank,
    rsi,
    slope,
    sma,
    true_range,
    wilder_smooth,
)
from traidingbrain.data.frames import bars_to_frame
from traidingbrain.domain.enums import Timeframe

TOLERANCE = 1e-9


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return bars_to_frame(bars_from_rows(synthetic_rows(EPOCH, Timeframe.H1, 400)))


# --------------------------------------------------------------------------- #
# Naive reference implementations
# --------------------------------------------------------------------------- #


def naive_ema(values: list[float], span: int) -> list[float]:
    alpha = 2.0 / (span + 1.0)
    out: list[float] = [math.nan] * len(values)
    if len(values) < span:
        return out
    current = values[0]
    for i in range(1, len(values)):
        current = alpha * values[i] + (1 - alpha) * current
        if i >= span - 1:
            out[i] = current
    out[span - 1] = _replay_ema(values, span, alpha)
    return out


def _replay_ema(values: list[float], span: int, alpha: float) -> float:
    current = values[0]
    for i in range(1, span):
        current = alpha * values[i] + (1 - alpha) * current
    return current


def naive_wilder(values: list[float], period: int) -> list[float]:
    out: list[float] = [math.nan] * len(values)
    start = next((i for i, v in enumerate(values) if not math.isnan(v)), None)
    if start is None or start + period > len(values):
        return out
    seed_end = start + period
    out[seed_end - 1] = sum(values[start:seed_end]) / period
    for i in range(seed_end, len(values)):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def naive_true_range(frame: pd.DataFrame) -> list[float]:
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    closes = frame["close"].tolist()
    out = [math.nan]
    for i in range(1, len(highs)):
        out.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    return out


def naive_rsi(values: list[float], period: int) -> list[float]:
    gains = [math.nan] + [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [math.nan] + [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]
    avg_gain = naive_wilder(gains, period)
    avg_loss = naive_wilder(losses, period)
    out: list[float] = []
    for gain, loss in zip(avg_gain, avg_loss, strict=True):
        if math.isnan(gain) or math.isnan(loss):
            out.append(math.nan)
        elif loss == 0.0 and gain == 0.0:
            out.append(50.0)
        elif loss == 0.0:
            out.append(100.0)
        else:
            out.append(100.0 - 100.0 / (1.0 + gain / loss))
    return out


def assert_close(actual: pd.Series, expected: list[float], label: str) -> None:
    got = actual.to_numpy(dtype="float64")
    want = np.array(expected, dtype="float64")
    assert got.shape == want.shape, f"{label}: length mismatch"
    both_nan = np.isnan(got) & np.isnan(want)
    assert (np.isnan(got) == np.isnan(want)).all(), f"{label}: NaN positions differ"
    diff = np.abs(np.where(both_nan, 0.0, got - want))
    worst = float(np.nanmax(diff)) if diff.size else 0.0
    assert worst <= TOLERANCE, f"{label}: largest difference {worst:.3e} exceeds {TOLERANCE:.0e}"


# --------------------------------------------------------------------------- #
# Oracle agreement
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("span", [5, 21, 55])
def test_ema_matches_a_naive_loop(frame: pd.DataFrame, span: int) -> None:
    assert_close(ema(frame["close"], span), naive_ema(frame["close"].tolist(), span), "EMA")


@pytest.mark.parametrize("period", [7, 14, 21])
def test_wilder_matches_a_naive_loop(frame: pd.DataFrame, period: int) -> None:
    assert_close(
        wilder_smooth(frame["close"], period),
        naive_wilder(frame["close"].tolist(), period),
        "Wilder",
    )


def test_true_range_matches_a_naive_loop(frame: pd.DataFrame) -> None:
    assert_close(true_range(frame), naive_true_range(frame), "TR")


@pytest.mark.parametrize("period", [7, 14])
def test_atr_matches_a_naive_loop(frame: pd.DataFrame, period: int) -> None:
    assert_close(atr(frame, period), naive_wilder(naive_true_range(frame), period), "ATR")


@pytest.mark.parametrize("period", [7, 14, 21])
def test_rsi_matches_a_naive_loop(frame: pd.DataFrame, period: int) -> None:
    assert_close(rsi(frame["close"], period), naive_rsi(frame["close"].tolist(), period), "RSI")


def test_sma_matches_a_naive_loop(frame: pd.DataFrame) -> None:
    values = frame["close"].tolist()
    period = 20
    expected = [math.nan] * (period - 1) + [
        sum(values[i - period + 1 : i + 1]) / period for i in range(period - 1, len(values))
    ]
    assert_close(sma(frame["close"], period), expected, "SMA")


# --------------------------------------------------------------------------- #
# Definitions, pinned by hand
# --------------------------------------------------------------------------- #


def test_wilder_seeds_with_the_simple_average_not_the_first_value() -> None:
    """The seed is the whole difference between RMA and a careless EMA.

    With period 3 over [1, 2, 3, 4], Wilder's first output is the mean of the first
    three, 2.0, and the next is (2*2 + 4)/3 = 2.666... A recursion started at the
    first observation gives 2.37 and 3.19 instead -- close enough to look right on
    a chart and wrong enough to move a signal.
    """
    result = wilder_smooth(pd.Series([1.0, 2.0, 3.0, 4.0]), 3)

    assert math.isnan(result.iloc[0])
    assert math.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx((2.0 * 2 + 4.0) / 3)


def test_rsi_is_one_hundred_when_nothing_has_fallen() -> None:
    """A pure uptrend has no average loss, so the ratio is infinite.

    The conventional reading is 100. Letting an inf through would poison every
    downstream calculation with a NaN that is hard to trace back here.
    """
    rising = pd.Series([float(i) for i in range(1, 40)])
    result = rsi(rising, 14)
    assert result.iloc[-1] == pytest.approx(100.0)
    assert np.isfinite(result.iloc[14:]).all()


def test_rsi_is_fifty_on_a_flat_market() -> None:
    result = rsi(pd.Series([100.0] * 40), 14)
    assert result.iloc[-1] == pytest.approx(50.0)


def test_true_range_has_no_value_on_the_first_bar() -> None:
    """There is no previous close to gap from, so the first true range is unknown.

    Returning high minus low there would understate it and quietly bias the very
    first ATR reading.
    """
    frame = bars_to_frame(bars_from_rows(synthetic_rows(EPOCH, Timeframe.H1, 5)))
    assert math.isnan(true_range(frame).iloc[0])


def test_bollinger_uses_the_population_deviation(frame: pd.DataFrame) -> None:
    band = bollinger(frame["close"], 20, 2.0)
    window = frame["close"].iloc[-20:]
    expected = window.mean() + 2.0 * window.std(ddof=0)
    assert band.upper.iloc[-1] == pytest.approx(expected, abs=TOLERANCE)


def test_percent_b_places_price_within_the_band(frame: pd.DataFrame) -> None:
    band = bollinger(frame["close"], 20, 2.0)
    percent = band.percent_b(frame["close"])
    at_upper = band.percent_b(band.upper)
    at_lower = band.percent_b(band.lower)
    assert at_upper.iloc[-1] == pytest.approx(1.0)
    assert at_lower.iloc[-1] == pytest.approx(0.0)
    assert not math.isnan(percent.iloc[-1])


def test_macd_histogram_is_the_line_minus_its_signal(frame: pd.DataFrame) -> None:
    result = macd(frame["close"], 12, 26, 9)
    reconstructed = result.line - result.signal
    assert_close(result.histogram, reconstructed.tolist(), "MACD histogram")


def test_macd_rejects_a_fast_period_that_is_not_faster() -> None:
    with pytest.raises(ValueError, match="must be shorter"):
        macd(pd.Series([1.0, 2.0, 3.0]), fast=26, slow=12)


# --------------------------------------------------------------------------- #
# No lookahead
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "compute"),
    [
        ("EMA", lambda f: ema(f["close"], 21)),
        ("RSI", lambda f: rsi(f["close"], 14)),
        ("ATR", lambda f: atr(f, 14)),
        ("SMA", lambda f: sma(f["close"], 20)),
        ("MACD", lambda f: macd(f["close"]).histogram),
        ("BB", lambda f: bollinger(f["close"]).upper),
        ("VOL_PCT", lambda f: rolling_percentile_rank(f["close"], 50)),
        ("SLOPE", lambda f: slope(f["close"], 30)),
    ],
)
def test_no_indicator_reads_the_future(frame: pd.DataFrame, name: str, compute) -> None:
    """Truncating the data must not change any value that was already computed.

    This is the property that matters. An indicator that silently uses one future
    bar looks perfectly reasonable in isolation and makes every backtest built on
    it meaningless.
    """
    cut = 300
    full = compute(frame).to_numpy(dtype="float64")[:cut]
    truncated = compute(frame.iloc[:cut].copy()).to_numpy(dtype="float64")

    assert (np.isnan(full) == np.isnan(truncated)).all(), f"{name}: NaN pattern changed"
    difference = np.abs(np.where(np.isnan(full), 0.0, full - truncated))
    assert float(np.max(difference)) <= TOLERANCE, f"{name} changed when the future was removed"


def test_rolling_percentile_is_rolling_not_global() -> None:
    """A global percentile tells every bar how it compares to years it has not seen.

    A series that is calm and then explodes must not have its early bars ranked as
    low-volatility because of what came later.
    """
    calm = [1.0] * 100
    wild = [float(50 + i) for i in range(100)]
    series = pd.Series(calm + wild)

    ranks = rolling_percentile_rank(series, 50)

    assert ranks.iloc[80] == pytest.approx(1.0), (
        "inside the calm stretch the current value should rank at the top of what "
        "has been seen so far, not at the bottom of the whole file"
    )


def test_indicator_set_reports_when_it_is_ready(frame: pd.DataFrame) -> None:
    indicators = compute_all(frame)
    warmup = indicators.warmup_bars()

    assert warmup > 0
    assert not indicators.is_ready(0)
    assert indicators.is_ready(len(frame) - 1)
    assert indicators.is_ready(warmup)
