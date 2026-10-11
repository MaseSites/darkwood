"""Funding über einen Neustart: wird es verbucht, und wird es nur einmal verbucht?

**Der Test, der gefehlt hat.** Der Defekt lebte ausschliesslich auf dem
Wiederherstellungspfad: `restore_into` rief `broker.skip_to(last_minute_ts)`,
*bevor* die Position angehängt war, und `_charge_funding` schreibt nur einer
offenen Position zu. Also verbrauchte der Vorlauf jede Rate mit
`position=None` und verbuchte nichts. Jeder Test ohne Neustart konnte das
nicht sehen — und keiner hatte einen.

Belegt am echten Fall `live-LINKUSDT-1791303300000`: ein Short über die
Abrechnung am 07.10.2026 00:00 mit Rate +0,0001, Notional 709,3768 USDT. Ein
Short *erhält* bei positiver Rate, also fehlten +0,070938 USDT — der Ausfall
liess den Trade **schlechter** aussehen, nicht besser.

**Vier Dinge müssen gleichzeitig gelten**, und jedes hat hier seinen Fall:

1. Nach dem Neustart wird verbucht, was der Position zusteht.
2. Nichts wird zweimal verbucht — das war der Grund der alten Reihenfolge,
   und er bleibt gültig.
3. Eine Zeile ohne die neue Spalte (`None`) verhält sich wie vorher. Würde
   `None` zu 0, bekäme die offene Position jede Rate seit Eröffnung ein
   zweites Mal, bei jedem Neustart.
4. `restore_into` auf einen belegten Broker ist ein Fehler. Vorher hat
   `skip_to` das geprüft; nach dem Umbau tut es niemand mehr, also prüft es
   `restore_into` selbst.
"""

from __future__ import annotations

import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH
from traidingbrain.config.settings import SimulationConfig
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import FundingRate
from traidingbrain.live.paperstate import PaperState
from traidingbrain.sim.broker import OpenPosition, SimBroker

HOUR = 3_600_000
MINUTE = 60_000

#: Der echte Fall, auf Zahlen heruntergebrochen.
RATE = 0.0001
QTY = 500.0
ENTRY = 1.4187536
NOTIONAL = QTY * ENTRY


def config() -> SimulationConfig:
    return SimulationConfig.model_validate({
        "initial_equity": 1_000.0,
        "slippage_bps": 0.0,
        "fill_on_touch": True,
        "entry_expiry_bars": 8,
        "pessimistic_intrabar": True,
    })


def rates(*hours: int) -> list[FundingRate]:
    """Abrechnungen zu den angegebenen Stunden nach EPOCH."""
    return [FundingRate(ts=EPOCH + h * HOUR, rate=RATE) for h in hours]


def short_position(opened_hours: int = 0) -> OpenPosition:
    return OpenPosition(
        side=Side.SHORT,
        entry_price=ENTRY,
        qty=QTY,
        leverage=10.0,
        stop=ENTRY * 1.01,
        target=ENTRY * 0.98,
        liq_price=ENTRY * 1.09,
        opened_ts=EPOCH + opened_hours * HOUR,
        margin=NOTIONAL / 10.0,
        risk_amount=10.0,
    )


def broker_with(*hours: int) -> SimBroker:
    return SimBroker(make_symbol_spec(), config(), funding=rates(*hours))


def expected_credit(settlements: int) -> float:
    """Was ein Short bei positiver Rate erhaelt: -notional * rate * (-1)."""
    return settlements * NOTIONAL * RATE


# --------------------------------------------------------------------------- #
# 1. Nach dem Neustart wird verbucht, was der Position zusteht
# --------------------------------------------------------------------------- #


def test_a_position_held_across_a_restart_is_credited_its_funding() -> None:
    """Der Defekt selbst. Vorher kam hier 0,0 heraus."""
    broker = broker_with(8)
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_000.0,
        last_minute_ts=EPOCH + 9 * HOUR,
        position=short_position(opened_hours=0),
        funding_settled_ts=0,
    )
    state.restore_into(broker)

    assert broker.position is not None
    assert broker.position.funding_paid == pytest.approx(expected_credit(1))
    assert broker.position.funding_paid > 0, (
        "ein Short erhaelt bei positiver Rate -- ein Ausfall liess den Trade "
        "schlechter aussehen, nicht besser"
    )


def test_several_settlements_in_the_gap_are_all_credited() -> None:
    broker = broker_with(8, 16, 24)
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_000.0,
        last_minute_ts=EPOCH + 25 * HOUR,
        position=short_position(opened_hours=0),
        funding_settled_ts=0,
    )
    state.restore_into(broker)

    assert broker.position is not None
    assert broker.position.funding_paid == pytest.approx(expected_credit(3))


def test_a_settlement_before_the_position_opened_is_not_credited() -> None:
    """`_charge_funding` ueberspringt Raten, die vor der Eroeffnung lagen.

    Der Cursor bewegt sich trotzdem -- das ist der Unterschied zwischen
    "verbraucht" und "verbucht", und er ist der Grund, warum der Cursor
    persistiert werden muss.
    """
    broker = broker_with(2, 10)
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_000.0,
        last_minute_ts=EPOCH + 11 * HOUR,
        position=short_position(opened_hours=5),
        funding_settled_ts=0,
    )
    state.restore_into(broker)

    assert broker.position is not None
    assert broker.position.funding_paid == pytest.approx(expected_credit(1))
    assert broker.funding_settled_ts == EPOCH + 10 * HOUR


