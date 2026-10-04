"""Prefer a target that gets hit over one that pays more.

Measured 04.10.2026 over 2,734 journalled trades. Bucketed by the planned
reward-to-risk ratio, without looking at the outcome:

    <= 1.75     1258 Trades   -0.0261 R   41% Treffer   [-0.097, +0.044]
    2.50 +       490 Trades   -0.1933 R   18% Treffer   [-0.351, -0.032]
    alle        2734 Trades   -0.0908 R   33% Treffer

Half the sample -- the trades whose target was modest -- sits at breakeven
within its interval, while the ambitious ones are the worst group in the
record. The winners' planned ratio averaged 1.90 against the losers' 2.27, a
difference of -0.368 with interval [-0.445, -0.295].

The mechanism is not subtle: a nearer target is reached more often, each win is
smaller, and the gain in hit rate outweighs the loss in payoff. It also agrees
with the most harmful thing measured that day -- widening a stop while letting
the target travel with it was the only measurement whose interval excluded zero
on the bad side. Two independent measurements saying that reaching further
costs more than it pays.

**Two ways to act on it, and they are genuinely different bets.**

`Refuse` drops a proposal whose target is too far. Fewer trades, and the ones
left are the kind that measured better.

`Truncate` keeps the trade and pulls the target in to the cap. Same number of
trades -- which is what Severin actually wants -- and it converts would-be
losers into smaller winners rather than removing them. It is also the more
suspicious of the two, because it changes what every setup asked for rather
than choosing among them: a setup placed its target at a level for a reason,
and a cap placed at a ratio ignores that level entirely.

**What this cannot be.** The measurement above is over trades that happened. A
filter that removes trades frees the slots they occupied, and other setups fill
them -- so the only honest test is a backtest with the rule in place. That is
what `scripts/study_modest_target.py` does, and it is the test four levers
failed on 04.10.2026.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.domain.enums import Side
from traidingbrain.sim.plan import TradeIntent
from traidingbrain.strategies.guide import GuidePool

#: Where the measured gap sits.
#:
#: Not a search result: 1.75 is the upper edge of the best bucket of five whose
#: boundaries were set before looking. The buckets in between do not order --
#: 1.75-2.00 came out worse than 2.00-2.25 -- so the number carries the end of
#: the scale rather than a fitted optimum, and the forward journal is where it
#: has to prove itself.
CAP = 1.75


class Action(Enum):
    """What to do with a proposal that reaches too far."""

    REFUSE = "abgelehnt"
    TRUNCATE = "gekuerzt"


@dataclass
class ModestTarget:
    """A pool whose over-ambitious targets are refused, or pulled in."""

    inner: GuidePool
    action: Action = Action.REFUSE
    cap: float = CAP
    name: str = "guide-modest"
    touched: int = field(default=0)

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
        intent = self.inner.propose_at(analysis, index)
        if intent is None or intent.reward_risk <= self.cap:
            return intent

        self.touched += 1
        if self.action is Action.REFUSE:
            return None

        # The target moves to the cap, measured from the stop the setup chose.
        # The stop is left alone on purpose: it is where the setup says the idea
        # is wrong, and moving it was measured as actively harmful the same day.
        risk = abs(intent.entry - intent.stop)
        reach = risk * self.cap
        target = intent.entry + (reach if intent.side is Side.LONG else -reach)
        return TradeIntent(
            side=intent.side,
            entry=intent.entry,
            stop=intent.stop,
            target=target,
            confidence=intent.confidence,
            reason=f"{intent.reason} | Ziel auf {self.cap:.2f}R gekuerzt",
        )
