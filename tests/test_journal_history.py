"""Welche Historie eine Risikobremse lesen darf, und welche nicht.

**Warum das eigene Tests braucht.** Drei der sechs Sicherungen lesen
`AccountState.recent_trades`, und bis zum 12.10.2026 übergab jede Stelle,
die einen `AccountState` baute, dort `[]`. `journal/history.py` ist der
Produzent, der gefehlt hat — und seine wichtigste Eigenschaft ist nicht das
Umwandeln, sondern das **Weglassen**.

Gemessen über die 25 geschlossenen Live-Trades:

    gelesene Historie            Konten mit Verlustserie >= 2
    alle 25 Zeilen               AVAXUSDT, BTCUSDT
    nur laufende Signatur (7)    keine

Die 25 Zeilen sind drei Konfigurationsepochen plus einen Trade aus einer
zerstörten Kontogeneration. Eine Bremse, die das zusammenzählt, zählt eine
Verlustserie, die so nie stattgefunden hat — und löst dann aus, oder löst
nicht aus, auf Grundlage von Zeilen, die nicht zum laufenden System gehören.
Die Tests hier halten genau das fest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from traidingbrain.domain.enums import STATE_OF_EXIT, ExitReason, Side, TradeState
from traidingbrain.journal.history import (
    account_trades,
    as_closed_trade,
    closed_trades,
    konto_schluessel,
)
from traidingbrain.journal.record import JournalEntry, PostMortem, Source, TradeReason
from traidingbrain.journal.store import JournalStore

SIG = "1000.0|['A', 'B']|0.08|M15|refused-v1"
OTHER = "1000.0|['A', 'B', 'C']|0.15|H1|refused-v1"
HOUR = 3_600_000


def reason(**overrides: object) -> TradeReason:
    base: dict[str, object] = {
        "setup_key": "A",
        "setup_name": "Momentum-Breakout",
        "setup_source": "V08",
        "setup_timeframe": "H1",
        "side": "long",
        "entry": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "reward_risk": 2.0,
        "stop_distance_pct": 2.0,
        "rating": 71,
        "rating_band": "gemischt",
        "clarity": 0.4,
        "agreement": 0.8,
        "consensus": 0.7,
        "coverage": 0.7,
        "score_bullish": 1.2,
        "score_bearish": 0.3,
        "score_direction": "aufwärts",
        "conflict": 0.4,
        "breadth": 6,
        "readings": 190,
        "regime": "trend_up",
        "signal_timeframe": "M15",
    }
    base.update(overrides)
    return TradeReason(**base, families=[])  # type: ignore[arg-type]


def entry(trade_id: str = "live-BTCUSDT-1000", **overrides: object) -> JournalEntry:
    base: dict[str, object] = {
        "trade_id": trade_id,
        "source": Source.LIVE,
        "symbol": "BTCUSDT",
        "strategy": "guide-all",
        "opened_ts": 0,
        "closed_ts": 5 * HOUR,
        "exit_reason": ExitReason.STOP,
        "entry_price": 100.0,
        "exit_price": 98.0,
        "qty": 1.0,
        "leverage": 5.0,
        "risk_amount": 100.0,
        "gross_pnl": -100.0,
        "fees": 1.0,
        "funding": 0.0,
        "net_pnl": -101.0,
        "r_multiple": -1.01,
        "reason": reason(),
        "post_mortem": PostMortem(5, 0.0, 1.0, 0.0, False, True, "Sofort gegen uns."),
        "run_signature": SIG,
    }
    base.update(overrides)
    return JournalEntry(**base)  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: Path) -> JournalStore:
    return JournalStore(tmp_path / "journal.sqlite")


# --------------------------------------------------------------------------- #
# Der Filter ist der Zweck
# --------------------------------------------------------------------------- #


def test_only_rows_of_the_asked_signature_come_back(store: JournalStore) -> None:
    store.record([
        entry("live-BTCUSDT-1", run_signature=SIG),
        entry("live-BTCUSDT-2", run_signature=OTHER),
        entry("live-BTCUSDT-3", run_signature=SIG),
    ])
    got = closed_trades(store, signature=SIG)

    assert [t.proposal_id for t in got] == ["live-BTCUSDT-1", "live-BTCUSDT-3"]


def test_a_row_without_a_signature_is_dropped(store: JournalStore) -> None:
    """Das ist der Waisen-Fall, und er ist der Grund fuer dieses Modul.

    `live-BTCUSDT-1790928000000` traegt keine Signatur, hat die zehnfache
    Groesse des naechsten BTC-Trades und 4,98 % Risiko gegen einen Deckel von
    3 %. Rueckwirkend eine Signatur zu erfinden waere schlimmer als ihn
    weglassen.
    """
    store.record([
        entry("live-BTCUSDT-alt", run_signature=""),
        entry("live-BTCUSDT-neu", run_signature=SIG),
    ])
    got = closed_trades(store, signature=SIG)

    assert [t.proposal_id for t in got] == ["live-BTCUSDT-neu"]


def test_an_empty_signature_reads_nothing(store: JournalStore) -> None:
    """"Ich kenne meine Konfiguration nicht" ist kein Grund, alles zu lesen."""
    store.record([entry("live-BTCUSDT-1", run_signature=SIG)])

    assert closed_trades(store, signature="") == []


def test_the_symbol_filter_separates_the_accounts(store: JournalStore) -> None:
    store.record([
        entry("live-BTCUSDT-1", symbol="BTCUSDT"),
        entry("live-ETHUSDT-1", symbol="ETHUSDT"),
    ])

    assert len(closed_trades(store, signature=SIG)) == 2
    assert [t.symbol for t in closed_trades(store, signature=SIG, symbol="ETHUSDT")] == ["ETHUSDT"]


def test_replay_rows_do_not_leak_into_the_live_history(store: JournalStore) -> None:
    """Sonst zaehlt eine Bremse 7.335 Replay-Trades als Verlustserie."""
    store.record([
        entry("live-BTCUSDT-1", source=Source.LIVE),
        entry("BTCUSDT-9", source=Source.REPLAY),
    ])

    assert [t.proposal_id for t in closed_trades(store, signature=SIG)] == ["live-BTCUSDT-1"]


# --------------------------------------------------------------------------- #
# Die Umwandlung
# --------------------------------------------------------------------------- #


def test_the_fields_a_breaker_reads_survive_unchanged() -> None:
    """`net_pnl` und `closed_ts` sind die beiden, die die Bremsen anfassen."""
    trade = as_closed_trade(entry(net_pnl=-42.5, closed_ts=7 * HOUR))

    assert trade is not None
    assert trade.net_pnl == pytest.approx(-42.5)
    assert trade.closed_ts == 7 * HOUR
    assert trade.side is Side.LONG
    assert trade.state is TradeState.CLOSED_STOP


def test_a_short_keeps_its_side() -> None:
    trade = as_closed_trade(entry(reason=reason(side="short")))

    assert trade is not None
    assert trade.side is Side.SHORT


def test_a_rounded_negative_zero_fee_still_validates() -> None:
    """`ClosedTrade.fees` ist `ge=0`, und eine gerundete Null kommt als -0.0."""
    trade = as_closed_trade(entry(fees=-0.0))

    assert trade is not None
    assert trade.fees == 0.0


@pytest.mark.parametrize("field", ["entry_price", "exit_price", "qty"])
def test_a_degenerate_row_is_dropped_rather_than_forced(field: str) -> None:
    """Lieber eine Zeile weniger als eine Bremse, die auf Platzhaltern zaehlt."""
    assert as_closed_trade(entry(**{field: 0.0})) is None


def test_every_exit_reason_has_a_state() -> None:
    """Ohne das faellt ein neuer Ausstiegsgrund STILL aus der Historie.

    `as_closed_trade` benutzt `STATE_OF_EXIT.get(...)` und gibt `None` zurueck,
    wenn ein Grund fehlt -- also wuerden Trades mit einem neuen Grund einfach
    verschwinden, statt einen Fehler zu machen. Dieser Test ist die Bremse
    dagegen.
    """
    missing = [r for r in ExitReason if r not in STATE_OF_EXIT]

    assert not missing, f"ohne Endzustand und damit unsichtbar: {missing}"
    for reason_value, state in STATE_OF_EXIT.items():
        trade = as_closed_trade(entry(exit_reason=reason_value))
        assert trade is not None, reason_value
        assert trade.state is state


# --------------------------------------------------------------------------- #
# Ein Konto vergisst seine Verluste nicht, wenn man den Hebel verstellt
# --------------------------------------------------------------------------- #

KONTO_ALT = "1000.0|['A', 'B']|0.08|M15|refused-v1|plan30x7"
KONTO_NEU = "1000.0|['A', 'B']|0.08|M15|refused-v1|plan30x7r15f"
KONTO_ANDERS = "1000.0|['A', 'B']|0.08|M15|refused-v1|demo30x7"
KONFIG_ANDERS = "1000.0|['A', 'B', 'C']|0.08|M15|refused-v1|plan30x7"


def test_eine_neue_groessenregel_loescht_die_verlusthistorie_nicht(
    store: JournalStore,
) -> None:
    """Der stille Defekt vom 20.10.2026, mechanisch ausgeschlossen.

    Der Haendler filterte ueber die VOLLE Signatur. Als der Risikodeckel den
    Zusatz von `plan30x7` auf `plan30x7r15` schob, sah die Tagesbremse null
    Trades statt elf -- ein Druck auf "Apply" im Terminal setzte sie zurueck,
    in genau dem Moment, in dem sie etwas verhindern soll.

    Gemessen, bevor dies behoben wurde:

        Zusatz          Trades  heute USD  mit den scharfen Grenzen
        plan30x7            11     -99.00  blockiert, 21.9 h Abkuehlung
        plan30x7r15          0       0.00  ERLAUBT
    """
    store.record([
        entry("live-BTCUSDT-1", run_signature=KONTO_ALT),
        entry("live-BTCUSDT-2", run_signature=KONTO_ALT),
        entry("live-BTCUSDT-3", run_signature=KONTO_NEU),
    ])
    # Die Forschungssicht bleibt epochengetrennt -- das ist ihr Zweck.
    assert len(closed_trades(store, signature=KONTO_NEU)) == 1
    # Die Kontosicht sieht das ganze Konto, ueber beide Groessenregeln.
    assert len(account_trades(store, signature=KONTO_NEU)) == 3
    assert len(account_trades(store, signature=KONTO_ALT)) == 3


def test_die_kontosicht_poolt_nicht_ueber_konten_oder_konfigurationen(
    store: JournalStore,
) -> None:
    """Der Fehler vom 12.10.2026 darf durch die Behebung nicht zurueckkommen.

    Damals zaehlte die Bremse drei Konfigurationsepochen zusammen und fand
    Verlustserien, die so nie stattgefunden haben. Gepoolt wird AUSSCHLIESSLICH
    die Groessenregel desselben Kontos -- nicht das Konto, nicht die
    Setup-Auswahl, nicht das Kostentor.
    """
    store.record([
        entry("live-BTCUSDT-1", run_signature=KONTO_ALT),
        entry("live-BTCUSDT-2", run_signature=KONTO_ANDERS),
        entry("live-BTCUSDT-3", run_signature=KONFIG_ANDERS),
    ])
    assert len(account_trades(store, signature=KONTO_ALT)) == 1
    assert konto_schluessel(KONTO_ALT) == konto_schluessel(KONTO_NEU)
    assert konto_schluessel(KONTO_ALT) != konto_schluessel(KONTO_ANDERS)
    assert konto_schluessel(KONTO_ALT) != konto_schluessel(KONFIG_ANDERS)


def test_eine_signatur_ohne_kontozusatz_bleibt_fuer_sich(store: JournalStore) -> None:
    """Das Standardkonto traegt keinen Zusatz -- sein Schluessel ist leer.

    Ohne diesen Fall wuerde jede zusatzlose Signatur mit jeder anderen
    zusatzlosen gepoolt, auch wenn ihre Konfiguration verschieden ist. Der
    Praefix traegt das, und der bleibt scharf.
    """
    assert konto_schluessel(SIG) != konto_schluessel(OTHER)
    store.record([
        entry("live-BTCUSDT-1", run_signature=SIG),
        entry("live-BTCUSDT-2", run_signature=OTHER),
    ])
    assert len(account_trades(store, signature=SIG)) == 1


def test_ein_konfigurationsfeld_ist_kein_kontoname(store: JournalStore) -> None:
    """Die erste Fassung des Schluessels war zu locker, an echten Daten geprueft.

    Sie nahm den fuehrenden Buchstabenteil des letzten Feldes. Im Live-Journal
    las sie damit aus `...|refused-v1` das "Konto" `refused` und aus
    `...|portfolio|cap5` das Konto `cap` -- beides Konfigurationsfelder des
    Hauptkontos. Heute harmlos, weil jede dieser Signaturen fuer sich steht;
    ein spaeteres `cap12` waere aber mit `cap5` in einen Topf gefallen, und
    das ist der Fehler vom 12.10.2026 auf dem Rueckweg.

    Ein Kontozusatz hat die Form, die `signatur_zusatz()` erzeugt:
    Name, Marginanteil, "x", Hebel. Alles andere ist kein Konto.
    """
    kopf = "1000.0|['A', 'B']|0.08|M15|refused-v1|portfolio"
    assert konto_schluessel(f"{kopf}|cap5") != konto_schluessel(f"{kopf}|cap12")
    assert konto_schluessel(f"{kopf}|cap5") == konto_schluessel(f"{kopf}|cap5")
    # Ohne Zusatz ist der Schluessel die ganze Signatur -- es gibt keine
    # zweite Groessenregel, die man zusammenfassen koennte.
    assert konto_schluessel(f"{kopf}|cap5")[1] == ""
    assert konto_schluessel("1000.0|['A']|0.08|M15|refused-v1")[1] == ""
    # Und die echte Form wird weiterhin erkannt.
    assert konto_schluessel(f"{kopf}|plan30x7r15f")[1] == "plan"
    assert konto_schluessel(f"{kopf}|demo50x10")[1] == "demo"

    store.record([
        entry("live-BTCUSDT-1", run_signature=f"{kopf}|cap5"),
        entry("live-BTCUSDT-2", run_signature=f"{kopf}|cap12"),
    ])
    assert len(account_trades(store, signature=f"{kopf}|cap5")) == 1
