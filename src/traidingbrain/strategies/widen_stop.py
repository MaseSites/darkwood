"""Widen a stop that is too tight to pay for its own round trip.

Nine of twelve forward accounts say the same sentence: *Setups ausgeloest, alle
von der Risikoschicht abgelehnt -- meist zu enger Stop fuer die Gebuehren.* The
rule doing the refusing is right, and `min_economic_stop_fraction` says exactly
where its edge is: costs as a share of risk are `c / d`, so a ceiling `f`
demands `d >= c / f` and nothing about the strategy enters the formula.

That leaves one move that raises the trade count without touching the ceiling:
instead of refusing a stop at `d < c/f`, push it out to `c/f` and re-size. Risk
in CHF is unchanged -- a wider stop simply buys fewer units -- so the account
is no more exposed than before.

**What it costs, said plainly before the measurement.** A setup's stop is where
the idea is wrong. Moving it out means holding a trade whose own premise has
already failed, waiting for a level the setup never argued for. That has to show
up as a lower hit rate, and if it does not, the measurement is suspect rather
than good news. This is the opposite trade from the cost ceiling: the ceiling
buys quality by giving up trades, this buys trades by giving up the stop's
meaning. Which one wins is an empirical question, and the answer may be neither.

**Two ways to do it, and they are not the same bet.**

* `KEEP_TARGET` leaves the target where the setup put it. The reward-to-risk
  ratio falls, and `min_reward_risk` refuses whatever falls too far -- so this
  variant still loses some trades, just fewer.
* `KEEP_RATIO` moves the target out by the same factor, holding R:R. Severin
  asked for exactly this ("1:5 when explosive, 1:2 for a quick trade"), but a
  target further away is a target hit less often, and the stop it is paired
  with is no longer at structure either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import AppConfig
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.risk.sizing import min_economic_stop_fraction
from traidingbrain.sim.plan import TradeIntent
from traidingbrain.strategies.guide import GuidePool


class Target(Enum):
    """What happens to the target when the stop moves out."""

    KEEP_TARGET = "Ziel bleibt"
    KEEP_RATIO = "Verhaeltnis bleibt"


@dataclass
class WidenedStop:
    """A pool whose unaffordable stops are pushed out instead of refused.

    The widening is computed from the fee schedule and the ceiling, never from
    the chart: `min_economic_stop_fraction` is the same rule the risk layer
    enforces, read backwards. Deriving it any other way would let this wrapper
    and the layer that judges it disagree about where the edge is.
    """

    inner: GuidePool
    spec: SymbolSpec
    config: AppConfig
    mode: Target = Target.KEEP_RATIO
    name: str = "guide-widened"
    widened: int = field(default=0)

    @property
    def _floor(self) -> float:
        """Minimum stop distance as a fraction of price, for this venue."""
        return min_economic_stop_fraction(
            self.spec,
            self.config.engine.simulation.slippage_bps,
            self.config.risk.limits.max_cost_fraction_of_risk,
        )

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
        intent = self.inner.propose_at(analysis, index)
        if intent is None:
            return None

        needed = intent.entry * self._floor
        distance = abs(intent.entry - intent.stop)
        if distance <= 0 or distance >= needed:
            return intent

        self.widened += 1
        sign = -1.0 if intent.side is Side.LONG else 1.0
        stop = intent.entry + sign * needed
        if self.mode is Target.KEEP_TARGET:
            target = intent.target
        else:
            # Same reward-to-risk as the setup asked for, measured from the new
            # stop. Scaling the reward rather than re-deriving it keeps the
            # setup's own judgement about how far the move should run.
            reward = needed * intent.reward_risk
            target = intent.entry - sign * reward

        return TradeIntent(
            side=intent.side,
            entry=intent.entry,
            stop=stop,
            target=target,
            confidence=intent.confidence,
            reason=f"{intent.reason} | Stop auf {self._floor:.2%} verbreitert",
        )
