"""Ein Fill ohne Entscheidung ist verboten -- und das muss ein Abbruch sein.

**Die vier Negativfälle sind keine Erfindung, sondern Protokoll.**

* *Waise.* 17.10.2026: ein lebender Trade in BTCUSDT gehörte zu keinem Konto,
  dem Kontobuch fehlten 55,05 USDT, und die Waise hat die Vorwärtsstichprobe
  auf drei Wegen verunreinigt. Sie lief in jeder Auswertung mit und war in
  keiner erklärbar.
* *Widersprüchliche Signatur.* 11.10.2026: 78 Fills behaupteten einen anderen
  Lauf als ihre Entscheidung. Der Fall ist still -- beide Zeilen sind einzeln
  plausibel.
* *Doppelte Entscheidung mit anderem Inhalt.* Kann durch die Konstruktion nicht
  passieren, solange die ID abgeleitet wird. Der Test steht da, damit der Tag,
  an dem jemand eine ID übergibt, ein roter Test ist und keine Messung.
* *Nicht-deterministisches Replay.* Dieselbe Entscheidung zweimal muss denselben
  Schlüssel liefern, über Prozessgrenzen hinweg. Sonst wäre ein Replay nicht
  als Replay erkennbar, und `hash()` -- je Prozess gesalzen -- hätte genau das
  gebrochen.

**Und ein Fall, der ausdrücklich KEIN Fehler ist:** eine Entscheidung ohne Fill.
In ADAUSDT wurden 3.703 von 4.446 Absichten von Risikoregeln abgelehnt. Die
Ablehnungen sind selbst eine Messung; sie als Defekt zu behandeln hiesse, sie zu
verlieren.
"""

from __future__ import annotations

import dataclasses

import pytest

from traidingbrain.journal.provenance import (
    ContradictoryDecisionError,
    ContradictorySignatureError,
    DecisionRecord,
    FillProvenance,
    OrphanFillError,
    ProvenanceLedger,
)

STAMP = "fdba080e487f"

ENTSCHEIDUNG = DecisionRecord(
    identity_stamp=STAMP,
    symbol="BTCUSDT",
    decided_ts=1_667_419_200_000,
    side="short",
    entry=20_240.0,
    stop=20_695.2067,
    target=19_330.0,
    setup_key="B",
    setup_source="V06",
    signal_timeframe="H4",
)


def _fill(**ueberschreiben: object) -> FillProvenance:
    felder: dict[str, object] = {
        "decision_id": ENTSCHEIDUNG.decision_id,
        "identity_stamp": STAMP,
        "venue": "binance",
        "policy": "binance:safety-first",
        "liquidity_role_modelled": "maker",
        "liquidity_role_actual": None,
        "fee_rate": 0.0002,
        "fee_rate_actual": None,
        "fee_paid": 0.0890559,
        "reference_price": 20_240.0,
        "fill_price_modelled": 20_240.0,
        "fill_price_actual": None,
        "execution_id": None,
        "order_id": None,
    }
    felder.update(ueberschreiben)
    return FillProvenance(**felder)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. Der Schlüssel kommt aus dem Inhalt
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "feldname", [f.name for f in dataclasses.fields(DecisionRecord)]
)
def test_jedes_feld_bewegt_die_decision_id(feldname: str) -> None:
    """Ein Feld, das den Schlüssel nicht bewegt, trennt zwei Entscheidungen nicht.

    Feldliste aus `dataclasses.fields`, also wächst der Test mit.
    """
    feld = next(f for f in dataclasses.fields(DecisionRecord) if f.name == feldname)
    typ = feld.type
    anders: object
    if feldname == "decided_ts":
        anders = ENTSCHEIDUNG.decided_ts + 1
    elif typ is float or isinstance(getattr(ENTSCHEIDUNG, feldname), float):
        anders = getattr(ENTSCHEIDUNG, feldname) + 1.0
    else:
        anders = "ANDERS"

    neu = dataclasses.replace(ENTSCHEIDUNG, **{feldname: anders})
    assert neu.decision_id != ENTSCHEIDUNG.decision_id, (
        f"{feldname} aendert die decision_id nicht -- zwei verschiedene "
        f"Entscheidungen bekommen denselben Schluessel, und ein Fill kann an "
        f"der falschen haengen"
    )


