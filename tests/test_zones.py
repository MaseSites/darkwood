"""Supply/demand zones and order blocks, against the rules V09, V11 and V12 give.

Two kinds of test here, deliberately.

The helpers that decide one thing -- did price come back into the block, which
candle was the last one against the move, which of several zones is the true one
-- are tested on arrays written out by hand, because their answers should be
checkable with a pencil.

The detectors themselves are tested as **properties over a long generated
series**. A detector's fixture test proves it agrees with the fixture; what
actually needs guaranteeing is that every zone it ever emits satisfies the
source's criteria, and that none of them can be read before the bar its criteria
completed on. Those are statements about all zones, so they are tested that way.

The property that matters most is the confirmation index. An order block's three
criteria finish at the CHoCH, often many bars after the candle it is drawn from.
A backtest that placed the zone on the candle would enter on a verdict that did
not exist yet, and would do it while looking entirely reasonable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.indicators import atr
from traidingbrain.analysis.liquidity import ZoneKind
from traidingbrain.analysis.structure import StructureTimeline
from traidingbrain.analysis.zones import (
    MAX_APPROACH_ATR_PER_BAR,
    MIN_IMPULSE_ATR,
    StructuralZone,
    ZoneRole,
    ZoneTimeline,
    _gaps_by_index,
    _has_gap_between,
    _last_opposite_candle,
    _mitigated_before,
    _swept_left,
    find_order_blocks,
    find_supply_demand_zones,
    true_zone,
)
from traidingbrain.domain.enums import Bias

SWING_LOOKBACK = 3
SEQUENCE_LENGTH = 6


def walk(count: int = 1200, seed: int = 7) -> pd.DataFrame:
    """A deterministic series with enough shape for structure to happen.

    A trend that reverses a few times with noise on top -- not a model of the
    market, just a path that produces swings, breaks and changes of character in
    quantity. Fixed seed, so a failure is reproducible.
    """
    rng = np.random.default_rng(seed)
    price = 100.0
    rows = []
    for i in range(count):
        drift = 0.35 * np.sin(i / 90.0) + 0.15 * np.sin(i / 17.0)
        price = max(price + drift + float(rng.normal(0, 0.45)), 1.0)
        spread = abs(float(rng.normal(0, 0.5))) + 0.2
        open_ = price - float(rng.normal(0, 0.3))
        close = price
        rows.append(
            (
                open_,
                max(open_, close) + spread,
                min(open_, close) - spread,
                close,
            )
        )
    return frame_of(rows)


def frame_of(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [1_700_000_000_000 + i * 3_600_000 for i in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [1.0] * len(rows),
        }
    )


@pytest.fixture(scope="module")
def series() -> tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline]:
    frame = walk()
    volatility = atr(frame, 14)
    structure = StructureTimeline(frame, SWING_LOOKBACK, SEQUENCE_LENGTH)
    return frame, volatility, structure, ZoneTimeline(frame, volatility, structure)


# --------------------------------------------------------------------------- #
# The fixture has to contain what the tests are about
# --------------------------------------------------------------------------- #


def test_the_series_produces_both_kinds_of_zone(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    """Guarding the tests below rather than the code.

    Every property test here passes trivially on an empty list. If the generated
    series ever stops producing zones -- a changed threshold, a changed seed --
    this is what says so, instead of a green suite that checks nothing.
    """
    frame, _, _, zones = series
    found = zones.known_at(len(frame) - 1)
    roles = {zone.role for zone in found}

    assert ZoneRole.DEMAND in roles
    assert ZoneRole.SUPPLY in roles
    assert {ZoneRole.BULLISH_ORDER_BLOCK, ZoneRole.BEARISH_ORDER_BLOCK} & roles


# --------------------------------------------------------------------------- #
# Confirmation, which is where lookahead would enter
# --------------------------------------------------------------------------- #


def test_no_zone_is_readable_before_its_criteria_completed(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    """The one that matters.

    An order block's criteria finish at the CHoCH, which is regularly a dozen
    bars after the candle the zone is drawn from. Placing it on the candle would
    let a backtest enter on a verdict that did not exist yet -- and the equity
    curve would look better for exactly that reason.
    """
    frame, _, _, zones = series

    for index in range(0, len(frame), 17):
        for zone in zones.known_at(index):
            assert zone.confirmed_index <= index


def test_a_zone_is_confirmed_no_earlier_than_the_candle_it_is_drawn_from(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    frame, _, _, zones = series

    for zone in zones.known_at(len(frame) - 1):
        assert zone.confirmed_index >= zone.origin_index
        assert zone.confirmation_lag >= 0


def test_rewriting_the_future_cannot_change_an_earlier_reading() -> None:
    """The general guarantee, over both detectors at once.

    If any of this ever reaches forward -- a window with the wrong sign, a
    criterion checked against bars that had not closed -- this catches it
    without anyone having to suspect which line.
    """
    frame = walk(600)
    cut = 400

    def zones_up_to(source: pd.DataFrame) -> list[tuple[str, int, int, float, float]]:
        volatility = atr(source, 14)
        structure = StructureTimeline(source, SWING_LOOKBACK, SEQUENCE_LENGTH)
        timeline = ZoneTimeline(source, volatility, structure)
        return [
            (z.role.value, z.origin_index, z.confirmed_index, z.low, z.high)
            for z in timeline.known_at(cut - 1)
        ]

    before = zones_up_to(frame)
    mutated = frame.copy()
    mutated.loc[cut:, ["open", "high", "low", "close"]] = 999.0

    assert zones_up_to(mutated) == before


# --------------------------------------------------------------------------- #
# V09 — the zone is the origin of an aggressive, structure-breaking move
# --------------------------------------------------------------------------- #


def test_every_supply_demand_zone_came_from_a_break_of_structure(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    """V09: the move must have broken structure. Without that condition the
    detector marks a zone on every energetic candle, which is the "schwacher
    Drift" the video explicitly refuses."""
    frame, volatility, structure, _ = series

    zones = find_supply_demand_zones(frame, volatility, structure)

    assert zones
    for zone in zones:
        assert zone.broke_structure is True
        assert structure.state_at(zone.confirmed_index).bars_since_bos == 0


