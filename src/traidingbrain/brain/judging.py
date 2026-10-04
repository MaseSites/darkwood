"""Describing a trade the rules proposed, without telling the model its price.

`BrainJudged` asks the model about a candidate the setups already found, which
means the candidate has to be described. That description is the one place in
the judging path where the no-lookahead guarantee could quietly fail.

**Why a price would break it.** The scanning prompt shows no symbol, no date and
no price on purpose: a model that could see "this asset at this price" would
recognise the period and part of its answer would come from knowing what
happened next. No test can separate that from genuine reading. A proposal
carries three prices -- entry, stop, target -- and passing any of them through
would reinstate exactly the leak the rest of the system is built to prevent.

So the proposal is expressed the way the snapshot already expresses everything
else: as ATR distances, plus the level ids the model was shown anyway. The
property that makes this checkable is **scale invariance** -- multiply the whole
market by ten and this description must not change by a single character. That
is the same shape of test as the future-mutation one, and for the same reason:
it turns "we were careful" into something that fails loudly when it stops being
true.

**Why the version string changes.** The decision cache is keyed on the snapshot
hash, the model, the prompt version and the schema version. Asking a *different
question* about the same market state would otherwise collide with the scanner's
answer and be served from cache -- the judge would read back an answer to a
question nobody asked it. `JUDGE_VERSION` keeps the two apart.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from traidingbrain.brain.client import AnthropicBrain
from traidingbrain.domain.enums import Side
from traidingbrain.domain.snapshot import BrainInput, MarketSnapshot
from traidingbrain.domain.verdict import BrainDecision
from traidingbrain.sim.plan import TradeIntent

#: The judging question's version, distinct from the scanner's.
#:
#: Not a suffix for tidiness: it is part of the cache key, and without it the
#: judge would be served the scanner's answer to a different question about the
#: same bar.
JUDGE_VERSION = "v4-judge"

#: Decimals kept in the description.
#:
#: Two. Enough for a model to tell a tight stop from a wide one, and coarse
#: enough that the quotient of two roundings cannot be worked back into a price.
PLACES = 2


class ProposalView(BaseModel):
    """A setup's candidate, scale-free.

    Every field is either a direction, a dimensionless ratio, a distance in ATR,
    or an id the model has already been shown. There is deliberately no field
    that could hold a price.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    setup: str = Field(description="Which rule proposed this, by name")
    side: Side
    entry_offset_atr: float = Field(
        description="Where the entry sits relative to the last close, in ATR. "
        "Negative means below it."
    )
    stop_distance_atr: float = Field(gt=0, description="Entry to stop, in ATR")
    target_distance_atr: float = Field(gt=0, description="Entry to target, in ATR")
    reward_risk: float = Field(gt=0, description="Target distance over stop distance")
    nearest_stop_level: str | None = Field(
        default=None, description="Level id closest to the stop, or null if none is near"
    )
    nearest_target_level: str | None = Field(
        default=None, description="Level id closest to the target, or null if none is near"
    )

    def canonical_json(self) -> str:
        return self.model_dump_json(exclude_none=False)


#: How close a level must be to a price to be worth naming, in ATR.
#:
#: Beyond this the id would be noise: the point of naming one is to tell the
#: model that the stop sits *at* something it can see, and a level two ATR away
#: is not what the stop is resting on.
NEAR_ATR = 0.5


def _nearest_level(snapshot: MarketSnapshot, price: float) -> str | None:
    best: tuple[float, str] | None = None
    for level in snapshot.levels:
        distance = abs(level.price - price) / snapshot.atr
        if distance <= NEAR_ATR and (best is None or distance < best[0]):
            best = (distance, level.id)
    return None if best is None else best[1]


def describe(snapshot: MarketSnapshot, intent: TradeIntent) -> ProposalView:
    """Turn a proposal into something safe to show a model.

    Distances are divided by ATR and the offset is measured from the last closed
    price, so nothing absolute survives. Rounding happens last, on the already
    scale-free numbers -- rounding the prices first would leak their magnitude
    through the rounding error.
    """
    atr = snapshot.atr
    stop_distance = abs(intent.entry - intent.stop) / atr
    target_distance = abs(intent.target - intent.entry) / atr
    return ProposalView(
        setup=intent.reason.split(":")[0].strip() or "unbenannt",
        side=intent.side,
        entry_offset_atr=round((intent.entry - snapshot.price) / atr, PLACES),
        stop_distance_atr=round(stop_distance, PLACES),
        target_distance_atr=round(target_distance, PLACES),
        reward_risk=round(target_distance / stop_distance, PLACES),
        nearest_stop_level=_nearest_level(snapshot, intent.stop),
        nearest_target_level=_nearest_level(snapshot, intent.target),
    )


QUESTION = """\
A rule in this system has proposed the trade below for the market state that \
follows it. The rule found the pattern; your job is only to say whether this \
instance of it is one to take.

Judge the proposal as it stands. Do not move the entry, the stop or the target: \
those come from the rule and are not yours to change. Answer VALID TRADE if you \
would take this one, and INVALID TRADE or WAIT if you would not -- and when you \
would not, say which reading of the market state argues against it.

Proposal:
"""


def user_content(snapshot: MarketSnapshot, intent: TradeIntent) -> str:
    """The judging request: the question, the proposal, then the market state.

    Canonical JSON on both halves, so two identical situations produce identical
    bytes and hit the same cache entry.
    """
    return (
        QUESTION
        + describe(snapshot, intent).canonical_json()
        + "\n\nMarket state:\n\n"
        + snapshot.to_brain_input().canonical_json()
    )


class JudgingBrain(AnthropicBrain):
    """The same brain, asked whether to take a trade rather than to find one.

    Only two things differ from the scanner, and they are overridden together
    on purpose: the question (`render_user`) and the version string it is
    cached under (`prompt_version`). Changing one without the other is the
    silent collision described at the top of this module, so they sit side by
    side where a reader cannot miss that both moved.

    Everything else -- the system prompt, the schema, the guard, the scoring,
    the budget, the cache -- is inherited rather than reimplemented, which is
    what makes a judging run comparable to a scanning one.
    """

    prompt_version: str = JUDGE_VERSION
    _pending: tuple[MarketSnapshot, TradeIntent] | None = None

    def judge(self, snapshot: MarketSnapshot, intent: TradeIntent) -> BrainDecision:
        """One judgement on one proposal.

        The proposal travels on the instance because `decide` is handed a market
        state and not a candidate. Set immediately before the call and read
        inside it: the backtest is single-threaded and the forward trader
        decides one symbol at a time, so there is no window in which a second
        proposal could be pending. `render_user` raises rather than falling back
        if that assumption is ever broken, because a judgement rendered without
        its proposal would be a scanning answer recorded as a judging one.
        """
        self._pending = (snapshot, intent)
        try:
            return self.decide(snapshot)
        finally:
            self._pending = None

    def render_user(self, payload: BrainInput) -> str:
        pending = self._pending
        if pending is None:
            raise RuntimeError(
                "JudgingBrain was asked without a proposal. Call judge(), not decide()."
            )
        snapshot, intent = pending
        return user_content(snapshot, intent)
