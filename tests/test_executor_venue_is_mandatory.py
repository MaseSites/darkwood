"""Der Executor hat keine Vorgabe-Börse mehr, und er prüft die Zugangsdaten.

**Der Anlass, belegt in `audit/P0A_LEGACY_FREEZE.md`.**
`execution/order.py:91` trug `venue_name: str = "bybit"`. Die beiden
Produktionsaufrufer übergaben nichts:

    scripts/run_dashboard.py:144   BybitExecutor(key, secret, intents, kill, testnet=…)
    scripts/run_live.py:230        dieselbe Form

Die einzige Stelle, die es übergab, war `scripts/check_exchange.py:156` über
ein CLI-Argument. Gleichzeitig baute dieselbe Funktion in `run_dashboard.py`
sieben Zeilen weiter die Preisquelle aus `config.engine.exchange.name`, also
Binance. Eine Vorgabe, die eine andere Antwort gibt als die Konfiguration, ist
kein Vorgabewert — sie ist ein zweiter, unsichtbarer Konfigurationsort.

**Und die Zugangsdaten sind der eigentliche Grund für die Beschränkung.** Es
gibt nur `BybitCredentials` (`config/settings.py:461`), eingebunden als
`Secrets.bybit`. Ein Binance-Executor hätte keinen Zugangsdatenpfad, also ist
`venue_name="binance"` nicht „noch nicht unterstützt", sondern ein Zustand, in
dem die Schlüssel einer anderen Börse an eine Börse gingen.
"""

from __future__ import annotations

from typing import Any

import pytest

from traidingbrain.execution.intent import IntentLog
from traidingbrain.execution.order import BybitExecutor, UnsafeConfigurationError
from traidingbrain.execution.venuebinding import EXECUTABLE_VENUES
from traidingbrain.risk.limits import KillSwitch


class _FakeExchange:
    """Gerade genug, dass der Konstruktor nicht ans Netz geht."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        def _nichts(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args))
            return {}

        return _nichts


def _bauen(tmp_path, **kwargs: Any) -> BybitExecutor:
    basis: dict[str, Any] = {
        "api_key": "k",
        "api_secret": "s",
        "intents": IntentLog(tmp_path / "intents.sqlite"),
        "kill_switch": KillSwitch(tmp_path / "kill"),
        "testnet": True,
        "exchange": _FakeExchange(),
    }
    basis.update(kwargs)
    return BybitExecutor(**basis)


# --------------------------------------------------------------------------- #
# Kein Vorgabewert
# --------------------------------------------------------------------------- #


def test_ohne_venue_name_ist_der_executor_nicht_konstruierbar(tmp_path) -> None:
    """Die Vorgabe `"bybit"` ist weg -- ersatzlos, nicht ersetzt."""
    with pytest.raises(TypeError):
        _bauen(tmp_path)


def test_mit_venue_name_bybit_wird_er_gebaut(tmp_path) -> None:
    e = _bauen(tmp_path, venue_name="bybit")
    assert e.venue.name == "bybit"


# --------------------------------------------------------------------------- #
# Nur ausführbare Börsen, und der Grund steht in der Meldung
# --------------------------------------------------------------------------- #


def test_binance_wird_hart_abgelehnt(tmp_path) -> None:
    with pytest.raises(ValueError) as exc:
        _bauen(tmp_path, venue_name="binance")
    text = str(exc.value)
    assert "binance" in text
    assert "BybitCredentials" in text, (
        "die Meldung muss den GRUND nennen, nicht nur die Ablehnung"
    )


def test_eine_unbekannte_boerse_wird_abgelehnt(tmp_path) -> None:
    with pytest.raises(ValueError, match="kraken"):
        _bauen(tmp_path, venue_name="kraken")


def test_die_ausfuehrbare_menge_ist_dieselbe_wie_in_der_bindung(tmp_path) -> None:
    """Zwei Orte, eine Wahrheit.

    Wenn der Executor und `VenueBinding` verschiedene Mengen kennen, ist eine
    von beiden falsch -- und zwar still.
    """
    for venue in EXECUTABLE_VENUES:
        assert _bauen(tmp_path, venue_name=venue).venue.name == venue


# --------------------------------------------------------------------------- #
# Die beiden Schranken für echtes Geld bleiben, wie sie waren
# --------------------------------------------------------------------------- #


def test_mainnet_ohne_allow_live_bricht_ab(tmp_path) -> None:
    """Unverändert aus `order.py:98` -- hier nur mitgeprüft, nicht geändert."""
    with pytest.raises(UnsafeConfigurationError):
        _bauen(tmp_path, venue_name="bybit", testnet=False)


def test_mainnet_mit_allow_live_ist_konstruierbar(tmp_path) -> None:
    e = _bauen(tmp_path, venue_name="bybit", testnet=False, allow_live=True)
    assert e.testnet is False
