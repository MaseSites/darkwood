"""Eine Venue je Lauf, getrennte Umgebungen, und Bybit als einzige Ausführung.

**Was Master-Direktive 03 Phase 2 verlangt und warum.** Gleiche Venue heisst
nicht gleiche Umgebung. Ein Bybit-Mainnet-Preischeck mit
Bybit-Testnet-Ausführung ist eine **absichtliche, erlaubte** Kombination: die
Preisprobe soll gegen den echten Markt laufen, die Order gegen das Testnet.
Eine Binance-Preisquelle mit Bybit-Ausführung ist dagegen verboten — das ist
die Lage, die heute im Code steht (`run_dashboard.py:144` baut den Executor
ohne `venue_name`, also Bybit, während `:171` die Preisquelle aus der
Konfiguration baut, also Binance).

**Und eine Folge, die unbequem ist:** alle Kerzen dieses Projekts sind
Binance. Bybit ist die einzige ausführbare Venue. Beides zusammen heisst, dass
mit den heutigen Daten **keine ausführbare Bindung konstruierbar** ist. Das
ist kein Fehler dieser Tests, sondern der Zweck — die Lücke blockt die
Ausführung, statt sie falsch zu bepreisen.

`testnet=secrets.bybit.testnet` an eine Binance-Preisquelle zu übergeben
(`run_dashboard.py:173`) hat dazu noch eine zweite Folge: mit `testnet=true`
und `venue=binance` ruft `venue.build` `enable_demo_trading` und leitet auf
`demo-dapi.binance.com`. Die Driftprüfung verglich dann gegen Demo-Preise.
`run_live.py:96` setzt für dieselbe Quelle ausdrücklich `testnet=False` mit
der Begründung „Prices come from mainnet" — die beiden Runner widersprachen
sich bei derselben Entscheidung.
"""

from __future__ import annotations

import dataclasses

import pytest

from traidingbrain.execution.policy import policy_for
from traidingbrain.execution.venuebinding import (
    EXECUTABLE_VENUES,
    Environment,
    IncoherentVenueError,
    MainnetNotApprovedError,
    VenueBinding,
)


def _forschung(venue: str = "bybit", **kwargs: object) -> VenueBinding:
    basis: dict[str, object] = {
        "data_venue": venue,
        "price_venue": venue,
        "price_environment": Environment.MAINNET,
        "instrument_spec_venue": venue,
        "policy": policy_for(venue, "safety-first"),
    }
    basis.update(kwargs)
    return VenueBinding.research(**basis)  # type: ignore[arg-type]


def _ausfuehrbar(**kwargs: object) -> VenueBinding:
    basis: dict[str, object] = {
        "data_venue": "bybit",
        "price_venue": "bybit",
        "price_environment": Environment.MAINNET,
        "instrument_spec_venue": "bybit",
        "execution_venue": "bybit",
        "execution_environment": Environment.TESTNET,
        "policy": policy_for("bybit", "safety-first"),
    }
    basis.update(kwargs)
    return VenueBinding.executable(**basis)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Die erlaubte Kombination: Mainnet-Preis, Testnet-Ausführung
# --------------------------------------------------------------------------- #


def test_mainnet_preis_mit_testnet_ausfuehrung_ist_erlaubt() -> None:
    b = _ausfuehrbar()
    assert b.price_environment is Environment.MAINNET
    assert b.execution_environment is Environment.TESTNET
    assert b.venue == "bybit"
    assert b.executes


def test_die_umgebungen_stehen_im_fingerprint() -> None:
    """Ein Testnet-Ergebnis darf nicht als Mainnet-Ergebnis gelesen werden."""
    a = _ausfuehrbar().fingerprint()
    b = _ausfuehrbar(price_environment=Environment.TESTNET).fingerprint()
    assert a != b
    assert "price=bybit/mainnet" in a
    assert "exec=bybit/testnet" in a


def test_gleiche_bindung_gleicher_fingerprint() -> None:
    assert _ausfuehrbar().fingerprint() == _ausfuehrbar().fingerprint()


