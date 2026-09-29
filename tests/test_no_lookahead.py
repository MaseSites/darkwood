"""The most valuable test in this project.

A snapshot built at bar *i* must depend on nothing that happened after bar *i*. If
it does, every backtest built on it is measuring a system that knew the answer,
and nothing about the resulting numbers will look wrong -- they will look
excellent.

Two complementary attacks:

**Mutation.** Build the snapshot, then rewrite every bar after the decision point
with different prices, and build it again. The hash must be identical. This is
stronger than the usual truncation check because it catches code that reads the
future without needing the rows to exist -- a `shift(-1)`, a `center=True`
rolling window, a percentile taken over the whole file.

**Truncation.** Build from the full history, then from history cut off at the
decision point. Also identical. This catches the opposite failure: analysis whose
result depends on how much data happens to be loaded.

Both run across the whole snapshot, not one field, because a leak in a single
indicator is enough.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.fakes import fast_engine_config, multi_frame_fixture
from traidingbrain.analysis.pipeline import MultiFrameAnalysis, decision_time_ms
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.config.settings import EngineConfig
from traidingbrain.data.frames import normalise, timeframe_ms
from traidingbrain.domain.enums import Timeframe

#: Indices sampled across the usable range. Enough coverage to catch a leak,
#: cheap enough that the suite stays fast.
SAMPLE_COUNT = 24


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return fast_engine_config()


@pytest.fixture(scope="module")
def frames() -> dict[Timeframe, pd.DataFrame]:
    return multi_frame_fixture(6000)


@pytest.fixture(scope="module")
def builder(frames: dict[Timeframe, pd.DataFrame], config: EngineConfig) -> SnapshotBuilder:
    return SnapshotBuilder("TESTUSDT", MultiFrameAnalysis(frames, config), config)


def sample_indices(builder: SnapshotBuilder) -> list[int]:
    first = builder.analysis.first_ready_index()
    assert first is not None, "the fixture must produce buildable snapshots"
    last = len(builder.analysis.signal) - 1
    step = max(1, (last - first) // SAMPLE_COUNT)
    return list(range(first, last + 1, step))


def scramble_after(
    frames: dict[Timeframe, pd.DataFrame], cutoff_ms: int, seed: int
) -> dict[Timeframe, pd.DataFrame]:
    """Rewrite every bar that had not closed by `cutoff_ms`.

    Prices are scaled by a large random factor rather than nudged, so a leak
    produces an obvious mismatch instead of one hiding inside a rounding
    tolerance. OHLC ordering is preserved so the frames stay valid -- the point is
    a different future, not a corrupt one.
    """
    rng = np.random.default_rng(seed)
    out: dict[Timeframe, pd.DataFrame] = {}
    for timeframe, frame in frames.items():
        copy = frame.copy()
        closed_by_cutoff = copy["ts"] + timeframe_ms(timeframe) <= cutoff_ms
        future = ~closed_by_cutoff
        count = int(future.sum())
        if count:
            factor = rng.uniform(0.55, 1.8, size=count)
            for column in ("open", "high", "low", "close"):
                copy.loc[future, column] = copy.loc[future, column].to_numpy() * factor
            copy.loc[future, "volume"] = copy.loc[future, "volume"].to_numpy() * rng.uniform(
                0.1, 6.0, size=count
            )
            body_high = copy.loc[future, ["open", "close"]].max(axis=1)
            body_low = copy.loc[future, ["open", "close"]].min(axis=1)
            copy.loc[future, "high"] = np.maximum(copy.loc[future, "high"], body_high)
            copy.loc[future, "low"] = np.minimum(copy.loc[future, "low"], body_low)
        out[timeframe] = normalise(copy)
    return out


def truncate_after(
    frames: dict[Timeframe, pd.DataFrame], cutoff_ms: int
) -> dict[Timeframe, pd.DataFrame]:
    return {
        timeframe: frame.loc[frame["ts"] + timeframe_ms(timeframe) <= cutoff_ms].reset_index(
            drop=True
        )
        for timeframe, frame in frames.items()
    }


# --------------------------------------------------------------------------- #
# Mutation
# --------------------------------------------------------------------------- #


def test_rewriting_the_future_does_not_change_any_snapshot(
    frames: dict[Timeframe, pd.DataFrame],
    config: EngineConfig,
    builder: SnapshotBuilder,
) -> None:
    """Rewrite everything after the decision point. Every hash must survive.

    One pass over many decision points rather than a test per index: the analysis
    has to be rebuilt for each mutated history, and that is the expensive part.
    """
    indices = sample_indices(builder)
    signal = builder.analysis.signal
    checked = 0

    for seed, index in enumerate(indices):
        original = builder.build(index)
        if original is None:
            continue
        cutoff = decision_time_ms(signal.ts_at(index), config.timeframes.signal)

        mutated_frames = scramble_after(frames, cutoff, seed=seed)
        mutated = SnapshotBuilder(
            "TESTUSDT", MultiFrameAnalysis(mutated_frames, config), config
        ).build(index)

        assert mutated is not None, f"index {index}: snapshot vanished after mutation"
        assert mutated.to_brain_input().content_hash() == (
            original.to_brain_input().content_hash()
        ), (
            f"index {index}: the snapshot changed when only future bars were "
            f"rewritten, so something in the analysis is reading ahead"
        )
        checked += 1

    assert checked >= SAMPLE_COUNT // 2, f"only {checked} snapshots were actually compared"


def test_the_mutation_actually_changes_something(
    frames: dict[Timeframe, pd.DataFrame], config: EngineConfig, builder: SnapshotBuilder
) -> None:
    """Guard against a test that passes because it does nothing.

    If `scramble_after` quietly became a no-op, the test above would go green
    forever while proving nothing. So: a snapshot built *after* the cutoff must
    differ.
    """
    indices = sample_indices(builder)
    index = indices[len(indices) // 2]
    signal = builder.analysis.signal
    cutoff = decision_time_ms(signal.ts_at(index), config.timeframes.signal)

    mutated_frames = scramble_after(frames, cutoff, seed=99)
    later = min(index + 30, len(signal) - 1)

    before = builder.build(later)
    after = SnapshotBuilder("TESTUSDT", MultiFrameAnalysis(mutated_frames, config), config).build(
        later
    )

    assert before is not None and after is not None
    assert before.to_brain_input().content_hash() != after.to_brain_input().content_hash(), (
        "the mutation had no effect even on a later bar, so the test above is vacuous"
    )


# --------------------------------------------------------------------------- #
# Truncation
# --------------------------------------------------------------------------- #


def test_removing_the_future_does_not_change_any_snapshot(
    frames: dict[Timeframe, pd.DataFrame],
    config: EngineConfig,
    builder: SnapshotBuilder,
) -> None:
    """The same snapshot must come out of a file that stops at the decision point."""
    indices = sample_indices(builder)
    signal = builder.analysis.signal
    checked = 0

    for index in indices:
        original = builder.build(index)
        if original is None:
            continue
        cutoff = decision_time_ms(signal.ts_at(index), config.timeframes.signal)

        cut_frames = truncate_after(frames, cutoff)
        truncated_analysis = MultiFrameAnalysis(cut_frames, config)
        truncated_index = len(truncated_analysis.signal) - 1
        truncated = SnapshotBuilder("TESTUSDT", truncated_analysis, config).build(truncated_index)

        assert truncated is not None, f"index {index}: snapshot vanished after truncation"
        assert truncated.ts == original.ts, "truncation lined the frames up differently"
        assert truncated.to_brain_input().content_hash() == (
            original.to_brain_input().content_hash()
        ), (
            f"index {index}: the snapshot depends on how much history happens to be "
            f"loaded after the decision point"
        )
        checked += 1

    assert checked >= SAMPLE_COUNT // 2


# --------------------------------------------------------------------------- #
# Frame alignment
# --------------------------------------------------------------------------- #


def test_higher_frames_use_only_candles_that_have_closed(
    frames: dict[Timeframe, pd.DataFrame], config: EngineConfig, builder: SnapshotBuilder
) -> None:
    """The daily bar containing the current hour must not be read.

    Its high, low and close are still being written by the very hour being decided
    on. Using it is the most direct form of knowing the answer, and it is a single
    off-by-one away at all times.
    """
    indices = sample_indices(builder)
    signal = builder.analysis.signal

    for index in indices:
        aligned = builder.analysis.aligned_indices(index)
        if aligned is None:
            continue
        cutoff = decision_time_ms(signal.ts_at(index), config.timeframes.signal)
        for timeframe, bar_index in aligned.items():
            bar_ts = int(frames[timeframe]["ts"].iloc[bar_index])
            assert bar_ts + timeframe_ms(timeframe) <= cutoff, (
                f"{timeframe} bar at {bar_ts} had not closed by the decision time {cutoff}"
            )


def test_a_snapshot_is_refused_while_any_frame_is_warming_up(
    builder: SnapshotBuilder,
) -> None:
    """None, not a half-filled snapshot.

    A partial snapshot is worse than none: it looks complete, and it would tell the
    model that the higher frame is neutral when the truth is that nothing is known
    about it yet.
    """
    assert builder.build(0) is None
    first = builder.analysis.first_ready_index()
    assert first is not None
    assert builder.build(first - 1) is None
    assert builder.build(first) is not None
