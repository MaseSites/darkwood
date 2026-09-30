"""What the analysis found, in a shape that cannot count the same thing twice.

The problem this exists to solve, in the words of the project's own knowledge
base (`TRADING_ANALYSE_GRUNDLAGEN.md`, chapter 12.6):

    "RSI, Stochastic, StochRSI und Williams %R sind alle Momentum-/Range-Lage-
    Werkzeuge; vier gleiche Richtungen sind nicht vier unabhängige Belege."

and chapter 17:

    "Konfluenz bedeutet mehrere verschiedene Informationsfamilien stimmen in
    einer Hypothese überein... Drei Momentumindikatoren sind eine Familie."

Fifty indicators on one price series are not fifty opinions. Adding them means
counting one piece of information twenty times, and a score built that way pins
itself at an extreme whenever a single family agrees with itself -- which is
most of the time, because that is what a family is.

So a `Finding` is not a vote. It carries the family it belongs to, and it
carries `depends_on` for the cases where two findings in *different* families
still are not independent: chapter 17 names the fair value gap and the
displacement candle that created it, which live in different families and are
the same event seen twice.

**Evidence for and against are kept apart and never netted.** A score of 70 from
"80 for, 10 against" describes a different market than the same 70 from "85 for,
15 against", and reporting only the difference destroys exactly the part a
person needs in order to disagree with it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import StrEnum

from traidingbrain.domain.enums import Bias, Timeframe


class Family(StrEnum):
    """The information families from chapter 17, and nothing outside them.

    Membership is the unit of independence. Two findings in one family are one
    piece of evidence measured twice; two findings in different families are
    two, unless `depends_on` says otherwise.

    An enum rather than a string so a new detector cannot invent a family by
    typo and quietly earn itself a second vote.
    """

    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    STRUCTURE = "structure"
    LOCATION = "location"
    LIQUIDITY = "liquidity"
    TIME_NEWS = "time_news"
    POSITIONING = "positioning"
    HISTORY = "history"


@dataclass(frozen=True)
class Finding:
    """One thing the analysis noticed, with everything needed to weigh it.

    The fields are chapter 17's required list. They are not optional metadata:
    every one of them changes how much the finding counts, and a finding that
    cannot say which timeframe it is from or how fresh it is cannot be weighed
    against one that can.
    """

    key: str
    """Stable identifier, e.g. `rsi_h1` or `fvg_bullish_h4`. Used for
    `depends_on`, so it has to survive a rename of the label."""

    family: Family
    direction: Bias
    strength: float
    """How emphatic, 0 to 1. Not how likely -- nothing here is a probability."""

    timeframe: Timeframe
    source: str
    """Where the rule came from: a video id, a chapter, or `measured`."""

    label: str = ""
    """What a person reads. Free text; never used for logic."""

    freshness_bars: int | None = None
    """Bars since the thing happened. None when the notion does not apply --
    an indicator reading is about now and has no age."""

    distance_atr: float | None = None
    """How far the price is from it, in ATR. None for findings without a place."""

    depends_on: tuple[str, ...] = ()
    """Keys of findings this one is not independent of.

    Chapter 17's example: a fair value gap and the displacement candle that
    created it. They sit in different families -- location and volatility -- and
    counting both at full weight would report one event as two."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"{self.key}: strength {self.strength} is outside 0..1")
        if not self.key:
            raise ValueError("a finding without a key cannot be depended on")
        if self.key in self.depends_on:
            raise ValueError(f"{self.key} depends on itself")

    @property
    def signed_strength(self) -> float:
        """Strength with the direction's sign; zero for a neutral finding.

        Neutral is deliberately zero rather than a small number. A reading that
        takes no side contributes no evidence, and letting it lean would turn
        the absence of an opinion into one.
        """
        if self.direction is Bias.BULLISH:
            return self.strength
        if self.direction is Bias.BEARISH:
            return -self.strength
        return 0.0