# --------------------------------------------------------------------------- #
# Bybit ist die einzige ausführbare Venue
# --------------------------------------------------------------------------- #


def test_nur_bybit_ist_ausfuehrbar() -> None:
    assert frozenset({"bybit"}) == EXECUTABLE_VENUES


def test_binance_ausfuehrung_wird_hart_abgelehnt() -> None:
    """Und zwar nicht, weil Binance schlechter wäre.

    Es gibt nur `BybitCredentials` (`config/settings.py:461-470`), eingebunden
    als `Secrets.bybit`. Ein Binance-Executor hätte keinen Zugangsdatenpfad.
    Einen spekulativ zu bauen ist von der Direktive ausdrücklich untersagt.
    """
    with pytest.raises(IncoherentVenueError, match="binance"):
        VenueBinding.executable(
            data_venue="binance",
            price_venue="binance",
            price_environment=Environment.MAINNET,
            instrument_spec_venue="binance",
            execution_venue="binance",
            execution_environment=Environment.TESTNET,
            policy=policy_for("binance", "safety-first"),
        )


def test_binance_darf_forschen() -> None:
    """Die Ablehnung betrifft die Ausführung, nicht die Analyse."""
    b = _forschung("binance")
    assert b.venue == "binance"
    assert not b.executes
    assert b.execution_venue is None


# --------------------------------------------------------------------------- #
# Die heutige Lage: Binance-Daten, Bybit-Ausführung -- verboten
# --------------------------------------------------------------------------- #


def test_binance_daten_mit_bybit_ausfuehrung_bricht_ab() -> None:
    """Genau `run_dashboard.py:144` gegen `:171`.

    Und damit ist mit den heutigen Daten -- alle Kerzen Binance -- keine
    ausführbare Bindung konstruierbar. Das ist der Zweck.
    """
    with pytest.raises(IncoherentVenueError) as exc:
        VenueBinding.executable(
            data_venue="binance",
            price_venue="binance",
            price_environment=Environment.MAINNET,
            instrument_spec_venue="bybit",
            execution_venue="bybit",
            execution_environment=Environment.TESTNET,
            policy=policy_for("bybit", "safety-first"),
        )
    text = str(exc.value)
    assert "binance" in text and "bybit" in text
    assert "data_venue" in text


@pytest.mark.parametrize(
    "feld",
    ["data_venue", "price_venue", "instrument_spec_venue", "execution_venue"],
)
def test_jedes_einzelne_abweichende_venue_feld_bricht_ab(feld: str) -> None:
    with pytest.raises(IncoherentVenueError, match=feld):
        _ausfuehrbar(**{feld: "binance"})


def test_eine_policy_einer_anderen_venue_bricht_ab() -> None:
    with pytest.raises(IncoherentVenueError, match="policy"):
        _ausfuehrbar(policy=policy_for("binance", "safety-first"))


# --------------------------------------------------------------------------- #
# Mainnet-Ausführung braucht eine ausdrückliche Freigabe
# --------------------------------------------------------------------------- #


def test_mainnet_ausfuehrung_ohne_freigabe_bricht_ab() -> None:
    """Zwei unabhängige Signale, wie bei `order.py:98`.

    Dort verlangt `UnsafeConfigurationError` schon `testnet=False` UND
    `allow_live=True`, weil "ein einziger Konfigurationswert, versehentlich
    umgestellt, nicht genügen darf". Dieselbe Begründung gilt hier.
    """
    with pytest.raises(MainnetNotApprovedError):
        _ausfuehrbar(execution_environment=Environment.MAINNET)


def test_mainnet_ausfuehrung_mit_freigabe_ist_konstruierbar() -> None:
    b = _ausfuehrbar(
        execution_environment=Environment.MAINNET, mainnet_approved=True
    )
    assert b.execution_environment is Environment.MAINNET
    assert "exec=bybit/mainnet" in b.fingerprint()


