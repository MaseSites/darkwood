"""Die Experimentidentität muss vollständig sein, und zwar beweisbar.

**Der historische Anlass.** `execution/venuebinding.py:274` sagt es selbst: *„In
der Legacy-Signatur stand die Venue NICHT. Darum ist aus den Daten nicht
entscheidbar, ob die 7.335 Trades unter Bybit- oder Binance-Regeln entstanden --
die Antwort steht nur in einem Kommentar."* Ein fehlendes Identitätsfeld ist
unsichtbar: die Zeilen sehen identisch aus, und die Zahlen mitteln sich glatt.

Darum prüft dieser Test nicht, *dass* ein Stempel existiert, sondern die eine
Eigenschaft, aus der er seinen Wert zieht: **jedes einzelne Feld bewegt ihn.**
Feldweise, aus `dataclasses.fields` gelesen und nicht aus einer Liste von Hand
-- eine Liste wäre am Tag ihres Schreibens vollständig und danach nie wieder,
und genau diese Lücke soll der Test schliessen.

Am 18.10.2026 gemessen und hier festgehalten: der Gebührenplan gehört dazu.
Dieselben 7.335 Fills unter Bybits und unter Binances Takersatz unterscheiden
sich reliabel um +0.0014 R je Trade.
"""

from __future__ import annotations

import dataclasses

import pytest

from traidingbrain.config.settings import load_config
from traidingbrain.execution.policy import policy_for
from traidingbrain.execution.venuebinding import Environment, VenueBinding
from traidingbrain.journal.identity import (
    _LEER_ERLAUBT,
    ExperimentIdentity,
    IncompleteIdentityError,
    identity_for,
    strategy_version_of,
)
from traidingbrain.journal.version import decision_version, run_signature
from traidingbrain.strategies.guide import GuidePool

#: Eine Identität, die den **Istzustand vom 18.10.2026** beschreibt, samt
#: seinem Widerspruch: Analyse liest Bybit (hartkodiert in
#: `analysis/context.py`), alles andere Binance.
ISTZUSTAND = ExperimentIdentity(
    analysis_venue="bybit",
    data_venue="binance",
    price_venue="binance",
    price_environment="mainnet",
    instrument_spec_venue="bybit",
    execution_venue=None,
    execution_environment=None,
    policy="binance:limit-taker:limit_taker_allowed:Limit:0.0002/0.0005:0bps:unproven",
    fee_schedule="binance-usdm-standard-2026-10-18",
    fill_model="pessimistic-intrabar-m1",
    slippage_model="limit-entry-no-slip",
    funding_source="data/funding parquet",
    data_version="coverage:0f1e2d3c4b5a",
    strategy_version="guide-all|A:V08,B:V06,E:V11,F:V12,G:V13",
    decision_version="fdba080e487f",
    portfolio="pooled-1000usdt-cap5",
    # Der Istzustand mischt zwei Boersen, also traegt er den Grund dafuer.
    incoherence_reason=(
        "DEFAULT_SPEC traegt Bybits Instrumentregeln, die Kerzen kommen von "
        "Binance -- so ist die eingefrorene Population entstanden"
    ),
    run_signature="1000.0|['A', 'B', 'E', 'F', 'G']|0.08|M15|refused-v1|portfolio|cap5",
)

#: Ein Ersatzwert je Feldtyp, der garantiert vom Istzustand abweicht.
#: Die Felder, bei denen leer eine Aussage ist -- aus dem Modul gelesen,
#: damit der Test nicht eine zweite Vorstellung davon pflegt.
LEER_ERLAUBT = _LEER_ERLAUBT

#: Ein Ersatzwert je Feldtyp, der garantiert vom Istzustand abweicht.
ANDERS: dict[str, object] = {
    "execution_venue": "bybit",
    "execution_environment": "testnet",
}


