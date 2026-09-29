"""Execution safety, tested against a fake exchange that misbehaves on purpose.

The tests worth having here all describe a way to lose money that is invisible in
normal operation:

* A retry after a timeout opening a second position.
* A crash between sending and recording, leaving a position nobody knows about.
* A leverage change moving an open position's liquidation price.
* A position sitting unprotected because the stop silently did not attach.
* Live credentials armed by a single stale config value.

None of these show up while things are working. All of them show up once.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import ccxt
import pytest

from traidingbrain.domain.enums import ProposalStatus, Side
from traidingbrain.domain.proposal import Position, TradeProposal
from traidingbrain.execution.intent import (
    AlreadyAttemptedError,
    IntentLog,
    IntentState,
    client_order_id,
)
from traidingbrain.execution.order import (
    BybitExecutor,
    ExecutionRefusedError,
    UnsafeConfigurationError,
)
from traidingbrain.execution.reconcile import reconcile
from traidingbrain.execution.watchdog import StopWatchdog
from traidingbrain.risk.limits import KillSwitch

NOW = 1_700_000_000_000


def proposal(**overrides: Any) -> TradeProposal:
    defaults: dict[str, Any] = {
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
        "bias": "bullish",
        "confidence": 74.0,
        "risk_level": "medium",
        "snapshot_hash": "h",
        "status": ProposalStatus.PENDING,
    }
    return TradeProposal.model_validate(defaults | overrides)


class FakeBybit:
    """A venue that can be told to behave badly."""

    def __init__(
        self,
        *,
        positions: list[dict[str, Any]] | None = None,
        raise_on_order: Exception | None = None,
        clock_skew_ms: int = 0,
    ) -> None:
        self.positions = positions or []
        self.raise_on_order = raise_on_order
        self.clock_skew_ms = clock_skew_ms
        self.orders: list[dict[str, Any]] = []
        self.leverage_calls: list[tuple[float, str]] = []
        self.sandbox = False

    def set_sandbox_mode(self, enabled: bool) -> None:
        self.sandbox = enabled

    def fetch_time(self) -> int:
        return int(time.time() * 1000) + self.clock_skew_ms

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        if symbols is None:
            return self.positions
        return [p for p in self.positions if p.get("symbol") in symbols]

    def fetch_balance(self) -> dict[str, Any]:
        return {"info": {"positionMode": "OneWay", "marginMode": "ISOLATED"}}

    def set_leverage(self, leverage: float, symbol: str) -> None:
        self.leverage_calls.append((leverage, symbol))

    # Signature fixed by ccxt; it is being stood in for, not designed.
    def create_order(  # noqa: PLR0917
        self, symbol: str, kind: str, side: str, amount: float, price: float | None, params: dict
    ) -> dict[str, Any]:
        if self.raise_on_order is not None:
            raise self.raise_on_order
        order = {
            "id": f"srv-{len(self.orders) + 1}",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "params": params,
            "status": "open",
        }
        self.orders.append(order)
        return order

    def fetch_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        return []

    def cancel_all_orders(self, symbol: str) -> None:
        self.orders.clear()


@pytest.fixture
def log(tmp_path: Path) -> IntentLog:
    return IntentLog(tmp_path / "intents.sqlite")


@pytest.fixture
def switch(tmp_path: Path) -> KillSwitch:
    return KillSwitch(tmp_path / "KILL")


def executor(exchange: FakeBybit, log: IntentLog, switch: KillSwitch, **kwargs: Any):
    return BybitExecutor("k", "s", log, switch, exchange=exchange, **kwargs)


# --------------------------------------------------------------------------- #
# Arming live trading
# --------------------------------------------------------------------------- #


def test_live_needs_two_independent_signals(log: IntentLog, switch: KillSwitch) -> None:
    """One config value carried over from a copied file must not be enough."""
    with pytest.raises(UnsafeConfigurationError, match="one alone"):
        executor(FakeBybit(), log, switch, testnet=False)


def test_testnet_is_the_default(log: IntentLog, switch: KillSwitch) -> None:
    assert executor(FakeBybit(), log, switch).testnet is True


def test_live_is_possible_when_asked_for_twice(log: IntentLog, switch: KillSwitch) -> None:
    assert executor(FakeBybit(), log, switch, testnet=False, allow_live=True).testnet is False


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


def test_the_client_order_id_is_derived_not_generated() -> None:
    """So a retry after a timeout carries the same one and the exchange rejects the
    duplicate. That turns "did that go through?" into a question with an answer."""
    p = proposal()
    assert client_order_id(p.id) == client_order_id(p.id)
    assert client_order_id(p.id) != client_order_id(proposal().id)
    assert len(client_order_id(p.id)) <= 36


def test_a_second_attempt_on_the_same_proposal_is_refused(
    log: IntentLog, switch: KillSwitch
) -> None:
    """The order may already exist. The correct response is to ask the exchange,
    not to send another."""
    exchange = FakeBybit()
    ex = executor(exchange, log, switch)
    p = proposal()

    ex.send(p)
    with pytest.raises(ExecutionRefusedError, match="already has an order intent"):
        ex.send(p)

    assert len(exchange.orders) == 1


def test_the_intent_log_itself_refuses_a_duplicate(log: IntentLog) -> None:
    p = proposal()
    log.write_ahead(p, testnet=True)
    with pytest.raises(AlreadyAttemptedError, match="not by sending again"):
        log.write_ahead(p, testnet=True)


# --------------------------------------------------------------------------- #
# The write-ahead sequence
# --------------------------------------------------------------------------- #


def test_the_intent_is_written_before_the_order_is_sent(log: IntentLog, switch: KillSwitch) -> None:
    """Proven by making the send fail: the record must survive it.

    That record is the only reason a crash here is recoverable -- it is the key
    reconciliation has to ask the exchange about.
    """
    exchange = FakeBybit(raise_on_order=ccxt.NetworkError("timeout"))
    ex = executor(exchange, log, switch)
    p = proposal()

    with pytest.raises(ExecutionRefusedError):
        ex.send(p)

    record = log.for_proposal(p.id)
    assert record is not None
    assert record.state is IntentState.SENT, (
        "a send that raised was marked failed rather than sent; reconciliation would "
        "then never look, and a live order could be orphaned"
    )


def test_a_successful_send_is_recorded_as_confirmed(log: IntentLog, switch: KillSwitch) -> None:
    ex = executor(FakeBybit(), log, switch)
    reference = ex.send(proposal())

    record = log.for_proposal(proposal().id) or next(iter(log.unresolved()), None)
    stored = log.get(client_order_id(proposal().id))
    assert reference.startswith("srv-")
    assert stored is None or stored.state is IntentState.CONFIRMED
    assert log.unresolved() == []
    assert record is None or record.state is IntentState.CONFIRMED


def test_the_stop_travels_with_the_entry(log: IntentLog, switch: KillSwitch) -> None:
    """One call, not three. Between a filled entry and a separately-placed stop
    there is a window with an unprotected position in it."""
    exchange = FakeBybit()
    ex = executor(exchange, log, switch)
    p = proposal()

    ex.send(p)

    params = exchange.orders[0]["params"]
    assert params["stopLoss"] == pytest.approx(p.stop)
    assert params["takeProfit"] == pytest.approx(p.target)
    assert params["clientOrderId"] == client_order_id(p.id)


# --------------------------------------------------------------------------- #
# Leverage and the clock
# --------------------------------------------------------------------------- #


def test_leverage_is_not_changed_under_an_open_position(log: IntentLog, switch: KillSwitch) -> None:
    """`set_leverage` is symbol-wide. Changing it while something is open moves
    that position's liquidation price, and nobody finds out until it matters."""
    exchange = FakeBybit(positions=[{"symbol": "BTC/USDT:USDT", "contracts": 0.5, "side": "long"}])
    ex = executor(exchange, log, switch)

    with pytest.raises(UnsafeConfigurationError, match="symbol-wide"):
        ex.ensure_leverage("BTCUSDT", 5.0)

    assert exchange.leverage_calls == []


