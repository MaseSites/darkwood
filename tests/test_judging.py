"""The judging description, and the leak it must not have.

The scanning prompt hides the symbol, the date and every price on purpose: a
model that could see "this asset at this price" would recognise the period, and
part of its answer would come from knowing what happened next rather than from
the evidence. No test can separate those two afterwards -- which is why the
prevention has to be structural and why this file exists.

A proposal carries three prices. The test that matters is **scale invariance**:
multiply the whole market by ten and the description must not change by a single
character. A description that survives that cannot contain a price, whatever
anyone believed while writing it.
"""

from __future__ import annotations

import json

import pytest

from tests.factories import make_snapshot
from traidingbrain.brain.judging import (
    JUDGE_VERSION,
    NEAR_ATR,
    describe,
    user_content,
)
from traidingbrain.brain.prompt import PROMPT_VERSION
from traidingbrain.domain.enums import Side
from traidingbrain.sim.plan import TradeIntent


def intent_at(price: float, *, side: Side = Side.LONG, scale: float = 1.0) -> TradeIntent:
    """A long 2 ATR wide with a 3:1 target, placed relative to `price`."""
    atr = 100.0 * scale
    if side is Side.LONG:
        return TradeIntent(
            side=side,
            entry=price,
            stop=price - 2 * atr,
            target=price + 6 * atr,
            confidence=60.0,
            reason="A: Zone",
        )
    return TradeIntent(
        side=side,
        entry=price,
        stop=price + 2 * atr,
        target=price - 6 * atr,
        confidence=60.0,
        reason="A: Zone",
    )


# --------------------------------------------------------------------------- #
# The leak
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_scaling_the_whole_market_changes_nothing(side: Side) -> None:
    """The test that makes this safe rather than careful.

    Same situation, ten times the price and ten times the ATR. If a single
    character of the description moves, something absolute is in there -- and
    that something is enough for a model to date the period.
    """
    small = make_snapshot(price=10_000.0, atr=100.0)
    large = make_snapshot(price=100_000.0, atr=1_000.0)

    first = describe(small, intent_at(10_000.0, side=side)).canonical_json()
    second = describe(large, intent_at(100_000.0, side=side, scale=10.0)).canonical_json()

    assert first == second


def test_no_field_can_hold_a_price() -> None:
    """Checked against the serialised form rather than the class.

    A field added later with a plausible name -- `entry`, `stop_price` -- would
    pass a review and fail this.
    """
    snapshot = make_snapshot(price=10_000.0, atr=100.0)
    payload = json.loads(describe(snapshot, intent_at(10_000.0)).canonical_json())

    for name, value in payload.items():
        if not isinstance(value, (int, float)):
            continue
        assert abs(value) < 1_000, f"{name} is {value}, which is large enough to be a price"


def test_the_prices_themselves_appear_nowhere_in_the_request() -> None:
    """Belt and braces on the whole request, not just the proposal half."""
    snapshot = make_snapshot(price=12_345.0, atr=100.0)
    intent = intent_at(12_345.0)
    text = user_content(snapshot, intent)

    for price in (intent.entry, intent.stop, intent.target, snapshot.price):
        assert f"{price:.0f}" not in text, f"the price {price:.0f} reached the model"
        assert f"{price:.1f}" not in text


# --------------------------------------------------------------------------- #
# What it says
# --------------------------------------------------------------------------- #


def test_the_geometry_survives() -> None:
    """Hiding the price must not hide the shape of the trade.

    A judge that cannot tell a 2-ATR stop from a 6-ATR one is being asked to
    guess, and its answers would say nothing about judgement.
    """
    snapshot = make_snapshot(price=10_000.0, atr=100.0)
    view = describe(snapshot, intent_at(10_000.0))

    assert view.stop_distance_atr == pytest.approx(2.0)
    assert view.target_distance_atr == pytest.approx(6.0)
    assert view.reward_risk == pytest.approx(3.0)
    assert view.side is Side.LONG
    assert view.setup == "A"


def test_an_entry_away_from_the_last_close_is_located_not_hidden() -> None:
    """The offset is signed, because "the entry is a full ATR below here" and
    "a full ATR above" are different trades and the model needs to see which."""
    snapshot = make_snapshot(price=10_000.0, atr=100.0)

    below = describe(snapshot, intent_at(9_900.0))
    above = describe(snapshot, intent_at(10_100.0))

    assert below.entry_offset_atr == pytest.approx(-1.0)
    assert above.entry_offset_atr == pytest.approx(+1.0)


def test_a_short_keeps_its_direction_and_its_positive_distances() -> None:
    """Distances are magnitudes; the side carries the direction.

    A short whose stop distance came through negative would read as an
    incoherent trade and the model would rightly refuse it, which would look
    like judgement and be arithmetic.
    """
    snapshot = make_snapshot(price=10_000.0, atr=100.0)
    view = describe(snapshot, intent_at(10_000.0, side=Side.SHORT))

    assert view.side is Side.SHORT
    assert view.stop_distance_atr > 0
    assert view.target_distance_atr > 0
    assert view.reward_risk == pytest.approx(3.0)


def test_a_level_the_stop_rests_on_is_named() -> None:
    """The point of naming one is to say the stop sits *at* something visible.

    The ids are ones the model is shown in the market state anyway, so this adds
    no information it did not have -- it connects the proposal to it.
    """
    snapshot = make_snapshot(price=10_000.0, atr=100.0)
    level = snapshot.levels[0]
    intent = TradeIntent(
        side=Side.LONG,
        entry=level.price + 300.0,
        stop=level.price,
        target=level.price + 900.0,
        confidence=60.0,
        reason="B: Sweep",
    )

    view = describe(snapshot, intent)

    assert view.nearest_stop_level == level.id


def test_a_stop_resting_on_nothing_names_nothing() -> None:
    """Null rather than the least-far level.

    Naming a level two ATR away would tell the model the stop is at structure
    when it is not, which is a claim about the setup that the setup never made.
    """
    snapshot = make_snapshot(price=10_000.0, atr=100.0)
    far = max(lvl.price for lvl in snapshot.levels) + 50 * snapshot.atr
    intent = TradeIntent(
        side=Side.SHORT,
        entry=far,
        stop=far + 2 * snapshot.atr,
        target=far - 6 * snapshot.atr,
        confidence=60.0,
        reason="B: Sweep",
    )

    view = describe(snapshot, intent)

    assert view.nearest_stop_level is None
    assert NEAR_ATR < 1.0, "a threshold above an ATR would name whatever happened to be closest"


# --------------------------------------------------------------------------- #
# The cache
# --------------------------------------------------------------------------- #


def test_the_judging_question_has_its_own_version() -> None:
    """Otherwise the judge reads back the scanner's answer.

    The cache is keyed on the snapshot hash, the model, the prompt version and
    the schema version. Two different questions about the same bar with the same
    version string collide, and the collision is silent: a cache hit looks like
    a cache hit.
    """
    assert JUDGE_VERSION != PROMPT_VERSION


def test_the_question_tells_the_model_the_levels_are_not_its_to_move() -> None:
    """The division of labour has to be in the prompt, not only in the code.

    `BrainJudged` discards the model's plan and keeps the setup's levels. A
    model that believed it was being asked to place the trade would answer a
    question whose answer is then thrown away, and its reasoning would be about
    numbers that never got used.
    """
    snapshot = make_snapshot(price=10_000.0, atr=100.0)
    text = user_content(snapshot, intent_at(10_000.0))

    assert "not yours to change" in text
    assert "Do not move the entry, the stop or the target" in text
