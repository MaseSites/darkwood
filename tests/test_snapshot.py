"""The snapshot itself: the ladder, the readings, and what stays out.

The lookahead property lives in `test_no_lookahead.py`. This file covers the other
half of the contract -- that the thing handed to the model is scale-free, stable,
and complete enough to trade from.

The golden test at the end freezes the whole serialised snapshot. It will fail on
any deliberate change to the analysis, which is the point: the decision cache is
keyed on this exact text, so a change here silently invalidates every cached
answer and makes the next backtest cost full price. That should be a decision, not
a surprise.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import pairwise

import pandas as pd
import pytest

from tests.fakes import fast_engine_config, multi_frame_fixture
from traidingbrain.analysis.levels import MERGE_TOLERANCE_ATR
from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.config.settings import EngineConfig
from traidingbrain.domain.enums import LevelKind, Timeframe
from traidingbrain.domain.snapshot import MarketSnapshot


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return fast_engine_config()


@pytest.fixture(scope="module")
def frames() -> dict[Timeframe, pd.DataFrame]:
    return multi_frame_fixture(6000)


@pytest.fixture(scope="module")
def builder(frames: dict[Timeframe, pd.DataFrame], config: EngineConfig) -> SnapshotBuilder:
    return SnapshotBuilder("TESTUSDT", MultiFrameAnalysis(frames, config), config)


@pytest.fixture(scope="module")
def snapshot(builder: SnapshotBuilder) -> MarketSnapshot:
    result = builder.build(len(builder.analysis.signal) - 1)
    assert result is not None
    return result


def many_snapshots(builder: SnapshotBuilder, count: int = 30) -> list[MarketSnapshot]:
    first = builder.analysis.first_ready_index()
    assert first is not None
    last = len(builder.analysis.signal) - 1
    step = max(1, (last - first) // count)
    found = [builder.build(i) for i in range(first, last + 1, step)]
    return [s for s in found if s is not None]


# --------------------------------------------------------------------------- #
# The ladder
# --------------------------------------------------------------------------- #


def test_ids_are_sequential_and_ordered_by_price(snapshot: MarketSnapshot) -> None:
    """Descending price, assigned after selection.

    Ordering by price rather than by discovery keeps ids stable: the same market
    shape gets the same ids no matter which analysis contributed which candidate,
    which is what lets the decision cache hit at all.
    """
    assert [lvl.id for lvl in snapshot.levels] == [f"lvl_{i}" for i in range(len(snapshot.levels))]
    prices = [lvl.price for lvl in snapshot.levels]
    assert prices == sorted(prices, reverse=True)


def test_the_current_price_is_always_an_anchor(builder: SnapshotBuilder) -> None:
    """Without it there is no way to express "enter here, now".

    It is also the level most easily lost: it is brand new by definition, so any
    rule that prefers older levels when two sit at the same price will drop it.
    """
    for snapshot in many_snapshots(builder):
        kinds = [lvl.kind for lvl in snapshot.levels]
        assert LevelKind.CURRENT in kinds, f"no current anchor at ts {snapshot.ts}"
        current = next(lvl for lvl in snapshot.levels if lvl.kind is LevelKind.CURRENT)
        assert current.distance_atr == pytest.approx(0.0, abs=1e-9)
        assert current.price == pytest.approx(snapshot.price)


def test_there_is_structure_on_both_sides_of_price(builder: SnapshotBuilder) -> None:
    """A trade needs somewhere to put a stop and somewhere to aim.

    A ladder that is entirely above or entirely below the current price cannot
    express either.
    """
    thin = []
    for snapshot in many_snapshots(builder):
        above = [lvl for lvl in snapshot.levels if lvl.distance_atr > 0]
        below = [lvl for lvl in snapshot.levels if lvl.distance_atr < 0]
        if not above or not below:
            thin.append(snapshot.ts)
    assert not thin, f"{len(thin)} snapshots had levels on only one side of price"


def test_distances_agree_with_prices(snapshot: MarketSnapshot) -> None:
    for level in snapshot.levels:
        expected = (level.price - snapshot.price) / snapshot.atr
        assert level.distance_atr == pytest.approx(expected, abs=1e-9)


def test_levels_are_not_duplicated(snapshot: MarketSnapshot) -> None:
    """Near-identical prices are merged, so the ladder is landmarks, not a price list."""
    prices = sorted(lvl.price for lvl in snapshot.levels)
    gaps = [b - a for a, b in pairwise(prices)]
    assert all(gap > 0 for gap in gaps)
    assert min(gaps) > MERGE_TOLERANCE_ATR * snapshot.atr * 0.5, (
        "two levels survived that describe effectively the same price"
    )


def test_several_timeframes_reach_the_ladder(builder: SnapshotBuilder) -> None:
    """One frame must not crowd out the rest.

    The lowest timeframe always has the most swings and the nearest ones, so a
    pure nearest-first rule fills the ladder with it and the higher frames vanish
    -- leaving the model looking at a fifteen-minute chart while being told it has
    multi-timeframe context.
    """
    seen: set[Timeframe] = set()
    for snapshot in many_snapshots(builder):
        seen.update(lvl.timeframe for lvl in snapshot.levels)
    assert len(seen) >= 2, f"levels only ever came from {seen}"


def test_anchors_resolve_back_to_prices(snapshot: MarketSnapshot) -> None:
    """The one path from a model answer to a number."""
    for level in snapshot.levels:
        assert snapshot.resolve(level.id) == pytest.approx(level.price)
        offset = snapshot.resolve(level.id, offset_atr=-0.5)
        assert offset is not None
        assert offset == pytest.approx(level.price - 0.5 * snapshot.atr)


# --------------------------------------------------------------------------- #
# What the model sees
# --------------------------------------------------------------------------- #


def test_no_reading_carries_a_price(builder: SnapshotBuilder) -> None:
    """Every indicator value must be scale-free.

    One raw price is enough for the model to work out the symbol and roughly the
    month, and from there part of its answer is memory rather than analysis. RSI
    and %B are bounded; the moving-average spread and MACD histogram are divided
    by ATR; the volume ratio and close-in-range are dimensionless.
    """
    for snapshot in many_snapshots(builder):
        scale = snapshot.price
        for frame_view in snapshot.frames:
            for reading in frame_view.indicators:
                assert abs(reading.value) < scale / 100, (
                    f"{reading.name}={reading.value} looks like it is on the price scale"
                )


def test_frames_appear_in_configured_order(snapshot: MarketSnapshot, config: EngineConfig) -> None:
    """Highest first, so the model reads context before detail -- and so the
    serialisation is stable, which the cache key depends on."""
    assert [view.timeframe for view in snapshot.frames] == list(config.timeframes.context)


def test_history_starts_empty_and_says_so(snapshot: MarketSnapshot) -> None:
    """Before the history engine exists, the honest answer is zero cases.

    `sample_is_sufficient` being false is what stops a confidence number leaning
    on evidence that is not there.
    """
    assert snapshot.history.similar_situations_found == 0
    assert snapshot.history.sample_is_sufficient is False
    assert snapshot.history.historical_winrate is None


def test_the_same_snapshot_hashes_the_same_twice(snapshot: MarketSnapshot) -> None:
    first = snapshot.to_brain_input()
    second = snapshot.to_brain_input()
    assert first.content_hash() == second.content_hash()
    assert first.canonical_json() == second.canonical_json()


def test_different_bars_hash_differently(builder: SnapshotBuilder) -> None:
    """Guard against a hash that is stable because it ignores its input."""
    hashes = {s.to_brain_input().content_hash() for s in many_snapshots(builder)}
    assert len(hashes) > 1


def test_the_payload_stays_small(snapshot: MarketSnapshot) -> None:
    """Prompt size is paid on every call, and this one is sent thousands of times.

    A ladder that grows without limit is the usual way this creeps up.
    """
    payload = snapshot.to_brain_input().canonical_json()
    assert len(payload) < 12_000, f"brain input grew to {len(payload)} characters"


# --------------------------------------------------------------------------- #
# Golden
# --------------------------------------------------------------------------- #


def test_the_serialised_snapshot_is_frozen(
    snapshot: MarketSnapshot, golden: Callable[[str, object], None]
) -> None:
    """Freeze the full payload.

    This fails whenever the analysis changes what it reports, which is exactly
    when someone should be told: the decision cache is keyed on this text, so the
    change invalidates every stored answer and the next backtest pays full price.
    """
    golden("brain_input", json.loads(snapshot.to_brain_input().canonical_json()))
