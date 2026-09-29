"""The system's central claim, tested across every layer at once.

Each layer already has its own tests. This file exists because the claim is not a
property of any one of them -- it is a property of how they fit together, and that
is exactly the kind of thing that survives a refactor of each part individually
and then quietly stops being true.

The claim: **no order reaches an exchange without a human having held the confirm
button on the exact trade that gets sent.**

Every test here tries to break it from a different direction, and each attack is
one somebody would actually make by accident: skipping the token, reusing one,
adjusting the trade after confirming, confirming twice at once, confirming while
halted, or confirming something the analysis never proposed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.factories import make_snapshot, make_symbol_spec
from traidingbrain.api.app import Services, create_app
from traidingbrain.brain.fake import FakeBrain
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.proposal import TradeProposal
from traidingbrain.execution.intent import AlreadyAttemptedError, IntentLog
from traidingbrain.proposals.builder import BuildFailure, ProposalBuilder
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits

pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])

NOW = 1_700_000_000_000


class CountingExchange:
    """Stands where Bybit would, and counts.

    The only assertion that matters in most of this file is `len(sent) == 0`.
    """

    def __init__(self) -> None:
        self.sent: list[TradeProposal] = []

    def send(self, proposal: TradeProposal) -> str:
        self.sent.append(proposal)
        return f"order-{len(self.sent)}"


class FixedPrice:
    def __init__(self, price: float) -> None:
        self.price = price

    def last_price(self, symbol: str) -> float | None:
        return self.price


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


@pytest.fixture
def system(tmp_path: Path, config: AppConfig):
    """The whole stack, wired as it is in production but with a counted exchange."""
    kill_switch = KillSwitch(tmp_path / "KILL")
    limits = RiskLimits(config.risk.limits, kill_switch)
    exchange = CountingExchange()

    services = Services(
        config=config,
        store=ProposalStore(tmp_path / "proposals.sqlite"),
        builder=ProposalBuilder(config, limits),
        limits=limits,
        kill_switch=kill_switch,
        specs={"BTCUSDT": make_symbol_spec()},
        executor=exchange,
        account=AccountState(
            equity=10_000.0,
            starting_equity_today=10_000.0,
            starting_equity_this_week=10_000.0,
            open_positions=[],
            recent_trades=[],
            now_ms=NOW,
        ),
    )

    # The analysis really runs: a hand-written proposal would not prove the chain.
    decision = FakeBrain(config).decide(make_snapshot())
    built = services.builder.build(
        decision, make_snapshot(), make_symbol_spec(), services.account_state()
    )
    if isinstance(built, BuildFailure):
        pytest.skip(f"the analysis declined this fixture: {built}")

    services.store.put(built)
    services.prices = FixedPrice(built.entry)
    intents = IntentLog(tmp_path / "intents.sqlite")

    return TestClient(create_app(services)), services, exchange, built, intents


def confirm(client: TestClient, proposal_id: str, token: str) -> Any:
    return client.post(f"/api/proposals/{proposal_id}/confirm", json={"token": token})


# --------------------------------------------------------------------------- #
# The happy path, so the rest means something
# --------------------------------------------------------------------------- #


def test_a_properly_confirmed_trade_does_reach_the_exchange(system) -> None:
    """Without this, every other test in the file could pass by nothing working."""
    client, _services, exchange, proposal, _intents = system

    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]
    response = confirm(client, proposal.id, token)

    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert len(exchange.sent) == 1
    assert exchange.sent[0].id == proposal.id


def test_what_is_sent_is_exactly_what_was_shown(system) -> None:
    """The numbers on the screen and the numbers in the order are the same object."""
    client, _services, exchange, proposal, _intents = system
    shown = client.get(f"/api/proposals/{proposal.id}").json()

    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]
    confirm(client, proposal.id, token)

    sent = exchange.sent[0]
    assert sent.entry == pytest.approx(shown["entry"])
    assert sent.stop == pytest.approx(shown["stop"])
    assert sent.target == pytest.approx(shown["target"])
    assert sent.qty == pytest.approx(shown["qty"])
    assert sent.leverage == pytest.approx(shown["leverage"])


# --------------------------------------------------------------------------- #
# Six ways to try to get around it
# --------------------------------------------------------------------------- #


def test_confirming_without_a_token_sends_nothing(system) -> None:
    client, _services, exchange, proposal, _intents = system

    assert confirm(client, proposal.id, "").status_code == 409
    assert confirm(client, proposal.id, "made-up").status_code == 409
    assert exchange.sent == []


def test_a_token_cannot_be_reused(system) -> None:
    """A double-click, a retried request, two open tabs."""
    client, _services, exchange, proposal, _intents = system
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    confirm(client, proposal.id, token)
    second = confirm(client, proposal.id, token)

    assert second.status_code == 409
    assert len(exchange.sent) == 1


def test_adjusting_after_getting_a_token_invalidates_it(system) -> None:
    """The attack that matters most: look at one trade, change it, confirm the first."""
    client, _services, exchange, proposal, _intents = system
    if proposal.leverage < 2:
        pytest.skip("no headroom to lower leverage in this fixture")

    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]
    client.post(f"/api/proposals/{proposal.id}/adjust", json={"leverage": proposal.leverage - 1})

    response = confirm(client, proposal.id, token)

    assert response.status_code == 409
    assert exchange.sent == []


def test_a_hundred_simultaneous_confirmations_send_one_order(system) -> None:
    """Every layer together: token, compare-and-swap, executor."""
    client, _services, exchange, proposal, _intents = system
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: confirm(client, proposal.id, token), range(100)))

    assert len(exchange.sent) == 1, f"{len(exchange.sent)} orders left the building"


def test_the_kill_switch_beats_a_valid_token(system) -> None:
    """Held correctly, confirmed correctly, and still refused."""
    client, services, exchange, proposal, _intents = system
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    services.kill_switch.engage("stepping away from the desk")
    response = confirm(client, proposal.id, token)

    assert response.status_code == 423
    assert exchange.sent == []


def test_a_declined_proposal_cannot_be_confirmed_afterwards(system) -> None:
    client, _services, exchange, proposal, _intents = system
    token = client.post(f"/api/proposals/{proposal.id}/token").json()["token"]

    client.post(f"/api/proposals/{proposal.id}/reject")
    response = confirm(client, proposal.id, token)

    assert response.status_code == 409
    assert exchange.sent == []


def test_a_stale_price_refuses_before_a_token_is_even_issued(system) -> None:
    """The refusal lands at the point where it matters, not after.

    A proposal priced twenty minutes ago is a proposal priced against a market that
    has moved, and sending it is executing a trade nobody agreed to.
    """
    client, services, exchange, proposal, _intents = system
    tolerance = services.config.risk.execution.max_price_drift_bps
    services.prices = FixedPrice(proposal.entry * (1 + tolerance * 3e-4))

    response = client.post(f"/api/proposals/{proposal.id}/token")

    assert response.status_code == 409
    assert exchange.sent == []


# --------------------------------------------------------------------------- #
# And the layer below
# --------------------------------------------------------------------------- #


def test_nothing_is_sent_when_no_executor_is_wired(tmp_path: Path, config: AppConfig) -> None:
    """The default this build ships with, asserted rather than assumed.

    It is what makes it safe to point the dashboard at real account data while the
    interface is still being shaped.
    """
    kill_switch = KillSwitch(tmp_path / "KILL")
    limits = RiskLimits(config.risk.limits, kill_switch)
    services = Services(
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
    decision = FakeBrain(config).decide(make_snapshot())
    built = services.builder.build(
        decision, make_snapshot(), make_symbol_spec(), services.account_state()
    )
    if isinstance(built, BuildFailure):
        pytest.skip(str(built))
    services.store.put(built)
    services.prices = FixedPrice(built.entry)

    client = TestClient(create_app(services))
    token = client.post(f"/api/proposals/{built.id}/token").json()["token"]
    result = confirm(client, built.id, token).json()

    assert result["sent"] is False
    assert services.executor is None


def test_the_intent_log_refuses_a_second_attempt_at_the_same_proposal(system) -> None:
    """One layer deeper than the API: even a direct call cannot send twice.

    Whatever happened to the first attempt, the correct response is to ask the
    exchange, not to send again.
    """
    _client, _services, _exchange, proposal, intents = system

    intents.write_ahead(proposal, testnet=True)
    with pytest.raises(AlreadyAttemptedError):
        intents.write_ahead(proposal, testnet=True)