def test_every_supply_demand_move_was_aggressive_in_atr(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    """"Aggressiv" measured in ATR, because the same number of dollars is
    aggressive in a quiet week and unremarkable in a violent one."""
    frame, volatility, structure, _ = series
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    units = volatility.to_numpy(dtype="float64")

    for zone in find_supply_demand_zones(frame, volatility, structure):
        end = zone.confirmed_index
        if zone.is_bullish:
            extent = highs[end] - lows[zone.origin_index]
        else:
            extent = highs[zone.origin_index] - lows[end]
        assert extent >= MIN_IMPULSE_ATR * units[end]


def test_the_zone_candle_closed_against_the_move(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    """V09: "die letzte Gegenkerze vor dem Impuls". A demand zone drawn from an
    up candle is not this rule; it is a different one nobody stated."""
    frame, volatility, structure, _ = series
    opens = frame["open"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")

    for zone in find_supply_demand_zones(frame, volatility, structure):
        origin = zone.origin_index
        if zone.is_bullish:
            assert closes[origin] < opens[origin]
        else:
            assert closes[origin] > opens[origin]


# --------------------------------------------------------------------------- #
# V11 — all three criteria, re-derived from the bars
# --------------------------------------------------------------------------- #


def test_every_order_block_passes_all_three_criteria_independently(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    """The fidelity test: each criterion re-checked from the bars, not from the
    detector's own bookkeeping.

    V11 accepts the last candle before a reversal only when it swept liquidity
    left, price left it impulsively opening a gap, and the move produced a
    CHoCH. Three conditions, so three chances for one to be quietly dropped
    while the other two keep the detector looking correct.
    """
    frame, volatility, structure, _ = series
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    gaps = _gaps_by_index(frame, volatility)

    blocks = find_order_blocks(frame, volatility, structure)
    assert blocks

    for block in blocks:
        upward = block.role is ZoneRole.BULLISH_ORDER_BLOCK
        state = structure.state_at(block.confirmed_index)

        assert state.bars_since_choch == 0, "validated somewhere other than a CHoCH"
        assert state.break_direction is (Bias.BULLISH if upward else Bias.BEARISH)
        assert _swept_left(structure, highs, lows, block.origin_index, upward=upward)
        assert _has_gap_between(gaps, block.origin_index, block.confirmed_index, bullish=upward)
        assert not _mitigated_before(
            highs,
            lows,
            block.origin_index,
            block.confirmed_index,
            low=block.low,
            high=block.high,
            bullish=upward,
        )


def test_the_gap_an_order_block_requires_runs_the_right_way() -> None:
    """A bullish block needs a bullish imbalance in the move away from it. The
    mirror gap would mean price left downwards, which is the opposite setup."""
    frame = walk(400)
    gaps = _gaps_by_index(frame, atr(frame, 14))
    kinds = {gap.kind for bucket in gaps.values() for gap in bucket}

    assert ZoneKind.FVG_BULLISH in kinds and ZoneKind.FVG_BEARISH in kinds
    assert _has_gap_between(gaps, 0, len(frame) - 1, bullish=True)


# --------------------------------------------------------------------------- #
# Mitigation, and the bars that must not count as it
# --------------------------------------------------------------------------- #


def test_the_bars_leaving_a_block_do_not_count_as_returning_to_it() -> None:
    """The subtlety that decides whether this criterion works at all.

    The bars right after the origin are still in contact with it -- the first of
    them opens at the origin's own close. Counting those as a return marks
    essentially every candidate as mitigated, and the setup then never fires
    while every individual rule still reads correctly. Found by measuring: the
    criterion was rejecting all 213 candidates in a four-year sample.
    """
    #                 0     1     2     3      4      5
    highs = np.array([10.0, 10.5, 12.0, 14.0, 16.0, 18.0])
    lows = np.array([9.0, 9.8, 11.0, 13.0, 15.0, 17.0])

    # Bar 1 still overlaps the origin's 9-10 band; it is the move leaving.
    assert not _mitigated_before(highs, lows, 0, 5, low=9.0, high=10.0, bullish=True)


def test_coming_back_after_clearing_the_block_is_mitigation() -> None:
    #                 0     1     2     3     4     5
    highs = np.array([10.0, 14.0, 16.0, 13.0, 10.5, 18.0])
    lows = np.array([9.0, 13.0, 15.0, 11.0, 9.5, 17.0])

    assert _mitigated_before(highs, lows, 0, 5, low=9.0, high=10.0, bullish=True)


def test_a_block_price_never_left_is_not_reported_as_mitigated() -> None:
    """Whether that is a block at all is decided by the displacement criterion,
    which is the rule the source gives for it. This helper answers one question
    and does not quietly answer a second."""
    highs = np.array([10.0, 10.2, 10.1, 10.3])
    lows = np.array([9.0, 9.4, 9.2, 9.5])

    assert not _mitigated_before(highs, lows, 0, 3, low=9.0, high=10.0, bullish=True)


def test_mitigation_is_judged_in_the_mirror_for_a_bearish_block() -> None:
    highs = np.array([10.0, 6.0, 4.0, 7.0, 9.8, 3.0])
    lows = np.array([9.0, 5.0, 3.0, 6.0, 9.0, 2.0])

    assert _mitigated_before(highs, lows, 0, 5, low=9.0, high=10.0, bullish=False)


# --------------------------------------------------------------------------- #
# The origin candle
# --------------------------------------------------------------------------- #


def test_the_origin_is_the_nearest_candle_that_closed_against_the_move() -> None:
    opens = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    closes = np.array([11.0, 10.5, 13.0, 14.0, 15.0])

    assert _last_opposite_candle(opens, closes, 4, upward=True) == 1


def test_the_search_for_an_origin_is_bounded() -> None:
    """An unbounded walk finds an origin for any move at all, including the slow
    drift V09 refuses. The bound is what makes "the impulse" one leg."""
    opens = np.array([10.0] + [11.0] * 40)
    closes = np.array([9.0] + [12.0] * 40)

    assert _last_opposite_candle(opens, closes, 40, upward=True, limit=5) is None
    assert _last_opposite_candle(opens, closes, 40, upward=True, limit=99) == 0


def test_an_index_outside_the_series_returns_nothing_rather_than_raising() -> None:
    opens = np.array([10.0, 11.0])
    closes = np.array([9.0, 12.0])

    assert _last_opposite_candle(opens, closes, 99, upward=True) is None
    assert _last_opposite_candle(opens, closes, -1, upward=True) is None


# --------------------------------------------------------------------------- #
# The retest, which V09 wants first and slow
# --------------------------------------------------------------------------- #


def test_the_first_visit_is_marked_and_the_second_is_not(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    """V09 wants the *first* return. Without this the same zone would be traded
    again on every later visit, which is a different setup with a worse record
    and the same name."""
    frame, _, _, zones = series
    seen_first = seen_later = 0

    for zone in zones.known_at(len(frame) - 1):
        firsts = []
        for index in range(zone.confirmed_index + 1, len(frame)):
            touch = zones.touch_at(zone, index)
            if touch is None:
                continue
            firsts.append(touch.is_first)
        if firsts:
            assert firsts[0] is True
            assert not any(firsts[1:]), "a later visit reported itself as the first"
            seen_first += 1
            seen_later += len(firsts) > 1

    assert seen_first, "no zone was ever revisited, so this proved nothing"
    assert seen_later, "no zone was visited twice, so the second half proved nothing"


def test_a_sharp_approach_is_reported_as_not_slow(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    """V09's no-trade condition: "ein scharfer aggressiver Rücklauf". Reported
    as a measurement rather than a refusal, because the video attaches it to one
    setup and the engine may want the same zone for another."""
    frame, _, _, zones = series
    speeds = [
        zones.touch_at(zone, index)
        for zone in zones.known_at(len(frame) - 1)
        for index in range(zone.confirmed_index + 1, len(frame), 5)
    ]
    touches = [touch for touch in speeds if touch is not None]

    assert touches
    for touch in touches:
        assert touch.was_slow == (touch.approach_atr_per_bar <= MAX_APPROACH_ATR_PER_BAR)


def test_a_zone_stops_being_unmitigated_once_price_has_been_back(
    series: tuple[pd.DataFrame, pd.Series, StructureTimeline, ZoneTimeline],
) -> None:
    frame, _, _, zones = series
    last = len(frame) - 1

    live = zones.unmitigated_at(last)
    known = zones.known_at(last)

    assert live, "nothing survived, so this proves nothing"
    assert len(live) < len(known), "nothing was mitigated, so this proves nothing"


# --------------------------------------------------------------------------- #
# V12 — which of several stacked zones to use
# --------------------------------------------------------------------------- #


def zone(low: float, high: float, *, bullish: bool = True, broke: bool = True) -> StructuralZone:
    return StructuralZone(
        role=ZoneRole.DEMAND if bullish else ZoneRole.SUPPLY,
        low=low,
        high=high,
        origin_index=0,
        confirmed_index=1,
        source="test",
        broke_structure=broke,
    )


def test_a_zone_with_another_below_it_is_inducement_and_is_not_chosen() -> None:
    """V12's whole point: price is likely to run the lower zone first, so the
    upper one is bait. "Nicht automatisch die tiefste Zone wählen" -- and not
    automatically the nearest either."""
    deep = zone(80.0, 82.0)
    shallow = zone(90.0, 92.0)

    assert true_zone([deep, shallow], price=100.0, bullish=True) is deep


def test_a_zone_that_never_broke_structure_is_not_the_true_zone() -> None:
    """V12: "Prüfen, welche Zone das relevante Hoch tatsächlich brach." """
    passive = zone(80.0, 82.0, broke=False)
    structural = zone(90.0, 92.0)

    assert true_zone([passive, structural], price=100.0, bullish=True) is None


def test_nothing_qualifying_returns_nothing_rather_than_the_nearest() -> None:
    """A fallback here would be exactly the mistake the video warns about,
    wearing the clothes of a sensible default."""
    above = zone(120.0, 122.0)

    assert true_zone([above], price=100.0, bullish=True) is None
    assert true_zone([], price=100.0, bullish=True) is None


def test_the_bearish_side_is_the_mirror() -> None:
    far = zone(120.0, 122.0, bullish=False)
    near = zone(108.0, 110.0, bullish=False)

    assert true_zone([far, near], price=100.0, bullish=False) is far


def test_zones_on_the_wrong_side_of_price_are_ignored() -> None:
    """A demand zone above price is not somewhere a long can be entered on a
    pullback; it is somewhere price already is."""
    below = zone(90.0, 92.0)
    above = zone(110.0, 112.0)

    assert true_zone([below, above], price=100.0, bullish=True) is below
