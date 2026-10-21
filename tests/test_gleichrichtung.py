"""Die Grenze für gleichgerichtete Positionen.

Der Anlass ist gemessen, nicht ausgedacht: am 20.10.2026 starben vier
Positionen in derselben Minute, alle vier long; über die 19 Trades des
Plankontos erzeugten zwei Fünfzehn-Minuten-Kerzen acht Einstiege — 42 % aller
Trades — und kosteten zusammen 90,61 USD.

Was hier geprüft wird, ist nicht, ob die Grenze hilft. Das kann dieser Test
nicht wissen und keine 19 Trades können es. Geprüft wird, dass sie **das
Richtige** begrenzt: die Konzentration, nicht die Richtung, und nur mit
bekannter Seite.
"""

from __future__ import annotations

import pytest

from traidingbrain.config.settings import LimitsConfig
from traidingbrain.domain.enums import Side
from traidingbrain.domain.proposal import Position
from traidingbrain.risk.limits import AccountState, RiskLimits


def _grenzen(**over: object) -> LimitsConfig:
    basis = {
        "max_open_positions": 5,
        "max_positions_per_symbol": 1,
        "max_daily_loss_pct": 0.9,
        "max_weekly_loss_pct": 0.9,
        "cooldown_after_consecutive_losses": 99,
        "cooldown_hours": 0,
        "min_reward_risk": 1.0,
        "max_cost_fraction_of_risk": 0.9,
    }
    basis.update(over)
    return LimitsConfig(**basis)   # type: ignore[arg-type]


def _position(symbol: str, side: Side) -> Position:
    return Position(
        symbol=symbol, side=side, qty=1.0, entry_price=100.0,
        leverage=7.0, liquidation_price=50.0 if side is Side.LONG else 150.0,
        opened_ts=1_000,
    )


def _state(*positionen: Position) -> AccountState:
    return AccountState.from_history(
        equity=1000.0, history=[], now_ms=1_000_000,
        open_positions=list(positionen),
    )


def test_ohne_grenze_bleibt_alles_wie_vorher() -> None:
    """`None` ist die Vorgabe, und sie darf nichts aendern.

    Eine neue Grenze, die sich still einschaltet, veraendert jede bestehende
    Konfiguration, ohne dass es jemand sieht -- in diesem Fall die laufende
    Vorwaertsstichprobe.
    """
    limits = RiskLimits(_grenzen())
    state = _state(*[_position(f"S{i}USDT", Side.LONG) for i in range(4)])
    assert limits.check(state, symbol="XUSDT", side=Side.LONG).allowed


def test_die_dritte_gleichgerichtete_wird_abgelehnt() -> None:
    limits = RiskLimits(_grenzen(max_same_direction=2))
    state = _state(_position("AUSDT", Side.LONG), _position("BUSDT", Side.LONG))
    v = limits.check(state, symbol="CUSDT", side=Side.LONG)
    assert not v.allowed
    assert "long" in v.reason.lower()


def test_die_gegenrichtung_bleibt_offen() -> None:
    """Die Grenze begrenzt Konzentration, nicht Richtung.

    Die erste Fassung versuchte, die Seite aus dem Bestand zu ERRATEN, und
    haette hier einen Short abgelehnt, weil zwei Longs offen sind. Eine
    Grenze, die die falsche Seite trifft, ist schlimmer als keine.
    """
    limits = RiskLimits(_grenzen(max_same_direction=2))
    state = _state(_position("AUSDT", Side.LONG), _position("BUSDT", Side.LONG))
    assert limits.check(state, symbol="CUSDT", side=Side.SHORT).allowed


def test_ohne_bekannte_seite_wird_nicht_geprueft() -> None:
    """Ohne Richtung gibt es keine Richtungsgrenze — und kein Raten."""
    limits = RiskLimits(_grenzen(max_same_direction=1))
    state = _state(_position("AUSDT", Side.LONG), _position("BUSDT", Side.LONG))
    assert limits.check(state, symbol="CUSDT").allowed


@pytest.mark.parametrize("grenze", [1, 2, 3])
def test_die_grenze_ist_die_zahl_der_ERLAUBTEN(grenze: int) -> None:
    """`max_same_direction: 2` heisst zwei offen, die dritte blockiert."""
    limits = RiskLimits(_grenzen(max_same_direction=grenze))
    offen = [_position(f"S{i}USDT", Side.SHORT) for i in range(grenze)]
    assert not limits.check(_state(*offen), symbol="XUSDT", side=Side.SHORT).allowed
    assert limits.check(_state(*offen[:-1]), symbol="XUSDT", side=Side.SHORT).allowed


def test_das_plankonto_hat_die_grenze_und_die_produktion_nicht() -> None:
    """Die Konfigurationen sagen, was sie sollen — sonst ist der Code Zierde."""
    from pathlib import Path

    from traidingbrain.config.settings import load_config

    assert load_config(Path("config_offen")).risk.limits.max_same_direction == 2
    assert load_config(Path("config")).risk.limits.max_same_direction is None
