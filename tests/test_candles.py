"""The candlestick patterns from the guide, built by hand so each is checkable.

Every fixture here is a handful of candles written out digit by digit, because a
pattern test on generated data proves that the code agrees with itself. The
numbers in the assertions can be read off the fixture with a pencil.

Two things this file is really guarding:

The first is **fidelity to the source**. Each test names the video and quotes the
condition it encodes. If someone later loosens a threshold to make a backtest
look better, the quote is sitting next to the number, and the change stops being
a tuning decision and becomes an argument with the source.

The second is **no lookahead**, which for candles has one specific shape. V03's
doji needs two candles after it to mean anything. Marking that on the doji's own
bar would hand the engine two bars it did not have, inside a signal it would be
trading -- and every backtest would look better for it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.candles import (
    BREAKOUT_BODY_BEYOND_FRACTION,
    MOMENTUM_BODY_MULTIPLE,
    CandlePattern,
    CandleTimeline,
    confirm_breakout,
)
from traidingbrain.domain.enums import Bias


def candles(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """(open, high, low, close) per bar, on a fixed hourly grid."""
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


def flat_atr(frame: pd.DataFrame, value: float = 1.0) -> pd.Series:
    """A constant volatility unit, so a threshold in ATR is readable by hand."""
    return pd.Series([value] * len(frame), index=frame.index)


def quiet(count: int, price: float = 100.0) -> list[tuple[float, float, float, float]]:
    """Small alternating candles: something for a momentum test to be large against."""
    rows = []
    for i in range(count):
        up = i % 2 == 0
        rows.append((price, price + 0.6, price - 0.6, price + 0.4 if up else price - 0.4))
    return rows


def found(frame: pd.DataFrame, index: int) -> tuple[CandlePattern, ...]:
    return CandleTimeline(frame, flat_atr(frame)).at(index)


# --------------------------------------------------------------------------- #
# V03 — the patterns, one at a time
# --------------------------------------------------------------------------- #


def test_bullish_engulfing_opens_at_or_below_the_previous_close() -> None:
    """V03: "Neue Kerze öffnet am/unter vorherigem Close und schließt über
    vorherigem Open."

    "am" is in the source and it is not a rounding allowance: on a continuously
    traded market one bar's close is usually the next bar's open, so reading it
    as strictly below would reject the ordinary case.
    """
    frame = candles([*quiet(6), (100.0, 100.2, 98.0, 98.5), (98.5, 101.0, 98.4, 100.6)])

    assert CandlePattern.BULLISH_ENGULFING in found(frame, 7)


def test_a_close_short_of_the_previous_open_is_not_engulfing() -> None:
    """The negative half, which is the half that stops a pattern matching
    everything: closing inside the previous body is not engulfing it."""
    frame = candles([*quiet(6), (100.0, 100.2, 98.0, 98.5), (98.5, 100.0, 98.4, 99.6)])

    assert CandlePattern.BULLISH_ENGULFING not in found(frame, 7)


def test_bearish_engulfing_is_the_mirror() -> None:
    frame = candles([*quiet(6), (100.0, 102.0, 99.8, 101.5), (101.5, 101.6, 99.0, 99.4)])

    assert CandlePattern.BEARISH_ENGULFING in found(frame, 7)


def test_a_momentum_candle_is_twice_the_recent_body() -> None:
    """V03: "ungefähr zwei- bis dreimal so groß wie vorherige Kerzen".

    The quiet bars have a body of 0.4, so the threshold sits at 0.8 and this
    candle's body of 3.0 clears it with room to spare -- deliberately, so the
    test does not turn into a test of the exact multiple.
    """
    frame = candles([*quiet(6), (100.0, 103.2, 99.9, 103.0)])

    assert CandlePattern.MOMENTUM_UP in found(frame, 6)


def test_a_candle_just_under_the_multiple_is_not_momentum() -> None:
    body = MOMENTUM_BODY_MULTIPLE * 0.4 * 0.9
    frame = candles([*quiet(6), (100.0, 100.0 + body + 0.1, 99.9, 100.0 + body)])

    assert CandlePattern.MOMENTUM_UP not in found(frame, 6)


def test_a_long_wick_is_not_momentum_even_when_the_range_is_large() -> None:
    """Measured on the body, not the range. A long wick says the move was
    rejected, which is the opposite of what a momentum candle claims -- and V08
    refuses exactly this shape as a breakout."""
    frame = candles([*quiet(6), (100.0, 106.0, 99.9, 100.3)])

    assert CandlePattern.MOMENTUM_UP not in found(frame, 6)


def test_a_doji_has_a_small_body_and_wicks_on_both_sides() -> None:
    frame = candles([*quiet(6), (100.0, 101.0, 99.0, 100.02)])
    patterns = found(frame, 6)

    assert CandlePattern.DOJI in patterns
    assert CandlePattern.DOJI_LONG_LEGGED in patterns


@pytest.mark.parametrize(
    ("row", "variant"),
    [
        ((100.0, 100.05, 99.0, 100.02), CandlePattern.DOJI_DRAGONFLY),
        ((100.0, 101.0, 99.95, 100.02), CandlePattern.DOJI_GRAVESTONE),
    ],
)
def test_the_named_doji_variants_are_told_apart_by_which_side_the_wick_is_on(
    row: tuple[float, float, float, float], variant: CandlePattern
) -> None:
    frame = candles([*quiet(6), row])

    assert variant in found(frame, 6)


def test_a_hammer_is_a_long_lower_wick_on_a_real_body() -> None:
    """V03: body with a long lower wick; sellers were pushed back."""
    # Body 1.0, lower wick 3.0, almost nothing above.
    frame = candles([*quiet(6), (100.0, 101.1, 97.0, 101.0)])

    assert CandlePattern.HAMMER in found(frame, 6)


def test_a_doji_is_not_also_read_as_a_hammer() -> None:
    """A dragonfly doji is a long lower wick on almost no body -- which V03
    already names. Letting it read as both would count one candle as two
    independent signals, and confluence tests count signals."""
    frame = candles([*quiet(6), (100.0, 100.05, 97.0, 100.02)])
    patterns = found(frame, 6)

    assert CandlePattern.DOJI_DRAGONFLY in patterns
    assert CandlePattern.HAMMER not in patterns


def test_a_shooting_star_is_the_mirror_of_a_hammer() -> None:
    frame = candles([*quiet(6), (100.0, 102.0, 98.9, 99.0)])

    assert CandlePattern.SHOOTING_STAR in found(frame, 6)


def test_a_tweezer_bottom_is_red_then_green_at_the_same_low() -> None:
    """V03: "rote, dann grüne Kerze mit ähnlichen Tiefdochten an Support"."""
    frame = candles([*quiet(6), (100.0, 100.2, 98.0, 98.4), (98.4, 100.0, 98.02, 99.8)])

    assert CandlePattern.TWEEZER_BOTTOM in found(frame, 7)


def test_two_lows_far_apart_are_not_a_tweezer() -> None:
    """"Ähnlich" is measured in ATR, so it scales with how much the market is
    moving. Here the lows are a full ATR apart."""
    frame = candles([*quiet(6), (100.0, 100.2, 98.0, 98.4), (98.4, 100.0, 99.2, 99.8)])

    assert CandlePattern.TWEEZER_BOTTOM not in found(frame, 7)


def test_a_marubozu_is_a_large_candle_with_almost_no_wicks() -> None:
    frame = candles([*quiet(6), (100.0, 103.0, 100.0, 103.0)])

    assert CandlePattern.MARUBOZU_UP in found(frame, 6)


def test_a_small_wickless_candle_is_not_a_marubozu() -> None:
    """V03 says "große Kerze ohne Dochte". A tiny wickless bar is a pause, not
    the continuation signal the video describes."""
    frame = candles([*quiet(6), (100.0, 100.3, 100.0, 100.3)])

    assert CandlePattern.MARUBOZU_UP not in found(frame, 6)


def test_three_candles_wicking_the_same_way_is_the_multiple_wick_pattern() -> None:
    """V03: "mindestens drei Kerzen mit Dochten in dieselbe Richtung"."""
    row = (100.0, 100.4, 98.0, 100.2)
    frame = candles([*quiet(6), row, row, row])

    assert CandlePattern.MULTIPLE_WICK_UP in found(frame, 8)


def test_two_is_not_three() -> None:
    row = (100.0, 100.4, 98.0, 100.2)
    frame = candles([*quiet(6), row, row])

    assert CandlePattern.MULTIPLE_WICK_UP not in found(frame, 7)


# --------------------------------------------------------------------------- #
# The doji's confirmation, which is where lookahead would enter
# --------------------------------------------------------------------------- #


def test_the_doji_confirmation_lands_two_bars_after_the_doji() -> None:
    """V03 waits for "zwei Kerzen gleicher neuer Richtung" after the doji.

    The confirmation is reported on the second confirming bar, because that is
    the first bar on which the video's condition is true. Marking it on the doji
    would let a backtest enter two bars before the evidence existed, and the
    result would look better for exactly that reason.
    """
    doji = (100.0, 101.0, 99.0, 100.02)
    up = (100.0, 101.2, 99.9, 101.0)
    timeline = CandleTimeline(candles([*quiet(6), doji, up, up]), flat_atr(candles(quiet(9))))

    assert CandlePattern.DOJI_CONFIRMED_UP not in timeline.at(6)
    assert CandlePattern.DOJI_CONFIRMED_UP not in timeline.at(7)
    assert CandlePattern.DOJI_CONFIRMED_UP in timeline.at(8)


def test_one_up_and_one_down_candle_do_not_confirm_anything() -> None:
    doji = (100.0, 101.0, 99.0, 100.02)
    frame = candles([*quiet(6), doji, (100.0, 101.2, 99.9, 101.0), (101.0, 101.1, 99.5, 99.8)])
    patterns = found(frame, 8)

    assert CandlePattern.DOJI_CONFIRMED_UP not in patterns
    assert CandlePattern.DOJI_CONFIRMED_DOWN not in patterns


def test_changing_later_bars_cannot_change_an_earlier_reading() -> None:
    """The general form of the same guarantee, over the whole timeline.

    If any detector ever reaches forward -- a window written with the wrong sign,
    a pattern confirmed from bars that had not closed -- this is what catches it,
    and it catches it without anyone having to suspect which one.
    """
    rng = np.random.default_rng(11)
    rows = [
        (
            float(price),
            float(price + rng.uniform(0, 2)),
            float(price - rng.uniform(0, 2)),
            float(price + rng.uniform(-1, 1)),
        )
        for price in rng.uniform(95, 105, 60)
    ]
    frame = candles(rows)
    cut = 30
    before = [CandleTimeline(frame, flat_atr(frame)).at(i) for i in range(cut)]

    mutated = frame.copy()
    mutated.loc[cut:, ["open", "high", "low", "close"]] = 999.0
    after = [CandleTimeline(mutated, flat_atr(mutated)).at(i) for i in range(cut)]

    assert before == after


# --------------------------------------------------------------------------- #
# Conflicting patterns
# --------------------------------------------------------------------------- #


def test_a_bar_arguing_both_ways_reads_as_neutral() -> None:
    """V03's own rule is that patterns are hints needing context. A bar showing
    one bullish and one bearish pattern is saying it is unclear, and reporting
    the majority would turn that into a stance the video never takes."""
    # Engulfing up, but the long upper wick is a shooting star.
    frame = candles([*quiet(6), (100.0, 100.2, 99.0, 99.2), (99.1, 103.5, 99.0, 100.5)])
    timeline = CandleTimeline(frame, flat_atr(frame))
    patterns = timeline.at(7)

    assert CandlePattern.BULLISH_ENGULFING in patterns
    assert CandlePattern.SHOOTING_STAR in patterns
    assert timeline.bias_at(7) is Bias.NEUTRAL


def test_an_unread_bar_is_neutral_rather_than_an_error() -> None:
    frame = candles(quiet(4))
    timeline = CandleTimeline(frame, flat_atr(frame))

    assert timeline.at(-1) == ()
    assert timeline.bias_at(999) is Bias.NEUTRAL


# --------------------------------------------------------------------------- #
# V08 — the breakout confirmation, which is the point of that video
# --------------------------------------------------------------------------- #


def test_a_wick_through_the_level_does_not_confirm_a_breakout() -> None:
    """V08: "Nur ein Docht oder eine kleine Körperspitze über dem Level zählt
    nicht." This refusal is the entire subject of the video, so it is reported
    as its own answer rather than as a silent no."""
    frame = candles([*quiet(6), (100.0, 104.0, 99.9, 100.4)])

    verdict = confirm_breakout(frame, flat_atr(frame), 6, level=102.0, upward=True)

    assert verdict.confirmed is False
    assert verdict.form == "none"
    assert verdict.detail


def test_a_momentum_candle_mostly_beyond_the_level_confirms_it() -> None:
    """V08's first accepted form: "eine einzelne große Kerze, deren Körper
    mehrheitlich jenseits des Ausbruchsniveaus liegt"."""
    frame = candles([*quiet(6), (100.0, 104.2, 99.9, 104.0)])

    verdict = confirm_breakout(frame, flat_atr(frame), 6, level=101.0, upward=True)

    assert verdict.confirmed is True
    assert verdict.form == "momentum_candle"


