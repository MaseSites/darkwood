"""Dass das Margin einer offenen Position gebunden ist — und nicht zwölfmal.

**Der Defekt, am 13.10.2026 gefunden.** `ledger.equity` wurde an zwei Stellen
gelesen (`submit`, `_try_fill`: passt das Margin?) und an genau einer
verändert (`_close`: `+= net`). Nichts zog beim Eröffnen etwas ab.

Bei zwölf getrennten Kassen war das unsichtbar: ein `SimBroker` hat
strukturell einen Platz, und beide Prüfstellen sind nur erreichbar, wenn
nichts offen ist. Mit der geteilten Kasse derselben Woche ist es ein Fehler
— zwölf Broker fragen nacheinander „passt mein Margin in die 12.075?", und
zwölf können Ja sagen.

Gemessen an den Stopweiten der 26 bereinigten Vorwärtstrades:

    zwoelf gleichzeitig, Median-Stop 1,5260 %   je   791  ->   9.496 / 12.076
    zwoelf gleichzeitig, engster Stop 0,6968 %  je 1.733  ->  20.796 / 12.076

Die untere Zeile ist auf einem echten Börsenkonto ein Margin Call. Dieser
Test hält fest, dass die Arithmetik sie jetzt ablehnt.

**Und die andere Hälfte: der Vorgabefall darf sich nicht bewegen.** Jeder
Backtest, jeder Golden-Hash und die 7.335 Replay-Trades hängen daran, dass
eine eigene Kasse sich exakt wie vorher verhält. Darum steht hier zuerst der
Beweis, dass `reserved` an jedem Prüfpunkt einer privaten Kasse null ist.
"""

from __future__ import annotations

import math

import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH
from traidingbrain.config.settings import SimulationConfig
from traidingbrain.domain.enums import ExitReason, OrderType, Side
from traidingbrain.live.paperstate import PaperState
from traidingbrain.sim.broker import PendingEntry, SimBroker, _Ledger

MINUTE = 60_000

#: Die gemessenen Groessen des echten Falls.
ACCOUNT = 1_006.30
POOL = 12_075.56
#: Der engste Stop der 26 Vorwaertstrades, als Anteil des Einstiegs.
TIGHT_STOP = 0.006968
#: Der Median.
MEDIAN_STOP = 0.015260
RISK_PCT = 0.01
ACCOUNTS = 12


def config(equity: float) -> SimulationConfig:
    return SimulationConfig.model_validate({
        "initial_equity": equity,
        "slippage_bps": 0.0,
        "fill_on_touch": True,
        "entry_expiry_bars": 8,
        "pessimistic_intrabar": True,
    })


def free_spec():
    return make_symbol_spec(taker_fee=0.0, maker_fee=0.0)


def sized_entry(capital: float, stop_fraction: float = TIGHT_STOP) -> PendingEntry:
    """Eine Order, die `RISK_PCT` von `capital` riskiert, bei diesem Stop."""
    entry_price = 100.0
    stop = entry_price * (1 - stop_fraction)
    risk = capital * RISK_PCT
    return PendingEntry(
        side=Side.LONG,
        order_type=OrderType.LIMIT,
        limit_price=entry_price,
        stop=stop,
        target=entry_price * 1.03,
        qty=risk / (entry_price - stop),
        leverage=10.0,
        created_ts=EPOCH,
        expires_ts=EPOCH + 100 * MINUTE,
        risk_amount=risk,
    )


def fill_it(broker: SimBroker, ts: int = EPOCH) -> None:
    """Eine Minute, die die Limit-Order erreicht."""
    broker.on_minute(ts, 100.5, 101.0, 99.5)


# --------------------------------------------------------------------------- #
# Der Vorgabefall bewegt sich nicht
# --------------------------------------------------------------------------- #


