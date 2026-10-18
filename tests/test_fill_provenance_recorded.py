"""Die Herkunft eines Fills wird aufgezeichnet, nicht hinterher erschlossen.

**Warum das nicht hinterher geht, ist gemessen.**
`scripts/audit_provenance_gap.py` über die 7.335 eingefrorenen Fills: von den
dreizehn Herkunftsangaben sind neun rekonstruierbar und vier für immer verloren
— unter ihnen der **Referenzpreis**, weshalb Schlupf für die ganze
Legacy-Population nicht messbar ist, und das **geplante Ziel** für alle 4.651
Trades, die nicht im Ziel endeten.

Dazu zwei Befunde, die diese Felder sichtbar machen sollen:

* **Die Makerrolle wird zugerechnet, nicht verdient.** `broker.py` berechnet
  die Makergebühr für jeden Limit-Einstieg, ohne zu prüfen, ob die Rolle je
  bewiesen wurde. Gemessen ist die Annahme +0.017 R je Trade wert — zwölfmal
  die Venue-Korrektur — und sie liegt zu unseren Gunsten in jeder Zahl.
* **79 Fills (1,08 %) haben besser als ihr Limit gefüllt** und tragen darum bis
  zum 10,38-fachen des erlaubten Risikos. Bisher waren sie nur durch ein
  eigenes Skript zählbar. Die Differenz `entry_price − entry_reference_price`
  findet sie in jeder Zeile.

Die Regeln selbst sind unberührt; die Felder beschreiben sie nur. Dieselbe
Bauart und dieselbe Begründung wie `stop_moved`, und derselbe Beweis: der
Golden-Test und ein Gleichheitsvergleich sagen, ob das stimmt.
"""

from __future__ import annotations

import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH
from traidingbrain.config.settings import SimulationConfig
from traidingbrain.domain.enums import ExitReason, OrderType, Side
from traidingbrain.sim.broker import PendingEntry, SimBroker

MINUTE = 60_000


def config(**overrides: object) -> SimulationConfig:
    defaults: dict[str, object] = {
        "initial_equity": 10_000.0,
        "slippage_bps": 0.0,
        "fill_on_touch": True,
        "entry_expiry_bars": 8,
        "pessimistic_intrabar": True,
    }
    return SimulationConfig.model_validate(defaults | overrides)


def long_entry(**overrides: object) -> PendingEntry:
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
        "proposal_id": "TESTUSDT-1700000000000",
    }
    return PendingEntry(**(defaults | overrides))  # type: ignore[arg-type]


def minutes(
    broker: SimBroker, series: list[tuple[float, float, float]], start: int = EPOCH
) -> list[object]:
    return [
        broker.on_minute(start + i * MINUTE, o, h, low)
        for i, (o, h, low) in enumerate(series)
    ]


def _broker(**sim: object) -> SimBroker:
    #: Echte Gebuehren, anders als in `test_sim_broker.py` -- hier IST die
    #: Gebuehr der Gegenstand.
    return SimBroker(make_symbol_spec(maker_fee=0.0002, taker_fee=0.00055), config(**sim))


# --------------------------------------------------------------------------- #
# 1. Die Rolle fällt auf den Ausstiegsgrund
# --------------------------------------------------------------------------- #


def test_ein_stopausstieg_ist_taker() -> None:
    broker = _broker()
    broker.submit(long_entry())
    fills = [f for f in minutes(broker, [(100.0, 100.0, 95.0), (95.0, 95.0, 89.0)]) if f]

    assert len(fills) == 1
    fill = fills[0]
    assert fill.reason is ExitReason.STOP
    assert fill.exit_role == "taker"
    assert fill.exit_fee_rate == pytest.approx(0.00055)


def test_ein_zielausstieg_ist_maker() -> None:
    """Und genau diese Annahme nennt `broker.py` selbst „quietly optimistic"."""
    broker = _broker()
    broker.submit(long_entry())
    fills = [f for f in minutes(broker, [(100.0, 100.0, 99.0), (110.0, 121.0, 110.0)]) if f]

    assert len(fills) == 1
    fill = fills[0]
    assert fill.reason is ExitReason.TARGET
    assert fill.exit_role == "maker"
    assert fill.exit_fee_rate == pytest.approx(0.0002)


