"""The score, and the one mistake it exists to make impossible.

Fifty indicators on one price series are not fifty opinions. Adding them counts
one piece of information twenty times, and a score built that way sits at an
extreme whenever a family agrees with itself -- which is what a family is. The
project's own knowledge base says so twice, in chapter 12.6 and again in chapter
17, and those two sentences are the specification for this module.

Almost every test below is a different way of asking the same question: **can
this be fooled by repetition?** Through one family, through a restatement in
another family, through a stale finding repeated, through a family that is
actually split. The answer has to be no in every one of them, because the ways a
scoring model gets talked into a number are all forms of the same trick.

The rest guard the second rule: evidence for and against is never netted. A
subtraction is where counter-evidence goes to die, and chapter 17 requires it to
be carried.
"""

from __future__ import annotations

import pytest

from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe
from traidingbrain.score.engine import (
    DEFAULT_FAMILY_WEIGHTS,
    FRESHNESS_HALF_LIFE_BARS,
    MIN_AGREEMENT,
    REGIME_MODIFIERS,
    compute,
)
from traidingbrain.score.findings import (
    Evidence,
    Family,
    Finding,
    independence_weights,
    reconcile,
)


def finding(
    key: str,
    family: Family = Family.MOMENTUM,
    direction: Bias = Bias.BULLISH,
    strength: float = 0.8,
    **extra: object,
) -> Finding:
    return Finding(
        key=key,
        family=family,
        direction=direction,
        strength=strength,
        timeframe=Timeframe.H1,
        source="test",
        **extra,  # type: ignore[arg-type]
    )


def evidence_of(*findings: Finding) -> Evidence:
    bundle = Evidence()
    for item in findings:
        bundle.add(item)
    return bundle


# --------------------------------------------------------------------------- #
# The thing this module exists for
# --------------------------------------------------------------------------- #


def test_four_agreeing_oscillators_are_one_family_not_four_votes() -> None:
    """Chapter 12.6, quoted: "RSI, Stochastic, StochRSI und Williams %R sind
    alle Momentum-/Range-Lage-Werkzeuge; vier gleiche Richtungen sind nicht vier
    unabhängige Belege."

    The single assertion this whole file is built around.
    """
    four = evidence_of(*(finding(name) for name in ("rsi", "stoch", "stochrsi", "willr")))
    one = evidence_of(finding("rsi"))

    assert compute(four).bullish == pytest.approx(compute(one).bullish)


def test_adding_more_of_the_same_family_never_raises_the_score() -> None:
    """The property behind the test above, over a whole family.

    Not "stays equal" but "never rises": a fifth agreeing oscillator may drag
    the median or dilute freshness, and both of those are allowed to lower it.
    What must never happen is repetition buying strength.
    """
    scores = []
    members = []
    for index in range(1, 9):
        members.append(finding(f"osc_{index}"))
        scores.append(compute(evidence_of(*members)).bullish)

    assert scores == sorted(scores, reverse=True), scores


def test_two_different_families_do_count_twice() -> None:
    """The control. If independence never added anything, the safe way to pass
    every test above would be to ignore evidence entirely."""
    one = evidence_of(finding("rsi", Family.MOMENTUM))
    two = evidence_of(finding("rsi", Family.MOMENTUM), finding("bos", Family.STRUCTURE))

    assert compute(two).bullish > compute(one).bullish


def test_breadth_counts_families_not_findings() -> None:
    """Chapter 17's actual definition of confluence. One family at full
    strength is one family, however loud."""
    loud = evidence_of(*(finding(f"osc_{i}", strength=1.0) for i in range(6)))

    assert compute(loud).breadth == 1


# --------------------------------------------------------------------------- #
# Shared causes across families
# --------------------------------------------------------------------------- #


def test_a_finding_that_names_its_cause_counts_less() -> None:
    """Chapter 17: a fair value gap and the displacement candle that created it
    are one event seen twice. They live in different families, so family
    reconciliation alone cannot catch them -- `depends_on` has to."""
    independent = evidence_of(
        finding("displacement", Family.VOLATILITY),
        finding("fvg", Family.LOCATION),
    )
    declared = evidence_of(
        finding("displacement", Family.VOLATILITY),
        finding("fvg", Family.LOCATION, depends_on=("displacement",)),
    )

    assert compute(declared).bullish < compute(independent).bullish


