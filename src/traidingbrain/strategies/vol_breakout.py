"""A volatility expansion, traded in the direction it expanded.

The first candidate from a strategy family this project has never tested. Nine
hypotheses were measured on 05.10.2026 and all nine failed -- and all nine lay
inside *one* family of nine. Every shipped setup is continuation logic waiting
for price to return to a zone, and 93% of bars have no zone within one ATR, so
the search looked exhausted while having covered an eighth of the ground.

**Why this family should behave differently, structurally rather than
hopefully.** The whole deficit measured today is one quantity:

    net_r = (captured move - fee) / stop_fraction

and the toll in R is `round_trip_fee / stop_fraction`. A zone-return entry
places its stop just past a level, so `stop_fraction` is small and the toll is
large -- which is exactly why the cost rule refuses about a third of all
signals, and why its refusals are the worst group in the whole ledger. A
volatility breakout puts its stop beyond a bar that is unusually large, so its
`stop_fraction` should be bigger and its toll smaller. This is not a prediction
that it works; it is a reason to expect its *cost structure* to differ, which is
the one lever the identity leaves.

**Measured on BTC before any backtest, and the claim holds only on the higher
timeframe.** `default_timeframe` is H4 for this reason and not by taste:

    arm       n    median stop    cost_r    refused by the cost rule
    vol-H1  269        1.024%     0.0733    9%
    vol-H4   96        2.544%     0.0295    0%
    shipped 3300       1.264%     0.0593    about a third

On H1 the stop is *narrower* than the shipped setups' and the toll therefore
*higher* -- so "a volatility breakout has a wide stop by construction" is
simply false there. An H1 bar at twice its recent average range is still about
1% of price. The structural advantage needs the bar to be large in absolute
terms, which is a property of the timeframe and not of the rule. On H4 the toll
halves and the cost rule refuses none of them.

H4 costs signal count: 96 over roughly ten months on one market against 269 on
H1. Across four markets that is still a few hundred a year, which is enough for
the six-month arithmetic -- but it is a real trade and worth naming rather than
discovering later.

**The claim being tested.** A transition from quiet to busy carries direction:
when range expands sharply after a calm stretch, the direction of the expanding
bar continues far enough to pay for itself. That is a different claim from
anything measured here, and it is the hypothesis the research order lists as
"Volatilitaetsausbruch".

**What is deliberately not done.** No parameter search. The thresholds below
are stated once, with a reason for each, and the arm is measured as it stands.
Tuning them against the result is how a family with no edge produces a
candidate -- and the register would then be counting one attempt where there
were twenty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from traidingbrain.analysis.pipeline import (
    FrameAnalysis,
    MultiFrameAnalysis,
    decision_time_ms,
)
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.sim.plan import TradeIntent

#: Volatility percentile below which the market counts as quiet.
#:
#: `RegimeTimeline` already computes this as a rolling rank, never global, so
#: "quiet" means quiet relative to its own recent history rather than to an era.
QUIET_BELOW = 0.35

#: How much larger the triggering bar's range must be than the recent average.
#:
#: Two, because that is the smallest multiple that is unambiguous: a bar twice
#: the average range is not a normal bar. A smaller threshold would fire on
#: ordinary noise and a larger one would wait for the move to be over.
EXPANSION = 2.0

#: Bars of recent range the expansion is measured against.
LOOKBACK = 20

#: Where the stop goes, in multiples of the triggering bar's own range beyond
#: its extreme.
#:
#: Beyond the bar rather than at its midpoint: the claim is that the expansion
#: continues, so the trade is wrong precisely when price comes back through the
#: bar that started it. A stop inside the bar would be hit by the noise of the
#: move it is trying to follow.
STOP_BEYOND = 0.25

#: Target as a multiple of risk. Fixed, not optimised.
#:
#: Two, so the setup needs roughly a third of its trades to be right -- and so
#: that the comparison with the shipped setups is on comparable terms, since
#: their mean planned reward-to-risk is about 2.15.
REWARD = 2.0

#: Fraction of the expanding bar's range given up before entry.
#:
#: Entry is at the bar's close, which is where the decision is taken. Zero
#: rather than a pullback: a pullback entry is a second hypothesis bolted onto
#: the first, and then a failure cannot be attributed to either.
ENTRY_OFFSET = 0.0

#: The confidence handed to the engine. Mid-band on purpose.
#:
#: The risk ladder is capped at 1% until calibration is proven, so every band
#: sizes identically today and this number cannot change what is risked. It is
#: set in the middle so that it also will not once the cap lifts, until this arm
#: has earned a claim about its own reliability.
CONFIDENCE = 70.0


@dataclass
class VolBreakout:
    """Trade the direction of a sharp range expansion out of a quiet stretch.

    An `AnalysisStrategy`: it reads the analysis at a bar index rather than a
    snapshot, like `GuidePool`, so the engine recognises it through
    `wants_analysis` and no snapshot is built for it.
    """

    #: H4, measured rather than chosen: see the table in the module docstring.
    #: On H1 this rule's stop is narrower than the shipped setups' and its
    #: toll higher, which removes the only structural reason to try it.
    timeframe: Timeframe = Timeframe.H4
    name: str = "vol-breakout"
    quiet_below: float = QUIET_BELOW
    expansion: float = EXPANSION
    lookback: int = LOOKBACK

    #: Counted so a run with no trades can be told apart from a run where the
    #: rule never fired. The first is a result; the second is a bug.
    fired: int = field(default=0, compare=False)
    quiet_bars: int = field(default=0, compare=False)

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
        found = self._bar_to_judge(analysis, index)
        if found is None:
            return None
        frame, at = found

        # The bar *before* the expansion is the one that has to be quiet. Asking
        # whether the expanding bar itself sits in a quiet regime is close to a
        # contradiction, and it is the kind of off-by-one that makes a rule fire
        # almost never while looking correct.
        before = frame.regime.state_at(at - 1)
        if before.volatility_percentile > self.quiet_below:
            return None
        self.quiet_bars += 1

        highs = frame.column("high")
        lows = frame.column("low")
        closes = frame.column("close")
        ranges = highs[at - self.lookback : at] - lows[at - self.lookback : at]
        average = float(np.mean(ranges)) if ranges.size else 0.0
        span = float(highs[at] - lows[at])
        if average <= 0 or span < self.expansion * average:
            return None

        close = float(closes[at])
        open_ = float(frame.column("open")[at])
        if span <= 0 or not np.isfinite(close) or close <= 0:
            return None

        # Direction from the bar, not from the trend: the claim is about the
        # expansion itself. A bar that expanded and closed down is a downward
        # expansion however bullish the higher timeframes look.
        side = Side.LONG if close > open_ else Side.SHORT
        self.fired += 1

        entry = close
        if side is Side.LONG:
            stop = float(lows[at]) - STOP_BEYOND * span
            target = entry + REWARD * (entry - stop)
        else:
            stop = float(highs[at]) + STOP_BEYOND * span
            target = entry - REWARD * (stop - entry)

        intent = TradeIntent(
            side=side,
            entry=entry,
            stop=stop,
            target=target,
            confidence=CONFIDENCE,
            reason=(
                f"Spanne {span / average:.1f}x des Mittels der letzten {self.lookback} Kerzen, "
                f"vorherige Vola im {100 * before.volatility_percentile:.0f}. Perzentil"
            ),
        )
        return intent if intent.is_coherent else None

    def _bar_to_judge(
        self, analysis: MultiFrameAnalysis, index: int
    ) -> tuple[FrameAnalysis, int] | None:
        """The bar of this arm's own timeframe that just closed, if any.

        Three conditions, and the third is the same guard GuidePool uses for
        the same reason: the loop steps on the signal timeframe, so without
        it an H1 setup would be proposed on every signal bar its candle
        spans -- one rule, several entries, and a backtest that trades a
        multiple of what the rule describes."""
        aligned = analysis.aligned_indices(index)
        if aligned is None:
            return None
        frame = analysis.analyses.get(self.timeframe)
        at = aligned.get(self.timeframe)
        if frame is None or at is None or at < self.lookback:
            return None
        decision = decision_time_ms(analysis.signal.ts_at(index), analysis.signal_timeframe)
        if not self._just_closed(analysis, decision):
            return None
        return frame, at

    def _just_closed(self, analysis: MultiFrameAnalysis, decision_ms: int) -> bool:
        """Did a candle of this arm's timeframe finish in the step just ended?"""
        frame = analysis.analyses.get(self.timeframe)
        if frame is None:
            return False
        step = timeframe_ms(analysis.signal_timeframe)
        now = frame.index_at_or_before(decision_ms)
        before = frame.index_at_or_before(decision_ms - step)
        return now is not None and now != before
