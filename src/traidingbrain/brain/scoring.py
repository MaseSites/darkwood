"""Confidence, computed here rather than asked for.

The specification gives weights -- structure 30%, indicators 25%, liquidity 20%,
news 15%, history 10% -- and a confidence from 0 to 100. The obvious
implementation asks the model for the number. That is the wrong way round.

A model asked to output "78" will produce a plausible 78 whether or not anything
supports it. The number is fluent, not derived, and nothing downstream can tell
the difference. So the model is asked for something it is actually good at -- a
directional read on each factor, with a reason and its own certainty about that
read -- and the arithmetic happens here, where it can be inspected, tested, and
re-run with different weights without touching a prompt.

The mapping is deliberately plain. A weighted score of zero means the factors
cancel out, which is a 50, not a 0. Full agreement in the direction of the stated
bias is 100. Agreement pointing the *other* way is below 50, which is the right
answer for a verdict whose own evidence contradicts its conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass

from traidingbrain.config.settings import WeightsConfig
from traidingbrain.domain.enums import Bias, Factor
from traidingbrain.domain.snapshot import HistoryStats
from traidingbrain.domain.verdict import BrainVerdict

#: Midpoint of the confidence scale: the factors say nothing either way.
NEUTRAL_CONFIDENCE = 50.0


@dataclass(frozen=True)
class ScoreBreakdown:
    """How the confidence number was arrived at, factor by factor.

    Kept whole rather than reduced to a single float, because "why is the system
    74% confident" is the question anyone will ask first, and the answer should be
    readable rather than reconstructed.
    """

    confidence: float
    directional_score: float
    contributions: dict[Factor, float]
    weights_used: dict[Factor, float]
    missing_factors: list[Factor]
    capped_by_history: bool
    bias: Bias

    def explain(self) -> str:
        parts = [
            f"{factor.value}={value:+.2f}"
            for factor, value in sorted(self.contributions.items(), key=lambda kv: kv[0].value)
        ]
        line = f"confidence {self.confidence:.0f} from {', '.join(parts)}"
        if self.missing_factors:
            line += f"; not scored: {', '.join(f.value for f in self.missing_factors)}"
        if self.capped_by_history:
            line += "; capped because the history sample is too small to support more"
        return line


def score(verdict: BrainVerdict, weights: WeightsConfig, history: HistoryStats) -> ScoreBreakdown:
    """Turn factor scores into one confidence number.

    Factors the model did not score are dropped and the remaining weights
    renormalised, rather than counted as zero. Counting a missing factor as zero
    pulls the result toward the middle and quietly makes every incomplete answer
    look more uncertain than the evidence that *is* present warrants.
    """
    configured = weights.effective_weights()
    bias_sign = {Bias.BULLISH: 1.0, Bias.BEARISH: -1.0, Bias.NEUTRAL: 0.0}[verdict.bias]

    contributions: dict[Factor, float] = {}
    for factor in configured:
        reading = verdict.score_for(factor)
        if reading is None:
            continue
        value = reading.score
        if weights.confidence.scale_by_factor_confidence:
            # A strong signal the model is unsure about should count for less than
            # a weak one it is certain of.
            value *= reading.confidence
        contributions[factor] = value

    missing = [factor for factor in configured if factor not in contributions]
    if not contributions:
        return ScoreBreakdown(
            confidence=NEUTRAL_CONFIDENCE,
            directional_score=0.0,
            contributions={},
            weights_used={},
            missing_factors=missing,
            capped_by_history=False,
            bias=verdict.bias,
        )

    total_weight = sum(configured[factor] for factor in contributions)
    used = {factor: configured[factor] / total_weight for factor in contributions}
    directional = sum(used[factor] * value for factor, value in contributions.items())

    # Confidence is agreement *with the stated bias*. A verdict whose own factors
    # point the other way should land below the midpoint, and this does that
    # without a special case.
    aligned = directional * bias_sign
    confidence = NEUTRAL_CONFIDENCE + NEUTRAL_CONFIDENCE * aligned

    capped = False
    if not history.sample_is_sufficient and confidence > weights.confidence.cap_without_history:
        confidence = float(weights.confidence.cap_without_history)
        capped = True

    confidence = max(
        float(weights.confidence.floor), min(float(weights.confidence.ceiling), confidence)
    )

    return ScoreBreakdown(
        confidence=confidence,
        directional_score=directional,
        contributions=contributions,
        weights_used=used,
        missing_factors=missing,
        capped_by_history=capped,
        bias=verdict.bias,
    )