@dataclass(frozen=True)
class FamilyVerdict:
    """What one family says, after its members have been reconciled.

    A family speaks once. Which is the whole point: the four momentum
    oscillators that agree produce one verdict with high `agreement`, not four
    findings with four votes.
    """

    family: Family
    direction: Bias
    strength: float
    agreement: float
    """How much its members agreed, 0 to 1. Low agreement is information: it
    says the family is split, which is an honest answer and not a weak yes."""

    members: tuple[str, ...]

    @property
    def signed_strength(self) -> float:
        if self.direction is Bias.BULLISH:
            return self.strength
        if self.direction is Bias.BEARISH:
            return -self.strength
        return 0.0


def reconcile(findings: list[Finding]) -> list[FamilyVerdict]:
    """Collapse each family to a single verdict.

    Within a family the answer is the **median** signed strength, not the mean
    and not the majority. The median is what stops one extreme member from
    carrying a family: three oscillators reading mildly bullish and one reading
    violently bearish is a mildly bullish family with poor agreement, which is
    the truthful description. A mean would let the loud one decide.

    Agreement is one minus the mean absolute deviation from that median, scaled
    so that a family pulling in opposite directions lands near zero. It is
    reported rather than folded in, because "the family is split" and "the
    family is weakly bullish" are different states that a single number cannot
    hold.
    """
    verdicts: list[FamilyVerdict] = []
    for family in Family:
        members = [finding for finding in findings if finding.family is family]
        if not members:
            continue
        signed = [finding.signed_strength for finding in members]
        centre = statistics.median(signed)
        spread = (
            statistics.mean(abs(value - centre) for value in signed) if len(signed) > 1 else 0.0
        )
        verdicts.append(
            FamilyVerdict(
                family=family,
                direction=_direction_of(centre),
                strength=abs(centre),
                # Two members a full unit apart is total disagreement, which is
                # the widest the signed scale allows on either side of a median.
                agreement=round(max(0.0, 1.0 - spread), 4),
                members=tuple(finding.key for finding in members),
            )
        )
    return verdicts


def _direction_of(signed: float) -> Bias:
    if signed > 0:
        return Bias.BULLISH
    if signed < 0:
        return Bias.BEARISH
    return Bias.NEUTRAL


def independence_weights(findings: list[Finding]) -> dict[str, float]:
    """How much each finding may count, after shared causes are discounted.

    A finding that depends on others is not extra evidence for what they already
    said. Its weight is divided by one plus the number of findings it declares a
    dependence on, so a fair value gap that names the displacement candle it came
    from counts half -- and the pair together count as one and a half rather than
    two.

    Deliberately blunt. There is no covariance matrix here and there should not
    be: the dependencies are the ones a person wrote down because a source said
    they exist, and a number derived from data would claim a precision the
    sources do not have.

    A dependence on a key that is not present is ignored rather than an error.
    Detectors run independently, and one being switched off must not make
    another's weight wrong.
    """
    present = {finding.key for finding in findings}
    weights: dict[str, float] = {}
    for finding in findings:
        live = [key for key in finding.depends_on if key in present]
        weights[finding.key] = 1.0 / (1.0 + len(live))
    return weights


@dataclass
class Evidence:
    """Everything found at one moment, for and against, never netted.

    `for_` and `against` are separate because the difference between them
    destroys the thing a person needs most. Two markets both scoring 70 -- one
    quiet and one where a strong bullish read is fighting a strong bearish one --
    are not the same trade, and only the two numbers tell them apart.
    """

    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        if any(existing.key == finding.key for existing in self.findings):
            raise ValueError(f"duplicate finding key {finding.key!r}")
        self.findings.append(finding)

    def verdicts(self) -> list[FamilyVerdict]:
        return reconcile(self.findings)

    def supporting(self, direction: Bias) -> list[Finding]:
        return [f for f in self.findings if f.direction is direction]

    def counter_evidence(self, direction: Bias) -> list[Finding]:
        """Findings arguing the other way.

        Chapter 17 asks for this explicitly and by name: higher-timeframe
        resistance against a lower-timeframe break, negative CVD against a
        rising price, news in five minutes against a quiet technical picture.
        Kept as a list rather than a number because what argues against a trade
        is the part somebody has to read.
        """
        if direction is Bias.NEUTRAL:
            return []
        other = Bias.BEARISH if direction is Bias.BULLISH else Bias.BULLISH
        return self.supporting(other)

    def families_present(self) -> set[Family]:
        return {finding.family for finding in self.findings}
