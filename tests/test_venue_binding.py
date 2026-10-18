"""Eine Venue je Lauf, oder ein Abbruch — die Invariante als Objekt.

**Der Anlass.** `config/settings.yaml` sagt `exchange.name: binance`.
`execution/order.py:91` hat `venue_name: str = "bybit"` als Vorgabewert, und
`scripts/run_dashboard.py:144` sowie `scripts/run_live.py:230` bauen den
Executor OHNE `venue_name`. Gleichzeitig liest die Driftprüfung beim
Bestätigen (`api/app.py:813`) `services.prices`, das mit
`config.engine.exchange.name` gebaut wird. Ergebnis: Binance-Kerzen,
Binance-Driftprüfung, Bybit-Instrumentregeln, Bybit-Order.

Der Pfad ist heute schlafend -- das Dashboard läuft ohne `--execute`. Die
Bybit-Testnet-Schlüssel sind aber hinterlegt, also ist er einen Schalter
entfernt.

**Warum ein Objekt und keine Prüffunktion.** Eine Funktion muss aufgerufen
werden. Ein Wert, der nur kohärent konstruierbar ist, kann nicht vergessen
werden -- und genau das Vergessen ist hier passiert: `venue()` in
`data/venue.py` existiert, `ExecutionPolicy` prüft ihre Gebühren, und trotzdem
konnten fünf Entscheidungen auseinanderlaufen, weil niemand sie zusammen
betrachtet hat.

Die fünf, die übereinstimmen müssen:

    analysis_venue        woher die Kerzen kommen
    price_check_venue     woher der Preis für die Driftprüfung kommt
    instrument_spec_venue woher Tick, min_qty, MMR, max_leverage kommen
    fee_schedule_venue    welcher Gebührenplan gerechnet wird
    execution_venue       wohin die Order geht
"""

from __future__ import annotations

import pytest

from traidingbrain.execution.policy import policy_for
from traidingbrain.execution.venuebinding import (
    IncoherentVenueError,
    VenueBinding,
)


def _binance() -> VenueBinding:
    return VenueBinding(
        analysis_venue="binance",
        price_check_venue="binance",
        instrument_spec_venue="binance",
        execution_venue="binance",
        policy=policy_for("binance", "safety-first"),
        testnet=True,
    )


# --------------------------------------------------------------------------- #
# Der Fall, der heute im Code steht
# --------------------------------------------------------------------------- #


def test_binance_analyse_mit_bybit_ausfuehrung_bricht_ab() -> None:
    """Genau die Lage aus `run_dashboard.py:144` und `run_live.py:230`."""
    with pytest.raises(IncoherentVenueError) as exc:
        VenueBinding(
            analysis_venue="binance",
            price_check_venue="binance",
            instrument_spec_venue="bybit",
            execution_venue="bybit",
            policy=policy_for("bybit", "safety-first"),
            testnet=True,
        )
    text = str(exc.value)
    assert "binance" in text and "bybit" in text
    assert "instrument_spec_venue" in text
    assert "execution_venue" in text


@pytest.mark.parametrize(
    "feld",
    [
        "analysis_venue",
        "price_check_venue",
        "instrument_spec_venue",
        "execution_venue",
    ],
)
def test_jedes_einzelne_abweichende_feld_bricht_ab(feld: str) -> None:
    """Keine der fünf Stellen darf allein abweichen.

    Einzeln geprüft, weil ein Schutz, der nur das Paar
    (Analyse, Ausführung) vergleicht, die anderen drei durchlässt -- und die
    Instrumentregeln waren genau das Loch.
    """
    felder: dict[str, object] = {
        "analysis_venue": "binance",
        "price_check_venue": "binance",
        "instrument_spec_venue": "binance",
        "execution_venue": "binance",
        "policy": policy_for("binance", "safety-first"),
        "testnet": True,
    }
    felder[feld] = "bybit"
    with pytest.raises(IncoherentVenueError, match=feld):
        VenueBinding(**felder)  # type: ignore[arg-type]