def test_the_same_candle_confirms_one_level_and_not_a_higher_one() -> None:
    """"Mehrheitlich" is a majority, and it is measured against the level.

    One candle, two levels. The body runs 100 to 104: against a level at 101.5
    most of it is beyond, against one at 103.9 almost none of it is. Same bar,
    opposite answers -- which is what makes this a rule about the break rather
    than about the candle.
    """
    frame = candles([*quiet(6), (100.0, 104.2, 99.9, 104.0)])
    atr = flat_atr(frame)

    assert confirm_breakout(frame, atr, 6, level=101.5, upward=True).confirmed is True
    assert confirm_breakout(frame, atr, 6, level=103.9, upward=True).confirmed is False


def test_the_majority_boundary_sits_where_the_word_says() -> None:
    """Exactly half is not a majority. Boundaries are where a rule written from
    a word usually goes wrong, so this pins which side of it the code is on."""
    frame = candles([*quiet(6), (100.0, 104.2, 99.9, 104.0)])
    body = 104.0 - 100.0
    exactly_half = 104.0 - BREAKOUT_BODY_BEYOND_FRACTION * body

    at_half = confirm_breakout(frame, flat_atr(frame), 6, level=exactly_half, upward=True)

    assert at_half.confirmed is True, "the guide says mehrheitlich, read as at least half"


