"""Open interest, read as a stance.

The cell of the truth table worth testing hardest is the counter-intuitive one:
price rising while open interest falls is positions closing, and closing pressure
runs out. It argues *against* continuation even though the price is going that
way. Getting that backwards would give the system a confident bullish reading on
exactly the rallies that end.

The other thing tested here is silence. Bybit's history starts well after the
candles do, and a missing reading has to stay missing. Turning it into a zero
would assert that positioning did not change -- which happens to be the most
common reading in the table, so the bug would look like a plausible answer on
every bar it touched.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.positioning import (
    CHANGE_WINDOW,
    MIN_OI_CHANGE,
    PositioningTimeline,
)
from traidingbrain.domain.enums import Bias

HOUR = 3_600_000
START = 1_700_000_000_000


def price_frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [START + i * HOUR for i in range(len(closes))],
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": [1.0] * len(closes),
        }
    )


def oi_frame(values: list[float], *, offset: int = 0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [START + (i + offset) * HOUR for i in range(len(values))],
            "open_interest": values,
        }
    )


def ratio_frame(buys: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [START + i * HOUR for i in range(len(buys))],
            "buy_ratio": buys,
            "sell_ratio": [1 - b for b in buys],
        }
    )


def ramp(start: float, step: float, count: int) -> list[float]:
    return [start + step * i for i in range(count)]


# --------------------------------------------------------------------------- #
# The truth table
# --------------------------------------------------------------------------- #


def test_price_up_on_rising_interest_is_new_longs() -> None:
    bars = 30
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, bars)), oi_frame(ramp(1000.0, 20.0, bars))
    )

    view = timeline.at(bars - 1)

    assert view.known
    assert view.reading == "new_longs"
    assert view.bias is Bias.BULLISH


def test_price_up_on_falling_interest_is_short_covering_and_argues_bearish() -> None:
    """The cell a chart cannot show, and the reason this module exists.

    A rally driven by shorts being forced out looks identical to one driven by
    buyers, right up until the last short is out and it stops.
    """
    bars = 30
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, bars)), oi_frame(ramp(2000.0, -20.0, bars))
    )

    view = timeline.at(bars - 1)

    assert view.reading == "short_covering"
    assert view.bias is Bias.BEARISH, "a squeeze is not demand"


def test_price_down_on_rising_interest_is_new_shorts() -> None:
    bars = 30
    timeline = PositioningTimeline(
        price_frame(ramp(200.0, -1.0, bars)), oi_frame(ramp(1000.0, 20.0, bars))
    )

    assert timeline.at(bars - 1).reading == "new_shorts"
    assert timeline.at(bars - 1).bias is Bias.BEARISH


def test_price_down_on_falling_interest_is_a_flush_and_argues_bullish() -> None:
    bars = 30
    timeline = PositioningTimeline(
        price_frame(ramp(200.0, -1.0, bars)), oi_frame(ramp(2000.0, -20.0, bars))
    )

    view = timeline.at(bars - 1)

    assert view.reading == "long_liquidation"
    assert view.bias is Bias.BULLISH


def test_a_negligible_change_is_not_given_a_label() -> None:
    """Without a floor every bar gets a confident reading out of rounding noise."""
    bars = 30
    tiny = MIN_OI_CHANGE / 10
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, bars)),
        oi_frame([1000.0 * (1 + tiny * i / bars) for i in range(bars)]),
    )

    view = timeline.at(bars - 1)

    assert view.reading == "flat_interest"
    assert view.bias is Bias.NEUTRAL


# --------------------------------------------------------------------------- #
# Silence
# --------------------------------------------------------------------------- #


def test_no_data_at_all_reports_unknown_rather_than_neutral() -> None:
    """The distinction the whole prompt depends on.

    Neutral is a claim about the market. Unknown is a claim about the data, and a
    model shown the first when the second is true will weight the silence.
    """
    timeline = PositioningTimeline(price_frame(ramp(100.0, 1.0, 30)), None, None)

    view = timeline.at(29)

    assert view.known is False
    assert view.reading == "unknown"
    assert "no data" in view.describe()


def test_a_period_before_the_venue_reported_stays_unknown() -> None:
    """Open interest starts in 2023; the candles start earlier. Both are right."""
    bars = 40
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, bars)),
        oi_frame(ramp(1000.0, 20.0, 10), offset=30),
    )

    assert timeline.at(5).known is False
    assert timeline.at(bars - 1).known is True


def test_a_long_gap_is_not_papered_over_with_the_last_reading() -> None:
    """A venue that stopped reporting is not positioning that stopped changing."""
    bars = 40
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, bars)),
        oi_frame(ramp(1000.0, 20.0, 5)),  # data only for the first five hours
    )

    assert timeline.at(bars - 1).known is False


def test_a_crowd_reading_survives_without_open_interest() -> None:
    """Thin evidence is still evidence, and is reported as the thin kind."""
    bars = 30
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, bars)), None, ratio_frame([0.72] * bars)
    )

    view = timeline.at(bars - 1)

    assert view.known is True
    assert view.reading == "crowded"
    assert view.oi_change_pct is None
    assert view.crowd_is_stretched is True


@pytest.mark.parametrize(("ratio", "expected"), [(0.75, Bias.BEARISH), (0.25, Bias.BULLISH)])
def test_a_crowded_book_argues_against_the_crowd(ratio: float, expected: Bias) -> None:
    bars = 30
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, bars)), None, ratio_frame([ratio] * bars)
    )

    assert timeline.at(bars - 1).bias is expected


def test_a_balanced_book_says_nothing() -> None:
    bars = 30
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, bars)), None, ratio_frame([0.51] * bars)
    )

    view = timeline.at(bars - 1)

    assert view.crowd_is_stretched is False
    assert view.bias is Bias.NEUTRAL


# --------------------------------------------------------------------------- #
# No lookahead
# --------------------------------------------------------------------------- #


def test_a_reading_does_not_change_when_the_future_is_rewritten() -> None:
    """The same guarantee the rest of the analysis is held to.

    The percentile is the risk here: ranking a value against the whole series
    would quietly include tomorrow, and it would arrive looking like a
    normalisation step rather than like a signal.
    """
    bars = 400
    closes = ramp(100.0, 0.5, bars)
    oi = ramp(1000.0, 5.0, bars)
    cut = 250

    before = PositioningTimeline(price_frame(closes), oi_frame(oi)).at(cut)

    rng = np.random.default_rng(7)
    mutated_closes = list(closes)
    mutated_oi = list(oi)
    for i in range(cut + 1, bars):
        mutated_closes[i] = float(rng.uniform(50, 500))
        mutated_oi[i] = float(rng.uniform(100, 9000))
    after = PositioningTimeline(price_frame(mutated_closes), oi_frame(mutated_oi)).at(cut)

    assert before == after


def test_the_percentile_stays_empty_until_there_is_enough_history() -> None:
    """A rank over twenty samples is noise wearing a statistic's clothes."""
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, 40)), oi_frame(ramp(1000.0, 20.0, 40))
    )

    assert timeline.at(39).oi_percentile is None


def test_indices_before_the_change_window_report_nothing() -> None:
    timeline = PositioningTimeline(
        price_frame(ramp(100.0, 1.0, 30)), oi_frame(ramp(1000.0, 20.0, 30))
    )

    assert timeline.at(CHANGE_WINDOW - 1).known is False


def test_an_index_outside_the_frame_is_unknown_rather_than_an_error() -> None:
    timeline = PositioningTimeline(price_frame(ramp(100.0, 1.0, 10)))

    assert timeline.at(-1).known is False
    assert timeline.at(999).known is False
