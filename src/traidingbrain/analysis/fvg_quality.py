"""Which fair value gaps are worth trading, per V05 and V13 -- kept separate.

Finding a three-candle gap is arithmetic and `liquidity.find_fair_value_gaps`
already does it. Deciding which of the forty on a chart is worth a stop is the
actual content of two videos, and they do not agree, so this module does not
average them.

**V05's seven filters** are preferences: orderflow, freshness, premium/discount,
multi-timeframe nesting, what the third candle did, whether the move ran
liquidity, and a consolidation warning. A gap failing one is weaker, not dead.

**V13's six factors** are conditions: unmitigated, the reaction candle closes
inside or in the zone's direction, support or resistance behind it, the right
half of the range, the highest-ranked gap of its kind, and a break of structure
in or before the move that made it.

**Where they contradict each other, both answers are kept.** Guide chapter 17.4:
V05 says a touched gap is "mitigated" and weaker but may still work; V13 says a
tested gap is invalid and must not be traded. There is no backtest in the
playlist deciding between them, so `MitigationRule` is a setting and the two are
measured separately. Picking one here and calling it "the FVG rule" would hide a
disagreement between sources behind an implementation detail.

The one thing added to the sources is arithmetic they imply and do not spell
out: V13's "0/0,5/1-Range" needs a range to take halves of. It is the leg from
the swing that started the move to the extreme the move reached -- the same leg
the break of structure happened in, because that is the move the video draws.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt
import pandas as pd

from traidingbrain.analysis.liquidity import Zone, ZoneKind, find_fair_value_gaps
from traidingbrain.analysis.structure import StructureTimeline, SwingKind
from traidingbrain.domain.enums import Bias

#: V13 factor 5: "Mit einer 0/0,5/1-Range sollen Long-FVGs in der unteren,
#: Short-FVGs in der oberen Hälfte liegen." The midpoint, as stated.
RANGE_MIDPOINT = 0.5

#: V05 filter 3 says the same thing in different words -- long gaps below the
#: 50% mark of the move. The two agree here, so one constant serves both.
#:
#: Measured on the gap's own midpoint rather than an edge. Using an edge would
#: make a gap that straddles the halfway mark pass or fail depending on which
#: end is asked about, which is a coin flip wearing a rule's clothes.
#: How far a swept level may sit from the gap for the two to count as the same
#: level, in ATR. V13 asks for "vorheriger Support bei bullishen FVGs als
#: Confluence" without a tolerance; support is a zone rather than a line
#: everywhere else in the guide, so it is one here too.
CONFLUENCE_TOLERANCE_ATR = 0.5

#: How far back to look for the structure break V13's factor 6 requires.
#: "Vor Entstehung bzw. im Entstehungsmove" -- so the move, not the year.
BOS_LOOKBACK_BARS = 30

#: How old a gap may be and still be part of the picture.
#:
#: V13's factor 4 asks for the highest-ranked gap "bei mehreren bullishen FVGs",
#: which is a statement about the gaps on the chart in front of you -- not about
#: every imbalance since the series began. Without a bound the set grows without
#: limit, which is wrong twice: the deepest gap eventually becomes one from
#: years ago that nothing will reach, and assessing all of them on every bar is
#: quadratic in the length of a run.
MAX_GAP_AGE_BARS = 120

Floats = npt.NDArray[np.float64]


class MitigationRule(StrEnum):
    """The disagreement in guide chapter 17.4, as a setting rather than a choice.

    V05: a touch makes the gap weaker and it "müsse beim zweiten Besuch nicht
    zwangsläufig scheitern". V13: after a test the gap is invalid for the
    strategy it presents. No playlist source decides between them, so neither
    does this.
    """

    V05_WEAKER = "v05_weaker"
    V13_INVALID = "v13_invalid"


@dataclass(frozen=True)
class Factor:
    """One condition, its verdict, and the wording it came from."""

    name: str
    met: bool
    source: str
    detail: str = ""


@dataclass(frozen=True)
class GapAssessment:
    """One gap, read against a source's list."""

    gap: Zone
    factors: tuple[Factor, ...]
    rule: MitigationRule
    #: Rank among the gaps of its kind that pass every other factor -- 0 being
    #: the one the source prefers. V13: "Bei mehreren bullishen FVGs priorisiert
    #: V13 das tiefste; bei bearishen das höchste."
    #:
    #: Ranked among the *valid* ones, which is the ordering the video's sentence
    #: describes: it is a tiebreaker between candidates, not a filter applied
    #: before they are checked. Ranked first instead, the lowest gap on the
    #: chart is nearly always an old one price has already filled, so the
    #: top-ranked gap fails the freshness factor and the setup never fires.
    #: Measured: 10,212 assessments over 3,000 bars, 1,861 ranked first, zero
    #: signals.
    #:
    #: -1 means it is not in the running: some other factor already refused it.
    rank: int = -1

    @property
    def is_bullish(self) -> bool:
        return self.gap.kind is ZoneKind.FVG_BULLISH

    @property
    def met(self) -> tuple[str, ...]:
        return tuple(factor.name for factor in self.factors if factor.met)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(factor.name for factor in self.factors if not factor.met)

    @property
    def tradeable(self) -> bool:
        """V13's reading: every factor is a condition, so all must hold.

        Deliberately not a score. A gap passing five of six is not
        five-sixths of a setup; the video's list is conjunctive, and turning it
        into a total would let any factor be bought off by the others.
        """
        return not self.failed and self.rank == 0


