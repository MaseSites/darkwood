"""Ask the model about a trade the rules already found.

Measured 04.10.2026: the guide's entries have a gross expectancy of -0.0102 R
[-0.070, +0.051], indistinguishable from zero, and the whole net loss is the
toll. Four levers were measured that day and all four failed, because three of
them only moved the toll or the trade count -- and a cheaper toll on an entry
with no edge walks the result toward zero and stops there. The one that did
touch the entries, the liquidity-lean filter, made them worse.

So the remaining question is whether judgement helps where a rule does not, and
`BrainStrategy` answers a different one. It runs the model as a **scanner**: the
gate watches every bar, 19% of them pass, and the model has to find the trade
itself. On BTC alone that is 26,100 calls -- $338 on the Batch API, or fourteen
hours through a subscription.

This runs it as a **judge** instead. Severin's rules already find candidates;
the model is asked only where one has fired, which on BTC is 2,855 calls over
four years -- an eighth of the scanner, and about an hour and a half through a
subscription at no per-call cost.

**The division of labour is the point, not the saving.** The setup owns the
levels: entry, stop and target stay exactly where the rule put them, because
those are Severin's rules and the measurement that motivated this says nothing
against them -- it says the *selection* carries no information. The model owns
only the selection: whether this instance of a known pattern is one to take.
Keeping the model's own levels instead would make the comparison against the
unfiltered pool a comparison between two systems rather than a measurement of
what judgement adds.

**It can only subtract.** Like every filter here, it never proposes a trade the
rules did not. A wrapper that also added trades would be a second strategy
wearing a filter's name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.domain.enums import Side
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.domain.verdict import BrainDecision
from traidingbrain.sim.plan import TradeIntent
from traidingbrain.strategies.guide import GuidePool


class BrainLike(Protocol):
    """What this needs from a brain. Satisfied by all three of them."""

    def decide(
        self, snapshot: MarketSnapshot, brain_input: object | None = None
    ) -> BrainDecision: ...


@dataclass
class Tally:
    """Why each proposal survived or did not, so a run can be read afterwards."""

    proposed: int = 0
    no_snapshot: int = 0
    vetoed: int = 0
    wrong_side: int = 0
    kept: int = 0

    def sentence(self) -> str:
        if not self.proposed:
            return "kein Setup hat ausgelöst"
        parts = [f"{self.proposed} vorgeschlagen", f"{self.kept} behalten"]
        if self.vetoed:
            parts.append(f"{self.vetoed} abgelehnt")
        if self.wrong_side:
            parts.append(f"{self.wrong_side} Gegenrichtung")
        if self.no_snapshot:
            parts.append(f"{self.no_snapshot} ohne Snapshot")
        return ", ".join(parts)


@dataclass
class BrainJudged:
    """A pool whose proposals the model may veto, but never replace."""

    inner: GuidePool
    brain: BrainLike
    builder: SnapshotBuilder
    name: str = "guide-judged"
    #: Keep the model's confidence for sizing, or keep the setup's.
    #:
    #: Off by default. The risk ladder above 1% is locked until the history
    #: engine shows that high confidence really does do better, and a model's
    #: self-reported number is not evidence about itself -- so letting it size
    #: the position would change two things at once and attribute both to
    #: judgement.
    use_model_confidence: bool = False
    tally: Tally = field(default_factory=Tally)
    decisions: list[BrainDecision] = field(default_factory=list)

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
        intent = self.inner.propose_at(analysis, index)
        if intent is None:
            return None
        self.tally.proposed += 1

        snapshot = self.builder.build(index)
        if snapshot is None:
            # Warm-up, or a frame that cannot be described yet. Letting the
            # trade through unjudged keeps this a filter rather than a second
            # gate: the comparison is about what the model adds, and refusing
            # what it was never shown would credit it with those refusals.
            self.tally.no_snapshot += 1
            return intent

        decision = self.brain.decide(snapshot)
        self.decisions.append(decision)

        if not decision.is_tradeable:
            self.tally.vetoed += 1
            return None

        # A model that wants the other direction is disagreeing with the setup,
        # not confirming it. Taking the trade anyway would record a veto as an
        # endorsement.
        if decision.plan is not None and decision.plan.side is not intent.side:
            self.tally.wrong_side += 1
            return None

        self.tally.kept += 1
        if not self.use_model_confidence:
            return intent
        return TradeIntent(
            side=intent.side,
            entry=intent.entry,
            stop=intent.stop,
            target=intent.target,
            confidence=decision.confidence,
            reason=intent.reason,
        )

    def summary(self) -> str:
        cached = sum(1 for d in self.decisions if d.from_cache)
        vetoes = self.tally.vetoed + self.tally.wrong_side
        share = 100 * vetoes / self.tally.proposed if self.tally.proposed else 0.0
        return (
            f"  gefragt         {len(self.decisions):,} ({cached:,} aus dem Cache)\n"
            f"  abgelehnt       {vetoes:,} von {self.tally.proposed:,} ({share:.0f}%)\n"
            f"  {self.tally.sentence()}"
        )


def judged(
    pool: GuidePool,
    brain: BrainLike,
    symbol: str,
    analysis: MultiFrameAnalysis,
    config: object,
) -> BrainJudged:
    """Wire a pool, a brain and the snapshot builder they share."""
    return BrainJudged(
        inner=pool,
        brain=brain,
        builder=SnapshotBuilder(symbol, analysis, config),  # type: ignore[arg-type]
    )


__all__ = ["BrainJudged", "BrainLike", "Side", "Tally", "judged"]
