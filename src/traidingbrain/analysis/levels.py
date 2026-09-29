"""The named price ladder -- the only prices the model ever refers to.

The model is never shown a price and never writes one. It is shown a list of
levels with opaque ids and their distance in ATR, and it answers by naming an id
plus an offset. `MarketSnapshot.resolve` turns that back into a number.

Two things this buys, and both matter more than they look:

* A hallucinated price is not something the guard has to catch. There is no field
  in which the model could put one.
* The ids have to be **stable for the same market shape**, or the decision cache
  never hits and a backtest costs full price on every re-run. So ids are assigned
  by a deterministic rule -- descending price -- rather than by discovery order,
  which would depend on which analysis ran first.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from traidingbrain.analysis.liquidity import ZoneKind
from traidingbrain.analysis.pipeline import FrameAnalysis
from traidingbrain.analysis.structure import SwingKind
from traidingbrain.domain.enums import LevelKind, Timeframe
from traidingbrain.domain.snapshot import Level

#: Upper bound on ladder size. Every extra level is prompt tokens on every call
#: and one more thing for the model to weigh; past a dozen or so they stop being
#: distinct landmarks and become a price list.
MAX_LEVELS = 14

#: Two candidate levels closer together than this are the same level.
MERGE_TOLERANCE_ATR = 0.08

#: Window used to count how often price has revisited a level.
TOUCH_LOOKBACK_BARS = 120

#: Kinds that stay in the ladder even when the ladder is full. Without a floor,
#: a cluster of near levels can crowd out the structural anchors a stop needs.
PROTECTED_KINDS = frozenset(
    {
        LevelKind.CURRENT,
        LevelKind.SWING_HIGH,
        LevelKind.SWING_LOW,
        LevelKind.PREV_DAY_HIGH,
        LevelKind.PREV_DAY_LOW,
    }
)


@dataclass(frozen=True)
class _Candidate:
    kind: LevelKind
    timeframe: Timeframe
    price: float
    age_bars: int


def _count_touches(frame: pd.DataFrame, price: float, upto_index: int, tolerance: float) -> int:
    """How often price has come back to a level, within the trailing window only."""
    start = max(0, upto_index - TOUCH_LOOKBACK_BARS + 1)
    highs = frame["high"].to_numpy(dtype="float64")[start : upto_index + 1]
    lows = frame["low"].to_numpy(dtype="float64")[start : upto_index + 1]
    return int(np.sum((lows <= price + tolerance) & (highs >= price - tolerance)))


def _swing_candidates(analysis: FrameAnalysis, index: int, limit: int = 3) -> list[_Candidate]:
    """Recent confirmed swings, and only confirmed ones.

    `recent_swings` filters on `confirmed_index`, so a swing that formed but is not
    yet knowable cannot reach the ladder.
    """
    out: list[_Candidate] = []
    for kind, level_kind in (
        (SwingKind.HIGH, LevelKind.SWING_HIGH),
        (SwingKind.LOW, LevelKind.SWING_LOW),
    ):
        for swing in analysis.structure.recent_swings(index, kind=kind, limit=limit):
            out.append(
                _Candidate(
                    kind=level_kind,
                    timeframe=analysis.timeframe,
                    price=swing.price,
                    age_bars=index - swing.index,
                )
            )
    return out


def _zone_candidates(analysis: FrameAnalysis, index: int) -> list[_Candidate]:
    """Liquidity pools and unfilled imbalances, as the levels they imply."""
    mapping = {
        ZoneKind.EQUAL_HIGHS: LevelKind.EQUAL_HIGHS,
        ZoneKind.EQUAL_LOWS: LevelKind.EQUAL_LOWS,
    }
    out: list[_Candidate] = []
    for zone in analysis.liquidity.state_at(index).zones:
        age = index - zone.created_index
        if zone.kind in mapping:
            out.append(
                _Candidate(
                    kind=mapping[zone.kind],
                    timeframe=analysis.timeframe,
                    price=zone.mid,
                    age_bars=age,
                )
            )
        else:
            # A gap is three levels: an entry edge, a midpoint and a far edge. The
            # midpoint is where imbalance is usually resolved, the edges are where
            # a stop can sit just outside it.
            for level_kind, price in (
                (LevelKind.FVG_HIGH, zone.high),
                (LevelKind.FVG_MID, zone.mid),
                (LevelKind.FVG_LOW, zone.low),
            ):
                out.append(
                    _Candidate(
                        kind=level_kind,
                        timeframe=analysis.timeframe,
                        price=price,
                        age_bars=age,
                    )
                )
    return out


def _session_candidates(
    higher: dict[Timeframe, tuple[FrameAnalysis, int]],
) -> list[_Candidate]:
    """Previous day and previous week extremes.

    The aligned index is already the newest *closed* bar on those frames, so these
    are genuinely the last completed session rather than the one in progress.
    """
    mapping = {
        Timeframe.D1: (LevelKind.PREV_DAY_HIGH, LevelKind.PREV_DAY_LOW),
        Timeframe.W1: (LevelKind.PREV_WEEK_HIGH, LevelKind.PREV_WEEK_LOW),
    }
    out: list[_Candidate] = []
    for timeframe, (high_kind, low_kind) in mapping.items():
        entry = higher.get(timeframe)
        if entry is None:
            continue
        analysis, index = entry
        out.append(
            _Candidate(
                kind=high_kind,
                timeframe=timeframe,
                price=float(analysis.frame["high"].iloc[index]),
                age_bars=0,
            )
        )
        out.append(
            _Candidate(
                kind=low_kind,
                timeframe=timeframe,
                price=float(analysis.frame["low"].iloc[index]),
                age_bars=0,
            )
        )
    return out


def build_levels(
    analyses: dict[Timeframe, tuple[FrameAnalysis, int]],
    signal_timeframe: Timeframe,
    price: float,
    atr: float,
    *,
    max_levels: int = MAX_LEVELS,
) -> list[Level]:
    """Assemble the ladder for one decision point.

    Ids are assigned last, after selection and ordering, so that the same market
    shape always yields the same ids regardless of which analysis produced which
    candidate.
    """
    if atr <= 0:
        raise ValueError("ATR must be positive to express distances in ATR units")

    signal_analysis, signal_index = analyses[signal_timeframe]

    candidates: list[_Candidate] = [
        _Candidate(kind=LevelKind.CURRENT, timeframe=signal_timeframe, price=price, age_bars=0)
    ]
    for timeframe, (analysis, index) in analyses.items():
        candidates.extend(_swing_candidates(analysis, index))
        # Zones from the signal frame and the one above it. Higher frames produce
        # gaps too large to trade around, and lower ones produce noise.
        if timeframe in (signal_timeframe, Timeframe.H4):
            candidates.extend(_zone_candidates(analysis, index))
    candidates.extend(_session_candidates(analyses))

    merged = _merge_near(candidates, tolerance=MERGE_TOLERANCE_ATR * atr)
    selected = _select(merged, price=price, atr=atr, max_levels=max_levels)

    # Descending price: a deterministic order that does not depend on which
    # analysis contributed which candidate.
    selected.sort(key=lambda c: (-c.price, c.kind.value, c.timeframe.value))

    touch_tolerance = MERGE_TOLERANCE_ATR * atr
    return [
        Level(
            id=f"lvl_{position}",
            kind=candidate.kind,
            timeframe=candidate.timeframe,
            price=candidate.price,
            distance_atr=(candidate.price - price) / atr,
            age_bars=candidate.age_bars,
            touches=_count_touches(
                signal_analysis.frame, candidate.price, signal_index, touch_tolerance
            ),
        )
        for position, candidate in enumerate(selected)
    ]


def _merge_near(candidates: list[_Candidate], tolerance: float) -> list[_Candidate]:
    """Collapse candidates that describe the same price.

    A swing low, an equal-lows pool and a gap edge within a few basis points of
    each other are one level wearing three hats. The oldest wins, because age is
    what makes a level significant.
    """
    ordered = sorted(candidates, key=lambda c: (c.price, -c.age_bars, c.kind.value))
    kept: list[_Candidate] = []
    for candidate in ordered:
        if not kept or abs(candidate.price - kept[-1].price) > tolerance:
            kept.append(candidate)
            continue
        if _outranks(candidate, kept[-1]):
            kept[-1] = candidate
    return kept


def _rank(kind: LevelKind) -> int:
    """Precedence when two candidates describe the same price.

    `current` outranks everything. It is the anchor a market entry is expressed
    against, and it is brand new by definition -- so under an age-based rule it
    loses to any swing that happens to sit at the same price, and quietly vanishes
    from the ladder. That leaves the model with no way to say "enter here, now".
    """
    if kind is LevelKind.CURRENT:
        return 2
    return 1 if kind in PROTECTED_KINDS else 0


def _outranks(candidate: _Candidate, incumbent: _Candidate) -> bool:
    """Which of two levels at the same price should represent it.

    A structural anchor beats an incidental one -- a stop can sit behind a swing
    low in a way it cannot sit behind the midpoint of a gap. Between two of equal
    standing, the older level wins, because a level price has respected for longer
    is the one traders are actually watching.
    """
    candidate_rank = _rank(candidate.kind)
    incumbent_rank = _rank(incumbent.kind)
    if candidate_rank != incumbent_rank:
        return candidate_rank > incumbent_rank
    return candidate.age_bars > incumbent.age_bars


#: Liquidity zones guaranteed a place in the ladder when any exist.
#:
#: Without a reserved quota they never make it. There are always more swings than
#: slots, and swings are the protected kind, so a pure nearest-first selection
#: fills the ladder with them and silently drops every pool and gap -- starving a
#: factor that carries a fifth of the decision weight.
ZONE_QUOTA = 4

#: Session extremes (previous day and week) guaranteed a place. These are the
#: levels the rest of the market is watching, and there are at most four.
SESSION_QUOTA = 4

#: Swings kept per timeframe per side. A cap, not a target: without it the
#: fifteen-minute frame contributes a dozen near swings and the daily frame none,
#: which reads as though nothing above the hourly chart exists.
SWINGS_PER_FRAME_PER_SIDE = 2

_ZONE_KINDS = frozenset(
    {
        LevelKind.EQUAL_HIGHS,
        LevelKind.EQUAL_LOWS,
        LevelKind.FVG_HIGH,
        LevelKind.FVG_MID,
        LevelKind.FVG_LOW,
    }
)

_SESSION_KINDS = frozenset(
    {
        LevelKind.PREV_DAY_HIGH,
        LevelKind.PREV_DAY_LOW,
        LevelKind.PREV_WEEK_HIGH,
        LevelKind.PREV_WEEK_LOW,
    }
)


def _nearest(candidates: list[_Candidate], price: float, limit: int) -> list[_Candidate]:
    return sorted(candidates, key=lambda c: (abs(c.price - price), c.kind.value))[:limit]


def _select(
    candidates: list[_Candidate], *, price: float, atr: float, max_levels: int
) -> list[_Candidate]:
    """Fill the ladder by quota, so every kind of level is represented.

    The order below is the order of usefulness for placing a trade: you need to
    know where you are, where the nearest structure above and below is (that is
    where a stop goes), what the wider market is watching, where liquidity is
    resting, and only then more structure.
    """
    if len(candidates) <= max_levels:
        return list(candidates)

    chosen: list[_Candidate] = []
    taken: set[int] = set()

    def take(pool: list[_Candidate], limit: int) -> None:
        for candidate in _nearest(pool, price, limit):
            key = id(candidate)
            if key not in taken and len(chosen) < max_levels:
                taken.add(key)
                chosen.append(candidate)

    current = [c for c in candidates if c.kind is LevelKind.CURRENT]
    swings = [c for c in candidates if c.kind in (LevelKind.SWING_HIGH, LevelKind.SWING_LOW)]
    zones = [c for c in candidates if c.kind in _ZONE_KINDS]
    session = [c for c in candidates if c.kind in _SESSION_KINDS]

    take(current, 1)
    # The nearest structure either side: without these there is nowhere to put a stop.
    take([c for c in swings if c.price > price], 1)
    take([c for c in swings if c.price < price], 1)
    take(session, SESSION_QUOTA)
    take(zones, ZONE_QUOTA)

    # Remaining room goes to structure, capped per frame and side so no single
    # timeframe dominates.
    budget: dict[tuple[Timeframe, LevelKind], int] = {}
    for candidate in _nearest(swings, price, len(swings)):
        key = (candidate.timeframe, candidate.kind)
        if budget.get(key, 0) >= SWINGS_PER_FRAME_PER_SIDE:
            continue
        if id(candidate) in taken or len(chosen) >= max_levels:
            continue
        budget[key] = budget.get(key, 0) + 1
        taken.add(id(candidate))
        chosen.append(candidate)

    if len(chosen) < max_levels:
        take([c for c in candidates if id(c) not in taken], max_levels - len(chosen))
    return chosen