# --------------------------------------------------------------------------- #
# 2. Nichts wird zweimal verbucht
# --------------------------------------------------------------------------- #


def test_funding_already_settled_is_not_charged_again() -> None:
    """Der Grund der alten Reihenfolge, und er gilt weiter.

    Die Abrechnung um 08:00 ist schon verbucht, der Cursor steht darauf. Nach
    dem Neustart darf nur die um 16:00 dazukommen.
    """
    broker = broker_with(8, 16)
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_000.0,
        last_minute_ts=EPOCH + 17 * HOUR,
        position=short_position(opened_hours=0),
        funding_settled_ts=EPOCH + 8 * HOUR,
    )
    state.restore_into(broker)

    assert broker.position is not None
    assert broker.position.funding_paid == pytest.approx(expected_credit(1)), (
        "die 08:00-Abrechnung stand schon im persistierten funding_paid"
    )


def test_two_restarts_in_a_row_credit_once() -> None:
    """Ein Neustartzyklus, zweimal gefahren. Der Cursor muss das tragen."""
    first = broker_with(8)
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_000.0,
        last_minute_ts=EPOCH + 9 * HOUR,
        position=short_position(opened_hours=0),
        funding_settled_ts=0,
    )
    state.restore_into(first)
    state.capture_from(first, reason=None)
    after_first = first.position.funding_paid if first.position else 0.0

    second = broker_with(8)
    state.restore_into(second)

    assert second.position is not None
    assert after_first == pytest.approx(expected_credit(1))
    assert second.position.funding_paid == pytest.approx(after_first), (
        "capture_from muss den Cursor mitnehmen, sonst zahlt jeder Neustart erneut"
    )


# --------------------------------------------------------------------------- #
# 3. Die Migration: None ist nicht 0
# --------------------------------------------------------------------------- #


def test_a_row_without_the_column_behaves_as_before() -> None:
    """`funding_settled_ts=None` heisst: Zeile aus der Zeit davor.

    Hergeleitet wird genau der Wert, den das alte
    `skip_to(last_minute_ts)` hinterlassen haette -- also nichts
    nachtraeglich verbucht. Altzeilen verhalten sich exakt wie bisher.
    """
    broker = broker_with(8, 16)
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_000.0,
        last_minute_ts=EPOCH + 17 * HOUR,
        position=short_position(opened_hours=0),
        funding_settled_ts=None,
    )
    state.restore_into(broker)

    assert broker.position is not None
    assert broker.position.funding_paid == pytest.approx(0.0), (
        "None zu 0 zu machen wuerde hier zwei Raten erfinden, bei JEDEM Neustart"
    )
    assert broker.funding_settled_ts == EPOCH + 16 * HOUR


def test_a_legacy_row_still_settles_what_comes_after_it() -> None:
    """Die Herleitung darf den Cursor nicht ueber das Ende hinaus setzen."""
    broker = broker_with(8, 16)
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_000.0,
        last_minute_ts=EPOCH + 9 * HOUR,
        position=short_position(opened_hours=0),
        funding_settled_ts=None,
    )
    state.restore_into(broker)
    assert broker.funding_settled_ts == EPOCH + 8 * HOUR

    # Die 16:00-Abrechnung liegt noch vor dem Cursor und wird normal verbucht.
    broker.on_minute(EPOCH + 16 * HOUR, ENTRY, ENTRY, ENTRY)
    assert broker.position is not None
    assert broker.position.funding_paid == pytest.approx(expected_credit(1))


# --------------------------------------------------------------------------- #
# 4. Ein belegter Broker ist ein Fehler
# --------------------------------------------------------------------------- #


def test_restoring_onto_an_occupied_broker_raises() -> None:
    """Vorher hat `skip_to` das geprueft; jetzt prueft es `restore_into`.

    Ohne diese Zeile wuerde ein zweiter Aufruf die laufende Position
    stillschweigend ueberschreiben -- und der Umbau hat die alte Pruefung
    entfernt, weil `skip_to` nicht mehr aufgerufen wird.
    """
    broker = broker_with(8)
    broker.position = short_position()
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_000.0,
        last_minute_ts=EPOCH + 9 * HOUR,
        funding_settled_ts=0,
    )
    with pytest.raises(RuntimeError, match="already holds"):
        state.restore_into(broker)


def test_a_flat_account_restores_without_funding_work() -> None:
    """Der haeufigste Fall: nichts offen, nichts zu verbuchen."""
    broker = broker_with(8)
    state = PaperState(
        symbol="LINKUSDT",
        equity=1_234.56,
        last_minute_ts=EPOCH + 9 * HOUR,
        funding_settled_ts=0,
    )
    state.restore_into(broker)

    assert broker.position is None
    assert broker.equity == pytest.approx(1_234.56)
    # Der Cursor ist trotzdem vorgerueckt -- sonst wuerde die naechste offene
    # Position eine Rate aus der Vergangenheit gutgeschrieben bekommen.
    assert broker.funding_settled_ts == EPOCH + 8 * HOUR
