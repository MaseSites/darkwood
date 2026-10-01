"""The score: two numbers, a direction, and the reasons -- never one number.

What this rejects, and why it matters more than what it computes:

**It does not return a single 0-100.** Evidence for and evidence against are
reported apart. A market where a strong bullish read is fighting a strong
bearish one, and a market where a mild bullish read meets silence, can produce
the same difference and are not the same trade. `TRADING_ANALYSE_GRUNDLAGEN.md`
chapter 17 requires counter-evidence to be carried explicitly, and a subtraction
is where it goes to die.

**It does not decide anything.** Sizing, leverage and the confirm button live
elsewhere and are unchanged. This describes a situation.

**Weights are configuration, not code.** Every one lives in `weights.yaml` with
the reason beside it, so changing one is a commit somebody can argue with rather
than a constant somebody nudged.

The arithmetic is deliberately simple: reconcile each family to one verdict,
discount findings that declare a shared cause, apply the family weight and the
situational modifiers, sum the two sides separately. Anything more elaborate
would claim a precision the sources do not have -- the inputs are readings from
videos and rules of thumb, and a covariance matrix over that is decoration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from traidingbrain.domain.enums import Bias, RegimeKind
from traidingbrain.score.findings import (
    Evidence,
    Family,
    FamilyVerdict,
    Finding,
    independence_weights,
)

#: How much each family may contribute before situational modifiers.
#:
#: Structure and location lead because every setup in the guide is built on
#: them; momentum trails because chapter 12.2 is explicit that an extreme can
#: persist through a whole trend. These are a starting point to be measured
#: against outcomes, not a finding -- which is why they are here with their
#: reason rather than buried in an expression.
#:
#: **A property anyone changing these has to know about.** The weight is not
#: the only asymmetry between families. A family of two emphatic structural
#: readings has a median near its members' strength; a family of seventy
#: indicator readings has a median near zero, because that is what seventy
#: measurements of a noisy thing do. Measured on real bars: structure reads
#: 0.75 where the trend family reads 0.02 from seventy indicators. So structure
#: dominates by roughly its weight *times* that gap, which is a good deal more
#: than 1.00 against 0.70 suggests.
#:
#: That is not obviously wrong -- the sources do put structure first, and a
#: family whose members disagree *should* be quiet. It is recorded because the
#: next person to tune these numbers will otherwise assume the weights are the
#: whole story, and because the question it raises is empirical: it wants
#: measuring against outcomes, not adjusting by argument.
DEFAULT_FAMILY_WEIGHTS: dict[Family, float] = {
    Family.STRUCTURE: 1.00,
    Family.LOCATION: 0.90,
    Family.LIQUIDITY: 0.80,
    Family.TREND: 0.70,
    Family.VOLUME: 0.60,
    Family.TIME_NEWS: 0.60,
    Family.POSITIONING: 0.50,
    Family.HISTORY: 0.50,
    Family.MOMENTUM: 0.40,
    Family.VOLATILITY: 0.30,
}

#: What a regime does to a family's weight.
#:
#: Chapter 12.2: "overbought kann in starkem Trend lange bestehen" -- so a
#: momentum extreme is worth a great deal inside a range and very little inside
#: a trend. This is the single largest situational effect in the model and the
#: one the sources are most insistent about.
REGIME_MODIFIERS: dict[RegimeKind, dict[Family, float]] = {
    RegimeKind.TREND_UP: {Family.MOMENTUM: 0.35, Family.TREND: 1.25},
    RegimeKind.TREND_DOWN: {Family.MOMENTUM: 0.35, Family.TREND: 1.25},
    RegimeKind.RANGE: {Family.MOMENTUM: 1.40, Family.LOCATION: 1.20, Family.TREND: 0.50},
    RegimeKind.MANIPULATION: {Family.LIQUIDITY: 1.30, Family.MOMENTUM: 0.60},
}

#: How much a finding keeps as it ages, per bar since it happened.
#:
#: Applied only to findings that carry a `freshness_bars`, which is the ones the
#: notion means something for. An indicator reading is about now and has no age;
#: giving it one would decay a fact that has not aged.
FRESHNESS_HALF_LIFE_BARS = 40.0

#: Below this, a family's members disagree enough that the family is reported
#: as split rather than as weakly directional.
MIN_AGREEMENT = 0.35


@dataclass(frozen=True)
class ScoredFamily:
    """One family's contribution, with everything that shaped it."""

    verdict: FamilyVerdict
    base_weight: float
    regime_modifier: float
    contribution: float
    """Signed. Positive argues up, negative argues down."""

    split: bool
    """True when the family's members disagreed too much to take a side."""


