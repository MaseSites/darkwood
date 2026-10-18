"""Die benannte Ausnahme vom Kohärenztor -- und warum sie keine Aufweichung ist.

**Der Anlass ist gemessen, nicht gedacht.** Am 18.10.2026 sollte
`scripts/replay_all_markets.py` seine Identität aufschreiben, und
`VenueBinding.research()` hat den Lauf abgewiesen:

    IncoherentVenueError: Ein Lauf, 4 Boersen-Entscheidungen, aber 2
    verschiedene Boersen: ['binance', 'bybit']. data_venue='binance',
    price_venue='binance', instrument_spec_venue='bybit', policy='binance'.

Das Tor hatte recht. Der Replay liest Binance-Kerzen und baut seine
Instrumentregeln aus `DEFAULT_SPEC`, dessen Zahlen Bybits sind. Phase 2 hat
dieses Tor gebaut, ohne diesen Fall zu kennen -- und es hat ihn gefunden.

**Und die eingefrorene Population ist genau so entstanden.** Sie muss
reproduzierbar bleiben, also braucht ein Lauf, der sie nachrechnet, einen Weg,
inkohärent zu sein. Dass dieser Weg keine Aufweichung ist, hängt an drei
Eigenschaften, und jede hat hier einen Test:

1. Er heisst anders, also trifft ihn niemand versehentlich.
2. Er verlangt einen Grund als **Text**. Ein `allow=True` wird kopiert; ein
   Feld, das man füllen muss, wird gelesen.
3. Er kann **nicht ausführen** -- und das ist die eigentliche Sicherung. Ein
   Lauf, der nicht weiss, welche Instrumentregeln gelten, darf messen und
   niemals senden.
"""

from __future__ import annotations

import dataclasses

import pytest

from traidingbrain.execution.policy import policy_for
from traidingbrain.execution.venuebinding import (
    Environment,
    IncoherentVenueError,
    VenueBinding,
)

BINANCE = policy_for("binance", "safety-first")
BYBIT = policy_for("bybit", "safety-first")

#: Genau der Zustand, den der Replay am 18.10.2026 hatte.
LEGACY_GRUND = (
    "DEFAULT_SPEC traegt Bybits Instrumentregeln, die Kerzen kommen von "
    "Binance -- so ist die eingefrorene Population von 7.335 Fills entstanden"
)


def _legacy(**ueberschreiben: object) -> VenueBinding:
    felder: dict[str, object] = {
        "data_venue": "binance",
        "price_venue": "binance",
        "price_environment": Environment.MAINNET,
        "instrument_spec_venue": "bybit",
        "policy": BINANCE,
        "reason": LEGACY_GRUND,
    }
    felder.update(ueberschreiben)
    return VenueBinding.legacy_incoherent(**felder)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. Das Tor bleibt scharf
# --------------------------------------------------------------------------- #


def test_research_weist_den_legacy_zustand_weiter_ab() -> None:
    """Der Fall, der heute Abend aufgetreten ist, bleibt ein Abbruch.

    Das ist der wichtigste Test dieser Datei: die Ausnahme darf den Normalweg
    nicht verändern.
    """
    with pytest.raises(IncoherentVenueError) as fehler:
        VenueBinding.research(
            data_venue="binance",
            price_venue="binance",
            price_environment=Environment.MAINNET,
            instrument_spec_venue="bybit",
            policy=BINANCE,
        )
    # Und die Meldung nennt den Ausweg, damit niemand das Tor aufweicht, weil
    # er ihn nicht findet.
    assert "legacy_incoherent" in str(fehler.value)


def test_die_meldung_nennt_die_betroffenen_felder() -> None:
    with pytest.raises(IncoherentVenueError, match="instrument_spec_venue"):
        VenueBinding.research(
            data_venue="binance",
            price_venue="binance",
            price_environment=Environment.MAINNET,
            instrument_spec_venue="bybit",
            policy=BINANCE,
        )


# --------------------------------------------------------------------------- #
# 2. Der Grund ist Pflicht
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("grund", ["", "   ", "\t"])
def test_ohne_grund_gibt_es_keine_ausnahme(grund: str) -> None:
    with pytest.raises(IncoherentVenueError, match="ohne Grund"):
        _legacy(reason=grund)


def test_der_grund_steht_im_fingerprint() -> None:
    """Sonst wären ein kohärenter und ein inkohärenter Lauf dieselbe Zeile."""
    inkohaerent = _legacy()
    kohaerent = VenueBinding.research(
        data_venue="binance",
        price_venue="binance",
        price_environment=Environment.MAINNET,
        instrument_spec_venue="binance",
        policy=BINANCE,
    )
    assert "incoherent=" in inkohaerent.fingerprint()
    assert "incoherent=" not in kohaerent.fingerprint()
    assert inkohaerent.fingerprint() != kohaerent.fingerprint()


def test_zwei_verschiedene_gruende_sind_zwei_verschiedene_laeufe() -> None:
    a = _legacy()
    b = _legacy(reason="ein anderer Grund, der auch aufgeschrieben wurde")
    assert a.fingerprint() != b.fingerprint()


# --------------------------------------------------------------------------- #
# 3. Die eigentliche Sicherung: messen ja, senden nie
# --------------------------------------------------------------------------- #


def test_ein_inkohaerenter_lauf_fuehrt_nicht_aus() -> None:
    """`execution_venue` ist kein Parameter dieses Konstruktors.

    Es gibt also keinen Aufruf, der das ändert -- die Sicherung steckt in der
    Signatur und nicht in einer Prüfung, die jemand vergessen kann.
    """
    binding = _legacy()
    assert binding.execution_venue is None
    assert binding.execution_environment is None
    assert not binding.executes
    assert not binding.mainnet_approved


def test_auch_am_konstruktor_vorbei_bleibt_senden_verboten() -> None:
    """Die Prüfung sitzt zusätzlich im `__post_init__`.

    Weil der Konstruktor umgangen werden kann -- `dataclasses.replace` tut es
    -- und eine Sicherung, die nur in einer Signatur steht, ist keine.
    """
    binding = _legacy()
    with pytest.raises(IncoherentVenueError, match="darf nicht ausfuehren"):
        dataclasses.replace(
            binding,
            execution_venue="bybit",
            execution_environment=Environment.TESTNET,
        )


# --------------------------------------------------------------------------- #
# 4. Streng, wo Strenge nichts kostet
# --------------------------------------------------------------------------- #


def test_ein_kohaerenter_lauf_darf_diesen_weg_nicht_nehmen() -> None:
    """Sonst wanderte ein gegenstandsloser Grund in jeden Fingerprint."""
    with pytest.raises(IncoherentVenueError, match="KOHAERENTEN"):
        _legacy(instrument_spec_venue="binance")


def test_eine_unbekannte_boerse_bleibt_auch_mit_grund_verboten() -> None:
    """Inkohärent ist eine Ausnahme, unbekannt ist keine.

    Eine unbekannte Venue hat weder Gebührentabelle noch Instrumentregeln --
    daran ändert ein Grund nichts.
    """
    with pytest.raises(IncoherentVenueError, match="nicht unterstuetzt"):
        _legacy(instrument_spec_venue="irgendeinedex")


def test_der_legacy_zustand_laesst_sich_damit_aufschreiben() -> None:
    """Die Gegenprobe: der Fall von heute Abend geht jetzt durch -- benannt."""
    binding = _legacy()
    assert binding.data_venue == "binance"
    assert binding.instrument_spec_venue == "bybit"
    assert binding.incoherence_reason == LEGACY_GRUND
    assert "7.335" in binding.incoherence_reason
