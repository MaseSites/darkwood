"""The model as a judge over the rules' proposals.

The wrapper is small; what it must not do is large. Each test below is one way
the judge could quietly stop measuring what it claims to:

* **Replacing the setup's levels.** The division of labour is the whole design:
  the rule owns entry, stop and target, the model owns only whether to take
  this instance. A judge that handed back the model's own plan would turn the
  comparison against the unfiltered pool into a comparison between two
  systems.
* **Counting a disagreement as an endorsement.** A model that wants the other
  direction is contradicting the setup. Taking the trade anyway records a veto
  as a confirmation.
* **Taking credit for refusals it never made.** During warm-up there is no
  snapshot and so no judgement. Refusing those would credit the model with
  removing trades it was never shown.
* **Adding trades.** Every filter here can only subtract.
* **Sizing on self-reported confidence.** A model's own number is not evidence
  about itself, and the risk ladder above 1% stays locked until the history
  engine says otherwise -- so this is off unless a test turns it on.
"""

from __future__ import annotations

import pytest

from traidingbrain.domain.enums import Decision, Side
from traidingbrain.domain.verdict import BrainDecision, GuardVerdict
from traidingbrain.sim.plan import TradeIntent
from traidingbrain.strategies.brain_judge import BrainJudged, Tally


class OnePool:
    """Proposes exactly what the test hands it, so the judge is what is tested."""

    name = "one"

    def __init__(self, intent: TradeIntent | None) -> None:
        self.intent = intent

    def propose_at(self, analysis: object, index: int) -> TradeIntent | None:
        return self.intent


class StubBuilder:
    """A snapshot builder that either has one or does not."""

    def __init__(self, *, has_snapshot: bool = True) -> None:
        self.has_snapshot = has_snapshot

    def build(self, index: int) -> object | None:
        return object() if self.has_snapshot else None


class Verdictish:
    def __init__(self, decision: Decision) -> None:
        self.decision = decision
        self.reasoning = ["weil"]


class Planish:
    def __init__(self, side: Side) -> None:
        self.side = side
        self.entry, self.stop, self.target = 200.0, 190.0, 230.0


class StubBrain:
    """Answers however the test needs, and records that it was asked."""

    def __init__(
        self,
        *,
        tradeable: bool,
        side: Side = Side.LONG,
        confidence: float = 85.0,
        plan: bool = True,
    ) -> None:
        self.tradeable = tradeable
        self.side = side
        self.confidence = confidence
        self.plan_wanted = plan
        self.asked = 0

    def decide(self, snapshot: object, brain_input: object | None = None) -> object:
        self.asked += 1
        return StubDecision(
            tradeable=self.tradeable,
            side=self.side,
            confidence=self.confidence,
            plan=self.plan_wanted,
        )


class StubDecision:
    def __init__(self, *, tradeable: bool, side: Side, confidence: float, plan: bool) -> None:
        self._tradeable = tradeable
        self.plan = Planish(side) if plan else None
        self.confidence = confidence
        self.verdict = Verdictish(Decision.VALID_TRADE if tradeable else Decision.INVALID_TRADE)
        self.guard = GuardVerdict(passed=True, violations=[])
        self.from_cache = False

    @property
    def is_tradeable(self) -> bool:
        return self._tradeable


def long_intent() -> TradeIntent:
    return TradeIntent(
        side=Side.LONG, entry=100.0, stop=98.0, target=106.0, confidence=60.0, reason="A: Zone"
    )


def judge(
    intent: TradeIntent | None,
    brain: StubBrain,
    *,
    has_snapshot: bool = True,
    use_model_confidence: bool = False,
) -> BrainJudged:
    return BrainJudged(
        inner=OnePool(intent),  # type: ignore[arg-type]
        brain=brain,  # type: ignore[arg-type]
        builder=StubBuilder(has_snapshot=has_snapshot),  # type: ignore[arg-type]
        use_model_confidence=use_model_confidence,
    )


# --------------------------------------------------------------------------- #
# The division of labour
# --------------------------------------------------------------------------- #


def test_the_setups_levels_survive_an_approval() -> None:
    """The rule owns entry, stop and target; the model owns only the yes.

    The stub model wants 200/190/230, which is nothing like the setup's
    100/98/106. If any of its numbers come through, this has stopped being a
    measurement of judgement and become one of a different system.
    """
    original = long_intent()
    out = judge(original, StubBrain(tradeable=True, side=Side.LONG)).propose_at(object(), 0)

    assert out is not None
    assert (out.entry, out.stop, out.target) == (100.0, 98.0, 106.0)
    assert out.reason == "A: Zone"


def test_a_veto_removes_the_trade() -> None:
    rule = judge(long_intent(), StubBrain(tradeable=False))

    assert rule.propose_at(object(), 0) is None
    assert rule.tally.vetoed == 1
    assert rule.tally.kept == 0


