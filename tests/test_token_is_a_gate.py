"""Tokenausstellung und Anpassung müssen durch denselben Guard laufen.

**Der Istzustand, belegt in `audit/P0A_LEGACY_FREEZE.md` und
`tests/test_confirm_path_is_a_gate.py`:**

    builder.build()     prueft limits.check   -- builder.py:260
    builder.adjust()    prueft NICHT
    POST /token         prueft nur Preisdrift -- app.py:389
    POST /confirm       prueft Kill-Switch, Token, CAS -- app.py:405
    app.py:315          limits.check nur fuer die ANZEIGE

Das Abnahmekriterium von Stufe 7 des Bauplans lautet: *„Änderung 5x→4x
rechnet Grösse, Risiko und Liquidation sofort neu **und läuft erneut durch den
Guard**."* Es war nicht erfüllt.

**Und der Zustand, gegen den geprüft würde, war eingefroren.**
`run_dashboard.py:238` baute `AccountState.from_history(...)` einmal beim
Start, ohne `open_positions`. Die beiden Positionsprüfungen rechneten damit
`0 >= 5` und `0 >= 1` und konnten nicht auslösen — derselbe Defekt, den
`live/book.py` für den Papierhändler schon behoben hat.

Diese Tests nageln beide Tore fest: die Ausstellung des Tokens ist der Moment,
in dem das Senden autorisiert wird, also gehört der vollständige Guard dorthin
— mit einem Kontozustand, der **zur Prüfzeit** entsteht.
"""

from __future__ import annotations

import functools
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from traidingbrain.api.app import Services, create_app
from traidingbrain.config.settings import load_config
from traidingbrain.domain.enums import ProposalStatus, Side, Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.domain.proposal import Position, TradeProposal
from traidingbrain.proposals.builder import (
    BuildFailure,
    ProposalAdjustment,
    ProposalBuilder,
)
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits

#: Der In-Process-TestClient braucht Loopback; `pytest-socket` sperrt
#: Sockets sonst. Dieselbe Zeile steht in tests/test_api.py:38.
pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])

SYMBOL = "BTCUSDT"
NOW = 1_700_000_000_000
SPEC = SymbolSpec(symbol=SYMBOL, **DEFAULT_SPEC)


class _Prices:
    """Eine Preisquelle, die genau den Vorschlagspreis nennt -- keine Drift."""

    def __init__(self, price: float) -> None:
        self.price = price

    def last_price(self, symbol: str) -> float:
        return self.price


def _position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        side=Side.LONG,
        qty=0.01,
        entry_price=50_000.0,
        leverage=5.0,
        liquidation_price=40_000.0,
        opened_ts=NOW - 3_600_000,
    )


def _konto(positions: list[Position] | None = None) -> AccountState:
    return AccountState(
        equity=1_000.0,
        starting_equity_today=1_000.0,
        starting_equity_this_week=1_000.0,
        open_positions=positions or [],
        recent_trades=[],
        now_ms=NOW,
    )


@pytest.fixture
def services(tmp_path: Path) -> Services:
    config = load_config()
    limits = RiskLimits(config.risk.limits)
    s = Services(
        config=config,
        store=ProposalStore(tmp_path / "proposals.sqlite"),
        builder=ProposalBuilder(config, limits),
        limits=limits,
        kill_switch=KillSwitch(tmp_path / "KILL"),
    )
    s.specs[SYMBOL] = SPEC
    return s


def _vorschlag(services: Services) -> TradeProposal:
    """Ein gespeicherter Vorschlag, in der Form, die der Store erwartet.

    Felder und Schreibweise aus `tests/test_chart.py:37` uebernommen, damit
    dieser Test nicht eine eigene Vorstellung von `TradeProposal` pflegt.
    """
    proposal = TradeProposal(
        symbol=SYMBOL,
        side=Side.LONG,
        entry=50_000.0,
        stop=49_000.0,
        target=52_000.0,
        qty=0.01,
        leverage=5.0,
        notional=500.0,
        margin=100.0,
        liquidation_price=40_000.0,
        risk_amount=10.0,
        risk_pct=0.01,
        equity_at_build=1_000.0,
        bias="bullish",
        confidence=75.0,
        risk_level="medium",
        snapshot_hash="x" * 64,
        status=ProposalStatus.PENDING,
        snapshot_ts=NOW,
        signal_timeframe=Timeframe.M15,
        price_at_build=50_000.0,
        atr_at_build=500.0,
        levels=[],
    )
    services.store.put(proposal)
    return proposal


# --------------------------------------------------------------------------- #
# Das Tor bei der Tokenausstellung
# --------------------------------------------------------------------------- #


def test_ein_token_wird_bei_vollen_plaetzen_verweigert(services: Services) -> None:
    """Der Fall, der heute durchgeht.

    Fünf offene Positionen, der Platzdeckel steht auf fünf -- und ohne Tor
    bekäme dieser Vorschlag trotzdem ein Token.
    """
    proposal = _vorschlag(services)
    services.prices = _Prices(proposal.entry)
    voll = [_position(f"SYM{i}USDT") for i in range(services.config.risk.limits.max_open_positions)]
    services.account_provider = functools.partial(_konto, voll)

    client = TestClient(create_app(services))
    antwort = client.post(f"/api/proposals/{proposal.id}/token")
    assert antwort.status_code == 423, antwort.text
    assert "already open" in antwort.text