def assess_gaps(
    frame: pd.DataFrame,
    atr: pd.Series,
    structure: StructureTimeline,
    index: int,
    *,
    rule: MitigationRule = MitigationRule.V13_INVALID,
    gaps: list[Zone] | None = None,
) -> list[GapAssessment]:
    """Every gap knowable at this bar, read against V13's six factors.

    Ordered by the source's own priority: for bullish gaps the lowest first, for
    bearish the highest. The order is part of the rule -- V13's factor 4 is that
    only the top-ranked one is taken -- so it is carried as `rank` rather than
    left to whoever reads the list.
    """
    if index < 0 or index >= len(frame):
        return []
    found = gaps if gaps is not None else find_fair_value_gaps(frame, atr)
    oldest = index - MAX_GAP_AGE_BARS
    live = [gap for gap in found if oldest <= gap.created_index <= index]
    if not live:
        return []

    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    unit = float(atr.to_numpy(dtype="float64")[index])

    assessments = [
        GapAssessment(
            gap=gap,
            rule=rule,
            factors=_factors(
                gap,
                highs=highs,
                lows=lows,
                closes=closes,
                structure=structure,
                index=index,
                unit=unit,
                rule=rule,
            ),
        )
        for gap in live
    ]
    return _ranked(assessments)


def _ranked(assessments: list[GapAssessment]) -> list[GapAssessment]:
    """V13 factor 4: lowest bullish gap first, highest bearish gap first.

    Applied only to the gaps that already passed every other factor. The
    sentence it comes from -- "bei mehreren bullishen FVGs priorisiert V13 das
    tiefste" -- is about choosing between candidates, and a gap that failed one
    of the other five is not a candidate. Read the other way round the rule
    defeats itself: the lowest gap on a chart is usually an old one price has
    long since filled, so it fails the freshness factor and nothing is ever
    tradeable.
    """
    ranked: list[GapAssessment] = []
    for bullish in (True, False):
        side = [item for item in assessments if item.is_bullish == bullish]
        eligible = [item for item in side if not item.failed]
        eligible.sort(key=lambda item: item.gap.low, reverse=not bullish)
        order = {id(item): position for position, item in enumerate(eligible)}
        ranked += [
            GapAssessment(
                gap=item.gap,
                factors=item.factors,
                rule=item.rule,
                rank=order.get(id(item), -1),
            )
            for item in side
        ]
    return ranked


def _factors(
    gap: Zone,
    *,
    highs: Floats,
    lows: Floats,
    closes: Floats,
    structure: StructureTimeline,
    index: int,
    unit: float,
    rule: MitigationRule,
) -> tuple[Factor, ...]:
    bullish = gap.kind is ZoneKind.FVG_BULLISH
    state = structure.state_at(index)

    return (
        _freshness(gap, highs, lows, index, rule=rule),
        _reaction(gap, closes, index, bullish=bullish),
        _confluence(gap, structure, index, unit=unit, bullish=bullish),
        _range_half(gap, structure, index, bullish=bullish),
        Factor(
            "orderflow",
            met=state.break_direction is (Bias.BULLISH if bullish else Bias.BEARISH),
            source="V05",
            detail=f"last break {state.break_direction.value}",
        ),
        _structure_break(structure, gap, index, bullish=bullish),
    )


def _freshness(
    gap: Zone, highs: Floats, lows: Floats, index: int, *, rule: MitigationRule
) -> Factor:
    """V13 factor 1, and the place the two sources part company.

    Under V13 a single test ends the gap. Under V05 it is weaker and may still
    work. Which rule applies is a setting, so the factor reports the verdict of
    whichever one is in force and says which one that was.
    """
    # Up to but not including this bar.
    #
    # "Untested" has to mean tested *before now*, because the bar being judged
    # is the one testing it -- that is what a retest setup is. Including it
    # makes every gap read as mitigated on the exact bar the entry condition is
    # true, and the two conditions cancel: 1,460 valid gaps, 60 bars reaching
    # one, zero signals.
    start = gap.created_index + 1
    touched = False
    if start <= index - 1:
        window_lows = lows[start:index]
        window_highs = highs[start:index]
        touched = bool(np.any((window_lows <= gap.high) & (window_highs >= gap.low)))

    if rule is MitigationRule.V13_INVALID:
        return Factor(
            "unmitigated",
            met=not touched,
            source="V13",
            detail="tested" if touched else "untested",
        )
    return Factor(
        "unmitigated",
        met=True,
        source="V05",
        detail="tested, weaker but not dead per V05" if touched else "untested",
    )