def test_eine_policy_einer_anderen_venue_bricht_ab() -> None:
    """Der Gebührenplan ist die fünfte Stelle -- und die unauffälligste.

    `DEFAULT_SPEC` trägt Bybit-Gebühren und wurde auf Binance-Kerzen
    gerechnet, über 7.335 Trades. Niemandem ist es aufgefallen, weil keine
    Zeile Code die beiden je verglichen hat.
    """
    with pytest.raises(IncoherentVenueError, match="policy"):
        VenueBinding(
            analysis_venue="binance",
            price_check_venue="binance",
            instrument_spec_venue="binance",
            execution_venue="binance",
            policy=policy_for("bybit", "safety-first"),
            testnet=True,
        )


# --------------------------------------------------------------------------- #
# Was durchgehen muss
# --------------------------------------------------------------------------- #


def test_eine_kohaerente_bindung_wird_angenommen() -> None:
    b = _binance()
    assert b.venue == "binance"
    assert b.policy.venue == "binance"


def test_die_bindung_nennt_ihre_venue_genau_einmal() -> None:
    """`venue` ist abgeleitet, nicht ein sechstes Feld.

    Ein sechstes Feld waere eine sechste Stelle, die auseinanderlaufen kann.
    """
    b = _binance()
    assert b.venue == b.analysis_venue == b.execution_venue
    assert not hasattr(b, "_venue")


def test_bybit_ist_genauso_kohaerent_konstruierbar() -> None:
    b = VenueBinding(
        analysis_venue="bybit",
        price_check_venue="bybit",
        instrument_spec_venue="bybit",
        execution_venue="bybit",
        policy=policy_for("bybit", "maker-target"),
        testnet=True,
    )
    assert b.venue == "bybit"


# --------------------------------------------------------------------------- #
# Identität: der Lauf muss die Bindung tragen
# --------------------------------------------------------------------------- #


def test_der_fingerprint_unterscheidet_venues_und_policies() -> None:
    """Zwei Läufe auf verschiedenen Venues sind verschiedene Läufe.

    In der Legacy-Signatur stand die Venue NICHT. Darum ist nicht
    entscheidbar, ob die 7.335 Trades unter Bybit- oder Binance-Regeln
    entstanden -- die Antwort steht nur in einem Kommentar.
    """
    a = _binance().fingerprint()
    b = VenueBinding(
        analysis_venue="bybit",
        price_check_venue="bybit",
        instrument_spec_venue="bybit",
        execution_venue="bybit",
        policy=policy_for("bybit", "safety-first"),
        testnet=True,
    ).fingerprint()
    assert a != b
    assert "binance" in a and "bybit" in b

    # Dieselbe Venue, andere Policy -> anderer Fingerprint.
    c = VenueBinding(
        analysis_venue="binance",
        price_check_venue="binance",
        instrument_spec_venue="binance",
        execution_venue="binance",
        policy=policy_for("binance", "maker-target"),
        testnet=True,
    ).fingerprint()
    assert c != a

    # Und derselbe Lauf zweimal -> derselbe Fingerprint.
    assert _binance().fingerprint() == a


def test_testnet_und_mainnet_sind_verschiedene_laeufe() -> None:
    """Ein Testnet-Ergebnis darf nicht als Mainnet-Ergebnis gelesen werden."""
    t = _binance().fingerprint()
    m = VenueBinding(
        analysis_venue="binance",
        price_check_venue="binance",
        instrument_spec_venue="binance",
        execution_venue="binance",
        policy=policy_for("binance", "safety-first"),
        testnet=False,
    ).fingerprint()
    assert t != m
    assert "testnet" in t
    assert "mainnet" in m


# --------------------------------------------------------------------------- #
# Unbekannte Venues
# --------------------------------------------------------------------------- #


def test_eine_unbekannte_venue_bricht_ab() -> None:
    """Auch wenn alle fünf Felder übereinstimmen.

    Kohärent und unbekannt ist kein zulässiger Zustand: es gibt dann keine
    Gebührentabelle und keine Instrumentregeln.
    """
    with pytest.raises(IncoherentVenueError, match="kraken"):
        VenueBinding(
            analysis_venue="kraken",
            price_check_venue="kraken",
            instrument_spec_venue="kraken",
            execution_venue="kraken",
            policy=policy_for("bybit", "safety-first"),
            testnet=True,
        )
