"""What the chart is allowed to show.

One test here is worth more than the rest combined: the chart must not contain a
single bar after the decision. Everything else is legibility, and legibility
failures are visible. A chart quietly extending two candles past the decision is
invisible, makes every setup look better than it was, and would turn this screen
from a way of judging a trade into a way of being convinced by one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from traidingbrain.api.chart import MAX_LEVELS, build_chart
from traidingbrain.domain.enums import LevelKind, ProposalStatus, Side, Timeframe
from traidingbrain.domain.proposal import LevelMark, TradeProposal

HOUR = 3_600_000
START = 1_700_000_000_000


def bars(count: int = 300, *, start: int = START, base: float = 100.0) -> pd.DataFrame:
    """A plain rising series. The shape does not matter; the timestamps do."""
    return pd.DataFrame(
        {
            "ts": [start + i * HOUR for i in range(count)],
            "open": [base + i for i in range(count)],
            "high": [base + i + 0.5 for i in range(count)],
            "low": [base + i - 0.5 for i in range(count)],
            "close": [base + i + 0.2 for i in range(count)],
            "volume": [10.0] * count,
        }
    )


def proposal(
    *,
    decision_index: int = 200,
    levels: list[LevelMark] | None = None,
    side: Side = Side.LONG,
) -> TradeProposal:
    entry = 100.0 + decision_index
    return TradeProposal(
        symbol="BTCUSDT",
        side=side,
        entry=entry,
        stop=entry - 10 if side is Side.LONG else entry + 10,
        target=entry + 20 if side is Side.LONG else entry - 20,
        qty=1.0,
        leverage=5.0,
        notional=entry,
        margin=entry / 5,
        liquidation_price=entry - 60 if side is Side.LONG else entry + 60,
        risk_amount=100.0,
        risk_pct=0.01,
        equity_at_build=10_000.0,
        bias="bullish" if side is Side.LONG else "bearish",
        confidence=70.0,
        risk_level="medium",
        snapshot_hash="x" * 64,
        status=ProposalStatus.PENDING,
        snapshot_ts=START + decision_index * HOUR,
        signal_timeframe=Timeframe.H1,
        price_at_build=entry,
        atr_at_build=5.0,
        levels=levels or [],
    )


def level(price: float, kind: LevelKind = LevelKind.SWING_HIGH, *, touches: int = 1) -> LevelMark:
    return LevelMark(
        id=f"lvl_{int(price)}",
        kind=kind,
        timeframe=Timeframe.H1,
        price=price,
        distance_atr=0.0,
        age_bars=5,
        touches=touches,
    )


# --------------------------------------------------------------------------- #
# The one that matters
# --------------------------------------------------------------------------- #


def test_no_bar_after_the_decision_reaches_the_chart() -> None:
    """The reader must be able to judge the setup without seeing the outcome.

    A frame running to the present is the normal input here -- the store holds
    everything -- so this is not a defensive check against a strange caller. It is
    the trim that makes the endpoint safe to point at live data.
    """
    p = proposal(decision_index=200)

    view = build_chart(p, bars(300))

    assert view.candles, "the chart came back empty"
    assert max(candle.ts for candle in view.candles) == p.snapshot_ts
    assert all(candle.ts <= p.snapshot_ts for candle in view.candles)


def test_the_decision_bar_itself_is_included() -> None:
    """Off by one in the safe direction is still wrong: it hides the trigger bar."""
    p = proposal(decision_index=200)

    view = build_chart(p, bars(300))

    assert view.candles[-1].ts == p.snapshot_ts
    assert view.decision_ts == p.snapshot_ts


def test_a_frame_that_stops_early_is_not_padded() -> None:
    """Missing history is shown as missing, never invented."""
    p = proposal(decision_index=250)

    view = build_chart(p, bars(100))

    assert len(view.candles) == 100
    assert view.candles[-1].ts < p.snapshot_ts


# --------------------------------------------------------------------------- #
# Legibility
# --------------------------------------------------------------------------- #


def test_the_context_window_is_bounded() -> None:
    view = build_chart(proposal(decision_index=280), bars(300), context_bars=50)

    assert len(view.candles) == 50


def test_near_identical_levels_collapse_into_one() -> None:
    """Price returns to the same place, so the raw list is full of duplicates.

    Four lines a tenth of an ATR apart are one level drawn four times, and they
    crowd out everything else on the chart.
    """
    p = proposal(levels=[level(300.0 + offset) for offset in (0.0, 0.2, 0.4, 0.6)])

    view = build_chart(p, bars(300))

    assert len(view.levels) == 1
    assert view.levels_hidden == 3


def test_the_survivor_of_a_merge_is_the_better_evidenced_one() -> None:
    """A level price has returned to often is a level; a graze is a coincidence."""
    p = proposal(
        levels=[
            level(300.0, touches=1),
            level(300.3, touches=9),
        ]
    )

    view = build_chart(p, bars(300))

    assert len(view.levels) == 1
    assert view.levels[0].touches == 9


def test_the_number_of_lines_is_capped_and_the_remainder_counted() -> None:
    """An unreadable chart is worse than a sparse one: it still looks informative."""
    p = proposal(levels=[level(200.0 + i * 20) for i in range(30)])

    view = build_chart(p, bars(300))

    assert len(view.levels) <= MAX_LEVELS
    assert view.levels_hidden == 30 - len(view.levels)


def test_levels_are_ordered_top_to_bottom() -> None:
    """They are drawn on a price axis, so any other order is a puzzle."""
    p = proposal(levels=[level(p) for p in (250.0, 400.0, 180.0, 320.0)])

    view = build_chart(p, bars(300))
    prices = [line.price for line in view.levels]

    assert prices == sorted(prices, reverse=True)


def test_the_current_price_marker_is_not_drawn_as_a_level() -> None:
    """It is already the last candle, and a second line saying so is noise."""
    p = proposal(levels=[level(300.0, LevelKind.CURRENT), level(310.0)])

    view = build_chart(p, bars(300))

    assert [line.kind for line in view.levels] == ["swing_high"]


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #


def test_every_plan_line_carries_its_consequence() -> None:
    """A price is a fact; a price with its consequence is a decision.

    "Stop 85,468" tells you nothing you are agreeing to. "Stop 85,468, -100"
    does, and that is what someone is holding the button for.
    """
    view = build_chart(proposal(), bars(300))
    by_role = {line.role: line for line in view.plan}

    assert set(by_role) == {"entry", "stop", "target", "liquidation"}
    assert "100" in by_role["stop"].detail
    assert "R" in by_role["target"].detail
    assert "beyond the stop" in by_role["liquidation"].detail
    assert all(line.detail for line in view.plan)


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_the_plan_prices_match_the_proposal_exactly(side: Side) -> None:
    """The chart and the order must not be two versions of the same trade."""
    p = proposal(side=side)
    view = build_chart(p, bars(300))
    by_role = {line.role: line.price for line in view.plan}

    assert by_role["entry"] == p.entry
    assert by_role["stop"] == p.stop
    assert by_role["target"] == p.target
    assert by_role["liquidation"] == p.liquidation_price


def test_a_proposal_with_no_levels_still_charts() -> None:
    """Nothing named is a real state, and it must not be an error."""
    view = build_chart(proposal(levels=[]), bars(300))

    assert view.levels == []
    assert view.levels_hidden == 0
    assert len(view.plan) == 4


def test_the_note_says_why_the_chart_stops_where_it_does() -> None:
    """Without it, the missing right-hand side reads as broken data."""
    assert "decision" in build_chart(proposal(), bars(300)).note
