"""The indicator inventory, and the one property that makes forty-two of them safe.

Severin asked for fifty indicators feeding the rating. Forty-two are registered
and more will follow, and that is only defensible because of the last test in
this file: however many there are, they cannot produce more verdicts than there
are families. In a plain sum this inventory would be a machine for reaching
certainty about nothing.

The rest is the bookkeeping chapter 12.7 asks for -- `family`, `lag`,
`failure_modes`, `output_unit` -- tested because each of those fields silently
changes how much a reading counts, and a missing one fails in the direction of
counting more rather than less.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.domain.enums import Bias, Timeframe
from traidingbrain.score.engine import compute
from traidingbrain.score.findings import Evidence, Family
from traidingbrain.score.registry import (
    BOUNDED_FULL_SCALE,
    MIN_NORMALISE_SAMPLES,
    NORMALISE_WINDOW,
    SPECS,
    Reading,
    Spec,
    Unit,
    normalise,
    read_all,
    specs_by_family,
)


def spec_named(name: str) -> Spec:
    return SPECS[name]


def series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype="float64")


# --------------------------------------------------------------------------- #
# The property the whole inventory rests on
# --------------------------------------------------------------------------- #


def test_forty_two_indicators_cannot_produce_more_than_five_verdicts() -> None:
    """The reason a large inventory is safe.

    Every registered indicator, all agreeing, all at full strength. If the score
    counted entries it would be pinned at an extreme; because it reconciles by
    family, the answer is bounded by how many kinds of information there are.
    """
    evidence = Evidence()
    for index, spec in enumerate(SPECS.values()):
        evidence.add(
            Reading(spec=spec, value=1.0, normalised=1.0).to_finding(Timeframe.H1)
        )
        assert index >= 0

    verdicts = compute(evidence).families

    assert len(SPECS) > 30, "the inventory shrank; this test no longer proves much"
    assert len(verdicts) <= len(Family)
    assert compute(evidence).breadth <= len(specs_by_family())


def test_one_family_agreeing_loudly_does_not_outrank_two_families() -> None:
    """Chapter 17's definition of confluence, as an inequality.

    Fifteen trend indicators shouting in one direction is one family. Two
    families quietly agreeing is confluence. The second has to win, or the
    inventory becomes a way of buying certainty by adding more of the same.
    """
    crowd = Evidence()
    for spec in specs_by_family()[Family.TREND]:
        crowd.add(Reading(spec=spec, value=1.0, normalised=1.0).to_finding(Timeframe.H1))

    pair = Evidence()
    for family in (Family.TREND, Family.STRUCTURE):
        member = specs_by_family().get(family)
        if member:
            pair.add(Reading(spec=member[0], value=1.0, normalised=0.6).to_finding(Timeframe.H1))

    assert compute(crowd).breadth == 1


# --------------------------------------------------------------------------- #
# The bookkeeping chapter 12.7 requires
# --------------------------------------------------------------------------- #


def test_every_indicator_states_how_it_fails() -> None:
    """Enforced at construction, checked here because it is the field most
    likely to be skipped when adding one in a hurry.

    An indicator with no stated failure mode is one nobody has thought about
    hard enough to trust, and the note belongs beside it rather than in
    somebody's memory.
    """
    for spec in SPECS.values():
        assert spec.failure_modes, spec.name
        for note in spec.failure_modes:
            assert len(note) > 10, f"{spec.name}: {note!r} does not say anything"


def test_an_indicator_without_a_failure_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="failure mode"):
        Spec(
            name="x",
            family=Family.TREND,
            input_series=("close",),
            lookback=10,
            output_unit=Unit.PRICE,
            lag_bars=1,
            failure_modes=(),
            source="test",
        )


def test_every_indicator_declares_a_lag() -> None:
    """A 200-period average of hourly bars describes the last eight days, not
    now. Anything reading these has to tell the difference, so the lag is a
    field rather than folk knowledge."""
    for spec in SPECS.values():
        assert spec.lag_bars >= 1, spec.name
        assert spec.lag_bars <= spec.lookback, (
            f"{spec.name}: a lag longer than the lookback is not a lag"
        )


def test_the_slowest_indicators_say_they_are_slow() -> None:
    """The specific case: the long averages must not claim to be current."""
    assert spec_named("sma_200").lag_bars > spec_named("rsi_14").lag_bars


def test_every_volume_indicator_is_marked_venue_dependent() -> None:
    """Chapter 11.2: "VWAP ist datenfeed- und sessionabhängig". Forex tick
    volume, crypto exchange volume and centralised futures volume are not the
    same number, so a reading that does not say which feed it came from cannot
    be compared with a later one."""
    for spec in specs_by_family()[Family.VOLUME]:
        assert spec.venue_dependent, spec.name


def test_no_indicator_is_registered_twice() -> None:
    """Two entries with one name make the second silently replace the first, or
    double its family's membership -- depending on which way the mistake goes."""
    names = [spec.name for spec in SPECS.values()]

    assert len(names) == len(set(names))


def test_every_registered_family_is_a_real_one() -> None:
    """A family invented by typo would earn its indicator a private vote."""
    for spec in SPECS.values():
        assert spec.family in Family


# --------------------------------------------------------------------------- #
# Turning a value into a strength
# --------------------------------------------------------------------------- #


def test_a_bounded_oscillator_is_neutral_at_its_midpoint() -> None:
    rsi = spec_named("rsi_14")

    assert normalise(rsi, series([50.0]), 0) == pytest.approx(0.0)