def _abweichend(feld: dataclasses.Field[object]) -> object:
    return ANDERS.get(feld.name, "ANDERS-" + feld.name)


# --------------------------------------------------------------------------- #
# Die tragende Eigenschaft: jedes Feld bewegt den Stempel
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "feldname", [f.name for f in dataclasses.fields(ExperimentIdentity)]
)
def test_jedes_feld_bewegt_den_stempel(feldname: str) -> None:
    """Ein Feld, das den Stempel nicht bewegt, ist nicht im Stempel.

    Die Feldliste kommt aus `dataclasses.fields`, also wächst dieser Test
    automatisch mit. Ein später hinzugefügtes Feld, das nicht in `canonical()`
    landet, lässt diesen Test fallen -- und nicht erst eine Messung in einem
    halben Jahr.
    """
    feld = next(f for f in dataclasses.fields(ExperimentIdentity) if f.name == feldname)
    anders = dataclasses.replace(ISTZUSTAND, **{feldname: _abweichend(feld)})

    assert anders.stamp() != ISTZUSTAND.stamp(), (
        f"{feldname} aendert den Stempel nicht -- das Feld ist aufgezeichnet, "
        f"aber nicht gestempelt, und zwei verschiedene Laeufe bekommen "
        f"denselben Schluessel"
    )


def test_der_stempel_ist_ueber_prozesse_stabil() -> None:
    """Dieselbe Identität, zweimal gebaut, derselbe Stempel.

    `hashlib` und nicht Pythons `hash()` -- der ist je Prozess gesalzen, und
    ein Stempel, der sich beim Neustart ändert, trennt eine Stichprobe von
    sich selbst.
    """
    zwilling = ExperimentIdentity.from_dict(ISTZUSTAND.to_dict())
    assert zwilling.stamp() == ISTZUSTAND.stamp()
    assert zwilling == ISTZUSTAND


def test_zwei_getauschte_felder_sind_nicht_dasselbe() -> None:
    """Der kanonische Text trägt Feldnamen, nicht nur Werte.

    Ohne die Namen hätten `analysis_venue=a, data_venue=b` und
    `analysis_venue=b, data_venue=a` dieselbe Zeichenkette -- und genau dieser
    Tausch ist der Fehler, um den es hier geht.
    """
    getauscht = dataclasses.replace(
        ISTZUSTAND,
        analysis_venue=ISTZUSTAND.data_venue,
        data_venue=ISTZUSTAND.analysis_venue,
    )
    assert getauscht.stamp() != ISTZUSTAND.stamp()


def test_ein_wert_mit_trennzeichen_wird_abgelehnt() -> None:
    """Die Behauptung „das Trennzeichen kommt in keinem Wert vor", geprüft.

    Sie stand zuerst nur im Kommentar. Ein Nullbyte in einem Wert kann eine
    Feldgrenze vortäuschen, also wird er abgelehnt, statt gehofft, dass niemand
    einen schreibt.
    """
    with pytest.raises(IncompleteIdentityError, match="Trennzeichen"):
        dataclasses.replace(ISTZUSTAND, data_venue="binance\x00price_venue=x")


# --------------------------------------------------------------------------- #
# Fail-closed: eine Lücke ist kein Zustand
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "feldname",
    [
        f.name
        for f in dataclasses.fields(ExperimentIdentity)
        if f.name not in LEER_ERLAUBT
    ],
)
def test_ein_leeres_feld_wird_abgelehnt(feldname: str) -> None:
    """Leer ist nicht „unbekannt" -- leer mittelt sich mit jedem anderen Leeren."""
    with pytest.raises(IncompleteIdentityError, match=feldname):
        dataclasses.replace(ISTZUSTAND, **{feldname: "   "})


@pytest.mark.parametrize(
    "feldname",
    [
        f.name
        for f in dataclasses.fields(ExperimentIdentity)
        if f.name not in LEER_ERLAUBT
    ],
)
def test_ein_none_feld_wird_abgelehnt(feldname: str) -> None:
    with pytest.raises(IncompleteIdentityError, match=feldname):
        dataclasses.replace(ISTZUSTAND, **{feldname: None})