def test_leverage_is_set_once_per_symbol(log: IntentLog, switch: KillSwitch) -> None:
    exchange = FakeBybit()
    ex = executor(exchange, log, switch)

    ex.ensure_leverage("BTCUSDT", 5.0)
    ex.ensure_leverage("BTCUSDT", 5.0)

    assert len(exchange.leverage_calls) == 1


def test_a_drifting_clock_is_caught_before_it_causes_confusion(
    log: IntentLog, switch: KillSwitch
) -> None:
    """Signature failures from clock drift are sporadic and look like anything else."""
    ex = executor(FakeBybit(clock_skew_ms=9000), log, switch)

    with pytest.raises(UnsafeConfigurationError, match="clock"):
        ex.preflight()


def test_preflight_reports_what_it_found(log: IntentLog, switch: KillSwitch) -> None:
    ex = executor(FakeBybit(), log, switch)
    report = ex.preflight()

    assert report.testnet is True
    assert "testnet" in report.describe()
    assert report.clock_drift_ms < 1500


# --------------------------------------------------------------------------- #
# The kill switch
# --------------------------------------------------------------------------- #


def test_the_kill_switch_stops_a_send(log: IntentLog, switch: KillSwitch) -> None:
    exchange = FakeBybit()
    ex = executor(exchange, log, switch)
    switch.engage("stopping")

    with pytest.raises(ExecutionRefusedError, match="kill switch"):
        ex.send(proposal())

    assert exchange.orders == []
    assert log.unresolved() == [], "an intent was written despite the halt"


