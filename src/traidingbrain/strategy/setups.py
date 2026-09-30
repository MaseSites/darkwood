"""The guide's setups, one object each, kept apart on purpose.

`DAYTRADING_MASTER_GUIDE.md` chapter 30 opens with a sentence this module takes
literally: "Die folgenden Setups sind **getrennte Video-Modelle**. Sie sind keine
kombinierte Master-Strategie." So there is no master strategy here. Each setup
carries its own entry, stop and target from its own source, fires on its own,
and is measured on its own. Merging them would produce a strategy nobody in the
sources ever traded, with a backtest that could not say which part worked.

**Four of the seven are complete. Three are not, and that is reported rather
than patched.** A setup can only propose a trade when its source states an
entry, a stop *and* a target:

| Setup | Source | Entry | Stop | Target | Tradeable |
|---|---|---|---|---|---|
| A momentum breakout | V08 | yes | yes | yes (1.5R) | yes |
| B trendline fakeout | V06 | yes | yes | yes | needs trendlines |
| C supply/demand retest | V09 | yes | yes | yes | yes |
| D MTF sweep reversal | V10 | yes | **no** | yes | no |
| E Noc order block | V11 | yes | yes | **no** | no |
| F inducement order block | V12 | yes | yes | yes | yes |
| G six-factor FVG | V13 | yes | yes | yes | yes |

D's own rule card says "Stop Loss: Für dieses Beispiel nicht numerisch bzw.
positionsbezogen spezifiziert"; E's says "Take Profit: Nicht spezifiziert".
Chapter 20.2 then forbids filling those gaps: no playlist source gives a general
ATR stop, a fixed percentage or a buffer. A setup missing a stop is a setup with
unbounded loss, and inventing one would mean trading a rule nobody gave while
the label still said V10. They are detected and reported; they cannot propose.

**Where a number had to be chosen, it is derived from the chart rather than
invented.** V08 places the stop "knapp unter dem gebrochenen Level" without
saying how far. Rather than pick a buffer, the stop goes on the far side of the
level's own band -- a pool of equal highs is a band with a measured height, and
using it keeps the distance a property of the market instead of a constant
somebody tuned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from traidingbrain.analysis.candles import confirm_breakout
from traidingbrain.analysis.fvg_quality import MitigationRule, assess_gaps, best_gap
from traidingbrain.analysis.liquidity import Zone, ZoneKind
from traidingbrain.analysis.pipeline import FrameAnalysis
from traidingbrain.analysis.zones import StructuralZone, ZoneRole, true_zone
from traidingbrain.domain.enums import Bias, Side

#: V08: "Erstes Ziel bei 1,5R, halbe Position schließen, Rest laufen lassen."
BREAKOUT_FIRST_TARGET_R = 1.5

#: V08's runner exit: a Chandelier stop with an ATR multiplier of 2. Carried on
#: the signal rather than applied here, because trailing is a management rule
#: and this module's job ends when the trade is described.
CHANDELIER_ATR_MULTIPLE = 2.0

#: How far back a setup will look for the structure it needs. Bounded for the
#: same reason the impulse search is: without a bound, every setup eventually
#: finds something, and what it finds is not what the video was pointing at.
MAX_CONTEXT_BARS = 60


@dataclass(frozen=True)
class SetupSignal:
    """One setup firing on one bar, fully described.

    Entry, stop and target are absolute prices, all three taken from the source's
    own rule. `reasons` records which conditions were met, in the source's words,
    so a signal can be argued with rather than only accepted.
    """

    setup: str
    name: str
    source: str
    side: Side
    entry: float
    stop: float
    target: float
    bar_index: int
    reasons: tuple[str, ...] = ()
    #: The price the setup is built around -- the broken level, or the zone edge.
    #: Carried so the chart can draw the thing the rule is about, and so a test
    #: can check the rule against it rather than against the setup's own word.
    reference_level: float | None = None
    #: V08 alone asks for a runner. Anything reading this must either honour it
    #: or say it does not; silently ignoring it would trade a different exit.
    trail_atr_multiple: float | None = None
    scale_out_fraction: float | None = None

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_risk(self) -> float:
        risk = self.risk
        return abs(self.target - self.entry) / risk if risk > 0 else 0.0

    def is_coherent(self) -> bool:
        """Does this describe a trade that can exist?

        A long whose stop sits above its entry is not a conservative long, it is
        arithmetic that went wrong somewhere upstream. Checked here so a broken
        signal is dropped at its source rather than sized, drawn and proposed.
        """
        if self.risk <= 0:
            return False
        if self.side is Side.LONG:
            return self.stop < self.entry < self.target
        return self.target < self.entry < self.stop


class Setup(Protocol):
    """What every setup can do: say whether it fires on this bar.

    The three labels are read-only members. Declared as plain attributes they
    would be mutable, and a mutable attribute is invariant -- so a frozen
    dataclass, which is what every setup here is, would not satisfy the
    protocol.
    """

    @property
    def key(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def source(self) -> str: ...

    def evaluate(self, analysis: FrameAnalysis, index: int) -> SetupSignal | None: ...


# --------------------------------------------------------------------------- #
# Setup A -- momentum breakout with a two-stage exit (V08)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MomentumBreakout:
    """V08. A break of a level that has rejected price several times, confirmed
    by a body rather than a wick.

    The level is a pool of equal highs or lows, because that is what "Support /
    Resistance mit mehreren Rejections" is: two or more swings at the same price.
    A single swing is a level; a pool is the crowd of stops behind it.
    """

    key: str = "A"
    name: str = "Momentum-Breakout"
    source: str = "V08"

    def evaluate(self, analysis: FrameAnalysis, index: int) -> SetupSignal | None:
        if not analysis.is_ready(index) or index < 1:
            return None
        close = analysis.close_at(index)
        previous = analysis.close_at(index - 1)
        state = analysis.liquidity.state_at(index)

        for upward, kind in ((True, ZoneKind.EQUAL_HIGHS), (False, ZoneKind.EQUAL_LOWS)):
            pool = _nearest_broken_pool(state.zones_of(kind), close, upward=upward)
            if pool is None:
                continue
            # The break has to be *this* bar's. Without this the setup fires on
            # every bar price spends on the far side of a level it broke days
            # ago -- which is not a breakout, it is a location. Measured: 6,307
            # signals over five years, 3.4 a day, from a setup that should be
            # selective.
            already = previous > pool.high if upward else previous < pool.low
            if already:
                continue
            verdict = confirm_breakout(
                analysis.frame,
                analysis.indicators.atr,
                index,
                level=pool.high if upward else pool.low,
                upward=upward,
            )
            if not verdict.confirmed:
                continue

            side = Side.LONG if upward else Side.SHORT
            # "Knapp hinter dem gebrochenen Level." The level is a band with a
            # measured height, so the far side of it is the stop -- a distance
            # the market set rather than a buffer somebody chose.
            stop = pool.low if upward else pool.high
            risk = abs(close - stop)
            if risk <= 0:
                continue
            target = close + BREAKOUT_FIRST_TARGET_R * risk * side.sign

            signal = SetupSignal(
                setup=self.key,
                name=self.name,
                source=self.source,
                side=side,
                entry=close,
                stop=stop,
                target=target,
                bar_index=index,
                reasons=(
                    f"break of a pool of equal {'highs' if upward else 'lows'}",
                    f"confirmed by {verdict.form.replace('_', ' ')}: {verdict.detail}",
                    f"first target at {BREAKOUT_FIRST_TARGET_R}R per V08",
                ),
                reference_level=pool.high if upward else pool.low,
                trail_atr_multiple=CHANDELIER_ATR_MULTIPLE,
                scale_out_fraction=0.5,
            )
            return signal if signal.is_coherent() else None
        return None


# --------------------------------------------------------------------------- #
# Setup C -- supply/demand first retest (V09)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SupplyDemandRetest:
    """V09. The first return into the origin of an aggressive move that broke
    structure, approached slowly.

    Three conditions that each rule a lot out, and all three are the video's:
    the move must have been aggressive and broken structure, the return must be
    the *first*, and it must not be sharp. A gap at the origin is preferred
    rather than required -- V09 says a zone without one "könne funktionieren,
    sei laut Creator aber schwächer".
    """

    key: str = "C"
    name: str = "Supply/Demand-Retest"
    source: str = "V09"

    def evaluate(self, analysis: FrameAnalysis, index: int) -> SetupSignal | None:
        if not analysis.is_ready(index):
            return None

        for zone in analysis.zones.known_at(index):
            if zone.role not in (ZoneRole.DEMAND, ZoneRole.SUPPLY):
                continue
            if index - zone.confirmed_index > MAX_CONTEXT_BARS:
                continue
            touch = analysis.zones.touch_at(zone, index)
            if touch is None or not touch.is_first or not touch.was_slow:
                continue

            side = Side.LONG if zone.is_bullish else Side.SHORT
            entry = zone.high if zone.is_bullish else zone.low
            stop = zone.low if zone.is_bullish else zone.high
            target = _move_extreme(analysis, zone)
            if target is None:
                continue

            signal = SetupSignal(
                setup=self.key,
                name=self.name,
                source=self.source,
                side=side,
                entry=entry,
                stop=stop,
                target=target,
                bar_index=index,
                reasons=(
                    "aggressive move that broke structure",
                    "first return into the zone",
                    f"approach {touch.approach_atr_per_bar:.2f} ATR per bar, not sharp",
                    "gap at the origin"
                    if zone.has_fvg
                    else "no gap at the origin, weaker per V09",
                ),
                reference_level=entry,
            )
            return signal if signal.is_coherent() else None
        return None


# --------------------------------------------------------------------------- #
# Setup F -- inducement order block (V12)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class InducementOrderBlock:
    """V12. Take the zone that actually broke the relevant high, not the deepest.

    The selection is the setup. V12's warning is that the lowest zone is often
    inducement -- price is run down to it and the trade that was waiting there
    is the one that pays for the move. `true_zone` encodes that choice and
    returns nothing when no zone qualifies, which is the honest answer far more
    often than it is a missed trade.
    """

    key: str = "F"
    name: str = "Inducement-Orderblock"
    source: str = "V12"

    def evaluate(self, analysis: FrameAnalysis, index: int) -> SetupSignal | None:
        if not analysis.is_ready(index):
            return None
        close = analysis.close_at(index)
        # Zones that were still untouched going *into* this bar.
        #
        # Asking `unmitigated_at(index)` would be off by one in a way that makes
        # the setup impossible rather than rare: a zone first touched on this
        # bar is already excluded from that list, and the first touch is exactly
        # what the setup is waiting for. The two conditions cancelled and the
        # setup fired zero times in five years.
        live = analysis.zones.unmitigated_at(index - 1)

        for bullish in (True, False):
            chosen = true_zone(live, close, bullish=bullish)
            if chosen is None:
                continue
            # No age limit here, unlike the other setups, and that is V12's
            # rule rather than an oversight. The true zone is by construction
            # the deeper one -- price has to run the inducement above it first,
            # and that takes as long as it takes. Capping the age discarded
            # 8,359 of 8,637 candidates and the setup never fired once.
            touch = analysis.zones.touch_at(chosen, index)
            if touch is None or not touch.is_first:
                continue

            structure = analysis.structure.state_at(index)
            # V12 waits for a structure break *in the trade's direction* on the
            # lower timeframe before entering. Here that is the signal frame's
            # own break; without it the zone has been reached and nothing has
            # confirmed, which is the blind entry the video refuses.
            wanted = Bias.BULLISH if bullish else Bias.BEARISH
            if structure.break_direction is not wanted or not structure.bos:
                continue

            side = Side.LONG if bullish else Side.SHORT
            entry = chosen.high if bullish else chosen.low
            # "Stop unter dem Higher-Timeframe-Tief."
            stop = chosen.low if bullish else chosen.high
            target = _previous_extreme(analysis, index, bullish=bullish)
            if target is None:
                continue

            signal = SetupSignal(
                setup=self.key,
                name=self.name,
                source=self.source,
                side=side,
                entry=entry,
                stop=stop,
                target=target,
                bar_index=index,
                reasons=(
                    "true zone: nothing untested lies beyond it",
                    "the zone's own impulse broke structure",
                    "structure break in the trade's direction before entry",
                    "target at the previous high" if bullish else "target at the previous low",
                ),
                reference_level=entry,
            )
            return signal if signal.is_coherent() else None
        return None


# --------------------------------------------------------------------------- #
# Setup G -- six-factor fair value gap (V13)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SixFactorGap:
    """V13. The first test of the highest-ranked gap that passes all six factors.

    The most completely specified setup in the guide: it states the entry
    condition, the stop to the candle, and the target, and its six factors are
    conditions rather than preferences. That makes it the one that can be
    implemented with the least interpretation -- and the one whose failure would
    say the most, because there is nowhere for a judgement call to hide.

    The factors are conjunctive on purpose. A gap meeting five of six is not
    five-sixths of a setup; scoring them would let any one be bought off by the
    others, and the video's list is a list of requirements.
    """

    key: str = "G"
    name: str = "Sechs-Faktoren-FVG"
    source: str = "V13"
    mitigation: MitigationRule = MitigationRule.V13_INVALID

    def evaluate(self, analysis: FrameAnalysis, index: int) -> SetupSignal | None:
        if not analysis.is_ready(index):
            return None

        assessments = assess_gaps(
            analysis.frame,
            analysis.indicators.atr,
            analysis.structure,
            index,
            rule=self.mitigation,
            gaps=analysis.fair_value_gaps,
        )
        for bullish in (True, False):
            chosen = best_gap(assessments, bullish=bullish)
            if chosen is None:
                continue
            gap = chosen.gap
            # "Entry: Wenn Reaktionskerze im FVG oder in Zonenrichtung schließt."
            #
            # Two conditions on this bar, and the second is easy to miss. The
            # reaction has to be *this* bar, or the setup fires on every bar
            # price spends near a gap it once reacted to. And the bar has to be
            # a later one: the candle that creates a gap spans it by
            # construction, so without this the setup matches the gap's own
            # third candle and calls it a retest.
            if index <= gap.created_index:
                continue
            if not _bar_reaches(analysis, index, gap.low, gap.high):
                continue

            side = Side.LONG if bullish else Side.SHORT
            entry = analysis.close_at(index)
            # "Stop Loss: Am Low der Kerze, die das bullische FVG erzeugte."
            stop = _gap_candle_extreme(analysis, gap, bullish=bullish)
            target = _move_end(analysis, gap, index, bullish=bullish)
            if stop is None or target is None:
                continue

            signal = SetupSignal(
                setup=self.key,
                name=self.name,
                source=self.source,
                side=side,
                entry=entry,
                stop=stop,
                target=target,
                bar_index=index,
                reasons=(
                    *(f"{name} met" for name in chosen.met),
                    f"highest-ranked {'bullish' if bullish else 'bearish'} gap",
                ),
                reference_level=gap.mid,
            )
            return signal if signal.is_coherent() else None
        return None


# --------------------------------------------------------------------------- #
# The ones that cannot propose, and why
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Incomplete:
    """A setup whose source leaves a required piece unstated.

    Kept as an object rather than deleted, so the reason travels with the
    strategy. A missing setup looks like an oversight; this says what is missing
    and which rule card says so, and it is what a person needs in order to
    supply the number themselves.
    """

    key: str
    name: str
    source: str
    missing: str
    quote: str

    def evaluate(self, analysis: FrameAnalysis, index: int) -> SetupSignal | None:
        return None


INCOMPLETE: tuple[Incomplete, ...] = (
    Incomplete(
        key="D",
        name="MTF Liquidity Sweep Reversal",
        source="V10",
        missing="stop",
        quote="Stop Loss: Für dieses Beispiel nicht numerisch bzw. positionsbezogen spezifiziert.",
    ),
    Incomplete(
        key="E",
        name="Orderblock nach Noc Trading",
        source="V11",
        missing="target",
        quote="Take Profit: Nicht spezifiziert.",
    ),
    Incomplete(
        key="B",
        name="Trendlinien-Fakeout",
        source="V06",
        missing="trendline detection",
        quote="Mindestens zwei Swing-High-Anker; dritter Kontakt über Linie.",
    ),
)


TRADEABLE: tuple[Setup, ...] = (
    MomentumBreakout(),
    SupplyDemandRetest(),
    InducementOrderBlock(),
    SixFactorGap(),
)


def evaluate_all(analysis: FrameAnalysis, index: int) -> list[SetupSignal]:
    """Every setup that fires on this bar.

    A list rather than the best one. Two setups agreeing is information, and
    picking a winner here would throw it away before anything could weigh it --
    and the guide's own pre-trade checklist asks which single setup is being
    traded, which is a decision for the layer that knows the account.
    """
    return [
        signal for setup in TRADEABLE if (signal := setup.evaluate(analysis, index)) is not None
    ]


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #


def _nearest_broken_pool(pools: tuple[Zone, ...], close: float, *, upward: bool) -> Zone | None:
    """The pool this bar's close has just broken through, if any.

    Nearest first: a close above three stacked pools broke the nearest one on
    its way, and measuring the stop against a distant one would quietly triple
    the risk on the same trade.
    """
    candidates = [pool for pool in pools if (close > pool.high if upward else close < pool.low)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.high) if upward else min(candidates, key=lambda p: p.low)


def _move_extreme(analysis: FrameAnalysis, zone: StructuralZone) -> float | None:
    """The far end of the move the zone launched -- V09's target.

    Measured between the zone's origin and the bar its break confirmed on, which
    is the move the video points at. Reading further forward would be reading
    bars that had not closed when the zone was drawn.
    """
    start, end = zone.origin_index, zone.confirmed_index
    if end <= start:
        return None
    column = "high" if zone.is_bullish else "low"
    values = analysis.column(column)[start : end + 1]
    return float(values.max() if zone.is_bullish else values.min())


def _previous_extreme(analysis: FrameAnalysis, index: int, *, bullish: bool) -> float | None:
    """V12's target: "Ziel am vorherigen Hoch" (mirrored for a short).

    Taken from the confirmed swings, so the level is one the structure timeline
    had already dated -- not the highest bar in a window, which would include
    bars whose high was still being written.
    """
    swings = analysis.structure.recent_swings(index, limit=8)
    wanted = "high" if bullish else "low"
    prices = [swing.price for swing in swings if swing.kind.value == wanted]
    if not prices:
        return None
    return max(prices) if bullish else min(prices)


def _bar_reaches(analysis: FrameAnalysis, index: int, low: float, high: float) -> bool:
    """Did this bar trade into the band?

    The reaction has to belong to this bar. Without it the setup fires on every
    bar price spends in the neighbourhood of a gap it reacted to once, which is
    the same mistake the breakout made against its level.
    """
    return bool(
        analysis.column("low")[index] <= high and analysis.column("high")[index] >= low
    )


def _gap_candle_extreme(analysis: FrameAnalysis, gap: Zone, *, bullish: bool) -> float | None:
    """V13's stop: "Am Low der Kerze, die das bullische FVG erzeugte."

    Which of the three candles created it is the question, and the geometry
    answers it. A bullish gap is the space between the first candle's high and
    the third candle's low, so the third candle's low *is* the top of the gap --
    a stop there sits inside the zone being entered. Measured, that produced a
    stop 0.016% from entry and a reward-to-risk of 55.

    The candle that made the imbalance is the middle one: the displacement that
    jumped the price past the first candle's high. Its low sits under the gap,
    which is where a stop belongs -- the trade is wrong when the move that
    created the imbalance has been undone.
    """
    displacement = gap.created_index - 1
    if displacement < 0 or displacement >= len(analysis.frame):
        return None
    column = "low" if bullish else "high"
    return float(analysis.column(column)[displacement])


def _move_end(
    analysis: FrameAnalysis, gap: Zone, index: int, *, bullish: bool
) -> float | None:
    """V13's target: "Hoch/Tief des Moves" that made the gap.

    Measured from the gap's creation bar to now, which is the move as it stands
    when the decision is taken. Reading further would be reading bars that have
    not closed.
    """
    if index <= gap.created_index:
        return None
    column = "high" if bullish else "low"
    values = analysis.column(column)[gap.created_index : index + 1]
    return float(values.max() if bullish else values.min())


@dataclass
class SetupTally:
    """How often each setup fired, which is the first thing to know about it."""

    counts: dict[str, int] = field(default_factory=dict)

    def add(self, signal: SetupSignal) -> None:
        self.counts[signal.setup] = self.counts.get(signal.setup, 0) + 1

    def summary(self) -> str:
        if not self.counts:
            return "no setup fired"
        parts = [f"{key}: {count:,}" for key, count in sorted(self.counts.items())]
        return " | ".join(parts)
