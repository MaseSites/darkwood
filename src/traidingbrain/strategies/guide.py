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

from traidingbrain.analysis.pipeline import (
    MultiFrameAnalysis,
    decision_time_ms,
)
from traidingbrain.config.settings import AppConfig
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.domain.enums import Timeframe
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
        timeframe=signal.timeframe.value,
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


#: Which charts are searched, slowest first.
#:
#: Slowest first because a daily setup and an hourly one firing in the same
#: hour are not equal claims: the daily one rests on more and is the one a
#: person would take. Without an order the answer would depend on dictionary
#: insertion, which is not a preference anybody stated.
SEARCH_ORDER: tuple[Timeframe, ...] = (
    Timeframe.D1,
    Timeframe.H4,
    Timeframe.H1,
    Timeframe.M15,
)


def _just_closed(analysis: MultiFrameAnalysis, timeframe: Timeframe, decision_ms: int) -> bool:
    """Did a candle of this timeframe finish in the hour just ended?

    The loop steps hourly. Without this a four-hour setup would be proposed on
    all four hours its candle spans -- the same trade offered four times, and
    in a backtest four entries where the rule describes one.

    Asked of the frame rather than of the clock. The first version computed it
    from the grid, `(decision - offset) % step == 0`, which is true of real
    exchange bars and false of anything whose timestamps sit a little off it --
    and then every setup silently stops firing. The data answers the question
    it is the authority on.
    """
    frame = analysis.analyses.get(timeframe)
    if frame is None:
        return False
    step = timeframe_ms(analysis.signal_timeframe)
    now = frame.index_at_or_before(decision_ms)
    before = frame.index_at_or_before(decision_ms - step)
    return now is not None and now != before


def allowed_timeframes(config: AppConfig) -> tuple[Timeframe, ...]:
    """Die Ebenen aus der Konfiguration, in `SEARCH_ORDER`; None heisst alle."""
    wanted = config.engine.setups.timeframes
    if wanted is None:
        return SEARCH_ORDER
    return tuple(tf for tf in SEARCH_ORDER if tf in set(wanted))


def enabled_setups(config: AppConfig) -> tuple[Setup, ...]:
    """The setups configuration allows, in `TRADEABLE` order.

    Measured on 04.10.2026 over four markets and four years, which is why this
    function exists at all: with setup C in, the pool runs at -0.0920 R and the
    interval excludes zero; without it, -0.0583 R over a third fewer trades and
    the interval includes zero for the first time. More than half the loss is
    one setup.

    The distinction that makes it a real finding rather than "trade less":
    dropping setup A also improves the *sum*, by trading 730 fewer times at a
    negative expectancy, while making the per-trade number worse. Dropping C
    improves both, and the hit rate with them -- 32% to 37%.
    """
    allowed = set(config.engine.setups.enabled)
    return tuple(setup for setup in TRADEABLE if setup.key in allowed)


@dataclass
class GuidePool:
    """Every tradeable setup on every chart, first one to fire.

    **Why several charts.** Until now every setup read the hourly frame and
    nothing else, while the weekly, daily and four-hour frames were analysed
    only to feed the score. Severin reads the four-hour chart and kept pointing
    at entries there; the system had never looked. Searching each frame is what
    makes those visible, and it is also where longer trades come from -- a
    four-hour setup puts its stop at four-hour structure, so it is roughly four
    times wider, the target with it, and the trade runs for days.

    **One signal per candle, not per hour.** A four-hour setup is offered on
    the single hourly bar where its candle closed. Offering it on all four
    would be the same trade four times.

    "First" is by `SEARCH_ORDER` then by `TRADEABLE`, and the second of those is
    arbitrary -- worth saying out loud, because on a bar where two setups agree
    it decides which is taken.
    """

    name: str = "guide-all"

    setups: tuple[Setup, ...] = TRADEABLE
    """Which setups this pool may take.

    A field rather than the module constant read directly, so that asking
    "what would this look like without setup C" is a different pool rather than
    a patched global -- a measurement you can only take by editing the module
    you are measuring is not one you get the same way twice.

    **The default is every setup, and that is deliberately not what ships.**
    Anything that trades should build its pool with `for_config`, so the
    configured list decides. A default of "all of them" means a forgotten call
    site keeps trading a setup the configuration switched off, and the switch
    looks like it works for as long as nobody checks.
    """

    timeframes: tuple[Timeframe, ...] = SEARCH_ORDER
    """Welche Ebenen durchsucht werden, langsamste zuerst.

    Seit dem 21.10.2026 aus `setups.timeframes` der Konfiguration, damit
    "ohne M15" eine Einstellung mit Signaturspur ist und kein Umbau an
    `SEARCH_ORDER`. Die Reihenfolge bleibt die von `SEARCH_ORDER`, egal in
    welcher Reihenfolge die Liste in der Datei steht.
    """

    @classmethod
    def for_config(cls, config: AppConfig, *, name: str = "guide-all") -> GuidePool:
        """The pool as configured -- what the live system and every measurement
        of "the shipped system" should use."""
        return cls(
            name=name, setups=enabled_setups(config), timeframes=allowed_timeframes(config)
        )

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
        aligned = analysis.aligned_indices(index)
        if aligned is None:
            return None
        decision = decision_time_ms(analysis.signal.ts_at(index), analysis.signal_timeframe)

        for timeframe in self.timeframes:
            frame = analysis.analyses.get(timeframe)
            at = aligned.get(timeframe)
            if frame is None or at is None or not _just_closed(analysis, timeframe, decision):
                continue
            for setup in self.setups:
                signal = setup.evaluate(frame, at)
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