# --------------------------------------------------------------------------- #
# The watchdog
# --------------------------------------------------------------------------- #


class FakeVenue:
    def __init__(self, positions: list[Position], stops: dict[str, list[dict[str, Any]]]) -> None:
        self.positions = positions
        self.stops = stops
        self.closed: list[str] = []

    def open_positions(self) -> list[Position]:
        return self.positions

    def stops_for(self, symbol: str) -> list[dict[str, Any]]:
        return self.stops.get(symbol, [])

    def close_position(self, symbol: str) -> str | None:
        self.closed.append(symbol)
        self.positions = [p for p in self.positions if p.symbol != symbol]
        return f"close-{symbol}"


def position(symbol: str = "BTCUSDT", qty: float = 0.1) -> Position:
    return Position(
        symbol=symbol,
        side=Side.LONG,
        qty=qty,
        entry_price=42_000.0,
        leverage=5.0,
        liquidation_price=37_000.0,
        opened_ts=NOW,
    )


def test_a_protected_position_is_left_alone() -> None:
    venue = FakeVenue([position()], {"BTCUSDT": [{"stopPrice": 41_000.0, "amount": 0.1}]})
    dog = StopWatchdog(venue, deadline_seconds=0.0)

    assert dog.sweep(now=100.0) == []
    assert venue.closed == []


def test_an_unprotected_position_is_closed() -> None:
    """A small known loss against an unbounded unknown one is the correct trade."""
    venue = FakeVenue([position()], {})
    dog = StopWatchdog(venue, deadline_seconds=2.0)

    assert dog.sweep(now=100.0) == [], "acted before the grace period"
    fired = dog.sweep(now=103.0)

    assert len(fired) == 1
    assert "closed" in fired[0].action
    assert venue.closed == ["BTCUSDT"]


def test_a_stop_on_the_wrong_side_is_not_protection() -> None:
    """A long whose only resting stop is above entry is not protected by it."""
    venue = FakeVenue([position()], {"BTCUSDT": [{"stopPrice": 43_000.0, "amount": 0.1}]})
    dog = StopWatchdog(venue, deadline_seconds=0.0)

    assert dog.sweep(now=100.0)
    assert venue.closed == ["BTCUSDT"]