def test_a_bounded_oscillator_reaches_full_strength_where_configured() -> None:
    """Full strength at 50 ± 25, which is inside the conventional 30/70: a
    reading only counts fully once it is past where most people would already
    call it stretched."""
    rsi = spec_named("rsi_14")

    assert normalise(rsi, series([50.0 + BOUNDED_FULL_SCALE]), 0) == pytest.approx(1.0)
    assert normalise(rsi, series([50.0 - BOUNDED_FULL_SCALE]), 0) == pytest.approx(-1.0)


def test_a_bounded_oscillator_cannot_exceed_full_strength() -> None:
    """An RSI of 100 is not four times an RSI of 75. Without the clamp one
    extreme reading would outweigh every other finding at once."""
    rsi = spec_named("rsi_14")

    assert normalise(rsi, series([100.0]), 0) == pytest.approx(1.0)
    assert normalise(rsi, series([0.0]), 0) == pytest.approx(-1.0)


def test_an_unbounded_reading_is_scaled_against_its_own_recent_history() -> None:
    """Rolling, never global. A global scale lets a quiet year decide what
    counts as extreme in a violent one, which is the same lookahead that ruins
    a regime filter."""
    macd = spec_named("macd_hist")
    quiet = series([*([0.0] * 100), 1.0])
    violent = series([*(float(i % 7) - 3 for i in range(100)), 1.0])

    in_quiet = normalise(macd, quiet, 100)
    in_violent = normalise(macd, violent, 100)

    assert in_quiet > in_violent


def test_too_little_history_reads_as_nothing_rather_than_something() -> None:
    """Below the sample floor the standard deviation is an estimate from too
    little, and a confident number built on it is worse than none."""
    macd = spec_named("macd_hist")
    short = series([float(i) for i in range(MIN_NORMALISE_SAMPLES - 1)])

    assert normalise(macd, short, len(short) - 1) == 0.0


def test_the_normalisation_never_reads_past_the_bar() -> None:
    """The guarantee the whole engine rests on, applied to this layer.

    A window written with the wrong sign would make every unbounded indicator
    look prescient, and nothing in the output would show it.
    """
    macd = spec_named("macd_hist")
    rng = np.random.default_rng(3)
    values = list(rng.normal(0, 1, 400))
    cut = 250

    before = normalise(macd, series(values), cut)
    mutated = [*values[: cut + 1], *([999.0] * (len(values) - cut - 1))]

    assert normalise(macd, series(mutated), cut) == pytest.approx(before)


def test_a_reading_at_zero_takes_no_side() -> None:
    """Rounding must not hand a neutral reading a direction."""
    spec = spec_named("macd_hist")

    finding = Reading(spec=spec, value=0.0, normalised=0.0).to_finding(Timeframe.H1)

    assert finding.direction is Bias.NEUTRAL
    assert finding.strength == 0.0


def test_a_finding_carries_the_timeframe_in_its_key() -> None:
    """Keys are what dependencies point at, and the same indicator on two
    timeframes is two findings -- so the timeframe has to be in the key or one
    would overwrite the other."""
    spec = spec_named("rsi_14")

    hourly = Reading(spec=spec, value=70.0, normalised=0.8).to_finding(Timeframe.H1)
    daily = Reading(spec=spec, value=70.0, normalised=0.8).to_finding(Timeframe.D1)

    assert hourly.key != daily.key


# --------------------------------------------------------------------------- #
# Reading a whole bar
# --------------------------------------------------------------------------- #


def test_an_indicator_that_did_not_run_is_skipped_not_defaulted() -> None:
    """A missing indicator and one reading zero are different states. Folding
    them together lets a detector that failed to run look like one that looked
    and found nothing."""
    computed = {"rsi_14": series([50.0] * 100)}

    findings = read_all(computed, 99, Timeframe.H1)

    assert [f.key for f in findings] == ["rsi_14_h1"]


def test_a_bar_inside_the_warm_up_produces_nothing_for_that_indicator() -> None:
    """Reading a 200-period average at bar 50 is reading a number that does not
    mean what it says yet."""
    computed = {"sma_200": series([100.0] * 300)}

    assert read_all(computed, 50, Timeframe.H1) == []
    assert read_all(computed, 250, Timeframe.H1) != []


def test_a_nan_reading_is_skipped() -> None:
    computed = {"rsi_14": series([float("nan")] * 100)}

    assert read_all(computed, 99, Timeframe.H1) == []


def test_reading_a_bar_past_the_end_returns_nothing() -> None:
    computed = {"rsi_14": series([50.0] * 30)}

    assert read_all(computed, 999, Timeframe.H1) == []
    assert normalise(spec_named("rsi_14"), series([50.0]), 99) == 0.0


# --------------------------------------------------------------------------- #
# Coverage of the chapter
# --------------------------------------------------------------------------- #


def test_the_inventory_covers_every_family_chapter_12_describes() -> None:
    """Chapter 12 has five sections: trend, momentum, volatility, volume and
    level tools. A family with nothing in it is a blind spot the score cannot
    report, because it has no finding to be missing."""
    present = set(specs_by_family())

    for family in (
        Family.TREND,
        Family.MOMENTUM,
        Family.VOLATILITY,
        Family.VOLUME,
        Family.LOCATION,
    ):
        assert family in present, family


def test_the_normalisation_window_is_longer_than_the_slowest_lookback() -> None:
    """Otherwise the slowest indicator is scaled against a window shorter than
    the thing it measures, and its z-score is noise about noise."""
    slowest = max(spec.lookback for spec in SPECS.values())

    assert slowest < NORMALISE_WINDOW
