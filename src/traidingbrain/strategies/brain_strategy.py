"""The model as a strategy the backtest can run.

Thin by design. Everything that decides anything lives elsewhere -- the gate in
`brain.trigger`, the judgement in the model, the confidence arithmetic in
`brain.scoring`, the sanity checks in `brain.guard`, and the sizing in `risk`.
This module only translates between them.

That thinness is the point. When the comparison against the baseline comes out one
way or the other, the answer should be attributable to a specific layer, not to
glue code that quietly did something clever.
"""

from __future__ import annotations

from typing import Protocol

from traidingbrain.brain.trigger import Trigger, TriggerStats
from traidingbrain.config.settings import TriggerConfig
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.domain.verdict import BrainDecision
from traidingbrain.sim.engine import TradeIntent


class BrainLike(Protocol):
    def decide(
        self, snapshot: MarketSnapshot, brain_input: object | None = None
    ) -> BrainDecision: ...


class BrainStrategy:
    """Runs the gate, asks the brain, and converts an accepted plan into an intent."""

    def __init__(
        self,
        brain: BrainLike,
        trigger_config: TriggerConfig,
        *,
        name: str = "brain",
    ) -> None:
        self.brain = brain
        self.trigger = Trigger(trigger_config)
        self.name = name
        self.asked = 0
        self.tradeable = 0
        self.declined = 0
        self._bar = 0
        self.decisions: list[BrainDecision] = []

    def propose(self, snapshot: MarketSnapshot) -> TradeIntent | None:
        self._bar += 1
        if not self.trigger.should_ask(snapshot, self._bar):
            return None

        self.asked += 1
        decision = self.brain.decide(snapshot)
        self.decisions.append(decision)

        if not decision.is_tradeable or decision.plan is None:
            self.declined += 1
            return None

        self.tradeable += 1
        plan = decision.plan
        return TradeIntent(
            side=plan.side,
            entry=plan.entry,
            stop=plan.stop,
            target=plan.target,
            confidence=decision.confidence,
            reason="; ".join(decision.verdict.reasoning[:3]),
        )

    @property
    def stats(self) -> TriggerStats:
        return self.trigger.stats

    def summary(self) -> str:
        cached = sum(1 for d in self.decisions if d.from_cache)
        rejected = sum(1 for d in self.decisions if not d.guard.passed)
        return (
            f"  gate            {self.stats.summary()}\n"
            f"  asked           {self.asked:,} ({cached:,} served from cache)\n"
            f"  tradeable       {self.tradeable:,}\n"
            f"  declined        {self.declined:,} ({rejected:,} rejected by the guard)"
        )

    def guard_violations(self) -> dict[str, int]:
        """What the guard actually caught, counted.

        A rising rejection rate is a prompt problem, not a guard problem, and this
        is the number that says which check is firing.
        """
        counts: dict[str, int] = {}
        for decision in self.decisions:
            for violation in decision.guard.violations:
                # Strip the numbers so variants of the same complaint group.
                key = violation.split(",")[0].split(" is ")[0]
                counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
