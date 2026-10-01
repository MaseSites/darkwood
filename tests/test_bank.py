"""The indicator bank: forty-two calculations, and the traps they walk into.

Three of these tests exist because they caught something while this was being
written, and that is the only reason any of them is worth keeping:

* **Nothing may read past its bar.** Mutating every bar after *i* must leave
  the reading at *i* untouched, for every indicator, including the four that
  recurse bar by bar. Without this the whole inventory is decoration: a leak
  here makes a backtest look brilliant and shows up nowhere in the output.
* **No two indicators may produce the same series.** Three pairs did. Williams
  %R shifted by 100 *is* the raw stochastic; the accumulation/distribution line
  summed over a window *is* Chaikin money flow; a channel position is a channel
  position whichever family it is filed under. Each pair would have reported
  one measurement as two pieces of evidence.
* **Every registration needs a calculation.** A spec with no function is a
  silent hole -- `read_all` skips what it cannot find, so the score would just
  be quieter than it says it is.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.bank import CUMULATIVE_WINDOW, compute_bank
from traidingbrain.analysis.indicators import atr
from traidingbrain.domain.enums import Bias, Timeframe
from traidingbrain.score.engine import compute
from traidingbrain.score.findings import Evidence, Family
from traidingbrain.score.registry import (
    SPECS,
    Unit,
    context_at,
    normalise,
    read_all,
)

BARS = 900


def make_frame(seed: int = 11, bars: int = BARS) -> pd.DataFrame:
    """A plausible OHLCV series: a random walk with wicks and lognormal volume."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.004, bars)))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.003, bars)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.003, bars)))
    return pd.DataFrame(
        {
            "ts": np.arange(bars, dtype="int64") * 3_600_000,
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.lognormal(3.0, 0.5, bars),
        }
    )


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return make_frame()


@pytest.fixture(scope="module")
def bank(frame: pd.DataFrame) -> dict[str, pd.Series]:
    return compute_bank(frame, atr(frame, 14))


def finite(series: pd.Series) -> np.ndarray:
    values = series.to_numpy(dtype="float64")
    return values[np.isfinite(values)]


# --------------------------------------------------------------------------- #
# The inventory is complete, and every entry is its own
# --------------------------------------------------------------------------- #


def test_every_registered_indicator_has_a_calculation(bank: dict[str, pd.Series]) -> None:
    """The hole that would be invisible at runtime.

    `read_all` skips an indicator it cannot find, so a registration with no
    function makes the score quieter than it claims to be and says nothing
    about it. This test is the only place that is loud.
    """
    assert set(SPECS) - set(bank) == set()


def test_every_calculation_has_a_registration(bank: dict[str, pd.Series]) -> None:
    """The other direction: a number with no family, no lag, no failure mode."""
    assert set(bank) - set(SPECS) == set()


def test_no_two_indicators_produce_the_same_series(bank: dict[str, pd.Series]) -> None:
    """Found three pairs the first time it ran, and each one was real.

    Williams %R plus 100 is the raw stochastic, exactly. The A/D line summed
    over a window is Chaikin money flow, exactly. A twenty-bar channel position
    is the same number in the volatility family and in the location family.
    Each pair would have counted one measurement twice -- and two of them
    across a family boundary, where the median cannot catch it.
    """
    seen: dict[bytes, str] = {}
    for name, series in sorted(bank.items()):
        values = series.to_numpy(dtype="float64")
        fingerprint = np.round(values[np.isfinite(values)], 9).tobytes()
        twin = seen.get(fingerprint)
        assert twin is None, f"{name} and {twin} compute the same number"
        seen[fingerprint] = name


def test_every_indicator_produces_some_finite_readings(bank: dict[str, pd.Series]) -> None:
    """A series that is all NaN is a calculation that silently never runs."""
    for name, series in bank.items():
        assert len(finite(series)) > BARS // 4, f"{name} is mostly undefined"


def test_nothing_in_the_bank_is_infinite(bank: dict[str, pd.Series]) -> None:
    """An infinity survives a mean and poisons a whole family's verdict.

    Every one of these divides by something that can be zero -- a flat range, a
    bar with no volume, an ATR during warm-up. NaN is the honest answer there
    and it is what the score already knows how to skip.
    """
    for name, series in bank.items():
        assert not np.isinf(series.to_numpy(dtype="float64")).any(), name


