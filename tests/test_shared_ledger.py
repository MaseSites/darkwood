"""Eine geteilte Kasse: wofür sie da ist, und was ohne sie passiert.

**Die Frage, aus der das kam.** Der Papierhandel führt zwölf Broker mit je
1.000 USDT. Dadurch bemisst sich jede Position an einem Zwölftel des
Kapitals — 1 % Risiko je Trade sind 0,083 % des Ganzen. Das ist keine
Risikoentscheidung, das fällt aus der Struktur.

**Und die Grösse einfach zu verzwölffachen genügt nicht.** Gemessen über die
26 bereinigten Vorwärtstrades am 13.10.2026:

    Variante                                  Risiko/Trade   abgelehnt
    1 % je Einzelkonto (heute)                  10,06 USDT    0 von 26
    1 % vom Gesamten, zwoelf getrennte Kassen  120,76 USDT    6 von 26
    1 % vom Gesamten, geteilte Kasse           120,76 USDT    0 von 26

Die mittlere Zeile ist der Grund für diese Datei. Das Margin eines
1.006-USDT-Kontos trägt die Position nicht — im schlimmsten Fall braucht sie
1.733 USDT — und `submit` lehnt ab. Abgelehnt würden ausgerechnet die Trades
mit den **engsten Stops**, also die Population, die nach eigener Messung die
besseren Bruttozahlen hat. Eine Auswahl, die aus einer Verrohrungsgrenze
kommt und nicht aus einer Entscheidung, ist schlimmer als keine Umstellung.

Die Tests hier halten beide Hälften fest: dass die geteilte Kasse trägt, und
dass die getrennte an genau dieser Stelle scheitert.
"""

from __future__ import annotations

import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH
from traidingbrain.config.settings import SimulationConfig
from traidingbrain.domain.enums import OrderType, Side
from traidingbrain.sim.broker import PendingEntry, SimBroker, _Ledger

MINUTE = 60_000

#: Die gemessenen Groessen des echten Falls, gerundet.
ACCOUNT = 1_006.0
POOL = 12_075.0
#: Der engste Stop der 26 Vorwaertstrades: 0,6968 % des Einstiegs.
TIGHT_STOP = 0.006968


def config(equity: float) -> SimulationConfig:
    return SimulationConfig.model_validate({
        "initial_equity": equity,
        "slippage_bps": 0.0,
        "fill_on_touch": True,
        "entry_expiry_bars": 8,
        "pessimistic_intrabar": True,
    })


def portfolio_sized_entry(capital: float) -> PendingEntry:
    """Eine Order, die 1 % von `capital` riskiert, beim engsten gemessenen Stop."""
    entry_price = 100.0
    stop = entry_price * (1 - TIGHT_STOP)
    qty = capital * 0.01 / (entry_price - stop)
    return PendingEntry(
        side=Side.LONG,
        order_type=OrderType.LIMIT,
        limit_price=entry_price,
        stop=stop,
        target=entry_price * 1.03,
        qty=qty,
        leverage=10.0,
        created_ts=EPOCH,
        expires_ts=EPOCH + 100 * MINUTE,
        risk_amount=capital * 0.01,
    )


# --------------------------------------------------------------------------- #
# Was ohne geteilte Kasse passiert
# --------------------------------------------------------------------------- #


def test_a_portfolio_sized_order_does_not_fit_one_account() -> None:
    """Die mittlere Zeile der Tabelle, als Test.

    Das ist der Grund, warum "einfach eine Null mehr" nicht geht: die Order
    waere gross genug, dass ihr Margin das Einzelkonto uebersteigt, und
    `submit` lehnt ab -- ohne zu sagen, dass die Grenze das Kassenbuch war
    und nicht das Risiko.
    """
    broker = SimBroker(make_symbol_spec(taker_fee=0.0, maker_fee=0.0), config(ACCOUNT))
    order = portfolio_sized_entry(POOL)

    assert order.qty * order.limit_price / order.leverage > ACCOUNT, (
        "die Pruefgroesse selbst muss das Konto uebersteigen, sonst prueft der "
        "Test nichts"
    )
    assert broker.submit(order) is False
    assert broker.rejected_entries == 1


def test_the_same_order_fits_the_shared_ledger() -> None:
    """Und die untere Zeile: mit geteilter Kasse traegt dasselbe Margin."""
    shared = _Ledger(equity=POOL, peak_equity=POOL)
    broker = SimBroker(
        make_symbol_spec(taker_fee=0.0, maker_fee=0.0), config(ACCOUNT), ledger=shared
    )

    assert broker.submit(portfolio_sized_entry(POOL)) is True
    assert broker.rejected_entries == 0


# --------------------------------------------------------------------------- #
# Die geteilte Kasse ist wirklich geteilt
# --------------------------------------------------------------------------- #


def test_twelve_brokers_see_one_balance() -> None:
    shared = _Ledger(equity=POOL, peak_equity=POOL)
    brokers = [
        SimBroker(make_symbol_spec(), config(ACCOUNT), ledger=shared) for _ in range(12)
    ]

    assert all(b.equity == pytest.approx(POOL) for b in brokers)
    shared.equity -= 500.0
    assert all(b.equity == pytest.approx(POOL - 500.0) for b in brokers)


def test_a_loss_on_one_symbol_shrinks_what_the_others_may_risk() -> None:
    """Der Punkt der Zusammenlegung, und sein Preis.

    Ein Verlust auf einem Markt verkleinert die Kasse aller. Das ist genau
    das Verhalten eines echten Boersenkontos mit mehreren Maerkten -- und es
    ist der Unterschied zu zwoelf getrennten Konten, bei denen ein Markt den
    anderen nie beruehrt.
    """
    shared = _Ledger(equity=POOL, peak_equity=POOL)
    first, second = (
        SimBroker(make_symbol_spec(taker_fee=0.0, maker_fee=0.0), config(ACCOUNT),
                  ledger=shared)
        for _ in range(2)
    )
    before = second.equity
    shared.equity -= 1_000.0

    assert first.equity == pytest.approx(before - 1_000.0)
    assert second.equity == pytest.approx(before - 1_000.0)


def test_an_own_ledger_stays_private() -> None:
    """Ohne das Argument aendert sich nichts -- und das ist der Vorgabefall."""
    first = SimBroker(make_symbol_spec(), config(ACCOUNT))
    second = SimBroker(make_symbol_spec(), config(ACCOUNT))

    first.ledger.equity -= 500.0

    assert first.equity == pytest.approx(ACCOUNT - 500.0)
    assert second.equity == pytest.approx(ACCOUNT)
    assert first.owns_ledger and second.owns_ledger


def test_a_shared_ledger_is_marked_as_not_owned() -> None:
    """Woran der Wiederherstellungspfad es erkennt.

    `paperstate.restore_into` setzt die Kontostaende beim Neustart. Bei
    geteilter Kasse wuerden das zwoelf Broker hintereinander tun, und bei
    einem Absturz mitten im Zyklus mit zwoelf VERSCHIEDENEN Zahlen -- der
    letzte gewinnt, still. Dieses Flag ist, was das verhindert.
    """
    shared = _Ledger(equity=POOL, peak_equity=POOL)
    broker = SimBroker(make_symbol_spec(), config(ACCOUNT), ledger=shared)

    assert broker.owns_ledger is False
