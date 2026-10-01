"""Structure and liquidity as evidence -- and the two things the sources forbid.

Most of this file is about what must *not* be emitted. The detectors have been
drawing structure and liquidity on the chart for a while, and the temptation
when wiring them into a score is to let every drawn object argue a direction.
`TRADING_ANALYSE_GRUNDLAGEN.md` refuses two of them by name:

* **Pools get no direction.** Chapter 8.2: "Sichtbarkeit garantiert nicht, dass
  Preis dorthin läuft." The popular reading -- liquidity is a magnet, so equal
  highs above argue up -- is precisely the inference that sentence rejects.
* **A sweep alone is weak.** Chapter 8.3: "Ein Sweep allein ist keine
  Umkehrbestätigung." It counts for something only once a structure break has
  followed it, and then the pair must not be counted as two.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.pipeline import FrameAnalysis, analyse
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Bias, Timeframe
from traidingbrain.score.findings import Family
from traidingbrain.score.observations import (
    SWEEP_ALONE_STRENGTH,
    SWEEP_CONFIRMED_STRENGTH,
    liquidity_findings,
    observations_for,
    structure_findings,
)

BARS = 600


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


def frame_from(close: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": np.arange(len(close), dtype="int64") * 3_600_000,
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": close * 1.004,
            "low": close * 0.996,
            "close": close,
            "volume": np.full(len(close), 1000.0),
        }
    )


def analysed(close: np.ndarray, config: AppConfig) -> FrameAnalysis:
    return analyse(frame_from(close), Timeframe.H1, config.engine)


@pytest.fixture(scope="module")
def rising(config: AppConfig) -> FrameAnalysis:
    """A staircase up: each leg higher than the last, with pullbacks between.

    Built rather than randomised, because the thing under test is whether a
    sequence of higher highs and higher lows is read as one -- and a random
    walk that happens to rise does not reliably produce that sequence.
    """
    legs = []
    level = 100.0
    for _ in range(12):
        # Each leg drops its first point, which is the previous leg's last one.
        # Keeping it puts the peak price on two bars, and a tie is not a swing
        # -- a flat top is a level that has not been rejected yet. The first
        # version of this fixture produced zero swings for exactly that reason.
        legs.append(np.linspace(level, level * 1.06, 35)[1:])
        level *= 1.06
        legs.append(np.linspace(level, level * 0.98, 15)[1:])
        level *= 0.98
    return analysed(np.concatenate(legs), config)


@pytest.fixture(scope="module")
def noisy(config: AppConfig) -> FrameAnalysis:
    rng = np.random.default_rng(5)
    return analysed(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.004, BARS))), config)


def keys(findings: list) -> set[str]:
    return {finding.key for finding in findings}


# --------------------------------------------------------------------------- #
# What the sources forbid
# --------------------------------------------------------------------------- #


def test_a_pool_of_equal_highs_never_argues_a_direction(noisy: FrameAnalysis) -> None:
    """Chapter 8.2, as a test.

    Equal highs and equal lows are found, carried in `LiquidityState.zones` and
    drawn on the chart. They are not evidence, because being visible is not a
    reason for price to go there -- and the usual "liquidity is a magnet"
    reading would turn every drawn pool into a forecast.
    """
    found = False
    for index in range(100, len(noisy), 7):
        state = noisy.liquidity.state_at(index)
        if not state.zones:
            continue
        found = True
        emitted = keys(liquidity_findings(noisy, index))
        assert not any("equal" in key or "pool" in key for key in emitted), emitted

    assert found, "no pools were detected at all; this test proved nothing"


def test_a_sweep_on_its_own_counts_for_little(noisy: FrameAnalysis) -> None:
    """Chapter 8.3: "Ein Sweep allein ist keine Umkehrbestätigung.\""""
    seen = 0
    for index in range(100, len(noisy)):
        liquidity = noisy.liquidity.state_at(index)
        structure = noisy.structure.state_at(index)
        if not (liquidity.sweep_up or liquidity.sweep_down):
            continue
        sweep = next(
            (f for f in liquidity_findings(noisy, index) if f.key.startswith("liquidity_sweep")),
            None,
        )
        assert sweep is not None
        confirmed = (
            structure.bars_since_bos is not None
            and liquidity.bars_since_sweep is not None
            and structure.bars_since_bos <= liquidity.bars_since_sweep
            and structure.break_direction is sweep.direction
        )
        expected = SWEEP_CONFIRMED_STRENGTH if confirmed else SWEEP_ALONE_STRENGTH
        assert sweep.strength == pytest.approx(expected)
        seen += 1

    assert seen > 0, "no sweeps were detected at all; this test proved nothing"