def test_a_dependence_on_something_absent_is_ignored() -> None:
    """Detectors run independently, and switching one off must not silently
    change another's weight. A dangling reference is a detector that did not
    run, not a modelling error."""
    weights = independence_weights([finding("fvg", depends_on=("not_running",))])

    assert weights["fvg"] == pytest.approx(1.0)


def test_a_finding_cannot_depend_on_itself() -> None:
    with pytest.raises(ValueError, match="depends on itself"):
        finding("fvg", depends_on=("fvg",))


def test_two_findings_cannot_share_a_key() -> None:
    """Keys are what `depends_on` points at. Two findings with one key make a
    dependence ambiguous, and an ambiguous dependence is a silent miscount."""
    bundle = Evidence()
    bundle.add(finding("rsi"))

    with pytest.raises(ValueError, match="duplicate"):
        bundle.add(finding("rsi", Family.TREND))


# --------------------------------------------------------------------------- #
# Disagreement inside a family
# --------------------------------------------------------------------------- #


def test_a_family_pulling_both_ways_is_reported_as_split() -> None:
    """A split family is not a weak yes. It is a family that does not know, and
    reporting it as a small directional number would launder "unclear" into
    "slightly bullish"."""
    torn = evidence_of(
        finding("a", direction=Bias.BULLISH, strength=0.9),
        finding("b", direction=Bias.BEARISH, strength=0.9),
    )

    scored = compute(torn).families[0]

    assert scored.split is True
    assert scored.contribution == 0.0


def test_one_loud_dissenter_does_not_carry_its_family() -> None:
    """Reconciled on the median, not the mean.

    Three mild bulls and one violent bear is a mildly bullish family with poor
    agreement. A mean would let the loud one decide the direction, which is how
    one badly-parameterised indicator ends up steering a score.
    """
    verdict = reconcile(
        [
            finding("a", strength=0.3),
            finding("b", strength=0.3),
            finding("c", strength=0.3),
            finding("d", direction=Bias.BEARISH, strength=1.0),
        ]
    )[0]

    assert verdict.direction is Bias.BULLISH
    assert verdict.agreement < 1.0


def test_agreement_is_reported_rather_than_folded_in() -> None:
    """"The family is split" and "the family is weakly bullish" are different
    states, and one number cannot hold both."""
    united = reconcile([finding("a", strength=0.5), finding("b", strength=0.5)])[0]
    divided = reconcile([finding("a", strength=0.9), finding("b", strength=0.1)])[0]

    assert united.agreement > divided.agreement
    assert united.strength == pytest.approx(divided.strength), (
        "the two differ only in agreement; if their strengths differ too, "
        "this test is measuring something else"
    )


def test_the_split_threshold_is_the_configured_one() -> None:
    assert 0.0 < MIN_AGREEMENT < 1.0


# --------------------------------------------------------------------------- #
# Counter-evidence, which the difference would destroy
# --------------------------------------------------------------------------- #


def test_the_two_sides_are_reported_apart() -> None:
    """Chapter 17 requires counter-evidence to be carried explicitly.

    Two markets with the same lean and very different conflict are not the same
    trade, and only the pair of numbers tells them apart.
    """
    quiet = evidence_of(finding("bos", Family.STRUCTURE, strength=0.5))
    contested = evidence_of(
        finding("bos", Family.STRUCTURE, strength=1.0),
        finding("htf_resistance", Family.LOCATION, direction=Bias.BEARISH, strength=0.55),
    )

    a, b = compute(quiet), compute(contested)

    assert a.direction is b.direction
    assert b.conflict > a.conflict
    assert b.bearish > 0


def test_counter_evidence_is_listed_not_counted() -> None:
    """What argues against a trade is the part somebody has to read, so it is a
    list of findings rather than a number."""
    contested = evidence_of(
        finding("bos", Family.STRUCTURE, strength=0.9),
        finding("cvd", Family.VOLUME, direction=Bias.BEARISH, strength=0.6),
    )

    score = compute(contested)

    assert score.direction is Bias.BULLISH
    assert [f.key for f in score.counter_evidence] == ["cvd"]


def test_a_neutral_reading_contributes_nothing() -> None:
    """Taking no side is not a small lean. Letting a neutral finding tilt the
    score would turn the absence of an opinion into one."""
    assert finding("x", direction=Bias.NEUTRAL).signed_strength == 0.0

    score = compute(evidence_of(finding("x", direction=Bias.NEUTRAL)))

    assert score.bullish == 0.0
    assert score.bearish == 0.0


