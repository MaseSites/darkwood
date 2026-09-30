"""The properties the rest of the system is allowed to assume.

The most important group here is the one about what the brain can see. If
`to_brain_input` ever leaks a price, a timestamp or a symbol name, the model can
recognise which week it is looking at and answer from what it knows happened next.
No backtest would reveal that; the numbers would simply look good. So it is
checked directly.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.factories import BASE_PRICE, make_levels, make_snapshot, make_verdict
from traidingbrain.domain import (
    Bias,
    Decision,
    ProposalStatus,
    Side,
    Timeframe,
    TradeProposal,
    TradeState,
)
from traidingbrain.domain.enums import CONTEXT_FRAMES, EXECUTION_FRAME, SIGNAL_FRAME
from traidingbrain.domain.snapshot import NORM_PRECISION

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# What the brain may see
# --------------------------------------------------------------------------- #


def test_brain_input_carries_no_identifying_information() -> None:
    snapshot = make_snapshot()
    payload = snapshot.to_brain_input().canonical_json()

    assert snapshot.symbol not in payload, "the symbol name reached the model"
    assert str(snapshot.ts) not in payload, "the timestamp reached the model"
    assert "42000" not in payload.replace(".", ""), "an absolute price reached the model"

    parsed = json.loads(payload)
    assert set(parsed) == {
        "schema_version",
        "signal_timeframe",
        "atr_pct",
        "frames",
        "levels",
        "news",
        "positioning",
        "sentiment",
        "history",
    }


def test_sentiment_reaches_the_model_as_an_index_and_nothing_else() -> None:
    """The index is a bounded number, and that is the whole reason it is safe.

    Unlike open interest there is no absolute quantity to leak here -- 0 to 100
    carries no asset and no era. What would leak is a date, so the block has no
    timestamp and no age: the model is told the mood, not when it was measured.
    """
    sentiment = make_snapshot().to_brain_input().sentiment

    assert 0 <= sentiment.value <= 100
    assert set(sentiment.model_dump()) == {"known", "value", "label", "is_extreme"}


def test_positioning_reaches_the_model_as_ratios_and_never_as_a_contract_count() -> None:
    """Open interest is a large absolute number, and that is the danger.

    Fifty-six thousand contracts on one symbol and four hundred million on
    another identifies both instantly, and the size of the number carries the era
    as well as the asset. Only the change and the rank travel, both dimensionless
    -- the same discipline the price itself is held to.
    """
    snapshot = make_snapshot()
    positioning = snapshot.to_brain_input().positioning

    for value in (
        positioning.open_interest_change_pct,
        positioning.open_interest_percentile,
        positioning.crowd_long_ratio,
    ):
        assert value is None or -10.0 <= value <= 10.0, "an absolute contract count leaked"


def test_a_scheduled_event_reaches_the_model_without_a_date() -> None:
    """'FOMC in six hours' is evidence; 'FOMC on 2024-03-20' is a year and a month.

    The whole normalisation argument collapses if the news block carries a date:
    the model would know exactly when it is, and its answer would be partly
    recollection.
    """
    payload = make_snapshot().to_brain_input().canonical_json()
    parsed = json.loads(payload)

    for item in parsed["news"]:
        assert set(item) <= {"event", "impact", "sentiment", "minutes_until"}
        assert not re.search(r"20\d\d-\d\d-\d\d", json.dumps(item))


def test_brain_input_levels_expose_distance_but_never_price() -> None:
    snapshot = make_snapshot()
    for level in snapshot.to_brain_input().levels:
        assert "price" not in level
        assert set(level) == {"id", "kind", "timeframe", "distance_atr", "age_bars", "touches"}


def test_identical_shapes_at_different_price_levels_hash_identically() -> None:
    """The same setup on a $42k chart and a $84k chart is the same setup.

    This is what makes the decision cache worth having and what lets the system
    carry experience from BTC to the other symbols.
    """
    cheap_atr = BASE_PRICE * 0.01
    dear_atr = BASE_PRICE * 2 * 0.01
    cheap = make_snapshot(
        price=BASE_PRICE, atr=cheap_atr, levels=make_levels(BASE_PRICE, cheap_atr)
    )
    dear = make_snapshot(
        price=BASE_PRICE * 2, atr=dear_atr, levels=make_levels(BASE_PRICE * 2, dear_atr)
    )

    assert cheap.to_brain_input().content_hash() == dear.to_brain_input().content_hash()


@pytest.mark.parametrize("hash_seed", ["0", "12345"])
def test_content_hash_is_stable_across_processes(hash_seed: str) -> None:
    """Not Python's `hash()`, which is salted per interpreter run.

    A cache keyed on a salted hash misses on every restart -- silently, while
    appearing to work. Running under two different hash seeds proves the key is
    content-addressed rather than process-addressed.
    """
    expected = make_snapshot().to_brain_input().content_hash()
    env = dict(os.environ, PYTHONHASHSEED=hash_seed)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tests.factories import make_snapshot;"
            "print(make_snapshot().to_brain_input().content_hash())",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=PROJECT_ROOT,
        env=env,
    )
    assert result.stdout.strip() == expected


def test_canonical_json_is_key_order_independent() -> None:
    snapshot = make_snapshot()
    once = snapshot.to_brain_input().canonical_json()
    twice = snapshot.model_copy(deep=True).to_brain_input().canonical_json()
    assert once == twice


def test_normalised_floats_are_quantised() -> None:
    """Float noise in the last bits must not split one setup into two cache entries."""
    brain_input = make_snapshot(atr=420.000000001).to_brain_input()
    assert brain_input.atr_pct == round(brain_input.atr_pct, NORM_PRECISION)
    for level in brain_input.levels:
        distance = level["distance_atr"]
        assert isinstance(distance, float)
        assert distance == round(distance, NORM_PRECISION)


# --------------------------------------------------------------------------- #
# Anchors resolve, and only to levels that exist
# --------------------------------------------------------------------------- #


def test_anchor_resolves_to_a_price() -> None:
    snapshot = make_snapshot()
    resolved = snapshot.resolve("lvl_2", offset_atr=-0.3)
    level = snapshot.level_by_id("lvl_2")
    assert level is not None
    assert resolved == pytest.approx(level.price - 0.3 * snapshot.atr)


def test_unknown_anchor_resolves_to_nothing_rather_than_a_guess() -> None:
    assert make_snapshot().resolve("lvl_999") is None


def test_active_scenario_follows_bias_and_decision() -> None:
    assert make_verdict().active_scenario is not None
    assert make_verdict(decision=Decision.WAIT).active_scenario is None
    assert make_verdict(bias=Bias.NEUTRAL).active_scenario is None
    bearish = make_verdict(bias=Bias.BEARISH)
    assert bearish.active_scenario is not None
    assert bearish.active_scenario.side is Side.SHORT


# --------------------------------------------------------------------------- #
# A proposal cannot represent an incoherent trade
# --------------------------------------------------------------------------- #


def _proposal(**overrides: object) -> TradeProposal:
    defaults: dict[str, object] = {
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "entry": 42_000.0,
        "stop": 41_000.0,
        "target": 44_000.0,
        "qty": 0.1,
        "leverage": 5.0,
        "notional": 4_200.0,
        "margin": 840.0,
        "liquidation_price": 37_000.0,
        "risk_amount": 100.0,
        "risk_pct": 0.01,
        "equity_at_build": 10_000.0,
        "bias": Bias.BULLISH,
        "confidence": 74.0,
        "risk_level": "medium",
        "snapshot_hash": "deadbeef",
    }
    return TradeProposal.model_validate(defaults | overrides)


def test_a_coherent_long_is_accepted() -> None:
    proposal = _proposal()
    assert proposal.status is ProposalStatus.PENDING
    assert proposal.reward_risk == pytest.approx(2.0)
    assert proposal.liquidation_buffer_r == pytest.approx(4.0)


def test_inverted_long_is_rejected() -> None:
    with pytest.raises(ValidationError, match="stop < entry < target"):
        _proposal(stop=43_000.0)


def test_inverted_short_is_rejected() -> None:
    with pytest.raises(ValidationError, match="target < entry < stop"):
        _proposal(side=Side.SHORT, stop=41_000.0, target=44_000.0, liquidation_price=47_000.0)


def test_liquidation_inside_the_stop_is_rejected() -> None:
    """If the exchange closes the position before the plan says it is wrong, the
    stop is decoration. This is the invariant leverage exists to satisfy."""
    with pytest.raises(ValidationError, match="must sit below the stop"):
        _proposal(liquidation_price=41_500.0)


def test_short_liquidation_inside_the_stop_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must sit above the stop"):
        _proposal(
            side=Side.SHORT,
            entry=42_000.0,
            stop=43_000.0,
            target=40_000.0,
            liquidation_price=42_500.0,
        )


def test_risk_pct_is_hard_capped_by_the_type_itself() -> None:
    with pytest.raises(ValidationError):
        _proposal(risk_pct=0.25)


def test_proposal_expiry_is_time_based() -> None:
    proposal = _proposal()
    assert not proposal.is_expired(now_ms=proposal.created_ts)
    assert proposal.is_expired(now_ms=proposal.expires_ts)


# --------------------------------------------------------------------------- #
# Timeframes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("timeframe", "minutes", "bybit", "ccxt_tf"),
    [
        (Timeframe.M1, 1, "1", "1m"),
        (Timeframe.M15, 15, "15", "15m"),
        (Timeframe.H1, 60, "60", "1h"),
        (Timeframe.H4, 240, "240", "4h"),
        (Timeframe.D1, 1440, "D", "1d"),
        (Timeframe.W1, 10080, "W", "1w"),
    ],
)
def test_timeframe_mappings(timeframe: Timeframe, minutes: int, bybit: str, ccxt_tf: str) -> None:
    assert timeframe.minutes == minutes
    assert timeframe.bybit_interval == bybit
    assert timeframe.ccxt_timeframe == ccxt_tf


def test_execution_frame_is_not_analysed() -> None:
    """M1 exists to resolve intrabar ordering in the simulator, nothing else."""
    assert EXECUTION_FRAME not in CONTEXT_FRAMES
    assert SIGNAL_FRAME in CONTEXT_FRAMES


def test_side_arithmetic() -> None:
    assert Side.LONG.sign == 1
    assert Side.SHORT.sign == -1
    assert Side.LONG.opposite is Side.SHORT


@pytest.mark.parametrize(
    ("state", "terminal"),
    [
        (TradeState.PENDING_ENTRY, False),
        (TradeState.OPEN, False),
        (TradeState.CLOSED_STOP, True),
        (TradeState.CLOSED_TARGET, True),
        (TradeState.CLOSED_LIQUIDATED, True),
        (TradeState.EXPIRED_UNFILLED, True),
    ],
)
def test_trade_state_terminality(state: TradeState, terminal: bool) -> None:
    assert state.is_terminal is terminal