def test_eine_freigabe_ohne_mainnet_ist_harmlos_aber_sichtbar() -> None:
    """Die Freigabe allein tut nichts -- sie steht aber im Fingerprint.

    Sonst wären zwei Läufe mit und ohne erteilte Freigabe nicht zu
    unterscheiden.
    """
    ohne = _ausfuehrbar()
    mit = _ausfuehrbar(mainnet_approved=True)
    assert mit.execution_environment is Environment.TESTNET
    assert ohne.fingerprint() != mit.fingerprint()


# --------------------------------------------------------------------------- #
# Forschung braucht keine Ausführungsangaben
# --------------------------------------------------------------------------- #


def test_forschung_ohne_ausfuehrung_ist_konstruierbar() -> None:
    """Replays und der Papierhandel führen nichts aus.

    Sie zu zwingen, eine ausführbare Venue zu benennen, die sie nicht
    benutzen, wäre Zeremonie -- und würde Binance-Forschung unmöglich machen.
    """
    b = _forschung("binance")
    assert not b.executes
    assert b.execution_environment is None
    assert "exec=keine" in b.fingerprint()


def test_forschung_prueft_die_venues_trotzdem() -> None:
    with pytest.raises(IncoherentVenueError, match="price_venue"):
        _forschung("binance", price_venue="bybit")


def test_eine_unbekannte_venue_bricht_ab() -> None:
    with pytest.raises(IncoherentVenueError, match="kraken"):
        VenueBinding.research(
            data_venue="kraken",
            price_venue="kraken",
            price_environment=Environment.MAINNET,
            instrument_spec_venue="kraken",
            policy=policy_for("bybit", "safety-first"),
        )


# --------------------------------------------------------------------------- #
# Die Preisumgebung darf nicht aus der Ausführungsumgebung geraten werden
# --------------------------------------------------------------------------- #


def test_preisumgebung_ist_eine_eigene_angabe() -> None:
    """`run_dashboard.py:173` übergab `secrets.bybit.testnet` an die Preisquelle.

    Das koppelte die Preisumgebung an die Ausführungsumgebung einer ANDEREN
    Börse. Hier sind es zwei Felder, und beide müssen genannt werden.
    """
    testnet_preis = _ausfuehrbar(price_environment=Environment.TESTNET)
    assert testnet_preis.price_environment is Environment.TESTNET
    assert testnet_preis.execution_environment is Environment.TESTNET

    mainnet_preis = _ausfuehrbar(price_environment=Environment.MAINNET)
    assert mainnet_preis.price_environment is Environment.MAINNET
    assert mainnet_preis.fingerprint() != testnet_preis.fingerprint()


# --------------------------------------------------------------------------- #
# Aus der ersten Fassung uebernommen
# --------------------------------------------------------------------------- #


def test_die_bindung_nennt_ihre_venue_genau_einmal() -> None:
    """`venue` ist abgeleitet, nicht gespeichert.

    Ein eigenes Feld waere eine weitere Stelle, die von den anderen abweichen
    kann -- und die Abweichung zwischen Stellen ist genau das Problem, das
    dieses Objekt loest.
    """
    b = _ausfuehrbar()
    assert b.venue == b.data_venue == b.price_venue == b.execution_venue
    assert "venue" not in {f.name for f in dataclasses.fields(b)}


def test_eine_umgebung_ohne_boerse_ist_keine_angabe() -> None:
    """Die Gegenrichtung der Forschungs-Bindung."""
    with pytest.raises(IncoherentVenueError, match="execution_environment"):
        VenueBinding(
            data_venue="bybit",
            price_venue="bybit",
            price_environment=Environment.MAINNET,
            instrument_spec_venue="bybit",
            policy=policy_for("bybit", "safety-first"),
            execution_venue=None,
            execution_environment=Environment.TESTNET,
            mainnet_approved=False,
        )


def test_eine_boerse_ohne_umgebung_wird_nicht_geraten() -> None:
    with pytest.raises(IncoherentVenueError, match="execution_environment"):
        VenueBinding(
            data_venue="bybit",
            price_venue="bybit",
            price_environment=Environment.MAINNET,
            instrument_spec_venue="bybit",
            policy=policy_for("bybit", "safety-first"),
            execution_venue="bybit",
            execution_environment=None,
            mainnet_approved=False,
        )