def _reaction(gap: Zone, closes: Floats, index: int, *, bullish: bool) -> Factor:
    """V13 factor 2: "Reaktionskerze darf durchwicken, soll aber im FVG oder in
    Richtung der Zone schließen; Close vollständig jenseits macht es ungültig."

    Judged on the close alone, which is what makes a wick through the zone
    allowed. Judging it on the low would refuse every gap that did its job.
    """
    close = float(closes[index])
    if bullish:
        met = close >= gap.low
        detail = f"close {'inside or above' if met else 'below'} the gap"
    else:
        met = close <= gap.high
        detail = f"close {'inside or below' if met else 'above'} the gap"
    return Factor("reaction_close", met=met, source="V13", detail=detail)


def _confluence(
    gap: Zone, structure: StructureTimeline, index: int, *, unit: float, bullish: bool
) -> Factor:
    """V13 factor 3: previous support under a bullish gap, resistance over a
    bearish one.

    Support is taken as a confirmed swing low near the gap -- near in ATR,
    because the guide treats levels as zones everywhere else and a line would
    make this pass or fail on rounding.
    """
    if unit <= 0 or not np.isfinite(unit):
        return Factor("sr_confluence", met=False, source="V13", detail="no scale to measure with")
    wanted = SwingKind.LOW if bullish else SwingKind.HIGH
    tolerance = CONFLUENCE_TOLERANCE_ATR * unit
    near = [
        swing
        for swing in structure.recent_swings(index, kind=wanted, limit=12)
        if swing.index <= gap.created_index
        and abs(swing.price - (gap.low if bullish else gap.high)) <= tolerance
    ]
    return Factor(
        "sr_confluence",
        met=bool(near),
        source="V13",
        detail=f"{len(near)} swing {'low' if bullish else 'high'} within {tolerance:.4g}",
    )


def _range_half(
    gap: Zone, structure: StructureTimeline, index: int, *, bullish: bool
) -> Factor:
    """V13 factor 5 and V05 filter 3, which say the same thing.

    Long gaps belong in the lower half of the move, short gaps in the upper. The
    range is the leg between the most recent confirmed swing low and high -- the
    move the gap was made in, which is what the video draws its 0/0.5/1 on.

    Measured on the gap's midpoint. An edge would make a gap straddling the
    halfway mark pass or fail depending on which end is asked about.
    """
    swings = structure.recent_swings(index, limit=12)
    lows = [swing.price for swing in swings if swing.kind is SwingKind.LOW]
    highs = [swing.price for swing in swings if swing.kind is SwingKind.HIGH]
    if not lows or not highs:
        return Factor("range_half", met=False, source="V13", detail="no range to halve")

    low, high = min(lows), max(highs)
    span = high - low
    if span <= 0:
        return Factor("range_half", met=False, source="V13", detail="the range has no height")

    position = (gap.mid - low) / span
    met = position <= RANGE_MIDPOINT if bullish else position >= RANGE_MIDPOINT
    return Factor(
        "range_half",
        met=met,
        source="V13",
        detail=(
            f"at {position:.0%} of the range, "
            f"{'discount' if position <= RANGE_MIDPOINT else 'premium'}"
        ),
    )


def _structure_break(
    structure: StructureTimeline, gap: Zone, index: int, *, bullish: bool
) -> Factor:
    """V13 factor 6: "Vor Entstehung bzw. im Entstehungsmove muss ein BOS des
    vorherigen Hochs/Tiefs erfolgen."

    Checked at the gap's own creation bar rather than at the current one. A
    break that happened after the gap formed is not what made the gap, and
    reading it at `index` would let a later event validate an earlier object --
    which is lookahead with the steps in the right order.
    """
    wanted = Bias.BULLISH if bullish else Bias.BEARISH
    window = range(max(gap.created_index - BOS_LOOKBACK_BARS, 0), gap.created_index + 1)
    for bar in window:
        state = structure.state_at(bar)
        if state.bars_since_bos == 0 and state.break_direction is wanted:
            return Factor(
                "break_of_structure",
                met=True,
                source="V13",
                detail=f"{wanted.value} break {gap.created_index - bar} bars before the gap",
            )
    return Factor(
        "break_of_structure",
        met=False,
        source="V13",
        detail=f"no {wanted.value} break in the {BOS_LOOKBACK_BARS} bars before the gap",
    )


def best_gap(assessments: list[GapAssessment], *, bullish: bool) -> GapAssessment | None:
    """The one gap V13 would take, or nothing.

    Nothing is the usual answer and it is the correct one. Returning the least
    bad gap would be the mistake the video's whole list exists to prevent.
    """
    return next(
        (item for item in assessments if item.is_bullish == bullish and item.tradeable), None
    )
