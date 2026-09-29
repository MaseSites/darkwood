"""What the brain returns, and what the system makes of it.

Three types, in the order they come into existence:

`BrainVerdict` is the raw structured output of the model. It contains no prices
and no confidence number. It anchors every level to a level id plus an ATR offset,
and it scores each of the five factors in [-1, +1] with a reason.

`BrainDecision` is the verdict after Python has done its part: resolved the anchors
to real prices, computed the weighted confidence from the factor scores, and run
the guard. Confidence is arithmetic on scores the model gave, not a number the
model produced -- a model asked to output "78" will produce a plausible 78 whether
or not anything supports it.

`PostTradeReview` is the retrospective on a closed trade.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from traidingbrain.domain.enums import Bias, Decision, Factor, RiskLevel, Side

#: Every field in the structured-output models below is required and no extra keys
#: are allowed. Both are needed for the API to accept the schema, and both are
#: what make a malformed answer a hard failure instead of a silent default.
STRICT = ConfigDict(extra="forbid", frozen=True)


class FactorScore(BaseModel):
    """One of the five weighted inputs, scored by the model.

    The score is directional: positive favours the bullish case, negative the
    bearish one, zero means the factor says nothing here. `confidence` is how much
    the model trusts its own read of this factor -- a strong signal it is unsure
    about and a weak signal it is certain of are different things.
    """

    model_config = STRICT

    factor: Factor
    score: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=500)


class Anchor(BaseModel):
    """A price expressed as `level id + offset in ATR`.

    The model never writes a number that means money. It picks a level it was
    shown and nudges it. Python turns that into a price, so a hallucinated price
    is not something the guard has to catch -- it is something the model has no
    way to express.
    """

    model_config = STRICT

    level_id: str = Field(pattern=r"^lvl_\d+$")
    offset_atr: float = Field(ge=-10.0, le=10.0)


class ScenarioSpec(BaseModel):
    """One directional plan: where to get in, where to be wrong, where to take profit."""

    model_config = STRICT

    side: Side
    entry: Anchor
    stop: Anchor
    target: Anchor
    rationale: str = Field(min_length=1, max_length=500)


class Scenarios(BaseModel):
    """The three views the specification requires, always all three.

    Even when the model is bullish it must state the bearish case and what would
    invalidate its own read. A plan that cannot say how it would be wrong is not a
    plan.
    """

    model_config = STRICT

    bullish: ScenarioSpec
    bearish: ScenarioSpec
    invalidation: Anchor
    invalidation_note: str = Field(min_length=1, max_length=300)


class BrainVerdict(BaseModel):
    """Raw model output. No prices, no confidence number -- both are Python's job."""

    model_config = STRICT

    schema_version: int = Field(ge=1, le=1)
    bias: Bias
    decision: Decision
    risk: RiskLevel
    factor_scores: list[FactorScore] = Field(min_length=1, max_length=5)
    scenarios: Scenarios
    reasoning: list[str] = Field(min_length=1, max_length=8)
    market_commentary: str = Field(min_length=1, max_length=1000)

    def score_for(self, factor: Factor) -> FactorScore | None:
        return next((f for f in self.factor_scores if f.factor is factor), None)

    @property
    def active_scenario(self) -> ScenarioSpec | None:
        """The scenario the verdict actually argues for, if any."""
        if self.decision is not Decision.VALID_TRADE:
            return None
        if self.bias is Bias.BULLISH:
            return self.scenarios.bullish
        if self.bias is Bias.BEARISH:
            return self.scenarios.bearish
        return None


class ResolvedPlan(BaseModel):
    """A scenario after its anchors have been turned back into prices."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    side: Side
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)

    @property
    def stop_distance(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def target_distance(self) -> float:
        return abs(self.target - self.entry)

    @property
    def reward_risk(self) -> float:
        """R:R, computed here in Python and never taken from the model."""
        if self.stop_distance == 0:
            return 0.0
        return self.target_distance / self.stop_distance


class GuardVerdict(BaseModel):
    """The result of validating a model answer against reality.

    A rejected verdict is not an error to retry -- it is a NO TRADE with a logged
    reason. The rejection rate is a metric worth watching: a prompt whose answers
    keep failing the guard is a prompt that needs fixing, not a guard that needs
    loosening.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    violations: list[str] = Field(default_factory=list)


class BrainDecision(BaseModel):
    """The verdict after Python resolved, scored and checked it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_hash: str
    model_id: str
    prompt_version: str
    verdict: BrainVerdict
    confidence: float = Field(ge=0.0, le=100.0, description="Weighted sum of factor scores")
    plan: ResolvedPlan | None
    guard: GuardVerdict
    request_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    from_cache: bool = False

    @property
    def is_tradeable(self) -> bool:
        return (
            self.guard.passed
            and self.plan is not None
            and self.verdict.decision is Decision.VALID_TRADE
        )


class PostTradeReview(BaseModel):
    """Retrospective on a closed trade.

    `system_update_suggestion` is advisory only. It goes into a review queue and is
    never applied automatically -- a system that rewrites its own trading logic is
    exactly what the confirm-before-execute rule exists to prevent.
    """

    model_config = STRICT

    schema_version: int = Field(ge=1, le=1)
    trade_evaluation: str = Field(min_length=1, max_length=300)
    main_reason: str = Field(min_length=1, max_length=500)
    failing_factor: Factor | None
    timing_was_wrong: bool
    regime_was_misread: bool
    lesson: str = Field(min_length=1, max_length=500)
    system_update_suggestion: str = Field(min_length=1, max_length=500)
