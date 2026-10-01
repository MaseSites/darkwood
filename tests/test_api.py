"""The HTTP surface, and the three-step confirmation it enforces.

The interesting tests here are the refusals. A dashboard that happily confirms a
proposal priced twenty minutes ago, or lets a stale token through after the user
adjusted the leverage, would look completely normal in use and would occasionally
send a trade nobody agreed to.

Also checked: with no executor wired, no path through this service can place an
order. That is the guarantee that makes it safe to point this at a real account's
data while the interface is still being shaped.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.factories import make_snapshot, make_symbol_spec
from traidingbrain.api.app import Services, _cost_floor, create_app
from traidingbrain.api.market import build_market_view
from traidingbrain.brain.fake import FakeBrain
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.proposal import TradeProposal
from traidingbrain.proposals.builder import BuildFailure, ProposalBuilder
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits

#: The app runs in-process; nothing here reaches the network. asyncio still needs
#: a loopback socket pair for its event loop, so loopback is permitted and
#: everything else stays blocked.
pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])

NOW = 1_700_000_000_000


class FixedPrice:
    def __init__(self, price: float | None) -> None:
        self.price = price

    def last_price(self, symbol: str) -> float | None:
        return self.price


class RecordingExecutor:
    """Stands in for the exchange, and records rather than sends."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[TradeProposal] = []
        self.fail = fail

    def send(self, proposal: TradeProposal) -> str:
        if self.fail:
            raise RuntimeError("insufficient margin")
        self.sent.append(proposal)
        return f"order-{proposal.id[:8]}"


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


@pytest.fixture
def services(tmp_path: Path, config: AppConfig) -> Services:
    kill_switch = KillSwitch(tmp_path / "KILL")
    limits = RiskLimits(config.risk.limits, kill_switch)
    return Services(
        config=config,
        store=ProposalStore(tmp_path / "proposals.sqlite"),
        builder=ProposalBuilder(config, limits),
        limits=limits,
        kill_switch=kill_switch,
        specs={"BTCUSDT": make_symbol_spec()},
        account=AccountState(
            equity=10_000.0,
            starting_equity_today=10_000.0,
            starting_equity_this_week=10_000.0,
            open_positions=[],
            recent_trades=[],
            now_ms=NOW,
        ),
    )


@pytest.fixture
def client(services: Services) -> TestClient:
    return TestClient(create_app(services))


def seed(services: Services) -> TradeProposal:
    decision = FakeBrain(services.config).decide(make_snapshot())
    built = services.builder.build(
        decision, make_snapshot(), make_symbol_spec(), services.account_state()
    )
    if isinstance(built, BuildFailure):
        pytest.skip(f"the fake brain declined here: {built}")
    services.store.put(built)
    services.prices = FixedPrice(built.entry)
    return built


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def test_state_reports_that_nothing_can_trade(client: TestClient) -> None:
    """The default this stage ships with, stated explicitly rather than implied."""
    state = client.get("/api/state").json()

    assert state["execution_connected"] is False
    assert state["testnet"] is True
    assert state["kill_switch_engaged"] is False


def test_pending_proposals_come_back_fully_computed(client: TestClient, services: Services) -> None:
    """Every number pre-computed. An interface doing its own arithmetic is a second
    version of the number, and one of the two is wrong."""
    proposal = seed(services)

    view = client.get("/api/proposals").json()[0]

    assert view["id"] == proposal.id
    assert view["reward_risk"] == pytest.approx(proposal.reward_risk)
    assert view["liquidation_buffer_r"] == pytest.approx(proposal.liquidation_buffer_r)
    assert view["stop_distance_pct"] > 0
    assert view["reasoning"]


def test_an_unknown_proposal_is_a_404(client: TestClient) -> None:
    assert client.get("/api/proposals/nope").status_code == 404


# --------------------------------------------------------------------------- #
# Adjusting
# --------------------------------------------------------------------------- #


def test_lowering_leverage_returns_a_repriced_proposal(
    client: TestClient, services: Services
) -> None:
    """The change the user asked for by name: 5x to 4x."""
    proposal = seed(services)
    if proposal.leverage < 2:
        pytest.skip("no headroom to lower leverage here")

    response = client.post(
        f"/api/proposals/{proposal.id}/adjust", json={"leverage": proposal.leverage - 1}
    )

    assert response.status_code == 200
    adjusted = response.json()
    assert adjusted["leverage"] == proposal.leverage - 1
    assert adjusted["liquidation_buffer_r"] > proposal.liquidation_buffer_r
    assert adjusted["qty"] == pytest.approx(proposal.qty), (
        "leverage changed the position size, which it must not"
    )