def test_ein_token_wird_bei_gezogenem_kill_switch_verweigert(
    services: Services,
) -> None:
    proposal = _vorschlag(services)
    services.prices = _Prices(proposal.entry)
    services.account_provider = _konto
    services.kill_switch.engage("Test")

    client = TestClient(create_app(services))
    antwort = client.post(f"/api/proposals/{proposal.id}/token")
    assert antwort.status_code == 423
    assert "kill switch" in antwort.text.lower()


def test_ein_token_wird_bei_freiem_konto_ausgestellt(services: Services) -> None:
    """Die Gegenprobe -- das Tor darf nicht alles aussperren."""
    proposal = _vorschlag(services)
    services.prices = _Prices(proposal.entry)
    services.account_provider = _konto

    client = TestClient(create_app(services))
    antwort = client.post(f"/api/proposals/{proposal.id}/token")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["token"]


def test_eine_zweite_position_im_selben_symbol_verweigert_das_token(
    services: Services,
) -> None:
    proposal = _vorschlag(services)
    services.prices = _Prices(proposal.entry)
    services.account_provider = functools.partial(_konto, [_position(SYMBOL)])

    client = TestClient(create_app(services))
    antwort = client.post(f"/api/proposals/{proposal.id}/token")
    assert antwort.status_code == 423
    assert SYMBOL in antwort.text


# --------------------------------------------------------------------------- #
# Der Kontozustand entsteht zur Prüfzeit
# --------------------------------------------------------------------------- #


def test_der_kontozustand_wird_bei_jeder_pruefung_neu_geholt(
    services: Services,
) -> None:
    """Ein eingefrorener Zustand ist kein Börsenzustand.

    Der Anbieter wird gezählt. Wäre er einmal beim Start gelesen worden,
    stünde der Zähler nach zwei Anfragen auf eins.
    """
    proposal = _vorschlag(services)
    services.prices = _Prices(proposal.entry)
    aufrufe = {"n": 0}

    def anbieter() -> AccountState:
        aufrufe["n"] += 1
        return _konto()

    services.account_provider = anbieter
    client = TestClient(create_app(services))
    client.post(f"/api/proposals/{proposal.id}/token")
    client.post(f"/api/proposals/{proposal.id}/token")
    assert aufrufe["n"] >= 2, (
        f"der Kontozustand wurde {aufrufe['n']}x geholt -- er muss bei JEDER "
        f"Pruefung frisch entstehen"
    )


def test_ohne_kontozustand_wird_kein_token_ausgestellt(services: Services) -> None:
    """Fail-closed: kein Zustand heisst kein Senden, nicht 'dann eben ungeprüft'."""
    proposal = _vorschlag(services)
    services.prices = _Prices(proposal.entry)
    # Kein account_provider und kein account.

    client = TestClient(create_app(services))
    antwort = client.post(f"/api/proposals/{proposal.id}/token")
    assert antwort.status_code in (423, 503), antwort.text


# --------------------------------------------------------------------------- #
# `adjust()` durch denselben Guard
# --------------------------------------------------------------------------- #


def test_adjust_prueft_die_kontogrenzen(services: Services) -> None:
    """`build()` prüft sie (builder.py:260), `adjust()` tat es nicht.

    Dasselbe Konto, dieselben Grenzen -- die Anpassung muss am selben Tor
    scheitern wie der Bau.
    """
    proposal = _vorschlag(services)
    voll = [_position(f"SYM{i}USDT") for i in range(services.config.risk.limits.max_open_positions)]

    ergebnis = services.builder.adjust(
        proposal,
        ProposalAdjustment(leverage=4.0),
        SPEC,
        _konto(voll),
    )
    assert isinstance(ergebnis, BuildFailure), (
        "eine Anpassung bei vollen Plaetzen muss scheitern"
    )
    assert "already open" in (ergebnis.detail + ergebnis.reason)


def test_adjust_gelingt_bei_freiem_konto(services: Services) -> None:
    """Die Gegenprobe: 5x -> 4x muss weiterhin funktionieren."""
    proposal = _vorschlag(services)
    ergebnis = services.builder.adjust(
        proposal, ProposalAdjustment(leverage=4.0), SPEC, _konto()
    )
    assert isinstance(ergebnis, TradeProposal), ergebnis
    assert ergebnis.leverage <= 4.0


def test_adjust_prueft_auch_den_kill_switch(services: Services) -> None:
    """Der Kill-Switch gehört in dasselbe Tor.

    `limits.check` prüft ihn als erstes und allein hinreichend
    (`limits.py:204`) -- sobald `adjust()` durch `check` läuft, gilt das auch
    dort.
    """
    proposal = _vorschlag(services)
    services.kill_switch.engage("Test")
    geschuetzt = ProposalBuilder(
        services.config,
        RiskLimits(services.config.risk.limits, kill_switch=services.kill_switch),
    )
    ergebnis = geschuetzt.adjust(
        proposal, ProposalAdjustment(leverage=4.0), SPEC, _konto()
    )
    assert isinstance(ergebnis, BuildFailure)
    assert "kill switch" in (ergebnis.detail + ergebnis.reason).lower()
