"""Diagonal support and resistance, built the way V06 describes it.

Chapter 7.1 of the guide, which is also the whole specification:

    "Mindestens zwei signifikante Ankerpunkte. Offensichtliche Hochs/Tiefs mit
     sauberer Wegbewegung verwenden. Der Creator bevorzugt Dochte, akzeptiert
     aber in manchen Fällen Bodies. Entscheidend ist Konsistenz: nicht zwischen
     Docht und Body wechseln, um die eigene Erwartung passend zu machen."

That last sentence is a rule about the person drawing the line, and it is the
one worth encoding: a line fitted to whichever of wick or body happens to
produce a nicer picture is a line that will always exist. This module uses
wicks, always, for both kinds. `ANCHOR_SOURCE` says so in one place so that
changing it is a decision rather than a drift.

**A line is anchored on swings, not on bars.** Swings are confirmed late by
construction -- a high is only a high once price has turned away from it -- and
a trendline inherits that lateness. It becomes knowable on the bar its second
anchor was confirmed, never on the bar the anchor formed, which is the same
no-lookahead rule the rest of the analysis holds to.

**Two anchors make a line; a third contact makes it worth something.** Any two
points define a line, so a two-anchor trendline is a hypothesis with no
evidence. `touches` counts how often price came back and respected it, and
`is_validated` is what a setup should ask about.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from traidingbrain.analysis.structure import StructureTimeline, Swing, SwingKind

#: Which part of the candle anchors a line.
#:
#: Wicks, for both kinds, because V06 prefers them and because the rule that
#: matters is consistency rather than the choice itself. Named so that the
#: decision is visible in one place instead of implied by two array lookups.
ANCHOR_SOURCE = "wick"

#: Fewest anchors before a line exists at all.
MIN_ANCHORS = 2

#: Contacts before a line counts as validated. Three, because two is the line
#: itself: any two points lie on one, so a two-anchor line is a hypothesis with
#: no evidence for it yet.
MIN_TOUCHES = 3

#: How near a swing has to come, in ATR, to count as touching the line.
#:
#: Price does not land on a diagonal exactly, and a tolerance in price would
#: mean something different on BTC than on XRP. A quarter of an ATR is tight
#: enough that a line through unrelated swings does not collect touches by
#: accident.
TOUCH_TOLERANCE_ATR = 0.25

#: How far past a line a swing may poke before the line is abandoned.
#:
#: A resistance line that price has closed well above is not resistance any
#: more. Larger than the touch tolerance, so that a swing grazing the line
#: counts as a touch rather than as a break.
BREAK_TOLERANCE_ATR = 0.6

#: How many recent swings are considered as the second anchor.
#:
#: Every pair of swings defines a line, so without a bound this is quadratic in
#: the length of the run and most of the pairs are nonsense anyway -- a high
#: from two years ago and one from today describe nothing a trader would draw.
LOOKBACK_SWINGS = 10

#: Bars after which a line is dropped even if nothing broke it.
MAX_AGE_BARS = 400

#: Fewest bars between the two anchors.
#:
#: Without this the pairs include adjacent swings, and a line through two highs
#: a few bars apart is a near-vertical segment that extends to nonsense within
#: a day. Measured on BTC hourly: 78 lines survived every other filter, one of
#: them falling 73 points a candle. A trendline is a claim about a trend, and
#: two points an hour apart make no such claim.
MIN_ANCHOR_SPAN = 20

#: Steepest line worth keeping, as a fraction of ATR per bar.
#:
#: A diagonal that moves more than this each bar outruns the market it is drawn
#: on and is a drawing accident rather than a level. Generous, because a real
#: trendline in a fast market is steep; it only excludes the absurd.
MAX_SLOPE_ATR = 0.5


class TrendlineKind(StrEnum):
    RESISTANCE = "resistance"
    """Through swing highs: a falling or rising ceiling."""

    SUPPORT = "support"
    """Through swing lows."""


@dataclass(frozen=True)
class Trendline:
    """A diagonal level, with everything needed to judge it."""

    kind: TrendlineKind
    first_index: int
    first_price: float
    second_index: int
    second_price: float
    confirmed_index: int
    """The bar this became knowable on -- the second anchor's confirmation.

    Not the bar the anchor formed on. A swing high is only a high once price
    has turned away from it, and a line that claimed to exist earlier would be
    reading the future."""

    touches: int = MIN_ANCHORS
    broken_index: int | None = None

    @property
    def slope(self) -> float:
        span = self.second_index - self.first_index
        return (self.second_price - self.first_price) / span if span else 0.0

    def price_at(self, index: int) -> float:
        """Where the line sits at a bar, extended in both directions."""
        return self.first_price + self.slope * (index - self.first_index)

    @property
    def is_validated(self) -> bool:
        """Has price come back and respected it?

        Two anchors are the line itself. V06's own wording is "mindestens zwei
        signifikante Ankerpunkte; dritter Kontakt" -- the third contact is what
        separates a drawn line from an observed one.
        """
        return self.touches >= MIN_TOUCHES

    @property
    def is_falling(self) -> bool:
        return self.slope < 0


def _anchor_prices(frame: pd.DataFrame, kind: TrendlineKind) -> np.ndarray:
    column = "high" if kind is TrendlineKind.RESISTANCE else "low"
    return frame[column].to_numpy(dtype="float64")


def find_trendlines(
    frame: pd.DataFrame, structure: StructureTimeline, atr: pd.Series
) -> list[Trendline]:
    """Every trendline the swings support, each dated to when it was knowable.

    Built once over the whole series rather than per bar. A caller filters by
    `confirmed_index` and `broken_index`, which is what keeps the no-lookahead
    guarantee while costing one pass.
    """
    units = atr.to_numpy(dtype="float64")
    swings = structure.all_swings()
    out: list[Trendline] = []

    for kind in (TrendlineKind.RESISTANCE, TrendlineKind.SUPPORT):
        wanted = SwingKind.HIGH if kind is TrendlineKind.RESISTANCE else SwingKind.LOW
        same = [swing for swing in swings if swing.kind is wanted]
        prices = _anchor_prices(frame, kind)
        for position, second in enumerate(same):
            start = max(0, position - LOOKBACK_SWINGS)
            for first in same[start:position]:
                line = _build(
                    kind, first, second, prices=prices, units=units, length=len(frame)
                )
                if line is not None:
                    out.append(line)
    return out


def _build(
    kind: TrendlineKind,
    first: Swing,
    second: Swing,
    *,
    prices: np.ndarray,
    units: np.ndarray,
    length: int,
) -> Trendline | None:
    """One candidate line, counted and dated, or None if it never held.

    The counting walks forward from the second anchor only. Bars before it
    could not have been judged against a line that did not exist yet, and
    including them is the quiet way a trendline study scores itself on
    hindsight.
    """
    span = second.index - first.index
    if span < MIN_ANCHOR_SPAN:
        return None

    confirmed = max(first.confirmed_index, second.confirmed_index)
    slope = (second.price - first.price) / span
    unit_here = units[min(confirmed, len(units) - 1)]
    if not np.isfinite(unit_here) or unit_here <= 0:
        return None
    if abs(slope) > MAX_SLOPE_ATR * unit_here:
        return None
    touches = MIN_ANCHORS
    broken: int | None = None

    for index in range(confirmed, min(length, confirmed + MAX_AGE_BARS)):
        unit = units[index]
        if not np.isfinite(unit) or unit <= 0:
            continue
        level = first.price + slope * (index - first.index)
        distance = prices[index] - level
        if kind is TrendlineKind.SUPPORT:
            distance = -distance

        if distance > BREAK_TOLERANCE_ATR * unit:
            broken = index
            break
        if abs(distance) <= TOUCH_TOLERANCE_ATR * unit:
            touches += 1

    return Trendline(
        kind=kind,
        first_index=first.index,
        first_price=first.price,
        second_index=second.index,
        second_price=second.price,
        confirmed_index=confirmed,
        touches=touches,
        broken_index=broken,
    )


class TrendlineTimeline:
    """Which lines were drawable at each bar.

    The same shape as the other timelines here: built once, asked per bar, and
    the only accessor takes an index so that a caller cannot accidentally read
    a line that had not been confirmed yet.
    """

    def __init__(
        self, frame: pd.DataFrame, structure: StructureTimeline, atr: pd.Series
    ) -> None:
        self._lines = find_trendlines(frame, structure, atr)

    def __len__(self) -> int:
        return len(self._lines)

    def known_at(self, index: int) -> list[Trendline]:
        """Lines confirmed by this bar and not yet broken, newest first."""
        live = [
            line
            for line in self._lines
            if line.confirmed_index <= index
            and (line.broken_index is None or line.broken_index > index)
            and index - line.confirmed_index <= MAX_AGE_BARS
        ]
        live.sort(key=lambda line: line.confirmed_index, reverse=True)
        return live

    def validated_at(self, index: int) -> list[Trendline]:
        """Only the lines price has come back to and respected."""
        return [line for line in self.known_at(index) if line.is_validated]

    def best_at(self, index: int, *, limit: int = 4) -> list[Trendline]:
        """The few lines worth drawing or trading, best first.

        Seventy-eight validated lines at once is not a chart and not a signal;
        every diagonal that survives the filters is still a line somebody could
        have drawn, and a person draws two or three. Ranked by contacts first --
        the evidence -- and by the span between anchors second, because a line
        resting on highs two days apart describes more than one resting on highs
        two hours apart.
        """
        ranked = sorted(
            self.validated_at(index),
            key=lambda line: (line.touches, line.second_index - line.first_index),
            reverse=True,
        )
        return ranked[:limit]

    def broken_at(self, index: int) -> list[Trendline]:
        """Lines whose break happened on exactly this bar.

        The event setup B is built on. Asked for the bar rather than for a
        window, because "broken recently" is a different claim and the setup
        wants the bar it happened on.
        """
        return [line for line in self._lines if line.broken_index == index]