def test_dasselbe_replay_liefert_denselben_schluessel() -> None:
    """Ein Replay muss als Replay erkennbar sein.

    `hashlib` und nicht `hash()`: der ist je Prozess gesalzen, und dann waere
    derselbe Replay in jedem Lauf eine andere Entscheidung.
    """
    zwilling = DecisionRecord(
        identity_stamp=STAMP,
        symbol="BTCUSDT",
        decided_ts=1_667_419_200_000,
        side="short",
        entry=20_240.0,
        stop=20_695.2067,
        target=19_330.0,
        setup_key="B",
        setup_source="V06",
        signal_timeframe="H4",
    )
    assert zwilling.decision_id == ENTSCHEIDUNG.decision_id
    assert len(ENTSCHEIDUNG.decision_id) == 16


def test_zwei_preise_die_sich_erst_spaet_unterscheiden() -> None:
    """Der Grund für `float.hex()` statt Dezimaltext.

    `f"{x:.8f}"` bildet diese beiden Preise auf dieselbe Zeichenkette ab, und
    dann hätten zwei verschiedene Entscheidungen denselben Schlüssel.
    """
    a = dataclasses.replace(ENTSCHEIDUNG, entry=20_240.000000001)
    b = dataclasses.replace(ENTSCHEIDUNG, entry=20_240.000000002)
    assert f"{a.entry:.8f}" == f"{b.entry:.8f}"
    assert a.decision_id != b.decision_id


def test_ein_gestempelter_lauf_gehoert_in_den_schluessel() -> None:
    """Dieselbe Marktlage unter zwei Gebührenplänen ist nicht dieselbe Entscheidung.

    Sonst zeigten die Fills zweier Läufe auf eine Entscheidung -- genau die
    Verunreinigung, die diese Datei verhindern soll.
    """
    anderer_lauf = dataclasses.replace(ENTSCHEIDUNG, identity_stamp="a3ae652a0162")
    assert anderer_lauf.decision_id != ENTSCHEIDUNG.decision_id


# --------------------------------------------------------------------------- #
# 2. Die vier Negativfälle
# --------------------------------------------------------------------------- #


def test_eine_waise_wird_abgewiesen() -> None:
    """Der Fall vom 17.10.2026."""
    ledger = ProvenanceLedger()
    with pytest.raises(OrphanFillError, match="verboten"):
        ledger.record(_fill(decision_id="0" * 16))


def test_eine_leere_decision_id_ist_schon_am_feld_verboten() -> None:
    """Fail-closed eine Stufe früher: so eine Zeile soll nicht entstehen."""
    with pytest.raises(OrphanFillError, match="Waise"):
        _fill(decision_id="")


def test_eine_widerspruechliche_signatur_wird_abgewiesen() -> None:
    """Der Fall vom 11.10.2026, 78-mal."""
    ledger = ProvenanceLedger()
    ledger.register(ENTSCHEIDUNG)
    with pytest.raises(ContradictorySignatureError, match="zwei Laeufe"):
        ledger.record(_fill(identity_stamp="a3ae652a0162"))


def test_zwei_inhalte_unter_einem_schluessel_werden_abgewiesen() -> None:
    """Konstruktiv unmöglich -- und darum geprüft.

    Die ID wird abgeleitet, also kann dieser Fall nur eintreten, wenn jemand
    sie übergibt oder der Hash kollidiert. Dann soll ein Test fallen und nicht
    eine Messung schweigen.
    """
    ledger = ProvenanceLedger()
    fremd = dataclasses.replace(ENTSCHEIDUNG, target=19_000.0)
    assert fremd.decision_id != ENTSCHEIDUNG.decision_id

    # Was ein ÜBERGEBENER Schlüssel täte, direkt nachgestellt: fremder Inhalt
    # unter dem Schlüssel der echten Entscheidung. Am privaten Feld vorbei,
    # weil `register` genau das verhindert -- und das ist der Punkt des Tests.
    ledger._decisions[ENTSCHEIDUNG.decision_id] = fremd

    with pytest.raises(ContradictoryDecisionError, match="zwei verschiedene"):
        ledger.register(ENTSCHEIDUNG)