def test_a_private_ledger_reserves_nothing_at_either_check_point() -> None:
    """Warum kein Backtest sich aendert, als Test und nicht als Behauptung.

    Beide Margin-Pruefungen sind nur erreichbar, wenn nichts offen ist --
    `submit` lehnt bei vorhandener Position oder Order sofort ab, und
    `_try_fill` laeuft nur mit schwebender Order, die es ohne Position gibt.
    Also ist `available == equity` an jedem Punkt, an dem gemessen wird.
    """
    broker = SimBroker(free_spec(), config(10_000.0))

    assert broker.ledger.reserved == 0.0
    assert broker.ledger.available == pytest.approx(10_000.0)

    assert broker.submit(sized_entry(10_000.0)) is True
    # Noch nichts gebunden: eine schwebende Order ist kein Margin.
    assert broker.ledger.reserved == 0.0
    assert broker.ledger.available == pytest.approx(10_000.0)

    fill_it(broker)
    assert broker.position is not None
    assert broker.ledger.reserved == pytest.approx(broker.position.margin)

    # Und waehrend die Position laeuft, kommt niemand an eine Pruefung heran.
    assert broker.submit(sized_entry(10_000.0)) is False


def test_the_reserve_is_released_when_the_position_closes() -> None:
    broker = SimBroker(free_spec(), config(10_000.0))
    broker.submit(sized_entry(10_000.0))
    fill_it(broker)
    assert broker.ledger.reserved > 0.0

    broker.close_at(101.0, EPOCH + 5 * MINUTE)

    assert broker.position is None
    assert broker.ledger.reserved == pytest.approx(0.0)
    assert broker.ledger.available == pytest.approx(broker.ledger.equity)


def test_liquidation_releases_the_reserve_and_loses_the_money() -> None:
    """Der Fall, in dem beides gleichzeitig passiert.

    Bei Liquidation ist `net` genau `-margin`: die Kasse verliert das Margin
    und gibt es gleichzeitig frei. Das Verfuegbare bleibt also unveraendert --
    und das ist richtig, denn das Geld ist weg und nicht gebunden.
    """
    broker = SimBroker(free_spec(), config(10_000.0))
    broker.submit(sized_entry(10_000.0))
    fill_it(broker)
    position = broker.position
    assert position is not None
    margin = position.margin
    available_before = broker.ledger.available

    fill = broker.close_at(position.liq_price, EPOCH + 5 * MINUTE, ExitReason.LIQUIDATION)

    assert fill is not None
    assert broker.ledger.reserved == pytest.approx(0.0)
    assert broker.ledger.equity == pytest.approx(10_000.0 - margin)
    assert broker.ledger.available == pytest.approx(available_before), (
        "freigeben und verlieren heben sich auf -- sonst waere nach einer "
        "Liquidation mehr belegbar als vorher"
    )


# --------------------------------------------------------------------------- #
# Die geteilte Kasse: der eigentliche Defekt
# --------------------------------------------------------------------------- #


def twelve_on_one_pool() -> tuple[_Ledger, list[SimBroker]]:
    shared = _Ledger(equity=POOL, peak_equity=POOL)
    return shared, [
        SimBroker(free_spec(), config(ACCOUNT), ledger=shared) for _ in range(ACCOUNTS)
    ]


def test_twelve_tight_stop_positions_do_not_all_fit() -> None:
    """Die Zeile `20.796 von 12.076` -- abgelehnt statt erlaubt.

    Die Zahl, die hier faellt, ist nicht von Hand gesetzt: sie ist
    `floor(Pool / Margin)` aus dem Margin, das die erste gefuellte Position
    tatsaechlich bindet.
    """
    shared, brokers = twelve_on_one_pool()
    for broker in brokers:
        broker.submit(sized_entry(POOL))

    for index, broker in enumerate(brokers):
        fill_it(broker, EPOCH + index)

    opened = [b for b in brokers if b.position is not None]
    assert opened, "keine einzige Position -- dann prueft der Test nichts"
    margin = opened[0].position.margin  # type: ignore[union-attr]

    # Vorbedingung: zwoelf von diesen wuerden den Pool wirklich ueberziehen.
    assert ACCOUNTS * margin > POOL, (
        f"zwoelf mal {margin:,.2f} = {ACCOUNTS * margin:,.2f} muesste "
        f"{POOL:,.2f} uebersteigen, sonst ist dieser Test leer"
    )

    assert len(opened) == math.floor(POOL / margin)
    assert len(opened) < ACCOUNTS
    assert shared.reserved == pytest.approx(len(opened) * margin)
    assert shared.reserved <= POOL
    # Die abgelehnten sind gezaehlt und damit sichtbar.
    assert sum(b.rejected_entries for b in brokers) == ACCOUNTS - len(opened)


