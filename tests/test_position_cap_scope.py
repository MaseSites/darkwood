"""Für welchen Pfad `max_open_positions` gilt — festgenagelt, nicht kommentiert.

**Warum dieser Test existiert.** Das Audit vom 10.10.2026 nannte
`max_open_positions: 2` „toten Konfigurationstext", weil der Papierhandel die
Grenze nirgends durchsetzt — gemessener Höchststand fünf gleichzeitig offene
Positionen über die zwölf Papierkonten. Daraus folgte der Vorschlag, die
Einstellung entweder portfolioweit zu erzwingen oder sie zu löschen.

**Beides wäre falsch gewesen**, und zwar aus entgegengesetzten Gründen:

* *Löschen* ist eine Sicherheitsregression. Die Einstellung ist auf dem
  einzigen Pfad, der Geld berührt, aktiv — `RiskLimits.check` bekommt dort
  die echten offenen Positionen des Börsenkontos.
* *Portfolioweit erzwingen* poolt zwölf Konten, die `live/paper.py`
  absichtlich getrennt hält, damit der Vorwärtslauf mit den Backtests
  vergleichbar bleibt — und vergäbe den Platz nach Listenposition statt nach
  Signalqualität.

Die Einstellung ist eine **wahre, durchgesetzte Aussage über ein
Börsenkonto, das mehrere Symbole halten kann**. Dass sie im Papierhandel
wirkungslos ist, folgt aus der Struktur: zwölf getrennte Konten mit je einem
Einplatz-Broker. Ein Kommentar kann das behaupten; dieser Test hält es fest,
damit die nächste Aufräumaktion nicht wieder bei „tot, also weg" landet.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH
from traidingbrain.config.settings import SimulationConfig, load_config
from traidingbrain.domain.enums import OrderType, Side
from traidingbrain.domain.proposal import Position
from traidingbrain.risk.limits import AccountState, RiskLimits
from traidingbrain.sim.broker import PendingEntry, SimBroker
from traidingbrain.sim.plan import assess

NOW = 1_700_000_000_000
HOUR = 3_600_000
MINUTE = 60_000


def limits(cap: int) -> RiskLimits:
    """Die ausgelieferte Grenzenkonfiguration mit genau einem geaenderten Wert.

    Abgeleitet statt neu gebaut, damit der Test nicht an einer eigenen,
    moeglicherweise veralteten Vorstellung der uebrigen Felder haengt.
    """
    shipped = load_config().risk.limits
    return RiskLimits(shipped.model_copy(update={"max_open_positions": cap}))


def account(positions: list[Position]) -> AccountState:
    return AccountState(
        equity=10_000.0,
        starting_equity_today=10_000.0,
        starting_equity_this_week=10_000.0,
        open_positions=positions,
        recent_trades=[],
        now_ms=NOW,
    )


def position(symbol: str) -> Position:
    return Position(
        symbol=symbol,
        side=Side.LONG,
        qty=1.0,
        entry_price=100.0,
        leverage=5.0,
        liquidation_price=80.0,
        opened_ts=NOW - HOUR,
    )


def sim_config() -> SimulationConfig:
    return SimulationConfig.model_validate({
        "initial_equity": 1_000.0,
        "slippage_bps": 0.0,
        "fill_on_touch": True,
        "entry_expiry_bars": 8,
        "pessimistic_intrabar": True,
    })


def entry(**overrides: object) -> PendingEntry:
    defaults: dict[str, object] = {
        "side": Side.LONG,
        "order_type": OrderType.LIMIT,
        "limit_price": 100.0,
        "stop": 90.0,
        "target": 120.0,
        "qty": 1.0,
        "leverage": 5.0,
        "created_ts": EPOCH,
        "expires_ts": EPOCH + 100 * MINUTE,
        "risk_amount": 10.0,
    }
    return PendingEntry(**(defaults | overrides))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Der Pfad, auf dem die Grenze scharf ist
# --------------------------------------------------------------------------- #


def test_the_limit_blocks_a_third_position_on_the_exchange_path() -> None:
    """Zwei offene Positionen auf EINEM Konto, die dritte wird abgelehnt.

    Das ist der Pfad, auf dem Geld liegt: `scripts/run_live.py` uebergibt die
    echten offenen Positionen, `execution/order.py` liefert sie vom Konto.
    """
    verdict = limits(2).check(account([position("BTCUSDT"), position("ETHUSDT")]), symbol="SOLUSDT")

    assert not verdict.allowed
    assert any("positions already open" in blocker for blocker in verdict.blockers)
    assert "limit 2" in verdict.reason


def test_the_limit_allows_the_second_position() -> None:
    verdict = limits(2).check(account([position("BTCUSDT")]), symbol="ETHUSDT")

    assert verdict.allowed, verdict.reason


def test_the_shipped_configuration_carries_a_finite_limit() -> None:
    """Die ausgelieferte Zahl, damit ein stilles Hochsetzen auffaellt."""
    assert load_config().risk.limits.max_open_positions == 2


# --------------------------------------------------------------------------- #
# Warum sie im Papierhandel strukturell wirkungslos ist
# --------------------------------------------------------------------------- #


def test_one_broker_holds_at_most_one_position() -> None:
    """Die strukturelle Grenze je Papierkonto ist 1, nicht 2.

    Daraus folgt der ganze Abschnitt: wenn ein Konto nie zwei Positionen
    halten kann, kann keine Obergrenze ueber 1 sein Verhalten aendern.
    """
    broker = SimBroker(make_symbol_spec(taker_fee=0.0, maker_fee=0.0), sim_config())
    broker.submit(entry())
    broker.on_minute(EPOCH, 100.0, 101.0, 99.0)
    assert broker.position is not None, "die erste Order muss gefuellt sein"

    before = broker.rejected_entries
    accepted = broker.submit(entry(created_ts=EPOCH + MINUTE))

    assert accepted is False, "ein zweiter Einstieg darf nicht angenommen werden"
    assert broker.rejected_entries == before + 1, (
        "die Ablehnung wird gezaehlt -- eine Strategie, die staendig blockiert "
        "ist, ist nicht die, die gemessen wurde"
    )
    assert broker.position is not None


def test_no_legal_value_of_the_setting_can_change_a_paper_account() -> None:
    """Der kleinste erlaubte Wert ist 1, und 1 IST die strukturelle Grenze.

    Damit ist bewiesen, was der Kommentar in `config/risk.yaml` behauptet:
    im Papierhandel ist die Einstellung wirkungslos, und das ist kein Defekt,
    sondern eine Eigenschaft der Architektur. Ein Wert unter 1 -- der einzige,
    der etwas aendern wuerde -- ist von der Konfiguration verboten.
    """
    shipped = load_config().risk.limits
    assert shipped.model_copy(update={"max_open_positions": 1}).max_open_positions == 1
    with pytest.raises(ValidationError):
        type(shipped).model_validate(
            shipped.model_dump() | {"max_open_positions": 0}
        )


def test_the_paper_path_does_not_consult_the_limit_at_all() -> None:
    """`sim/plan.py:assess` nimmt kein `open_positions` und keine Historie.

    Gepruefter Zustand, nicht Absicht: solange diese Signatur so aussieht,
    kann der Papierpfad `RiskLimits.check` nicht aufrufen. Aendert sich das,
    faellt dieser Test und die Entscheidung gehoert neu getroffen -- statt
    dass eine Grenze unbemerkt anfaengt oder aufhoert zu greifen.
    """
    parameters = set(inspect.signature(assess).parameters)
    assert "equity" in parameters
    assert "open_positions" not in parameters
    assert "recent_trades" not in parameters
    assert "account" not in parameters