# --------------------------------------------------------------------------- #
# The guarantee the whole engine rests on
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cut", [300, 500, 700])
def test_no_indicator_reads_past_its_bar(cut: int) -> None:
    """Mutate every bar after `cut`; nothing at or before `cut` may move.

    Applied to all forty-two at once rather than to a chosen few, because the
    ones most likely to leak are the ones nobody suspects -- a groupby that
    aggregates the current calendar day, a rolling window with the wrong sign,
    a cumulative total read as a level. The four recursive indicators are the
    other half of the risk: a loop written backwards looks identical in a diff.
    """
    original = make_frame()
    before = compute_bank(original, atr(original, 14))

    rng = np.random.default_rng(99)
    mutated = original.copy()
    tail = slice(cut + 1, None)
    shock = 1.0 + rng.normal(0.0, 0.2, len(original) - cut - 1)
    for column in ("open", "high", "low", "close"):
        mutated.loc[mutated.index[tail], column] = (
            original[column].to_numpy(dtype="float64")[tail] * shock
        )
    mutated.loc[mutated.index[tail], "volume"] = rng.lognormal(5.0, 1.0, len(original) - cut - 1)
    after = compute_bank(mutated, atr(mutated, 14))

    for name in sorted(SPECS):
        head_before = before[name].to_numpy(dtype="float64")[: cut + 1]
        head_after = after[name].to_numpy(dtype="float64")[: cut + 1]
        np.testing.assert_allclose(
            head_before, head_after, rtol=1e-12, atol=1e-12, err_msg=f"{name} reads ahead"
        )


# --------------------------------------------------------------------------- #
# Each reading arrives in the unit it promised
# --------------------------------------------------------------------------- #


def test_bounded_readings_stay_inside_their_declared_bounds(
    bank: dict[str, pd.Series],
) -> None:
    """`normalise` maps by unit, so a unit that lies produces a silent mis-scale.

    Williams %R is the case: native to -100..0, registered as 0..100, and the
    bank shifts it. Had the shift been forgotten, every reading would have come
    out maximally bearish and nothing would have complained.
    """
    for name, spec in SPECS.items():
        values = finite(bank[name])
        if spec.output_unit is Unit.BOUNDED_100:
            assert values.min() >= -1e-9, name
            assert values.max() <= 100.0 + 1e-9, name
        elif spec.output_unit is Unit.BOUNDED_PM100:
            assert np.abs(values).max() <= 100.0 + 1e-9, name


def test_a_full_scale_is_only_set_where_it_means_something() -> None:
    """It is read solely for ATR-unit readings; anywhere else it would be a
    number somebody set and nothing used."""
    for spec in SPECS.values():
        if spec.full_scale is not None:
            assert spec.output_unit is Unit.ATR_UNITS, spec.name
            assert spec.full_scale > 0.0, spec.name


def test_the_long_averages_are_not_permanently_at_full_strength(
    bank: dict[str, pd.Series], frame: pd.DataFrame
) -> None:
    """Why `full_scale` is per indicator rather than one constant.

    Price sits within about an ATR of a 21-period average and routinely six
    from a 200-period one. On a shared scale the long averages would be pinned
    at the maximum through any trend -- the gradation discarded exactly where
    there is most of it to measure.
    """
    saturated = [
        float(np.mean(np.abs([normalise(SPECS[name], bank[name], i) for i in range(400, 900)])))
        for name in ("ema_21", "sma_200")
    ]

    assert max(saturated) < 0.95, "a moving average is reporting full strength almost always"


def test_a_normalised_reading_is_not_rescaled_against_its_history(
    bank: dict[str, pd.Series],
) -> None:
    """A close at the top of its channel is at the top of its channel.

    Scaling that against how often it has been there lately would destroy the
    thing it measures, which is why positions get their own unit instead of
    falling through to the rolling z-score.
    """
    index = BARS - 1
    raw = float(bank["donchian_pos_20"].to_numpy(dtype="float64")[index])

    assert normalise(SPECS["donchian_pos_20"], bank["donchian_pos_20"], index) == pytest.approx(
        float(np.clip(raw, -1.0, 1.0))
    )


# --------------------------------------------------------------------------- #
# What reaches the score, and what deliberately does not
# --------------------------------------------------------------------------- #


