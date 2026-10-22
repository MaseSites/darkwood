"""Das Seitenfeld des Chats ist in die Vorlage des Terminals eingebunden."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.factories import make_symbol_spec
from traidingbrain.api.app import Services, create_app
from traidingbrain.config.settings import load_config
from traidingbrain.proposals.builder import ProposalBuilder
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits

pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    config = load_config()
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
            equity=1_000.0,
            starting_equity_today=1_000.0,
            starting_equity_this_week=1_000.0,
            open_positions=[],
            recent_trades=[],
            now_ms=1_800_000_000_000,
        ),
    )
    return TestClient(create_app(services))


def test_vorlage_bindet_chat_ein(client: TestClient) -> None:
    html = client.get("/terminal").text

    assert 'id="chat"' in html
    assert "terminal-chat.js" in html
    assert "terminal-chat.css" in html
    assert "Bot fragen" in html


def test_chat_dateien_werden_ausgeliefert(client: TestClient) -> None:
    js = client.get("/static/terminal-chat.js")
    css = client.get("/static/terminal-chat.css")

    assert js.status_code == 200
    assert "/api/terminal/chat" in js.text and '"/nachricht"' in js.text
    assert "terminal:blick" in js.text
    assert css.status_code == 200 and "#chat" in css.text


def test_ausfuehren_zeigt_angepasste_margin(client: TestClient) -> None:
    """Ruling 18: weicht die aufgegebene Margin von der Karte ab, steht sie im Ergebnis."""
    js = client.get("/static/terminal-chat.js").text

    assert "Margin angepasst" in js
    assert "esc(money(r.margin_usd))" in js
