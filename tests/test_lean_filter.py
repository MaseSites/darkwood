"""The liquidity lean as a filter, and the three ways it could cheat.

The measurement behind it is one-sided: when nearly all untouched pivot weight
sits above the price, the following week returns -0.195 ATR against a baseline
of +0.761. The filter refuses a long into that, and a short into its mirror.

Three tests exist because three different mistakes would each make it look
better than it is, and all three are quiet:

* **Reading a bar that has not closed.** The lean comes from the hourly frame
  while the loop may step on a faster one, so "the lean now" has to mean the
  newest *closed* hourly bar. Off by one in the other direction and the filter
  knows the hour it is deciding inside.
* **Adding trades.** A filter that proposes anything of its own is a second
  strategy wearing a filter's name, and the comparison against the unfiltered
  pool stops measuring the filter.
* **Acting in the middle.** The measured effect lives at the ends; the middle
  buckets came out +0.937, +1.122 and +0.537, which is not a gradient. A filter
  that acted there would be acting on noise and would still look busy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.sim.plan import TradeIntent
from traidingbrain.strategies.lean_filter import EXTREME, LEAN_FRAME, LeanFiltered, LeanTimeline

H1_MS = 3_600_000


class FixedPool:
    """A pool that always wants the same trade, so the filter is what is tested."""

    name = "fixed"

    def __init__(self, side: Side) -> None:
        self.side = side
        self.asked = 0

    def propose_at(self, analysis: object, index: int) -> TradeIntent | None:
        self.asked += 1
        if self.side is Side.LONG:
            return TradeIntent(
                side=Side.LONG, entry=100.0, stop=98.0, target=106.0, confidence=60.0
            )
        return TradeIntent(side=Side.SHORT, entry=100.0, stop=102.0, target=94.0, confidence=60.0)


class FixedLean:
    """A timeline with one answer, so a test can name the situation."""

    def __init__(self, lean: float | None) -> None:
        self.lean = lean

    def at_time(self, ts: int) -> float | None:
        return self.lean


class FakeAnalysis:
    """Just enough of the pipeline for the filter to ask what time it is."""

    def __init__(self, ts: int = 1_000_000) -> None:
        self.signal = self
        self._ts = ts

    def ts_at(self, index: int) -> int:
        return self._ts


def filtered(lean: float | None, side: Side = Side.LONG) -> tuple[LeanFiltered, FixedPool]:
    pool = FixedPool(side)
    return LeanFiltered(inner=pool, timeline=FixedLean(lean)), pool  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# What it refuses
# --------------------------------------------------------------------------- #


def test_a_long_into_a_ceiling_of_weight_is_refused() -> None:
    """The measured condition: nearly everything untouched sits overhead, and
    the week that follows is the worst in the record."""
    rule, _ = filtered(0.8, Side.LONG)

    assert rule.propose_at(FakeAnalysis(), 10) is None
    assert rule.refused == 1


def test_a_short_into_a_floor_of_weight_is_refused() -> None:
    """The mirror, and it has to be there: the side with almost everything
    below is the best week in the record, which is the worst one to be short."""
    rule, _ = filtered(-0.8, Side.SHORT)

    assert rule.propose_at(FakeAnalysis(), 10) is None


def test_a_trade_going_with_the_lean_is_left_alone() -> None:
    """The filter only subtracts, and only against the lean. A long with the
    weight below it is exactly the condition that measured best."""
    rule, _ = filtered(-0.8, Side.LONG)

    assert rule.propose_at(FakeAnalysis(), 10) is not None
    assert rule.refused == 0


def test_the_middle_is_never_acted_on() -> None:
    """The buckets between the ends came out +0.937, +1.122 and +0.537 -- not a
    gradient. A filter that acted there would be acting on noise."""
    for lean in (-0.5, -0.2, 0.0, 0.2, 0.5):
        for side in (Side.LONG, Side.SHORT):
            rule, _ = filtered(lean, side)
            assert rule.propose_at(FakeAnalysis(), 10) is not None, f"lean {lean} {side}"


def test_an_unknown_lean_does_not_block_the_trade() -> None:
    """During warm-up, or on a feed with no volume, there is no lean.

    Unknown has to mean "no opinion" rather than "refuse": a filter that
    blocked everything it could not judge would quietly remove the first
    months of every backtest and look like a conservative one.
    """
    rule, _ = filtered(None, Side.LONG)

    assert rule.propose_at(FakeAnalysis(), 10) is not None


def test_it_never_proposes_a_trade_the_pool_did_not(monkeypatch: pytest.MonkeyPatch) -> None:
    """A filter that adds anything is a second strategy wearing a filter's
    name, and the comparison against the unfiltered pool stops being about the
    filter."""

    class Silent:
        name = "silent"

        def propose_at(self, analysis: object, index: int) -> TradeIntent | None:
            return None

    rule = LeanFiltered(inner=Silent(), timeline=FixedLean(-0.9))  # type: ignore[arg-type]

    assert rule.propose_at(FakeAnalysis(), 10) is None


# --------------------------------------------------------------------------- #
# The bar it reads
# --------------------------------------------------------------------------- #


def rising_frame(bars: int = 400) -> pd.DataFrame:
    base = np.arange(bars, dtype="float64")
    wobble = np.sin(base / 7.0) * 3.0
    close = 100.0 + base * 0.05 + wobble
    return pd.DataFrame(
        {
            "ts": base.astype("int64") * H1_MS,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100.0 + (base % 11) * 7.0,
        }
    )


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


def test_the_lean_is_read_from_the_newest_closed_bar(config: AppConfig) -> None:
    """The lean comes from the hourly frame while the loop may step on a faster
    one, so "now" has to mean the newest hourly bar that has *finished*.

    Asked for a timestamp in the middle of a bar, it must answer with the bar
    before it. The other way round, the filter would know the hour it is
    deciding inside -- which is the one mistake this project is built to avoid,
    and it would make every backtest on it look better than the live system.
    """
    frame = rising_frame()
    timeline = LeanTimeline(frame, config)
    stamps = frame["ts"].to_numpy(dtype="int64")

    at_close = timeline.at_time(int(stamps[300]))
    mid_bar = timeline.at_time(int(stamps[300]) + H1_MS // 2)
    next_close = timeline.at_time(int(stamps[301]))

    assert mid_bar == at_close, "a half-finished bar was read as closed"
    assert next_close is not None or at_close is not None


def test_asking_before_anything_was_confirmed_gives_no_opinion(config: AppConfig) -> None:
    frame = rising_frame()
    timeline = LeanTimeline(frame, config)

    assert timeline.at_time(-1) is None


def test_the_threshold_is_named_rather_than_written_into_the_rule() -> None:
    """0.6 was chosen by looking at the same data this is backtested on.

    That is the weakest part of the whole thing and it is why the number has a
    name and a docstring rather than sitting inside a comparison: it is the
    first thing to revisit when the forward journal has enough trades to
    disagree.
    """
    assert 0.0 < EXTREME < 1.0
    assert LEAN_FRAME is Timeframe.H1