def test_kein_ausfuehrungspfad_ist_ein_erlaubter_zustand() -> None:
    """Die beiden Ausnahmen, und sie sind eine Aussage.

    „Kein Ausführungspfad" ist der heutige Zustand -- `--execute` blockt, weil
    alle Kerzen von Binance kommen und nur Bybit ausführbar ist. Das ist ein
    echter Zustand und keine fehlende Angabe.
    """
    assert ISTZUSTAND.execution_venue is None
    assert not ISTZUSTAND.executes
    assert ISTZUSTAND.stamp()


# --------------------------------------------------------------------------- #
# Serialisierung in beide Richtungen streng
# --------------------------------------------------------------------------- #


def test_ein_unbekanntes_feld_wird_abgelehnt() -> None:
    """Stillschweigend verwerfen heisst, es aus dem Stempel zu entfernen."""
    blob = {**ISTZUSTAND.to_dict(), "neues_feld": "x"}
    with pytest.raises(IncompleteIdentityError, match="neues_feld"):
        ExperimentIdentity.from_dict(blob)


def test_ein_fehlendes_feld_wird_abgelehnt() -> None:
    blob = ISTZUSTAND.to_dict()
    del blob["fee_schedule"]
    with pytest.raises(IncompleteIdentityError, match="fee_schedule"):
        ExperimentIdentity.from_dict(blob)


def test_to_dict_deckt_jedes_feld_ab() -> None:
    """Sonst wäre die Aufzeichnung schmaler als der Stempel."""
    assert set(ISTZUSTAND.to_dict()) == {
        f.name for f in dataclasses.fields(ExperimentIdentity)
    }


# --------------------------------------------------------------------------- #
# Der Widerspruch ist abfragbar
# --------------------------------------------------------------------------- #


def test_der_venue_widerspruch_ist_abfragbar() -> None:
    """Der Istzustand vom 18.10.2026, als Zusicherung statt als Auditnotiz.

    Analyse liest `bybit` (hartkodiert), die Daten kommen von `binance`. Sollte
    dieser Test eines Tages fallen, ist der Widerspruch behoben -- und dann
    gehört die Identität in `ISTZUSTAND` nachgezogen, nicht der Test gelöscht.
    """
    assert not ISTZUSTAND.venues_agree()


def test_eine_stimmige_identitaet_meldet_das_auch() -> None:
    einig = dataclasses.replace(
        ISTZUSTAND, analysis_venue="binance", instrument_spec_venue="binance"
    )
    assert einig.venues_agree()


# --------------------------------------------------------------------------- #
# Gegen die echten Objekte, nicht gegen eine handgefuellte Aufzeichnung
# --------------------------------------------------------------------------- #


def test_die_identitaet_laesst_sich_aus_dem_echten_system_bauen() -> None:
    """Die eine Probe, die eine Fixture nicht ersetzt.

    Sechs gruene Tests gegen eine selbstgebaute Aufzeichnung und ein
    abgestuerzter Papierhaendler -- dieser Fehler ist in diesem Projekt schon
    einmal passiert. Darum baut dieser Test die Identitaet aus der echten
    Konfiguration, der echten Bindung und dem echten Setup-Pool.
    """
    config = load_config()
    binding = VenueBinding.research(
        data_venue=config.engine.exchange.name,
        price_venue=config.engine.exchange.name,
        price_environment=Environment.MAINNET,
        instrument_spec_venue=config.engine.exchange.name,
        policy=policy_for(config.engine.exchange.name, "safety-first"),
    )
    pool = GuidePool.for_config(config)

    identity = identity_for(
        config,
        binding,
        pool,
        data_version="coverage:probe",
        funding_source="data/funding",
        analysis_venue="bybit",
    )

    # Vollstaendig: `__post_init__` haette sonst abgebrochen.
    assert identity.stamp()
    assert len(identity.stamp()) == 12
    # Und der alte Schluessel zeigt auf dieselbe Zeile.
    assert identity.run_signature == run_signature(config)
    assert identity.decision_version == decision_version()
    # Die Strategiefassung traegt die Setup-Fassungen, nicht nur die Schluessel.
    assert "V" in identity.strategy_version
    for setup in pool.setups:
        assert f"{setup.key}:{setup.source}" in identity.strategy_version


