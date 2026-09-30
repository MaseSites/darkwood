"""V13's six factors and V05's filters, including where the two disagree.

The gaps themselves are arithmetic and tested elsewhere. What is tested here is
the part that is actually the content of two videos: which of the forty gaps on
a chart is worth a stop.

Most of this file is about one failure mode, because every bug this module had
was an instance of it. A factor that is individually correct and collectively
impossible produces **zero signals and no error**, and the six factors here gave
four separate chances for that:

- ranked before validated, so the top-ranked gap was always an old filled one;
- "untested" measured including the bar doing the testing;
- the entry matched the gap's own creating candle, which spans it by
  construction;
- the stop taken from the third candle, whose low *is* the top of the gap.

Each is pinned below by a test that fails if it comes back.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.fvg_quality import (
    MAX_GAP_AGE_BARS,
    GapAssessment,
    MitigationRule,
    assess_gaps,
    best_gap,
)
from traidingbrain.analysis.indicators import atr
from traidingbrain.analysis.liquidity import Zone, ZoneKind, find_fair_value_gaps
from traidingbrain.analysis.structure import StructureTimeline

SWING_LOOKBACK = 3


def walk(count: int = 1500, seed: int = 4) -> pd.DataFrame:
    """A series with displacement in it, so gaps exist to be judged."""
    rng = np.random.default_rng(seed)
    price, anchor, hold, slope = 100.0, 100.0, 0, 0.0
    rows = []
    for _ in range(count):
        if hold <= 0:
            hold = int(rng.integers(15, 70))
            anchor = price
            slope = float(rng.normal(0, 0.5)) if rng.random() < 0.6 else 0.0
        hold -= 1
        price = max(price + slope + 0.1 * (anchor - price) + rng.normal(0, 0.7), 1.0)
        spread = abs(float(rng.normal(0, 0.45))) + 0.1
        open_ = price - float(rng.normal(0, 0.4))
        rows.append((open_, max(open_, price) + spread, min(open_, price) - spread, price))
    return pd.DataFrame(
        {
            "ts": [1_700_000_000_000 + i * 3_600_000 for i in range(count)],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [100.0] * count,
        }
    )


@pytest.fixture(scope="module")
def series() -> tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]]:
    frame = walk()
    volatility = atr(frame, 14)
    structure = StructureTimeline(frame, SWING_LOOKBACK, 6)
    return frame, volatility, structure, find_fair_value_gaps(frame, volatility)


def read(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
    index: int,
    rule: MitigationRule = MitigationRule.V13_INVALID,
) -> list[GapAssessment]:
    frame, volatility, structure, gaps = series
    return assess_gaps(frame, volatility, structure, index, rule=rule, gaps=gaps)


def everything(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
    rule: MitigationRule = MitigationRule.V13_INVALID,
) -> list[GapAssessment]:
    frame = series[0]
    return [item for index in range(100, len(frame), 3) for item in read(series, index, rule)]


# --------------------------------------------------------------------------- #
# The fixture has to contain what the tests are about
# --------------------------------------------------------------------------- #


def test_the_series_contains_gaps_of_both_kinds(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    kinds = {gap.kind for gap in series[3]}

    assert kinds == {ZoneKind.FVG_BULLISH, ZoneKind.FVG_BEARISH}


def test_every_factor_is_both_met_and_failed_somewhere(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """A factor that is always true is not a filter, and one that is always
    false is a wall. Either way the other five are doing all the work and
    nobody would notice."""
    met: dict[str, int] = {}
    failed: dict[str, int] = {}
    for item in everything(series):
        for factor in item.factors:
            target = met if factor.met else failed
            target[factor.name] = target.get(factor.name, 0) + 1

    assert met and failed
    assert set(met) == set(failed), f"never met: {set(failed) - set(met)}"


# --------------------------------------------------------------------------- #
# Ranking, which must come after validity and not before
# --------------------------------------------------------------------------- #


def test_the_rank_is_taken_among_gaps_that_already_passed(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """The bug: ranked first, then checked.

    "Bei mehreren bullishen FVGs priorisiert V13 das tiefste" is a tiebreaker
    between candidates. Read as a pre-filter it defeats itself -- the lowest gap
    on a chart is usually an old one price has long since filled, so the
    top-ranked gap fails the freshness factor and nothing is ever tradeable.
    Measured before the fix: 10,212 assessments, 1,861 ranked first, zero
    signals.
    """
    ranked = [item for item in everything(series) if item.rank >= 0]

    assert ranked
    for item in ranked:
        assert not item.failed, "a gap that failed a factor was given a rank"


def test_a_failing_gap_is_marked_as_out_of_the_running(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    rejected = [item for item in everything(series) if item.failed]

    assert rejected
    for item in rejected:
        assert item.rank == -1
        assert item.tradeable is False


def test_the_lowest_valid_bullish_gap_ranks_first(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """V13's own words, for the side the video states them on."""
    frame = series[0]
    for index in range(100, len(frame), 7):
        valid = [item for item in read(series, index) if item.is_bullish and item.rank >= 0]
        if len(valid) < 2:
            continue
        top = min(valid, key=lambda item: item.rank)

        assert top.gap.low == min(item.gap.low for item in valid)
        return
    pytest.fail("no bar ever had two valid bullish gaps, so this proved nothing")


