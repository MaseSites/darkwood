"""The one number, and the properties that stop it from lying.

Severin asked for a single rating from 1 to 100. A single number is the thing
this project has refused everywhere else, for a good reason: a subtraction
hides whether a quiet market or a fight produced it. So this one rates
something a single number *can* hold -- how clear the picture is -- and carries
its direction and its four parts beside it.

The tests below are mostly about what it must never become:

* It must not be read as a forecast. A clean downward picture rates high, and
  the direction is a separate field.
* It must not be reachable by one strong part. A geometric mean is what makes
  that true, and the test for it is the one that would catch a well-meaning
  change to an average.
* It must not say 100 while a third of the families feed nothing into it.
"""

from __future__ import annotations

import pytest

from traidingbrain.domain.enums import Bias, Timeframe
from traidingbrain.score.engine import Score, ScoredFamily, compute
from traidingbrain.score.findings import Evidence, Family, FamilyVerdict, Finding
from traidingbrain.score.rating import CLEAR_LEAN, WEIGHTS, Rating, band_for, rate

ALL_FAMILIES = len(Family)


def scored(family: Family, contribution: float, *, split: bool = False) -> ScoredFamily:
    direction = Bias.BULLISH if contribution > 0 else Bias.BEARISH
    return ScoredFamily(
        verdict=FamilyVerdict(
            family=family,
            direction=direction,
            strength=abs(contribution),
            agreement=1.0,
            members=(f"{family.value}_x",),
        ),
        base_weight=1.0,
        regime_modifier=1.0,
        contribution=contribution,
        split=split,
    )


def score_of(*contributions: tuple[Family, float], families: int | None = None) -> Score:
    """A score with the given family contributions, summed the way `compute` does."""
    built = Score()
    built.families = [scored(family, value) for family, value in contributions]
    for _, value in contributions:
        if value > 0:
            built.bullish += value
        else:
            built.bearish += -value
    built.bullish = round(built.bullish, 4)
    built.bearish = round(built.bearish, 4)
    if families is not None:
        # Pad with split families: present, measured, but taking no side.
        while len(built.families) < families:
            built.families.append(scored(Family.HISTORY, 0.0, split=True))
    return built


def perfect() -> Score:
    """Every family present, all agreeing, emphatically."""
    share = CLEAR_LEAN / ALL_FAMILIES
    return score_of(*[(family, share) for family in Family])


# --------------------------------------------------------------------------- #
# What the number is, and is not
# --------------------------------------------------------------------------- #


def test_a_clean_picture_pointing_down_rates_high() -> None:
    """The point of the whole design. If a falling market rated low, the number
    would be a forecast of a rise wearing a quality label."""
    falling = score_of(*[(family, -CLEAR_LEAN / ALL_FAMILIES) for family in Family])

    rating = rate(falling)

    assert rating.value >= 90
    assert rating.direction is Bias.BEARISH


def test_everything_agreeing_everywhere_rates_at_the_top() -> None:
    assert rate(perfect()).value >= 95


def test_nothing_measured_rates_one_not_zero() -> None:
    """The scale Severin asked for starts at one, and a bar with no evidence is
    the worst case it describes rather than an absence of a case."""
    empty = Score()

    rating = rate(empty)

    assert rating.value == 1
    assert rating.direction is Bias.NEUTRAL


def test_a_fight_rates_far_below_a_quiet_agreement() -> None:
    """The reading the whole project refuses to collapse, as a rating.

    Two families pulling hard in opposite directions and two agreeing mildly
    can produce a similar lean. They are not the same picture, and the number
    has to separate them or it is the subtraction all over again.
    """
    fight = score_of(
        (Family.STRUCTURE, 0.9),
        (Family.MOMENTUM, -0.7),
        families=ALL_FAMILIES,
    )
    quiet = score_of(
        (Family.STRUCTURE, 0.2),
        (Family.MOMENTUM, 0.0001),
        families=ALL_FAMILIES,
    )

    assert rate(fight).value < rate(quiet).value


# --------------------------------------------------------------------------- #
# Why it is a product
# --------------------------------------------------------------------------- #


def test_one_strong_part_cannot_carry_the_rating() -> None:
    """The test that would catch a change to a weighted average.

    Perfectly emphatic evidence that most families contradict is not a good
    picture, and an average would let clarity's weight of three drag it to
    something respectable.
    """
    emphatic_but_contested = Score(bullish=CLEAR_LEAN * 2.0, bearish=CLEAR_LEAN * 1.0)
    emphatic_but_contested.families = [
        scored(Family.STRUCTURE, CLEAR_LEAN * 2.0),
        scored(Family.TREND, -CLEAR_LEAN * 0.4),
        scored(Family.MOMENTUM, -CLEAR_LEAN * 0.3),
        scored(Family.VOLUME, -CLEAR_LEAN * 0.3),
    ]

    # Half the clarity, and nothing arguing back.
    agreed = Score(bullish=CLEAR_LEAN * 0.5, bearish=0.0)
    agreed.families = [
        scored(Family.STRUCTURE, CLEAR_LEAN * 0.2),
        scored(Family.TREND, CLEAR_LEAN * 0.1),
        scored(Family.MOMENTUM, CLEAR_LEAN * 0.1),
        scored(Family.VOLUME, CLEAR_LEAN * 0.1),
    ]

    contested = rate(emphatic_but_contested)
    quiet = rate(agreed)

    # Stated as a comparison rather than against a threshold. The sharpest form
    # of the property: half the clarity with no contradiction has to beat
    # maximum clarity that most of the families argue against.
    assert contested.clarity == pytest.approx(1.0)
    assert quiet.clarity == pytest.approx(0.5)
    assert contested.value < quiet.value, "one maxed part carried the number"