def test_raising_leverage_is_refused_with_a_reason(client: TestClient, services: Services) -> None:
    proposal = seed(services)

    response = client.post(
        f"/api/proposals/{proposal.id}/adjust", json={"leverage": proposal.leverage + 10}
    )

    assert response.status_code == 422
    assert "lowering is always fine" in response.json()["detail"]


def test_adjusting_invalidates_a_token_issued_before(
    client: TestClient, services: Services
) -> None:
    """Otherwise it would be possible to look at one trade, change it, and confirm
    the version shown first."""
    proposal = seed(services)
    if proposal.leverage < 2:
        pytest.skip("no headroom to lower leverage here")

    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]
    client.post(f"/api/proposals/{proposal.id}/adjust", json={"leverage": proposal.leverage - 1})

    response = client.post(f"/api/proposals/{proposal.id}/confirm", json={"token": token})

    assert response.status_code == 409
    assert "changed" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# Confirming
# --------------------------------------------------------------------------- #


def test_a_drifted_price_refuses_to_issue_a_token(client: TestClient, services: Services) -> None:
    """A proposal built minutes ago was priced against a market that has moved.

    Sending it anyway is executing a trade nobody agreed to.
    """
    proposal = seed(services)
    tolerance = services.config.risk.execution.max_price_drift_bps
    services.prices = FixedPrice(proposal.entry * (1 + tolerance * 2e-4))

    response = client.post(f"/api/proposals/{proposal.id}/token")

    assert response.status_code == 409
    assert "moved" in response.json()["detail"]


def test_a_small_drift_is_tolerated(client: TestClient, services: Services) -> None:
    proposal = seed(services)
    services.prices = FixedPrice(proposal.entry * 1.00001)

    response = client.post(f"/api/proposals/{proposal.id}/token")

    assert response.status_code == 200
    assert response.json()["token"]


def test_confirming_without_an_executor_sends_nothing(
    client: TestClient, services: Services
) -> None:
    """The guarantee that makes this safe to point at a real account right now."""
    proposal = seed(services)
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    result = client.post(f"/api/proposals/{proposal.id}/confirm", json={"token": token}).json()

    assert result["sent"] is False
    assert "not connected" in result["reason"]
    assert "entry" in result["would_have_sent"]


def test_confirming_with_an_executor_sends_once(client: TestClient, services: Services) -> None:
    proposal = seed(services)
    executor = RecordingExecutor()
    services.executor = executor
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    result = client.post(f"/api/proposals/{proposal.id}/confirm", json={"token": token}).json()

    assert result["sent"] is True
    assert len(executor.sent) == 1
    assert executor.sent[0].id == proposal.id


def test_a_token_cannot_be_spent_twice(client: TestClient, services: Services) -> None:
    proposal = seed(services)
    services.executor = RecordingExecutor()
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    first = client.post(f"/api/proposals/{proposal.id}/confirm", json={"token": token})
    second = client.post(f"/api/proposals/{proposal.id}/confirm", json={"token": token})

    assert first.status_code == 200
    assert second.status_code == 409
    assert len(services.executor.sent) == 1  # type: ignore[union-attr]


def test_a_failed_send_is_reported_rather_than_swallowed(
    client: TestClient, services: Services
) -> None:
    proposal = seed(services)
    services.executor = RecordingExecutor(fail=True)
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    response = client.post(f"/api/proposals/{proposal.id}/confirm", json={"token": token})

    assert response.status_code == 502
    assert "insufficient margin" in response.json()["detail"]
    assert services.store.get(proposal.id).status.value == "failed"  # type: ignore[union-attr]


def test_a_rejected_proposal_disappears_from_the_list(
    client: TestClient, services: Services
) -> None:
    proposal = seed(services)

    assert client.post(f"/api/proposals/{proposal.id}/reject").json()["rejected"] is True
    assert client.get("/api/proposals").json() == []


# --------------------------------------------------------------------------- #
# The kill switch
# --------------------------------------------------------------------------- #


def test_the_kill_switch_blocks_confirmation(client: TestClient, services: Services) -> None:
    proposal = seed(services)
    services.executor = RecordingExecutor()
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    client.post("/api/kill", json={"reason": "stepping away"})
    response = client.post(f"/api/proposals/{proposal.id}/confirm", json={"token": token})

    assert response.status_code == 423
    assert "stepping away" in response.json()["detail"]
    assert services.executor.sent == []  # type: ignore[union-attr]