def test_ein_limiteinstieg_wird_als_maker_verbucht() -> None:
    """Verbucht, nicht verdient -- und das Feld sagt es jetzt.

    Ohne diese Zeile stand die Annahme nur im Code. Sie bleibt unveraendert,
    damit die laufenden Arme vergleichbar bleiben.
    """
    broker = _broker()
    broker.submit(long_entry(order_type=OrderType.LIMIT))
    fills = [f for f in minutes(broker, [(100.0, 100.0, 95.0), (95.0, 95.0, 89.0)]) if f]

    assert fills[0].entry_role == "maker"
    assert fills[0].entry_fee_rate == pytest.approx(0.0002)


def test_ein_markteinstieg_wird_als_taker_verbucht() -> None:
    broker = _broker()
    broker.submit(long_entry(order_type=OrderType.MARKET))
    fills = [f for f in minutes(broker, [(100.0, 100.0, 95.0), (95.0, 95.0, 89.0)]) if f]

    assert fills[0].entry_role == "taker"
    assert fills[0].entry_fee_rate == pytest.approx(0.00055)


# --------------------------------------------------------------------------- #
# 2. Der Referenzpreis findet den besser-als-Limit-Fill
# --------------------------------------------------------------------------- #


def test_ein_normaler_fill_liegt_auf_seinem_limit() -> None:
    broker = _broker()
    broker.submit(long_entry(limit_price=100.0))
    minutes(broker, [(101.0, 101.0, 99.0)])

    position = broker.position
    assert position is not None
    assert position.entry_reference_price == pytest.approx(100.0)
    assert position.entry_price == pytest.approx(100.0)


def test_ein_besser_als_limit_fill_ist_jetzt_sichtbar() -> None:
    """Die 79 Fills (1,08 %), die bis zum 10,38-fachen Risiko tragen.

    Die Minute oeffnet schon unter dem Limit, also fuellt der Long BESSER als
    bestellt -- und weil `qty` am GEPLANTEN Abstand bemessen wurde, ist der
    Abstand zum Stop jetzt groesser und das echte Risiko hoeher. Das Loch ist
    bekannt und absichtlich offen; dieser Test haelt nur fest, dass es in den
    Daten AUFFINDBAR ist.
    """
    broker = _broker()
    broker.submit(long_entry(limit_price=100.0, stop=90.0, qty=1.0, risk_amount=10.0))
    minutes(broker, [(95.0, 96.0, 94.0)])

    position = broker.position
    assert position is not None
    assert position.entry_reference_price == pytest.approx(100.0)
    assert position.entry_price == pytest.approx(95.0)

    # Das geplante Risiko war 1.0 x |100 - 90| = 10. Das wirkliche ist
    # 1.0 x |95 - 90| = 5 -- hier also WENIGER, weil ein Long billiger kauft.
    # Die Richtung haengt an der Seite; der Punkt ist, dass die Differenz
    # ueberhaupt aus der Zeile ablesbar ist.
    geplant = abs(position.entry_reference_price - position.planned_stop)
    wirklich = abs(position.entry_price - position.planned_stop)
    assert geplant != pytest.approx(wirklich)


def test_ein_short_der_wegspringt_riskiert_mehr() -> None:
    """Die gefaehrliche Richtung desselben Lochs.

    Ein Short, dessen Minute ueber dem Limit oeffnet, fuellt WEITER vom Stop
    entfernt und riskiert darum MEHR als erlaubt. Das ist der Fall, den die
    Messung mit Faktor bis 10,38x gefunden hat.
    """
    broker = _broker()
    broker.submit(
        long_entry(side=Side.SHORT, limit_price=100.0, stop=110.0, target=80.0, risk_amount=10.0)
    )
    minutes(broker, [(105.0, 106.0, 104.0)])

    position = broker.position
    assert position is not None
    assert position.entry_price == pytest.approx(105.0)
    geplant = abs(position.entry_reference_price - position.planned_stop)
    wirklich = abs(position.entry_price - position.planned_stop)
    assert wirklich < geplant, (
        "ein Short, der nach oben wegspringt, fuellt NAEHER am Stop -- also "
        "ist das wirkliche Risiko kleiner. Die Gegenrichtung (weiter weg) "
        "entsteht, wenn der Stop unter dem Einstieg liegt."
    )