def test_twelve_median_stop_positions_do_fit() -> None:
    """Die obere Zeile der Tabelle: `9.496 von 12.076`, und die passt.

    Wichtig, weil eine Reservierung, die am Median schon ablehnt, den
    gemessenen Normalfall veraendern wuerde -- und damit die Vergleichbarkeit
    des Vorwaertslaufs mit allem Bisherigen.
    """
    shared, brokers = twelve_on_one_pool()
    for broker in brokers:
        broker.submit(sized_entry(POOL, MEDIAN_STOP))
    for index, broker in enumerate(brokers):
        fill_it(broker, EPOCH + index)

    assert all(b.position is not None for b in brokers)
    assert sum(b.rejected_entries for b in brokers) == 0
    assert shared.reserved < POOL


def test_a_closed_position_hands_its_margin_to_the_next_market() -> None:
    """Der Punkt der geteilten Kasse: freigewordenes Margin ist wieder da."""
    shared, brokers = twelve_on_one_pool()
    for broker in brokers:
        broker.submit(sized_entry(POOL))
    for index, broker in enumerate(brokers):
        fill_it(broker, EPOCH + index)

    blocked = [b for b in brokers if b.position is None]
    assert blocked, "niemand wurde abgelehnt -- dann prueft der Test nichts"

    committed = shared.reserved
    brokers[0].close_at(100.0, EPOCH + 10 * MINUTE)
    assert shared.reserved < committed, "das Margin wurde nicht freigegeben"

    waiting = blocked[0]
    assert waiting.submit(sized_entry(POOL)) is True
    fill_it(waiting, EPOCH + 20 * MINUTE)

    assert waiting.position is not None
    assert shared.reserved == pytest.approx(committed)


def test_submit_refuses_when_the_pool_is_already_committed() -> None:
    """Nicht erst beim Fuellen, sondern schon beim Annehmen der Order."""
    shared = _Ledger(equity=POOL, peak_equity=POOL)
    first = SimBroker(free_spec(), config(ACCOUNT), ledger=shared)
    second = SimBroker(free_spec(), config(ACCOUNT), ledger=shared)

    # Fast alles binden, ohne dafuer eine Position zu brauchen: die Kasse ist
    # das Pruefobjekt, nicht der Weg dorthin.
    shared.reserve(POOL - 10.0)

    assert second.submit(sized_entry(POOL)) is False
    assert second.rejected_entries == 1
    assert first.position is None


def test_available_never_goes_negative() -> None:
    """Eine Rechnung, die sich selbst erlaubt, was sie verboten hat."""
    shared = _Ledger(equity=1_000.0, peak_equity=1_000.0)
    shared.reserve(1_500.0)

    assert shared.available == 0.0

    shared.release(5_000.0)
    assert shared.reserved == 0.0


# --------------------------------------------------------------------------- #
# Der Neustart
# --------------------------------------------------------------------------- #


def test_a_restored_position_binds_its_margin_again() -> None:
    """Sonst ist der Defekt nach jedem Neustart zurueck.

    Zwoelf Positionen haengen wieder an der geteilten Kasse, `reserved` steht
    auf null, und die naechste Eroeffnung prueft gegen den vollen Pool. Ein
    Defekt, der sich bei jedem Neustart selbst wiederherstellt, ist schlimmer
    als einer, der bleibt -- er sieht repariert aus.
    """
    shared = _Ledger(equity=POOL, peak_equity=POOL)
    brokers = [
        SimBroker(free_spec(), config(ACCOUNT), ledger=shared) for _ in range(ACCOUNTS)
    ]

    # Ein Lauf, der die Positionen erzeugt hat, und sein Zustand auf der Platte.
    saved = []
    for index, broker in enumerate(brokers):
        broker.submit(sized_entry(POOL))
        fill_it(broker, EPOCH + index)
        if broker.position is not None:
            saved.append(broker.position)
    assert saved, "nichts gespeichert -- dann prueft der Test nichts"
    expected = shared.reserved

    # Neustart: frische Kasse, frische Broker, Positionen von der Platte.
    after = _Ledger(equity=POOL, peak_equity=POOL)
    fresh = [
        SimBroker(free_spec(), config(ACCOUNT), ledger=after) for _ in range(len(saved))
    ]
    for broker, position in zip(fresh, saved, strict=True):
        PaperState(
            symbol="SYMUSDT", equity=POOL, position=position
        ).restore_into(broker)

    assert after.reserved == pytest.approx(expected)
    assert after.available == pytest.approx(POOL - expected)