def test_a_confirmed_sweep_does_not_count_the_break_twice(noisy: FrameAnalysis) -> None:
    """When the break is what makes the sweep count, it is the same
    information the structure family already reported. Without the declared
    dependence, one event would be two pieces of evidence in two families --
    which is what confluence is supposed to mean and this is not."""
    for index in range(100, len(noisy)):
        sweep = next(
            (f for f in liquidity_findings(noisy, index) if f.key.startswith("liquidity_sweep")),
            None,
        )
        if sweep is None or sweep.strength != pytest.approx(SWEEP_CONFIRMED_STRENGTH):
            continue
        assert sweep.depends_on == ("structure_break_h1",)
        return
    pytest.skip("no confirmed sweep in this series")


# --------------------------------------------------------------------------- #
# What they do say
# --------------------------------------------------------------------------- #


def test_a_staircase_up_reads_as_bullish_structure(rising: FrameAnalysis) -> None:
    """The sanity check: higher highs and higher lows have to come out bullish,
    or none of the careful refusals above matter."""
    index = len(rising) - 1
    trend = next(
        (f for f in structure_findings(rising, index) if f.key == "structure_trend_h1"), None
    )

    assert trend is not None, "a clean staircase produced no structural trend at all"
    assert trend.direction is Bias.BULLISH
    assert trend.strength > 0.3


def test_a_partly_agreeing_sequence_reads_weaker_than_a_clean_one(
    rising: FrameAnalysis, noisy: FrameAnalysis
) -> None:
    """The enum alone cannot tell three-for-two from five-for-none.

    Both are "bullish" to `StructureState.trend`, and treating them as the same
    strength would throw away the only gradation structure has.
    """
    clean = next(
        (f for f in structure_findings(rising, len(rising) - 1) if f.key.endswith("trend_h1")),
        None,
    )
    assert clean is not None

    weaker = [
        f.strength
        for index in range(100, len(noisy))
        for f in structure_findings(noisy, index)
        if f.key.endswith("trend_h1")
    ]

    assert weaker, "the noisy series produced no structural trend at all"
    assert min(weaker) < clean.strength


def test_a_change_of_character_on_the_break_bar_is_not_two_events(
    noisy: FrameAnalysis,
) -> None:
    """A change of character *is* a break of structure -- the one that went
    against the prior direction. When both point at the same bar, counting them
    separately reports one event as two."""
    for index in range(100, len(noisy)):
        state = noisy.structure.state_at(index)
        if state.bars_since_choch is None or state.bars_since_choch != state.bars_since_bos:
            continue
        found = {f.key: f for f in structure_findings(noisy, index)}
        choch = found.get("structure_choch_h1")
        if choch is None:
            continue
        assert choch.depends_on == ("structure_break_h1",)
        return
    pytest.skip("no simultaneous break and change of character in this series")


def test_a_break_carries_its_age(noisy: FrameAnalysis) -> None:
    """Freshness is what separates a break that just happened from one eleven
    bars ago, and the score decays only findings that declare an age."""
    for index in range(100, len(noisy)):
        found = next(
            (f for f in structure_findings(noisy, index) if f.key == "structure_break_h1"), None
        )
        if found is None:
            continue
        assert found.freshness_bars == noisy.structure.state_at(index).bars_since_bos
        return
    pytest.skip("no break of structure in this series")


def test_a_distant_gap_argues_nothing(noisy: FrameAnalysis) -> None:
    """A gap three ATR away is a level on a chart; a gap price is standing in
    is a thing happening. Every emitted gap has to be within reach, or the
    liquidity family would carry an opinion about somewhere else."""
    for index in range(100, len(noisy)):
        for found in liquidity_findings(noisy, index):
            if found.key.startswith("fvg_"):
                assert found.distance_atr is not None
                assert found.distance_atr <= 3.0


def test_every_observation_lands_in_structure_or_liquidity(noisy: FrameAnalysis) -> None:
    """These two families are what this module exists to fill. A finding
    leaking into another family would be weighed by a table that was not
    written for it."""
    for index in range(100, len(noisy), 5):
        for found in observations_for(noisy, index):
            assert found.family in (Family.STRUCTURE, Family.LIQUIDITY), found.key


def test_no_observation_is_emitted_twice_at_one_bar(noisy: FrameAnalysis) -> None:
    """`Evidence.add` refuses a duplicate key, so a collision here would not be
    a wrong number -- it would be a crash on a live bar."""
    for index in range(100, len(noisy), 3):
        emitted = [f.key for f in observations_for(noisy, index)]

        assert len(emitted) == len(set(emitted))
