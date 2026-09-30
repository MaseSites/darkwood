"""Supply/demand zones and order blocks, as V09, V11 and V12 define them.

Three objects that look alike on a chart and are not the same thing, so the
guide keeps them apart and so does this module:

**Supply and demand (V09).** The last opposite candle before an aggressive move
that broke structure. The zone runs from that candle's low to its high. The
video wants a *first* retest and a *slow* return; a sharp aggressive return is
its own refusal.

**Order blocks (V11).** The last candle before a reversal, but only once three
things have happened: it swept liquidity to its left, price left it impulsively
and opened a fair value gap, and that move produced a CHoCH. The block must stay
unmitigated until the CHoCH -- if price came back first, V11 sees no reason to
trade it later.

**Inducement (V12).** When several zones stack up, the lowest is not
automatically the one to use. A zone with an untested imbalance still below it
is a candidate for being run through; the "true zone" is the one whose impulse
actually broke the relevant high.

**Everything here is confirmation-indexed.** A zone's candle sits at
`origin_index`, but the zone is not *knowable* until the criteria that validate
it have completed, which is `confirmed_index`. That gap is the whole game: an
order block's three criteria finish at the CHoCH, often many bars after the
candle, and a backtest that placed the zone on the candle would be trading on a
verdict that did not exist yet. Reading a zone before its confirmation index is
made impossible rather than discouraged -- `known_at` is the only accessor.

What is deliberately absent: breaker blocks and IFVG. The guide's chapters 16
and 18 state that no playlist video defines them, and inventing a definition
here would put the strategy on a rule nobody in the sources ever gave.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt
import pandas as pd

from traidingbrain.analysis.liquidity import Zone, ZoneKind, find_fair_value_gaps
from traidingbrain.analysis.structure import StructureTimeline, Swing, SwingKind
from traidingbrain.domain.enums import Bias

#: How far back the search for the origin candle of an impulse may run.
#:
#: V09 describes the origin as "die letzte Gegenkerze vor dem Impuls", which
#: assumes you can see where the impulse began. Walking back indefinitely would
#: find an origin for any move at all, including a slow drift the video
#: explicitly refuses; this bounds "the impulse" to something a person would
#: point at as one leg.
MAX_IMPULSE_BARS = 12

#: V09 wants an *aggressive* move. Measured as the leg's extent in ATR, because
#: "aggressive" on a quiet day and on a violent one are different prices.
MIN_IMPULSE_ATR = 1.5

#: V09: the return into the zone should be slow; "ein scharfer aggressiver
#: Rücklauf" is one of its no-trade conditions. Same unit, per bar.
MAX_APPROACH_ATR_PER_BAR = 1.0

Floats = npt.NDArray[np.float64]


class ZoneRole(StrEnum):
    """What a zone is, kept distinct because the sources keep them distinct."""

    DEMAND = "demand"
    SUPPLY = "supply"
    BULLISH_ORDER_BLOCK = "bullish_order_block"
    BEARISH_ORDER_BLOCK = "bearish_order_block"


@dataclass(frozen=True)
class StructuralZone:
    """One zone, with the bar it came from and the bar it became usable on."""

    role: ZoneRole
    low: float
    high: float
    #: The candle the zone is drawn from.
    origin_index: int
    #: The first bar on which every criterion had completed. Never earlier than
    #: `origin_index`, and usually well after it.
    confirmed_index: int
    #: Which video's rule produced it, so a reading traces back to a source.
    source: str
    #: V09 prefers a gap at the origin; V11 requires one.
    has_fvg: bool = False
    #: Whether the impulse that left the zone broke structure (V09's condition).
    broke_structure: bool = False

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2.0

    @property
    def height(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.role in (ZoneRole.DEMAND, ZoneRole.BULLISH_ORDER_BLOCK)

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    @property
    def confirmation_lag(self) -> int:
        return self.confirmed_index - self.origin_index


@dataclass(frozen=True)
class ZoneTouch:
    """A visit to a zone, and whether it is the one the sources want.

    V09 wants the *first* return and wants it slow. Both are properties of the
    visit rather than of the zone, so they are answered here -- and `is_first`
    is the reason zones carry their touch history at all.
    """

    zone: StructuralZone
    index: int
    is_first: bool
    approach_atr_per_bar: float

    @property
    def was_slow(self) -> bool:
        return self.approach_atr_per_bar <= MAX_APPROACH_ATR_PER_BAR


def find_supply_demand_zones(
    frame: pd.DataFrame,
    atr: pd.Series,
    structure: StructureTimeline,
) -> list[StructuralZone]:
    """V09's zones: the origin candle of an aggressive, structure-breaking move.

    Built off breaks of structure rather than off every impulse, because V09's
    condition is that the move "brach Struktur" -- a hard test the timeline
    already performs, and one that keeps this from marking a zone on every
    energetic candle on the chart.
    """
    opens = frame["open"].to_numpy(dtype="float64")
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    atr_values = atr.to_numpy(dtype="float64")
    gaps = _gaps_by_index(frame, atr)

    zones: list[StructuralZone] = []
    for index in range(len(frame)):
        state = structure.state_at(index)
        if state.bars_since_bos != 0:
            # Only the bar a break confirms on. Every later bar would rediscover
            # the same zone and the list would fill with duplicates.
            continue

        unit = atr_values[index]
        if not np.isfinite(unit) or unit <= 0:
            continue

        if state.break_direction is Bias.NEUTRAL:
            continue
        upward = state.break_direction is Bias.BULLISH
        origin = _impulse_origin(opens, closes, index, upward=upward)
        if origin is None:
            continue

        extent = (highs[index] - lows[origin]) if upward else (highs[origin] - lows[index])
        if extent < MIN_IMPULSE_ATR * unit:
            # Not aggressive. V09 refuses a "schwacher Drift" as a zone, and
            # this is the only place that refusal can be enforced.
            continue

        zones.append(
            StructuralZone(
                role=ZoneRole.DEMAND if upward else ZoneRole.SUPPLY,
                low=float(lows[origin]),
                high=float(highs[origin]),
                origin_index=origin,
                confirmed_index=index,
                source="V09",
                has_fvg=_has_gap_between(gaps, origin, index, bullish=upward),
                broke_structure=True,
            )
        )
    return zones


def find_order_blocks(
    frame: pd.DataFrame,
    atr: pd.Series,
    structure: StructureTimeline,
) -> list[StructuralZone]:
    """V11's order blocks, and only the ones that pass all three criteria.

    1. The candle sweeps liquidity to its left.
    2. Price leaves impulsively and opens a fair value gap.
    3. The move produces a CHoCH.

    Plus the condition that decides most candidates: the block must stay
    unmitigated until the CHoCH. V11 is explicit that if price came back before
    then, there is no reason to trade the block later -- so a candidate that
    would otherwise look perfect is dropped, and dropping it is the rule.
    """
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    opens = frame["open"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    gaps = _gaps_by_index(frame, atr)

    blocks: list[StructuralZone] = []
    for index in range(len(frame)):
        state = structure.state_at(index)
        if state.bars_since_choch != 0:
            continue

        if state.break_direction is Bias.NEUTRAL:
            continue
        upward = state.break_direction is Bias.BULLISH
        # The block sits at the turn, not at the bar the turn was confirmed on.
        #
        # This is the correction that makes the rule mean what V11 says. A CHoCH
        # confirms several bars after the reversal, because the swing it breaks
        # needs its own confirmation first. Walking back from the confirmation
        # bar lands in the middle of the move away, and the candle found there
        # has almost always been traded through already -- so the unmitigated
        # test rejects nearly every candidate and the setup silently never
        # fires. Anchoring on the swing that turned is what "die letzte Kerze
        # vor einem starken Richtungswechsel" actually points at.
        turn = state.last_swing_low if upward else state.last_swing_high
        if turn is None:
            continue
        origin = _last_opposite_candle(opens, closes, turn.index, upward=upward)
        if origin is None:
            continue

        # (1) the candle swept liquidity to its left
        if not _swept_left(structure, highs, lows, origin, upward=upward):
            continue
        # (2) price left impulsively and opened an imbalance
        if not _has_gap_between(gaps, origin, index, bullish=upward):
            continue
        # (3) the block survived untouched until the CHoCH that validates it.
        # V11 is explicit: if price came back before then, there is no reason to
        # trade the block later. Dropping an otherwise perfect candidate here is
        # the rule, not a shortcoming of it.
        if _mitigated_before(
            highs, lows, origin, index, low=lows[origin], high=highs[origin], bullish=upward
        ):
            continue

        blocks.append(
            StructuralZone(
                role=ZoneRole.BULLISH_ORDER_BLOCK if upward else ZoneRole.BEARISH_ORDER_BLOCK,
                low=float(lows[origin]),
                high=float(highs[origin]),
                origin_index=origin,
                confirmed_index=index,
                source="V11",
                has_fvg=True,
                broke_structure=False,
            )
        )
    return blocks


class ZoneTimeline:
    """Every zone, readable only from the bar it was confirmed on.

    The accessor is `known_at` rather than a list, because a list invites a
    filter written once correctly and copied somewhere without the filter. The
    zones exist; reaching one early does not.
    """

    def __init__(
        self,
        frame: pd.DataFrame,
        atr: pd.Series,
        structure: StructureTimeline,
    ) -> None:
        self.frame = frame
        self._atr = atr.to_numpy(dtype="float64")
        self._highs = frame["high"].to_numpy(dtype="float64")
        self._lows = frame["low"].to_numpy(dtype="float64")

        zones = find_supply_demand_zones(frame, atr, structure)
        zones += find_order_blocks(frame, atr, structure)
        zones.sort(key=lambda zone: zone.confirmed_index)
        self._zones = zones
        self._confirmed = [zone.confirmed_index for zone in zones]

    def __len__(self) -> int:
        return len(self._zones)

    def known_at(self, index: int) -> list[StructuralZone]:
        """Zones the engine could legitimately have drawn by this bar."""
        return self._zones[: bisect_right(self._confirmed, index)]

    def unmitigated_at(self, index: int) -> list[StructuralZone]:
        """Known zones price has not traded back into yet.

        Mitigation is recomputed from the bars rather than cached on the zone,
        so a zone object is a statement about the past that never changes. A
        mutable `mitigated` flag would make the same zone mean different things
        at different points in one backtest.
        """
        return [
            zone
            for zone in self.known_at(index)
            if not self._touched_between(zone, zone.confirmed_index + 1, index)
        ]

    def touch_at(self, zone: StructuralZone, index: int) -> ZoneTouch | None:
        """This bar's visit to a zone, if it is one.

        V09 wants the first return and wants it slow, so both are reported. The
        speed is the approach measured over the bars it took, in ATR -- the one
        way to say "aggressive" that means the same thing in a quiet week and a
        violent one.
        """
        if index <= zone.confirmed_index or not self._touched(zone, index):
            return None
        first = not self._touched_between(zone, zone.confirmed_index + 1, index - 1)
        return ZoneTouch(
            zone=zone,
            index=index,
            is_first=first,
            approach_atr_per_bar=self._approach_speed(zone, index),
        )

    def _touched(self, zone: StructuralZone, index: int) -> bool:
        if index < 0 or index >= len(self._highs):
            return False
        return bool(self._lows[index] <= zone.high and self._highs[index] >= zone.low)

    def _touched_between(self, zone: StructuralZone, start: int, end: int) -> bool:
        if end < start:
            return False
        lows = self._lows[start : end + 1]
        highs = self._highs[start : end + 1]
        return bool(np.any((lows <= zone.high) & (highs >= zone.low)))

    def _approach_speed(self, zone: StructuralZone, index: int) -> float:
        """How fast price covered the last leg into the zone, in ATR per bar."""
        unit = self._atr[index]
        if not np.isfinite(unit) or unit <= 0:
            return float("inf")
        start = max(zone.confirmed_index + 1, index - MAX_IMPULSE_BARS)
        if index <= start:
            return float("inf")
        window_high = float(np.max(self._highs[start : index + 1]))
        window_low = float(np.min(self._lows[start : index + 1]))
        distance = (window_high - zone.high) if zone.is_bullish else (zone.low - window_low)
        return float(max(distance, 0.0) / unit / (index - start))


def true_zone(
    zones: list[StructuralZone],
    price: float,
    *,
    bullish: bool,
) -> StructuralZone | None:
    """V12's choice among stacked zones, which is not the nearest or the deepest.

    The video's rule in one sentence: do not take a zone that still has an
    untested imbalance beyond it, because price is likely to run through to
    that one first -- the lower zone is *inducement*. What is wanted is the zone
    whose own impulse broke the relevant high.

    Returns None rather than a fallback when nothing qualifies. A fallback here
    would be the exact mistake the video warns about, dressed as a default.
    """
    candidates = [
        zone
        for zone in zones
        if zone.is_bullish == bullish
        and zone.broke_structure
        and (zone.high < price if bullish else zone.low > price)
    ]
    if not candidates:
        return None

    def has_untested_zone_beyond(zone: StructuralZone) -> bool:
        return any(
            (other.low < zone.low) if bullish else (other.high > zone.high)
            for other in zones
            if other.is_bullish == bullish and other is not zone
        )

    structural = [zone for zone in candidates if not has_untested_zone_beyond(zone)]
    if not structural:
        return None
    # The nearest of what is left. Among zones that all caused the break, the
    # closest is the one price reaches first.
    return max(structural, key=lambda zone: zone.high) if bullish else min(
        structural, key=lambda zone: zone.low
    )


# --------------------------------------------------------------------------- #
# Shared machinery
# --------------------------------------------------------------------------- #


def _gaps_by_index(frame: pd.DataFrame, atr: pd.Series) -> dict[int, list[Zone]]:
    """Fair value gaps keyed by the bar they became visible on."""
    found: dict[int, list[Zone]] = {}
    for gap in find_fair_value_gaps(frame, atr):
        found.setdefault(gap.created_index, []).append(gap)
    return found


def _has_gap_between(
    gaps: dict[int, list[Zone]], origin: int, end: int, *, bullish: bool
) -> bool:
    """Did the move away from the origin open an imbalance?"""
    wanted = ZoneKind.FVG_BULLISH if bullish else ZoneKind.FVG_BEARISH
    return any(
        gap.kind is wanted
        for index in range(origin, end + 1)
        for gap in gaps.get(index, ())
    )


def _impulse_origin(
    opens: Floats, closes: Floats, end: int, *, upward: bool
) -> int | None:
    """The last candle against the move, walking back from where it ended.

    V09's "letzte Gegenkerze vor dem Impuls". Bounded by `MAX_IMPULSE_BARS`,
    because an unbounded walk finds an origin for any move at all -- including
    the slow drift the video refuses.
    """
    return _last_opposite_candle(opens, closes, end, upward=upward, limit=MAX_IMPULSE_BARS)


def _last_opposite_candle(
    opens: Floats, closes: Floats, end: int, *, upward: bool, limit: int = MAX_IMPULSE_BARS
) -> int | None:
    """The nearest candle at or before `end` that closed against the direction."""
    if end < 0 or end >= len(opens):
        return None
    for index in range(end, max(end - limit, 0) - 1, -1):
        against = closes[index] < opens[index] if upward else closes[index] > opens[index]
        if against:
            return index
    return None


def _swept_left(
    structure: StructureTimeline,
    highs: Floats,
    lows: Floats,
    index: int,
    *,
    upward: bool,
) -> bool:
    """V11's first criterion: the candle took liquidity to its left.

    For a bullish block that means its low went below a swing low the market had
    already made -- the stops resting under it. Only swings confirmed before the
    candle count, which is what stops this from being a statement about a level
    nobody could see yet.
    """
    kind = SwingKind.LOW if upward else SwingKind.HIGH
    prior: list[Swing] = [
        swing
        for swing in structure.swings_known_at(index)
        if swing.kind is kind and swing.index < index
    ]
    if not prior:
        return False
    recent = prior[-4:]
    if upward:
        return any(lows[index] < swing.price for swing in recent)
    return any(highs[index] > swing.price for swing in recent)


def _mitigated_before(
    highs: Floats,
    lows: Floats,
    origin: int,
    end: int,
    *,
    low: float,
    high: float,
    bullish: bool,
) -> bool:
    """Did price come *back* into the block before the CHoCH validated it?

    The word doing the work is "back". The bars right after the origin are still
    in contact with it -- they are the move leaving, and the first of them opens
    at the origin's own close. Counting those as a return marks almost every
    candidate as mitigated, which is how a criterion with a sound definition
    ends up rejecting the entire market.

    So the clock starts once price has cleared the block entirely. If it never
    clears it before the CHoCH, there was no return either; whether that counts
    as a block at all is decided by the displacement criterion, which is the one
    the source gives for it.
    """
    departed: int | None = None
    for index in range(origin + 1, end):
        clear = lows[index] > high if bullish else highs[index] < low
        if clear:
            departed = index + 1
            break
    if departed is None or departed >= end:
        return False
    window_lows = lows[departed:end]
    window_highs = highs[departed:end]
    return bool(np.any((window_lows <= high) & (window_highs >= low)))