def test_ein_replay_darf_dieselbe_entscheidung_zweimal_anmelden() -> None:
    """Idempotent, und das ist die Eigenschaft, die den Inhaltshash wertvoll macht."""
    ledger = ProvenanceLedger()
    a = ledger.register(ENTSCHEIDUNG)
    b = ledger.register(ENTSCHEIDUNG)
    assert a == b
    assert len(ledger.decisions) == 1


# --------------------------------------------------------------------------- #
# 3. Der Fall, der ausdrücklich kein Fehler ist
# --------------------------------------------------------------------------- #


def test_eine_entscheidung_ohne_fill_ist_der_normalfall() -> None:
    """3.703 von 4.446 Absichten in ADAUSDT wurden abgelehnt.

    Die Ablehnungen sind selbst eine Messung. Sie als Defekt zu behandeln
    hiesse, sie zu verlieren.
    """
    ledger = ProvenanceLedger()
    ledger.register(ENTSCHEIDUNG)
    assert len(ledger.unfilled()) == 1
    assert ledger.orphans() == ()


def test_ein_gueltiger_fill_geht_durch() -> None:
    """Die Gegenprobe -- das Tor darf nicht alles aussperren."""
    ledger = ProvenanceLedger()
    ledger.register(ENTSCHEIDUNG)
    ledger.record(_fill())
    assert len(ledger.fills) == 1
    assert ledger.decision_of(ledger.fills[0]) == ENTSCHEIDUNG
    assert ledger.unfilled() == ()


# --------------------------------------------------------------------------- #
# 4. Modelliert neben tatsächlich -- der Unterschied IST die Messung
# --------------------------------------------------------------------------- #


def test_ohne_echten_fillpreis_ist_der_schlupf_nicht_null_sondern_unbekannt() -> None:
    """`None` und nicht `0.0`.

    Eine Null würde behaupten, es sei gemessen worden und habe nichts ergeben.
    Genau diese Verwechslung hat am 16.10.2026 einen doppelt gezählten Schlupf
    verursacht.
    """
    assert _fill().slippage is None
    assert _fill(fill_price_actual=20_241.5).slippage == pytest.approx(1.5)


def test_ohne_echte_rolle_ist_die_makerannahme_unbewiesen() -> None:
    """Solange dieses Feld leer ist, gehoert `maker_role_proven = False`.

    Das Feld zu fuellen ist die einzige Art, die Annahme zu beweisen -- und
    zwei Drittel der Legacy-Fills haengen an ihr.
    """
    assert _fill().role_was_as_modelled is None
    assert _fill(liquidity_role_actual="maker").role_was_as_modelled is True
    assert _fill(liquidity_role_actual="taker").role_was_as_modelled is False


def test_eine_erfundene_liquidity_role_wird_abgewiesen() -> None:
    with pytest.raises(ValueError, match="keine Liquidity Role"):
        _fill(liquidity_role_modelled="irgendwas")
    with pytest.raises(ValueError, match="keine Liquidity Role"):
        _fill(liquidity_role_actual="irgendwas")


@pytest.mark.parametrize(
    "feldname", ["identity_stamp", "venue", "policy", "liquidity_role_modelled"]
)
def test_ein_leeres_pflichtfeld_wird_abgewiesen(feldname: str) -> None:
    with pytest.raises(ValueError, match=feldname):
        _fill(**{feldname: "  "})


def test_alle_dreizehn_angaben_der_direktive_sind_felder() -> None:
    """Die Liste aus dem Auftrag, gegen die Aufzeichnung geprüft.

    Namentlich, damit eine spätere Umbenennung auffällt statt durchzurutschen.
    """
    felder = {f.name for f in dataclasses.fields(FillProvenance)}
    for gefordert in (
        "decision_id",
        "venue",
        "policy",
        "liquidity_role_modelled",
        "liquidity_role_actual",
        "fee_rate",
        "fee_paid",
        "reference_price",
        "fill_price_modelled",
        "fill_price_actual",
        "execution_id",
        "order_id",
    ):
        assert gefordert in felder, f"{gefordert} fehlt in FillProvenance"