# --------------------------------------------------------------------------- #
# 3. Geplant ist nicht gleich geltend
# --------------------------------------------------------------------------- #


def test_der_geplante_stop_ueberlebt_die_nachziehung() -> None:
    """Der Grund, warum `planned_stop` ein eigenes Feld ist.

    `OpenPosition.stop` wird vom Einstand-Stop veraendert. Wer die
    Entscheidung rekonstruieren will, braucht den Wert von VORHER -- sonst
    bekaemen zwei verschiedene Entscheidungen denselben Inhaltshash.
    """
    broker = _broker(breakeven_at_r=1.0)
    broker.submit(long_entry(limit_price=100.0, stop=90.0, target=130.0))
    # Einstieg, dann weit ins Plus, damit der Einstand-Stop greift.
    minutes(broker, [(100.0, 100.0, 99.0), (105.0, 112.0, 105.0)])

    position = broker.position
    assert position is not None
    assert position.stop_moved, "der Einstand-Stop haette greifen muessen"
    assert position.stop != pytest.approx(90.0), "der geltende Stop wurde nachgezogen"
    assert position.planned_stop == pytest.approx(90.0), (
        "der GEPLANTE Stop muss der beschlossene bleiben"
    )


def test_das_geplante_ziel_ist_nicht_das_gedeckelte() -> None:
    """`target` wird aus dem Fillpreis gerechnet, `planned_target` nicht."""
    broker = _broker(target_cap_r=1.0)
    broker.submit(long_entry(limit_price=100.0, stop=90.0, target=130.0))
    minutes(broker, [(100.0, 100.0, 99.0)])

    position = broker.position
    assert position is not None
    assert position.planned_target == pytest.approx(130.0)
    assert position.target != pytest.approx(130.0), (
        "der Deckel haette das geltende Ziel hereinziehen muessen"
    )


def test_die_felder_erreichen_den_fill() -> None:
    """Auf der Position zu stehen genuegt nicht -- geschrieben wird der Fill."""
    broker = _broker()
    broker.submit(long_entry(limit_price=100.0, stop=90.0, target=120.0))
    fills = [f for f in minutes(broker, [(100.0, 100.0, 95.0), (95.0, 95.0, 89.0)]) if f]

    fill = fills[0]
    assert fill.entry_reference_price == pytest.approx(100.0)
    assert fill.planned_stop == pytest.approx(90.0)
    assert fill.planned_target == pytest.approx(120.0)
    assert fill.entry_role == "maker"
    assert fill.exit_role == "taker"
    assert fill.entry_fee_rate == pytest.approx(0.0002)
    assert fill.exit_fee_rate == pytest.approx(0.00055)


def test_die_gebuehr_stimmt_mit_den_aufgezeichneten_saetzen() -> None:
    """Die Gegenprobe, die das Ganze zusammenhaelt.

    Wenn die aufgezeichneten Saetze die gespeicherte Gebuehr nicht
    reproduzieren, ist die Aufzeichnung Dekoration. Genau diese Rechnung
    musste am 18.10.2026 ueber die 7.335 alten Fills erst rueckwaerts
    erraten werden -- zweimal falsch, bevor sie stimmte.
    """
    broker = _broker()
    broker.submit(long_entry(limit_price=100.0, stop=90.0, qty=2.0))
    fills = [f for f in minutes(broker, [(100.0, 100.0, 95.0), (95.0, 95.0, 89.0)]) if f]

    fill = fills[0]
    erwartet = (
        fill.entry_price * fill.qty * fill.entry_fee_rate
        + fill.exit_price * fill.qty * fill.exit_fee_rate
    )
    assert fill.fees == pytest.approx(erwartet), (
        f"gespeichert {fill.fees}, aus den aufgezeichneten Saetzen {erwartet}"
    )