@dataclass
class Score:
    """The reading: two sides, kept apart.

    `bullish` and `bearish` are both non-negative. Their difference is available
    as `lean`, and it is deliberately not the headline: a caller that wants one
    number has to ask for it, which is a small piece of friction in the right
    place.
    """

    bullish: float = 0.0
    bearish: float = 0.0
    families: list[ScoredFamily] = field(default_factory=list)
    counter_evidence: list[Finding] = field(default_factory=list)
    missing_families: list[Family] = field(default_factory=list)

    @property
    def lean(self) -> float:
        return self.bullish - self.bearish

    @property
    def direction(self) -> Bias:
        if self.lean > 0:
            return Bias.BULLISH
        if self.lean < 0:
            return Bias.BEARISH
        return Bias.NEUTRAL

    @property
    def conflict(self) -> float:
        """How much of the evidence is arguing against the lean, 0 to 1.

        The number the difference hides. High conflict with a strong lean is a
        market two readings disagree about, and it is the state where a person
        most needs to look rather than act.
        """
        total = self.bullish + self.bearish
        if total <= 0:
            return 0.0
        weaker = min(self.bullish, self.bearish)
        return round(2.0 * weaker / total, 4)

    @property
    def breadth(self) -> int:
        """How many families took a side.

        Chapter 17's actual definition of confluence: different information
        families agreeing. One family at full strength is one family, however
        loud, and this is the number that says so.
        """
        return sum(1 for scored in self.families if not scored.split)

    def describe(self) -> str:
        if not self.families:
            return "nothing measured"
        return (
            f"{self.direction.value}: {self.bullish:.1f} for / {self.bearish:.1f} against, "
            f"{self.breadth} families, conflict {self.conflict:.0%}"
        )


def compute(
    evidence: Evidence,
    *,
    regime: RegimeKind = RegimeKind.UNKNOWN,
    weights: dict[Family, float] | None = None,
) -> Score:
    """Turn findings into a score.

    Order matters and each step is one of the guide's rules:

    1. Reconcile each family to one verdict -- chapter 12.6, four oscillators
       agreeing are not four proofs.
    2. Discount findings that declare a shared cause -- chapter 17, a gap and
       the candle that made it are one event.
    3. Decay findings that have an age.
    4. Apply the family weight and the regime modifier -- chapter 12.2, an
       extreme means something different inside a trend.
    5. Sum the two sides apart.
    """
    table = dict(weights or DEFAULT_FAMILY_WEIGHTS)
    modifiers = REGIME_MODIFIERS.get(regime, {})
    independence = independence_weights(evidence.findings)

    score = Score()
    for verdict in evidence.verdicts():
        base = table.get(verdict.family, 0.0)
        modifier = modifiers.get(verdict.family, 1.0)
        # Two kinds of split, and either one is enough to silence the family.
        # The second matters most where the first cannot see it: every
        # indicator on the weekly can agree perfectly, every indicator on the
        # hourly can agree perfectly, and the two frames can point opposite
        # ways. A median over frames picks one of them and would then report
        # full strength for a market the timeframes cannot agree about.
        split = (
            verdict.agreement < MIN_AGREEMENT
            or verdict.timeframe_agreement < MIN_AGREEMENT
            or verdict.direction is Bias.NEUTRAL
        )

        # The family's own members decide how much of its weight survives: a
        # finding that shares a cause with another, or that happened long
        # enough ago to have faded, brings less of it.
        members = [f for f in evidence.findings if f.key in verdict.members]
        keep = _surviving_share(members, independence)
        contribution = 0.0 if split else verdict.signed_strength * base * modifier * keep

        score.families.append(
            ScoredFamily(
                verdict=verdict,
                base_weight=base,
                regime_modifier=modifier,
                contribution=round(contribution, 4),
                split=split,
            )
        )
        if contribution > 0:
            score.bullish += contribution
        else:
            score.bearish += -contribution

    score.bullish = round(score.bullish, 4)
    score.bearish = round(score.bearish, 4)
    score.counter_evidence = evidence.counter_evidence(score.direction)
    score.missing_families = [
        family for family in Family if family not in evidence.families_present()
    ]
    return score


def _surviving_share(members: list[Finding], independence: dict[str, float]) -> float:
    """What fraction of a family's weight its members justify.

    The mean of each member's independence weight times its freshness decay. A
    family whose every member is fresh and independent keeps all of it; one
    built from three restatements of the same stale event keeps a fraction,
    which is the honest reading of what it knows.
    """
    if not members:
        return 0.0
    shares = [
        independence.get(member.key, 1.0) * _freshness_factor(member.freshness_bars)
        for member in members
    ]
    return sum(shares) / len(shares)


def _freshness_factor(bars: int | None) -> float:
    """How much of a finding survives its age.

    `None` means the notion does not apply and nothing is taken away. That
    distinction is the reason this is not a plain exponential: an RSI reading is
    about the current bar, and decaying it would age a fact that has not aged.
    """
    if bars is None or bars <= 0:
        return 1.0
    return float(0.5 ** (bars / FRESHNESS_HALF_LIFE_BARS))