def test_which_families_never_spoke_is_reported() -> None:
    """A score built on two families is not the same claim as one built on
    eight, and the screen has to be able to say which were silent."""
    score = compute(evidence_of(finding("rsi", Family.MOMENTUM)))

    assert Family.MOMENTUM not in score.missing_families
    assert Family.STRUCTURE in score.missing_families


# --------------------------------------------------------------------------- #
# Regime, which is the largest situational effect
# --------------------------------------------------------------------------- #


def test_a_momentum_extreme_means_less_inside_a_trend() -> None:
    """Chapter 12.2: "overbought kann in starkem Trend lange bestehen."

    The sources are more insistent about this than about anything else in the
    weighting, so it is the one modifier with its own test.
    """
    momentum = evidence_of(finding("rsi", Family.MOMENTUM))

    in_range = compute(momentum, regime=RegimeKind.RANGE).bullish
    in_trend = compute(momentum, regime=RegimeKind.TREND_UP).bullish

    assert in_range > in_trend


def test_liquidity_counts_for_more_in_a_manipulation_regime() -> None:
    liquidity = evidence_of(finding("sweep", Family.LIQUIDITY))

    manipulated = compute(liquidity, regime=RegimeKind.MANIPULATION).bullish
    plain = compute(liquidity, regime=RegimeKind.UNKNOWN).bullish

    assert manipulated > plain


def test_an_unknown_regime_applies_no_modifier() -> None:
    """Warm-up is not a market state to weight against. Before the regime is
    readable the honest modifier is one."""
    assert RegimeKind.UNKNOWN not in REGIME_MODIFIERS


def test_every_family_has_a_weight() -> None:
    """A family without one silently contributes nothing, which looks exactly
    like a detector that never fired."""
    assert set(DEFAULT_FAMILY_WEIGHTS) == set(Family)
    for family, weight in DEFAULT_FAMILY_WEIGHTS.items():
        assert 0.0 < weight <= 1.0, family


def test_structure_outweighs_momentum_by_default() -> None:
    """Not arbitrary: every setup in the guide is built on structure, and
    chapter 12.2 spends its space on what momentum cannot tell you."""
    assert DEFAULT_FAMILY_WEIGHTS[Family.STRUCTURE] > DEFAULT_FAMILY_WEIGHTS[Family.MOMENTUM]


# --------------------------------------------------------------------------- #
# Age
# --------------------------------------------------------------------------- #


def test_an_older_finding_counts_less() -> None:
    fresh = evidence_of(finding("bos", Family.STRUCTURE, freshness_bars=0))
    stale = evidence_of(
        finding("bos", Family.STRUCTURE, freshness_bars=int(FRESHNESS_HALF_LIFE_BARS * 3))
    )

    assert compute(stale).bullish < compute(fresh).bullish / 2


def test_a_finding_with_no_age_is_not_decayed() -> None:
    """An indicator reading is about the current bar. Giving it an age and then
    decaying it would age a fact that has not aged -- which is why freshness is
    optional rather than defaulted to zero."""
    ageless = evidence_of(finding("rsi", Family.MOMENTUM))
    just_born = evidence_of(finding("rsi", Family.MOMENTUM, freshness_bars=0))

    assert compute(ageless).bullish == pytest.approx(compute(just_born).bullish)


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #


def test_nothing_measured_says_so() -> None:
    score = compute(Evidence())

    assert score.describe() == "nothing measured"
    assert score.direction is Bias.NEUTRAL
    assert score.conflict == 0.0


@pytest.mark.parametrize("strength", [-0.1, 1.1])
def test_a_strength_outside_the_scale_is_refused(strength: float) -> None:
    """The scale is 0 to 1 everywhere. A value outside it would silently
    outweigh every other finding rather than raising anything."""
    with pytest.raises(ValueError, match="outside"):
        finding("x", strength=strength)


def test_a_finding_without_a_key_is_refused() -> None:
    """Keys are what dependencies point at; an unnamed finding cannot be one."""
    with pytest.raises(ValueError, match="cannot be depended on"):
        finding("")


def test_the_description_names_both_sides_and_the_breadth() -> None:
    score = compute(
        evidence_of(
            finding("bos", Family.STRUCTURE),
            finding("cvd", Family.VOLUME, direction=Bias.BEARISH, strength=0.4),
        )
    )

    described = score.describe()

    assert "for" in described and "against" in described
    assert "families" in described and "conflict" in described
