"""The guide's setups as backtestable strategies -- one per setup, plus the pool.

Chapter 30 of `DAYTRADING_MASTER_GUIDE.md` asks for exactly this: "getrennte
Video-Modelle ... keine kombinierte Master-Strategie". So each setup gets its own
strategy and its own row in the results table. Pooling them first would produce
one number that cannot say which rule earned it, and the honest answer to "does
this work" is four answers.

The pool is here too, because it is the thing a person would actually run, and
because it is the only way to see what happens when two rules fire close
together. It is measured *alongside* the four, never instead of them.

**Confidence is fixed at the floor.** These strategies state a number the risk
layer needs and have no opinion to express with it: a rule either fired or it
did not. Setting it at the lowest tier keeps every setup on the same risk budget
and makes the comparison between them a comparison of their signals. A varying
confidence here would quietly turn the sizing ladder into part of the strategy,
and then a setup could look better than another for reasons that have nothing to
do with its entries.

Nothing about the money comes from the guide, which says so itself in chapter 23:
no position sizing formula, no percentage, no daily loss limit. Sizing, leverage,
liquidation distance and cost rules are the engine's, identical for every
strategy in the table, and that is what makes the rows comparable.
"""

from __future__ import annotations

from dataclasses import dataclass

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.sim.engine import TradeIntent
from traidingbrain.strategy.setups import TRADEABLE, Setup, SetupSignal

#: The confidence every guide strategy reports.
#:
#: Deliberately the bottom of the ladder. The videos give no confidence scale and
#: no sizing rule, so any number here is the engine's business rather than the
#: strategy's -- and a fixed one keeps four setups on one risk budget so the
#: comparison between them is about their signals.
FIXED_CONFIDENCE = 60.0


def _to_intent(signal: SetupSignal) -> TradeIntent | None:
    intent = TradeIntent(
        side=signal.side,
        entry=signal.entry,
        stop=signal.stop,
        target=signal.target,
        confidence=FIXED_CONFIDENCE,
        reason=f"{signal.setup} {signal.name} ({signal.source}): {'; '.join(signal.reasons)}",
    )
    return intent if intent.is_coherent else None


@dataclass
class GuideSetupStrategy:
    """One setup from the guide, run on its own.

    Reads the signal timeframe only. Every setup the guide states for a single
    chart is a single-chart rule; the two that are explicitly multi-timeframe
    (V10's 4H/15M model and V12's 1H/15M) are handled inside their own detectors
    rather than by giving every setup a second frame it does not use.
    """

    setup: Setup

    @property
    def name(self) -> str:
        return f"guide-{self.setup.key}"

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
        signal = self.setup.evaluate(analysis.signal, index)
        return _to_intent(signal) if signal is not None else None


@dataclass
class GuidePool:
    """Every tradeable setup at once, first one to fire.

    "First" is by the order in `TRADEABLE`, and that order is arbitrary -- which
    is worth saying out loud, because on a bar where two setups agree it decides
    which one is taken. Agreement is rare enough that ranking them would be
    inventing a preference the sources never state; if it turns out to matter,
    the per-setup rows are where that will show.
    """

    name: str = "guide-all"

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
        for setup in TRADEABLE:
            signal = setup.evaluate(analysis.signal, index)
            if signal is None:
                continue
            intent = _to_intent(signal)
            if intent is not None:
                return intent
        return None


def per_setup() -> list[GuideSetupStrategy]:
    """One strategy per tradeable setup, in the guide's own lettering."""
    return [GuideSetupStrategy(setup) for setup in TRADEABLE]


def all_strategies() -> list[GuideSetupStrategy | GuidePool]:
    """The four setups and the pool, which is the full comparison table."""
    return [*per_setup(), GuidePool()]