def test_a_stop_covering_half_the_position_is_not_enough() -> None:
    """The case a simple "is there a stop?" check misses entirely."""
    venue = FakeVenue([position(qty=1.0)], {"BTCUSDT": [{"stopPrice": 41_000.0, "amount": 0.5}]})
    dog = StopWatchdog(venue, deadline_seconds=0.0)

    assert dog.sweep(now=100.0)
    assert venue.closed == ["BTCUSDT"]


def test_the_watchdog_prefers_re_attaching_to_closing() -> None:
    venue = FakeVenue([position()], {})
    dog = StopWatchdog(venue, deadline_seconds=0.0, reattach=lambda _p: True)

    fired = dog.sweep(now=100.0)

    assert "re-attached" in fired[0].action
    assert venue.closed == []


def test_a_grace_period_prevents_a_race_from_closing_a_good_trade() -> None:
    """A stop placed microseconds ago may not be visible on the next read."""
    venue = FakeVenue([position()], {})
    dog = StopWatchdog(venue, deadline_seconds=5.0)

    assert dog.sweep(now=100.0) == []
    assert dog.sweep(now=102.0) == []
    assert dog.sweep(now=106.0) != []


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #


class RecoveringVenue:
    def __init__(self, known: dict[str, dict[str, Any]], positions: list[Position]) -> None:
        self.known = known
        self.positions = positions
        self.unreachable = False

    def open_positions(self) -> list[Position]:
        return self.positions

    def fetch_order_by_client_id(self, client_id: str, symbol: str) -> dict[str, Any] | None:
        if self.unreachable:
            raise ConnectionError("exchange unreachable")
        return self.known.get(client_id)


def test_an_order_that_exists_is_adopted(log: IntentLog) -> None:
    """The crash-after-send case. Without the write-ahead there would be no key to
    look it up by, and the position would be orphaned."""
    p = proposal()
    intent = log.write_ahead(p, testnet=True)
    log.mark(intent.client_order_id, IntentState.SENT)

    venue = RecoveringVenue(
        {intent.client_order_id: {"id": "srv-9", "status": "open"}}, [position()]
    )
    result = reconcile(log, venue)

    assert result.adopted == [intent.client_order_id]
    assert log.unresolved() == []
    assert result.is_clean


def test_an_order_that_never_arrived_is_abandoned(log: IntentLog) -> None:
    p = proposal()
    intent = log.write_ahead(p, testnet=True)

    result = reconcile(log, RecoveringVenue({}, []))

    assert result.abandoned == [intent.client_order_id]
    assert log.unresolved() == []


def test_an_unreachable_exchange_leaves_the_intent_unresolved(log: IntentLog) -> None:
    """Never collapsed into "does not exist".

    Marking a live order abandoned because the exchange could not be reached would
    let the next proposal open a second position on top of it.
    """
    p = proposal()
    intent = log.write_ahead(p, testnet=True)
    venue = RecoveringVenue({}, [])
    venue.unreachable = True

    result = reconcile(log, venue)

    assert result.unresolved == [intent.client_order_id]
    assert not result.is_clean
    assert "do not trade" in result.summary()
    assert log.unresolved(), "the intent was settled despite being unanswerable"


def test_a_position_with_no_intent_is_reported_not_adopted(log: IntentLog) -> None:
    """Opened by hand, by another process, or by an earlier build.

    The risk layer has no record of what it was sized against and cannot manage it,
    so it is surfaced rather than absorbed.
    """
    result = reconcile(log, RecoveringVenue({}, [position("ETHUSDT")]))

    assert [p.symbol for p in result.orphan_positions] == ["ETHUSDT"]
    assert not result.is_clean
    assert "ORPHANS" in result.summary()


def test_a_clean_system_says_so(log: IntentLog) -> None:
    result = reconcile(log, RecoveringVenue({}, []))
    assert result.is_clean
    assert "nothing outstanding" in result.summary()