def test_a_part_at_rock_bottom_hurts_without_erasing_the_rest() -> None:
    """A floor under the logarithm. Without it a single zero sends the rating
    to 1 whatever else is true, which stops the number from distinguishing
    between one bad part and everything bad."""
    one_bad = score_of(
        (Family.STRUCTURE, 0.4),
        (Family.TREND, -0.4),
        families=ALL_FAMILIES,
    )

    assert rate(one_bad).value > 1


# --------------------------------------------------------------------------- #
# Honesty about coverage
# --------------------------------------------------------------------------- #


def test_a_perfect_rating_is_impossible_while_families_stay_silent() -> None:
    """Three families feed nothing into the score today. A hundred while a
    third of the inventory never spoke would be a lie about how much was
    looked at -- so coverage is a part, and it caps the number."""
    seven_of_ten = score_of(
        *[(family, CLEAR_LEAN / 7) for family in list(Family)[:7]],
    )

    rating = rate(seven_of_ten)

    assert rating.coverage == pytest.approx(0.7)
    assert rating.value < 100


def test_coverage_counts_families_that_spoke_not_families_that_agreed() -> None:
    """A family that was measured and took no side was still looked at. Folding
    it in with the ones nothing is known about would understate what the
    system actually read."""
    with_split = score_of((Family.STRUCTURE, 0.5), families=5)

    assert rate(with_split).coverage == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Reading the number
# --------------------------------------------------------------------------- #


def test_the_weakest_part_is_named() -> None:
    """The useful half of a low rating. "41" says nothing a person can act on;
    "41, weakest part Einigkeit" says where to look."""
    contested = score_of(
        (Family.STRUCTURE, 0.6),
        (Family.TREND, -0.55),
        families=ALL_FAMILIES,
    )

    assert rate(contested).weakest in WEIGHTS


def test_every_rating_lands_in_a_band() -> None:
    for value in range(1, 101):
        assert band_for(value)


def test_the_bands_do_not_overlap_or_leave_a_gap() -> None:
    """Read from the top down, so a mistake here shows up as two bands
    claiming the same number -- which no caller would notice."""
    names = [band_for(value) for value in range(0, 101)]

    assert names[0] == "Durcheinander"
    assert names[100] == "eindeutig"
    assert len(set(names)) == 5


def test_the_parts_are_reported_so_the_number_can_be_argued_with() -> None:
    rating: Rating = rate(perfect())

    assert set(rating.parts) == set(WEIGHTS)
    assert all(0.0 <= value <= 1.0 for value in rating.parts.values())


# --------------------------------------------------------------------------- #
# Against a real score object
# --------------------------------------------------------------------------- #


def test_it_rates_a_score_the_engine_actually_produced() -> None:
    """The handwritten scores above are convenient and could drift from what
    `compute` emits. This one goes through the engine."""
    evidence = Evidence()
    for index, family in enumerate(list(Family)[:6]):
        evidence.add(
            Finding(
                key=f"f{index}",
                family=family,
                direction=Bias.BULLISH,
                strength=0.8,
                timeframe=Timeframe.H1,
                source="test",
            )
        )

    rating = rate(compute(evidence))

    assert 1 <= rating.value <= 100
    assert rating.direction is Bias.BULLISH


def test_measured_and_silent_rates_above_nothing_at_all() -> None:
    """Two different kinds of nothing.

    Every family measured and none taking a side is a real answer about a real
    market. No families at all is the absence of one. Collapsing them to the
    same number would throw away the distinction the whole score is built to
    preserve -- and `Score.conflict` reports zero for both, which reads as
    "nothing argues the other way" when the truth is that nothing argued.
    """
    silent = Score()
    silent.families = [scored(family, 0.0, split=True) for family in Family]

    nothing = Score()

    assert rate(silent).agreement == 0.0
    assert rate(nothing).value < rate(silent).value


def test_the_bands_are_not_so_generous_that_the_words_stop_meaning_anything() -> None:
    """Measured, like the scale.

    Over 5,336 bars the rating's deciles came out 24, 38, 48, 57, 64, 71, 76,
    82, 89. The first draft put "eindeutig" at 80, which called a quarter of
    all bars unambiguous -- a word that describes one bar in four is not
    describing anything. The thresholds sit near the measured deciles instead.
    """
    assert band_for(64) == "gemischt", "the median bar must not be called clear"
    assert band_for(89) == "eindeutig", "the top tenth is what the word is for"
    assert band_for(38) == "unklar"
    assert band_for(24) == "Durcheinander", "the bottom tenth"
