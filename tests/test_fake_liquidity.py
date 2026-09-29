"""Positioning folded into the liquidity factor.

Not a sixth factor, and the tests say why: the specification fixed five weights
that add to one, so a sixth would silently reweight the other five. Open interest
and the crowd ratio are statements about where positions sit, which is what the
liquidity factor already means.

The property worth pinning is the arithmetic of agreement. Two independent
readings pointing the same way should be worth more than either alone, and
pointing apart should be worth less than either -- and "less than either" is the
half that is easy to get wrong, because averaging two disagreeing signals
produces a confident zero rather than an admission of confusion.
"""

from __future__ import annotations

import pytest

from tests.factories import make_snapshot
from traidingbrain.brain.fake import _liquidity_read
from traidingbrain.domain.enums import Bias, Factor
from traidingbrain.domain.snapshot import LiquidityView, MarketSnapshot, PositioningStats


def snapshot_with(
    *,
    reading: str = "unknown",
    bias: Bias = Bias.NEUTRAL,
    strength: float = 0.0,
    known: bool = False,
) -> MarketSnapshot:
    base = make_snapshot()
    return base.model_copy(
        update={
            "positioning": PositioningStats(
                known=known, reading=reading, bias=bias, strength=strength
            )
        }
    )


def frame_with(*, sweep_up: bool = False, sweep_down: bool = False):
    base = make_snapshot()
    signal = next(f for f in base.frames if f.timeframe is base.signal_timeframe)
    return signal.model_copy(
        update={
            "liquidity": LiquidityView(
                sweep_up=sweep_up, sweep_down=sweep_down, bars_since_sweep=1, zone_level_ids=[]
            )
        }
    )


def test_nothing_to_say_produces_no_reading_at_all() -> None:
    """A factor with nothing behind it is dropped, not scored zero.

    Scoring zero would pull the weighted confidence toward the middle and make
    every incomplete answer look more uncertain than the evidence present
    actually warrants.
    """
    assert _liquidity_read(frame_with(), snapshot_with()) is None


def test_a_sweep_alone_is_still_a_reading() -> None:
    read = _liquidity_read(frame_with(sweep_down=True), snapshot_with())

    assert read is not None
    assert read.factor is Factor.LIQUIDITY
    assert read.score > 0, "sell-side taken and held is fuel for a move up"


def test_positioning_alone_is_still_a_reading() -> None:
    """Open interest works on bars where nothing was swept, which is most of them."""
    read = _liquidity_read(
        frame_with(),
        snapshot_with(known=True, reading="new_longs", bias=Bias.BULLISH, strength=0.8),
    )

    assert read is not None
    assert read.score > 0
    assert "new longs" in read.reason


def test_two_readings_agreeing_are_worth_more_than_either_alone() -> None:
    sweep_only = _liquidity_read(frame_with(sweep_down=True), snapshot_with())
    both = _liquidity_read(
        frame_with(sweep_down=True),
        snapshot_with(known=True, reading="new_longs", bias=Bias.BULLISH, strength=0.9),
    )

    assert sweep_only is not None and both is not None
    assert abs(both.score) > abs(sweep_only.score)
    assert both.confidence > sweep_only.confidence


def test_two_readings_disagreeing_are_worth_less_than_either_alone() -> None:
    """The half that is easy to get wrong.

    Averaging two opposing signals yields a confident zero, which reads as "the
    market is balanced" when the truth is "these two things contradict each
    other". The certainty has to fall, not the value alone.
    """
    sweep_only = _liquidity_read(frame_with(sweep_down=True), snapshot_with())
    conflicted = _liquidity_read(
        frame_with(sweep_down=True),
        snapshot_with(known=True, reading="new_shorts", bias=Bias.BEARISH, strength=0.9),
    )

    assert sweep_only is not None and conflicted is not None
    assert conflicted.confidence < sweep_only.confidence


def test_a_weak_positioning_reading_barely_counts() -> None:
    """Scaled by strength, so a reading the data barely supports barely moves it."""
    weak = _liquidity_read(
        frame_with(),
        snapshot_with(known=True, reading="new_longs", bias=Bias.BULLISH, strength=0.05),
    )
    strong = _liquidity_read(
        frame_with(),
        snapshot_with(known=True, reading="new_longs", bias=Bias.BULLISH, strength=1.0),
    )

    assert weak is not None and strong is not None
    assert abs(weak.score) < abs(strong.score)


def test_unknown_positioning_contributes_nothing_rather_than_neutrality() -> None:
    """The venue's history starts after the candles do, so this is a real state."""
    with_sweep = _liquidity_read(frame_with(sweep_up=True), snapshot_with())
    with_sweep_and_silence = _liquidity_read(
        frame_with(sweep_up=True), snapshot_with(known=False, reading="unknown")
    )

    assert with_sweep is not None and with_sweep_and_silence is not None
    assert with_sweep.score == with_sweep_and_silence.score
    assert with_sweep.confidence == with_sweep_and_silence.confidence


def test_the_score_stays_inside_the_range_the_schema_allows() -> None:
    """Two strong readings must not sum past the bound the verdict model enforces."""
    read = _liquidity_read(
        frame_with(sweep_down=True),
        snapshot_with(known=True, reading="long_liquidation", bias=Bias.BULLISH, strength=1.0),
    )

    assert read is not None
    assert -1.0 <= read.score <= 1.0
    assert 0.0 <= read.confidence <= 1.0


@pytest.mark.parametrize(
    ("reading", "bias"),
    [
        ("new_longs", Bias.BULLISH),
        ("short_covering", Bias.BEARISH),
        ("new_shorts", Bias.BEARISH),
        ("long_liquidation", Bias.BULLISH),
    ],
)
def test_every_reading_pushes_the_way_the_truth_table_says(reading: str, bias: Bias) -> None:
    read = _liquidity_read(
        frame_with(), snapshot_with(known=True, reading=reading, bias=bias, strength=0.8)
    )

    assert read is not None
    expected = 1.0 if bias is Bias.BULLISH else -1.0
    assert read.score * expected > 0