def test_a_model_wanting_the_other_direction_is_a_veto() -> None:
    """Disagreement is not confirmation.

    The model is tradeable but wants short where the setup wants long. Letting
    that through would record a contradiction as an endorsement -- and the
    trade taken would be one neither of them asked for.
    """
    rule = judge(long_intent(), StubBrain(tradeable=True, side=Side.SHORT))

    assert rule.propose_at(object(), 0) is None
    assert rule.tally.wrong_side == 1
    assert rule.tally.vetoed == 0, "a direction clash is its own category, not a plain veto"


def test_it_never_proposes_a_trade_the_rules_did_not() -> None:
    """Every filter here can only subtract."""
    brain = StubBrain(tradeable=True)
    rule = judge(None, brain)

    assert rule.propose_at(object(), 0) is None
    assert brain.asked == 0, "the model was asked about a trade that does not exist"
    assert rule.tally.proposed == 0


# --------------------------------------------------------------------------- #
# What it does not take credit for
# --------------------------------------------------------------------------- #


def test_a_proposal_with_no_snapshot_passes_unjudged() -> None:
    """Warm-up, or a frame that cannot be described yet.

    Refusing these would credit the model with removing trades it was never
    shown, which is the most flattering possible way to report a filter.
    """
    brain = StubBrain(tradeable=False)
    rule = judge(long_intent(), brain, has_snapshot=False)

    out = rule.propose_at(object(), 0)

    assert out is not None
    assert brain.asked == 0
    assert rule.tally.no_snapshot == 1
    assert rule.tally.vetoed == 0


def test_the_model_is_asked_once_per_proposal_and_only_then() -> None:
    """The cost argument depends on this exactly.

    Running the model as a scanner is 26,100 calls on BTC; as a judge it is
    2,855, because only a fired setup is worth a question. An extra call per
    bar would quietly restore the scanner's bill.
    """
    brain = StubBrain(tradeable=True)
    rule = judge(long_intent(), brain)

    for index in range(5):
        rule.propose_at(object(), index)

    assert brain.asked == 5
    assert rule.tally.proposed == 5


# --------------------------------------------------------------------------- #
# Sizing
# --------------------------------------------------------------------------- #


def test_the_setups_confidence_is_kept_by_default() -> None:
    """A model's self-reported confidence is not evidence about itself.

    The sizing ladder above 1% stays locked until the history engine shows that
    high confidence really does do better. Letting the model size the position
    would change two things at once and attribute both to judgement.
    """
    out = judge(long_intent(), StubBrain(tradeable=True, confidence=95.0)).propose_at(object(), 0)

    assert out is not None
    assert out.confidence == 60.0


def test_the_model_confidence_is_used_only_when_asked_for() -> None:
    out = judge(
        long_intent(), StubBrain(tradeable=True, confidence=95.0), use_model_confidence=True
    ).propose_at(object(), 0)

    assert out is not None
    assert out.confidence == 95.0
    assert (out.entry, out.stop, out.target) == (100.0, 98.0, 106.0), "levels still the rule's"


# --------------------------------------------------------------------------- #
# Reading a run afterwards
# --------------------------------------------------------------------------- #


def test_the_tally_says_what_happened() -> None:
    tally = Tally(proposed=10, kept=6, vetoed=3, wrong_side=1)
    text = tally.sentence()

    assert "10 vorgeschlagen" in text
    assert "6 behalten" in text
    assert "3 abgelehnt" in text


def test_a_run_with_no_setups_says_so_rather_than_nothing() -> None:
    assert Tally().sentence() == "kein Setup hat ausgelöst"


def test_the_summary_reports_the_veto_share() -> None:
    """The number that says whether the model is doing anything at all.

    A judge that vetoes nothing is an expensive no-op; one that vetoes almost
    everything has a prompt problem rather than an opinion.
    """
    rule = judge(long_intent(), StubBrain(tradeable=False))
    for index in range(4):
        rule.propose_at(object(), index)

    assert "4 von 4 (100%)" in rule.summary()


@pytest.mark.parametrize("decision", [Decision.VALID_TRADE, Decision.INVALID_TRADE])
def test_every_judgement_is_kept_for_later_reading(decision: Decision) -> None:
    """A run's decisions are the record of why it traded what it traded.

    Keeping only the approvals would leave a journal that cannot explain an
    absence, and most of what a filter does is absences.
    """
    rule = judge(long_intent(), StubBrain(tradeable=decision is Decision.VALID_TRADE))
    rule.propose_at(object(), 0)

    assert len(rule.decisions) == 1


def test_the_decision_type_this_wrapper_expects_still_looks_like_this() -> None:
    """A guard on the stubs above.

    The tests run against stand-ins, so a change to BrainDecision -- a renamed
    `is_tradeable`, a `plan` that stopped carrying a side -- would leave them
    green while the real thing broke. This asserts the shape they imitate.
    """
    fields = BrainDecision.model_fields

    assert "plan" in fields
    assert "confidence" in fields
    assert "guard" in fields
    assert hasattr(BrainDecision, "is_tradeable")