def test_eine_geaenderte_setupfassung_bewegt_die_strategieversion() -> None:
    """Der Grund, warum die Fassungen im Feld stehen.

    `run_signature` traegt die Liste der aktiven Schluessel (`['A','B',...]`),
    nicht ihre Fassung. Zwei Laeufe mit derselben Liste und einer neu
    geschriebenen Regel hatten bisher dieselbe Signatur.
    """
    config = load_config()
    echt = GuidePool.for_config(config)
    assert strategy_version_of(echt) != strategy_version_of(
        dataclasses.replace(echt, setups=echt.setups[:-1])
    )


def test_der_gebuehrenplan_der_policy_landet_im_feld() -> None:
    """Der Befund vom 18.10.2026, als Zusicherung.

    Die richtige Gebuehrentabelle EXISTIERT im Code -- `policy_for("binance",
    ...)` nennt 0.050 % Taker. Nur liest der Replay-Pfad sie nicht, sondern
    `DEFAULT_SPEC` mit Bybits 0.055 %. Die Identitaet traegt darum, welche
    Tabelle wirklich gegolten hat.
    """
    binance = policy_for("binance", "safety-first")
    bybit = policy_for("bybit", "safety-first")
    assert binance.fee_provenance != bybit.fee_provenance
    assert "0.050" in binance.fee_provenance
    assert "0.055" in bybit.fee_provenance


def test_der_grund_fuer_inkohaerenz_landet_in_der_identitaet() -> None:
    """Das Loch, das beim Durchlesen auffiel.

    Die Identitaet traegt `policy.fingerprint()`, nicht
    `binding.fingerprint()`. Der Grund, den `legacy_incoherent` verlangt, waere
    also in der Bindung geblieben und beim Serialisieren verschwunden -- genau
    der Fehler, den diese Phase behandelt: eine Angabe, die es gibt und die
    nicht in den Daten landet.
    """
    config = load_config()
    grund = "DEFAULT_SPEC ist Bybit, die Kerzen sind Binance"
    binding = VenueBinding.legacy_incoherent(
        data_venue="binance",
        price_venue="binance",
        price_environment=Environment.MAINNET,
        instrument_spec_venue="bybit",
        policy=policy_for("bybit", "maker-target"),
        reason=grund,
    )
    identity = identity_for(
        config,
        binding,
        GuidePool.for_config(config),
        data_version="coverage:probe",
        funding_source="data/funding",
        analysis_venue="bybit",
    )

    assert identity.incoherence_reason == grund
    assert identity.to_dict()["incoherence_reason"] == grund
    assert not identity.venues_agree()


def test_ein_kohaerenter_lauf_traegt_einen_leeren_grund() -> None:
    """Leer ist hier eine Aussage: dieser Lauf mischt nichts."""
    config = load_config()
    binding = VenueBinding.research(
        data_venue="binance",
        price_venue="binance",
        price_environment=Environment.MAINNET,
        instrument_spec_venue="binance",
        policy=policy_for("binance", "safety-first"),
    )
    identity = identity_for(
        config,
        binding,
        GuidePool.for_config(config),
        data_version="coverage:probe",
        funding_source="data/funding",
        analysis_venue="binance",
    )

    assert identity.incoherence_reason == ""
    assert identity.venues_agree()
    assert identity.stamp()