def test_a_reading_with_no_side_does_not_get_a_vote(bank: dict[str, pd.Series]) -> None:
    """ADX, ATR, band width, historical volatility, choppiness, relative volume.

    Every one of their registered failure modes says it in words -- "high ADX
    read as bullish", "volume is participation, never direction". Letting them
    in as neutral votes would be worse than dropping them: a family is
    reconciled by the median of its members, so four non-directional readings
    beside three directional ones pull the family to nothing.
    """
    findings = {finding.key for finding in read_all(bank, BARS - 1, Timeframe.H1)}

    for name, spec in SPECS.items():
        if not spec.directional:
            assert f"{name}_h1" not in findings, name


def test_a_reading_with_no_side_is_still_kept(bank: dict[str, pd.Series]) -> None:
    """Dropped from the evidence, not from the screen. How violent and how
    choppy change what a side is worth, and the person reading needs them."""
    context = context_at(bank, BARS - 1)

    assert {"adx_14", "atr_14", "choppiness_14", "rvol_20"} <= set(context)
    assert all(np.isfinite(value) for value in context.values())


def test_forty_two_indicators_on_five_timeframes_still_speak_once_per_family(
    bank: dict[str, pd.Series],
) -> None:
    """The property the whole inventory rests on, at full size.

    Five timeframes times forty-two readings is two hundred numbers. If the
    score counted entries it would be pinned at an extreme on every bar of
    every market. It is bounded by how many kinds of information exist.
    """
    evidence = Evidence()
    for timeframe in (Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1, Timeframe.W1):
        for finding in read_all(bank, BARS - 1, timeframe):
            evidence.add(finding)

    score = compute(evidence)

    assert len(evidence.findings) > 100
    assert len(score.families) <= len(Family)
    assert score.breadth <= len(Family)


def test_a_declared_dependency_points_at_a_real_indicator() -> None:
    """A dependence on a name nobody registered is ignored at runtime, which
    means a typo quietly restores the full weight it was meant to remove."""
    for spec in SPECS.values():
        for name in spec.depends_on:
            assert name in SPECS, f"{spec.name} depends on unknown {name}"


def test_a_dependent_reading_counts_for_less(bank: dict[str, pd.Series]) -> None:
    """Williams %R declares its dependence on the stochastic, and the
    independence weighting has to actually act on it -- otherwise the field is
    a comment."""
    findings = read_all(bank, BARS - 1, Timeframe.H1)
    willr = next(f for f in findings if f.key == "willr_14_h1")

    assert "stoch_14_h1" in willr.depends_on


def test_the_dependency_names_its_own_timeframe(bank: dict[str, pd.Series]) -> None:
    """The hourly reading depends on the hourly twin, not the daily one. A
    dependency pointing across timeframes would discount a finding because of
    something measured on a different clock."""
    daily = read_all(bank, BARS - 1, Timeframe.D1)
    willr = next(f for f in daily if f.key == "willr_14_d1")

    assert willr.depends_on == ("stoch_14_d1",)


def test_the_cumulative_window_matches_what_was_registered() -> None:
    """`obv` is registered with a twenty-bar lookback and the bank reads its
    change over twenty bars. Drifting apart would make the declared warm-up a
    different number from the real one."""
    assert SPECS["obv"].lookback == CUMULATIVE_WINDOW


# --------------------------------------------------------------------------- #
# Direction, end to end
# --------------------------------------------------------------------------- #


def test_a_sustained_rise_reads_bullish() -> None:
    """The sanity check the rest of this file does not provide.

    Every test above is about not fooling ourselves. This one asks whether the
    thing works at all: a market that has gone straight up for four hundred
    bars must not produce a bearish score.
    """
    bars = 600
    close = np.linspace(100.0, 200.0, bars)
    frame = pd.DataFrame(
        {
            "ts": np.arange(bars, dtype="int64") * 3_600_000,
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": np.full(bars, 1000.0),
        }
    )
    readings = compute_bank(frame, atr(frame, 14))

    evidence = Evidence()
    for finding in read_all(readings, bars - 1, Timeframe.H1):
        evidence.add(finding)
    score = compute(evidence)

    assert score.direction is Bias.BULLISH, score.describe()
    assert score.bullish > score.bearish