def test_the_kill_switch_shows_up_in_state(client: TestClient) -> None:
    client.post("/api/kill", json={"reason": "maintenance"})

    state = client.get("/api/state").json()

    assert state["kill_switch_engaged"] is True
    assert state["kill_switch_reason"] == "maintenance"
    assert state["limits_allow_trading"] is False


def test_the_kill_switch_releases_only_when_asked(client: TestClient) -> None:
    client.post("/api/kill", json={"reason": "x"})
    assert client.get("/api/state").json()["kill_switch_engaged"] is True

    client.delete("/api/kill")
    assert client.get("/api/state").json()["kill_switch_engaged"] is False


# --------------------------------------------------------------------------- #
# The market view without an exchange, which is the ordinary state
# --------------------------------------------------------------------------- #


def test_the_market_view_survives_having_no_instrument_rules(
    services: Services, config: AppConfig
) -> None:
    """The bug this pins took the whole chart down with a 404.

    The market panel annotates each setup with whether its stop is wide enough
    to be affordable, which needs the venue's fees. Asking for them strictly
    meant that with no exchange connected -- the ordinary state of this build --
    every chart request returned "no instrument rules loaded" and the screen
    showed two empty boxes.

    An optional annotation must never be able to fail the page it decorates.
    """
    services.specs = {}

    assert services.optional_spec("BTCUSDT") is None
    with pytest.raises(HTTPException):
        services.spec_for("BTCUSDT")


def test_the_cost_floor_is_zero_rather_than_guessed_when_fees_are_unknown(
    services: Services,
) -> None:
    """Zero means unknown, and the panel then shows no affordability note.

    Substituting typical fees would put a number on the screen that looks
    measured and is not -- and this particular number decides whether a setup
    is shown as untradeable.
    """
    services.specs = {}

    assert _cost_floor(services, "BTCUSDT") == 0.0
    services.specs = {"BTCUSDT": make_symbol_spec()}
    assert _cost_floor(services, "BTCUSDT") > 0.0


# --------------------------------------------------------------------------- #
# Saying how old the data is
# --------------------------------------------------------------------------- #


def _market_frame(last_ts: int, bars: int = 60) -> pd.DataFrame:
    hour = 3_600_000
    ts = last_ts - np.arange(bars, dtype="int64")[::-1] * hour
    close = np.full(bars, 100.0)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": np.full(bars, 10.0),
        }
    )


def test_a_current_market_does_not_warn() -> None:
    """A badge that is always lit is furniture. The newest bar is always a
    little behind by construction, so one bar's lag must stay silent."""
    hour = 3_600_000
    just_closed = (int(time.time() * 1000) // hour) * hour - hour

    view = build_market_view(
        make_snapshot(ts=just_closed),
        _market_frame(just_closed),
        timeframe=Timeframe.H1,
        available=[Timeframe.H1],
    )

    assert not view.stale
    assert view.behind_ms < 2 * hour


def test_a_screen_showing_history_says_so() -> None:
    """The defect this exists for.

    The collector runs on a machine that is sometimes off, the dashboard reads
    what is on disk, and a frozen screen looked exactly like a working one. For
    an hour the only way to discover that nothing had arrived since the day
    before was to ask. A number that does not move is either a quiet market or
    a broken pipe, and the screen owes an answer to which.
    """
    hour = 3_600_000
    yesterday = int(time.time() * 1000) - 20 * hour

    view = build_market_view(
        make_snapshot(ts=yesterday),
        _market_frame(yesterday),
        timeframe=Timeframe.H1,
        available=[Timeframe.H1],
    )

    assert view.stale
    assert view.behind_ms >= 19 * hour


def test_the_age_is_measured_from_the_close_not_the_open() -> None:
    """Bars are stamped with their open. Measuring from there would report a
    bar that has only just finished as an hour out of date, and the warning
    would fire on every working system."""
    hour = 3_600_000
    opened_an_hour_ago = int(time.time() * 1000) - hour

    view = build_market_view(
        make_snapshot(ts=opened_an_hour_ago),
        _market_frame(opened_an_hour_ago),
        timeframe=Timeframe.H1,
        available=[Timeframe.H1],
    )

    assert view.behind_ms < hour // 2