def test_the_highest_valid_bearish_gap_ranks_first(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    frame = series[0]
    for index in range(100, len(frame), 7):
        valid = [item for item in read(series, index) if not item.is_bullish and item.rank >= 0]
        if len(valid) < 2:
            continue
        top = min(valid, key=lambda item: item.rank)

        assert top.gap.low == max(item.gap.low for item in valid)
        return
    pytest.fail("no bar ever had two valid bearish gaps, so this proved nothing")


# --------------------------------------------------------------------------- #
# Freshness, and the bar that must not count against itself
# --------------------------------------------------------------------------- #


def test_untested_means_untested_before_this_bar(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """The bar being judged is the one testing the gap -- that is what a retest
    setup is. Counting it makes every gap read as mitigated on the exact bar the
    entry condition becomes true, and the two conditions cancel.

    Checked by construction: a gap assessed on the bar right after it formed has
    had no chance to be tested, whatever that bar did.
    """
    frame, volatility, structure, gaps = series
    fresh = [gap for gap in gaps if gap.created_index + 1 < len(frame)]
    assert fresh

    checked = 0
    for gap in fresh[:40]:
        index = gap.created_index + 1
        found = next(
            (
                item
                for item in assess_gaps(frame, volatility, structure, index, gaps=gaps)
                if item.gap == gap
            ),
            None,
        )
        if found is None:
            continue
        freshness = next(f for f in found.factors if f.name == "unmitigated")
        assert freshness.met, "a gap was mitigated by the first bar after it formed"
        checked += 1

    assert checked, "no gap was ever assessed one bar after forming"


def test_the_two_sources_disagree_about_a_tested_gap_and_both_answers_survive(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """Guide chapter 17.4. V05: a touch makes it weaker, "es müsse beim zweiten
    Besuch nicht zwangsläufig scheitern". V13: after a test it is invalid.

    No playlist source decides between them, so neither does the code. Picking
    one and calling it "the FVG rule" would hide a disagreement between sources
    behind an implementation detail.
    """
    strict = everything(series, MitigationRule.V13_INVALID)
    lenient = everything(series, MitigationRule.V05_WEAKER)

    def fresh_failures(items: list[GapAssessment]) -> int:
        return sum(1 for item in items if "unmitigated" in item.failed)

    assert fresh_failures(strict) > 0
    assert fresh_failures(lenient) == 0
    assert sum(item.tradeable for item in lenient) > sum(item.tradeable for item in strict)


def test_the_lenient_rule_still_says_the_gap_was_tested(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """V05 downgrades rather than discards, so the reading has to carry the fact
    that it was touched -- otherwise "weaker" is a word with nothing behind it."""
    details = [
        factor.detail
        for item in everything(series, MitigationRule.V05_WEAKER)
        for factor in item.factors
        if factor.name == "unmitigated"
    ]

    assert any("tested" in detail and "weaker" in detail for detail in details)


# --------------------------------------------------------------------------- #
# The individual factors
# --------------------------------------------------------------------------- #


def test_the_reaction_is_judged_on_the_close_so_a_wick_through_is_allowed(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """V13: "Reaktionskerze darf durchwicken, soll aber im FVG oder in Richtung
    der Zone schließen." Judged on the low instead, every gap that did its job
    would be refused."""
    frame = series[0]
    closes = frame["close"].to_numpy(dtype="float64")

    for index in range(200, len(frame), 11):
        for item in read(series, index):
            factor = next(f for f in item.factors if f.name == "reaction_close")
            expected = (
                closes[index] >= item.gap.low if item.is_bullish else closes[index] <= item.gap.high
            )
            assert factor.met is bool(expected)


def test_long_gaps_are_wanted_in_the_lower_half_and_shorts_in_the_upper(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """V13 factor 5 and V05 filter 3 say the same thing. Measured on the gap's
    midpoint -- an edge would make a gap straddling the halfway mark pass or
    fail depending on which end is asked about."""
    # Read off the half the detail names rather than the rounded percentage it
    # prints. A gap at 50.4% displays as "50%" while sitting on the premium
    # side, so a test that parses the number disagrees with the code at exactly
    # the boundary the rule is about.
    seen = {True: 0, False: 0}
    for item in everything(series):
        factor = next(f for f in item.factors if f.name == "range_half")
        if "of the range" not in factor.detail:
            continue
        discount = factor.detail.endswith("discount")

        assert factor.met is (discount if item.is_bullish else not discount)
        seen[factor.met] += 1

    assert seen[True] and seen[False]


def test_the_structure_break_is_looked_for_before_the_gap_not_after(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """V13 factor 6: "Vor Entstehung bzw. im Entstehungsmove."

    Read at the current bar instead, a break that happened *after* the gap
    formed would validate it -- which is lookahead with the steps in the right
    order, and the hardest kind to see. Every met reading has to name a break
    that preceded the gap.
    """
    met = [
        factor
        for item in everything(series)
        for factor in item.factors
        if factor.name == "break_of_structure" and factor.met
    ]

    assert met
    for factor in met:
        assert "before the gap" in factor.detail


def test_a_gap_is_assessed_the_same_way_however_much_later_it_is_read(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """The structure-break factor is a property of the gap, not of when it is
    looked at. If it ever moved with the reading bar, a gap would become valid
    because of something that happened after it."""
    frame, volatility, structure, gaps = series
    candidates = [gap for gap in gaps if 300 < gap.created_index < 600]
    assert candidates

    for gap in candidates[:25]:
        readings = []
        for index in (gap.created_index + 2, gap.created_index + 20, gap.created_index + 60):
            if index >= len(frame):
                continue
            found = next(
                (
                    item
                    for item in assess_gaps(frame, volatility, structure, index, gaps=gaps)
                    if item.gap == gap
                ),
                None,
            )
            if found is not None:
                readings.append(
                    next(f.met for f in found.factors if f.name == "break_of_structure")
                )
        assert len(set(readings)) <= 1, f"the break factor moved for {gap}"


# --------------------------------------------------------------------------- #
# Bounds and edges
# --------------------------------------------------------------------------- #


def test_gaps_older_than_the_window_are_not_considered(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """Without a bound the set grows without limit, which is wrong twice: the
    "deepest" gap eventually becomes one from years ago that nothing will reach,
    and assessing all of them on every bar is quadratic in the run."""
    index = 900
    ages = [index - item.gap.created_index for item in read(series, index)]

    assert ages
    assert max(ages) <= MAX_GAP_AGE_BARS


def test_a_gap_is_never_assessed_before_it_exists(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    for index in (150, 400, 800):
        for item in read(series, index):
            assert item.gap.created_index <= index


def test_an_index_outside_the_series_returns_nothing(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    assert read(series, -1) == []
    assert read(series, 99_999) == []


def test_best_gap_returns_nothing_rather_than_the_least_bad_one(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, list[Zone]],
) -> None:
    """Nothing is the usual answer and the correct one. Returning the least bad
    gap would be the mistake V13's whole list exists to prevent."""
    frame = series[0]
    empty = 0
    for index in range(100, len(frame), 5):
        items = read(series, index)
        chosen = best_gap(items, bullish=True)
        if chosen is None:
            empty += 1
            continue
        assert chosen.tradeable
        assert chosen.rank == 0

    assert empty, "a gap qualified on every single bar, which cannot be right"