def test_three_medium_candles_beyond_the_level_confirm_it() -> None:
    """V08's second accepted form. None of these three is a momentum candle on
    its own; together they are the sequence the video accepts."""
    step = (101.0, 101.9, 100.9, 101.8)
    frame = candles([*quiet(6), step, (101.8, 102.7, 101.7, 102.6), (102.6, 103.5, 102.5, 103.4)])

    verdict = confirm_breakout(frame, flat_atr(frame), 8, level=100.5, upward=True)

    assert verdict.confirmed is True
    assert verdict.form == "three_candles"


def test_a_red_candle_in_the_sequence_breaks_it() -> None:
    """V08's own counter-example: "Eine kleine Ausbruchskerze gefolgt von einer
    roten Kerze wird im Long-Beispiel verworfen."""
    up = (101.0, 101.9, 100.9, 101.8)
    down = (101.8, 102.0, 101.0, 101.1)
    frame = candles([*quiet(6), up, down, (101.1, 102.0, 101.0, 101.9)])

    verdict = confirm_breakout(frame, flat_atr(frame), 8, level=100.5, upward=True)

    assert verdict.confirmed is False


def test_a_downward_break_is_judged_the_same_way_in_the_mirror() -> None:
    frame = candles([*quiet(6), (100.0, 100.1, 95.8, 96.0)])

    verdict = confirm_breakout(frame, flat_atr(frame), 6, level=99.0, upward=False)

    assert verdict.confirmed is True
    assert verdict.form == "momentum_candle"


def test_a_doji_cannot_confirm_a_breakout() -> None:
    """A zero-height body has no fraction beyond anything. Treating it as fully
    beyond would let the least decisive candle on the chart confirm the most
    decisive claim."""
    frame = candles([*quiet(6), (100.0, 104.0, 99.0, 100.0)])

    verdict = confirm_breakout(frame, flat_atr(frame), 6, level=99.5, upward=True)

    assert verdict.confirmed is False


def test_too_little_history_says_so_rather_than_guessing() -> None:
    frame = candles(quiet(3))

    verdict = confirm_breakout(frame, flat_atr(frame), 2, level=100.0, upward=True)

    assert verdict.confirmed is False
    assert "not enough bars" in verdict.detail
