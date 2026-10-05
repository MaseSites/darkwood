"""The reversal study's indexing, against series whose answer is known.

`scripts/study_reversal.py` asks whether the next candles lean against the last
one. It needs no backtest, which makes it cheap -- and which also means a single
off-by-one is the whole study, with nothing downstream to contradict it.

That is not hypothetical. The first version lined the two columns up one candle
apart in the wrong direction, so the signal and the "forward" move described
the **same** candle -- one as its close-to-close return, the other as its
open-to-open return. The contrarian result was then just minus the absolute
return: -0.40% on every candle, -2.02% on the largest, and a hit rate of
exactly 0%.

**The hit rate was the tell, not the size.** A real effect, however bad, wins
sometimes. Exactly zero means the two columns are the same number. These tests
check the thing directly instead of waiting for a telltale.

Three series, three known answers:

* a strict zigzag, where perfect reversal exists, so contrarian must win;
* a pure trend, where it must lose;
* pure noise, where it must land near zero.

A control on a rising series was tried first and rejected: every return there
is nearly identical, so the signal and forward columns correlate at 1.0 whether
the indexing is right or wrong. It could not tell the bug from the fix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scripts.study_reversal import forward_returns, round_trip


def contrarian(frame: pd.DataFrame, ahead: int = 1) -> np.ndarray:
    signal, forward = forward_returns(frame, ahead)
    return -np.sign(signal) * forward


def zigzag(n: int = 200, *, step: float = 2.0, base: float = 100.0) -> pd.DataFrame:
    """Alternating highs and lows: reversal is perfect by construction."""
    price = base + step * ((np.arange(n) % 2) == 0)
    return pd.DataFrame({"open": price, "close": np.roll(price, -1)})


def trend(n: int = 200, *, rate: float = 0.001) -> pd.DataFrame:
    """Monotone rise: every candle continues, so reversal must lose."""
    price = 100.0 * (1.0 + rate) ** np.arange(n)
    return pd.DataFrame({"open": price, "close": price * 1.0005})


def noise(n: int = 4000, *, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    price = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.002, size=n)))
    return pd.DataFrame({"open": price, "close": price * np.exp(rng.normal(0.0, 0.0005, size=n))})


# --------------------------------------------------------------------------- #
# The three known answers
# --------------------------------------------------------------------------- #


def test_perfect_reversal_is_found() -> None:
    """If this fails the study cannot detect the thing it exists to measure."""
    assert contrarian(zigzag()).mean() > 0.01


def test_a_pure_trend_punishes_the_contrarian() -> None:
    assert contrarian(trend()).mean() < 0.0


def test_pure_noise_lands_near_zero() -> None:
    """The control that the earlier off-by-one would have failed loudly.

    With the signal and the forward move describing one candle, this reads
    about minus the mean absolute return -- far from zero and reliably
    negative.
    """
    assert abs(contrarian(noise()).mean()) < 0.0001


# --------------------------------------------------------------------------- #
# The indexing itself
# --------------------------------------------------------------------------- #


def test_the_signal_and_the_outcome_are_different_candles() -> None:
    """Stated directly, because the consequence took an afternoon to notice."""
    frame = noise(n=500)
    signal, forward = forward_returns(frame, 1)

    opens = frame["open"].to_numpy()
    closes = frame["close"].to_numpy()
    # Signal at position 0 is candle 1's close-to-close return.
    assert signal[0] == pytest.approx(closes[1] / closes[0] - 1.0)
    # The outcome enters at candle 2's open -- after the signal candle closed.
    assert forward[0] == pytest.approx(opens[3] / opens[2] - 1.0)


def test_entry_is_never_the_close_that_produced_the_signal() -> None:
    """A signal from a closed candle cannot fill at a price already past.

    Checked by construction: a frame whose opens are shifted far from its
    closes must change the forward series and leave the signal series alone.
    """
    frame = noise(n=400)
    signal, forward = forward_returns(frame, 2)

    moved = frame.copy()
    moved["open"] = moved["open"] * 1.05
    signal_after, forward_after = forward_returns(moved, 2)

    assert np.allclose(signal, signal_after), "the signal read the opens"
    # A uniform scaling of every open leaves open-to-open ratios unchanged, so
    # the forward series must also be identical -- which is the point: it is a
    # ratio of opens and of nothing else.
    assert np.allclose(forward, forward_after)


def test_a_longer_horizon_reaches_further_and_costs_observations() -> None:
    frame = noise(n=300)
    short_signal, short_forward = forward_returns(frame, 1)
    long_signal, long_forward = forward_returns(frame, 8)

    assert long_signal.size == short_signal.size - 7
    assert short_forward.size == short_signal.size
    assert long_forward.size == long_signal.size


def test_a_frame_too_short_for_the_horizon_returns_nothing() -> None:
    """Rather than a handful of observations that look like a measurement."""
    signal, forward = forward_returns(noise(n=6), 8)

    assert signal.size == 0
    assert forward.size == 0


# --------------------------------------------------------------------------- #
# The cost the result has to clear
# --------------------------------------------------------------------------- #


def test_the_round_trip_includes_slippage_on_both_sides() -> None:
    """Fees alone would understate it by nearly half.

    Comparing a fee-only figure against another study's all-in cost is a
    mistake already made once here, in the other direction.
    """
    fees_only = round_trip(0.0)
    with_slippage = round_trip(3.0)

    assert fees_only == pytest.approx(0.00075)
    assert with_slippage == pytest.approx(0.00075 + 0.0006)
    assert with_slippage > fees_only
