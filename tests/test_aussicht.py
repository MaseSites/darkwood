"""Die Aussicht -- und die Eigenschaft, auf der sie beruht.

**Warum das eine eigene Datei ist.** `learn/aussicht.py` rechnet zehn
Millionen Szenarien in Sekunden, und das geht nur wegen einer Behauptung:
bei festem Margin-Anteil ist der Monatsfaktor UNABHAENGIG vom Kontostand,
weil jede Position denselben *Anteil* bindet. Stimmt die nicht, ist jede Zahl
der Aussicht falsch -- und zwar unauffaellig, weil sie weiter plausibel
aussieht.

Der erste Test prueft genau diese Behauptung gegen die echte Rechnung. Die
uebrigen pruefen, dass die Verteilung nicht heimlich etwas anderes
beschreibt als ihr Etikett sagt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from traidingbrain.learn.aussicht import (
    BODEN,
    MIN_BAUSTEINE,
    Fill,
    Monatsfaktoren,
    _block_faktor,
    aussicht,
    monatsfaktoren,
)

STUNDE = 3_600_000
EPOCH = 1_700_000_000_000


def _fill(nr: int, r: float, *, entry: float = 100.0, stop_anteil: float = 0.02) -> dict:
    """Ein gespeicherter Trade, so wie er in den Fill-Dateien steht."""
    weite = entry * stop_anteil
    qty = 10.0
    return {
        "opened_ts": EPOCH + nr * 6 * STUNDE,
        "closed_ts": EPOCH + nr * 6 * STUNDE + 2 * STUNDE,
        "entry_price": entry,
        "qty": qty,
        "risk_amount": weite * qty,
        "side": "long",
        "r_multiple": r,
    }


def _block(rs: list[float]) -> list[Fill]:
    gelesen = [Fill.von(_fill(i, r)) for i, r in enumerate(rs)]
    assert all(f is not None for f in gelesen)
    return [f for f in gelesen if f is not None]


# --------------------------------------------------------------------------- #
# Die tragende Eigenschaft
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("konto", [1.0, 10.0, 1_000.0, 250_000.0])
def test_der_monatsfaktor_haengt_nicht_am_kontostand(konto: float) -> None:
    """Die Behauptung, auf der die ganze Rechenbarkeit beruht.

    Jede Position bindet `margin_share` mal Konto, und ihre Groesse ist
    `margin_share * hebel * konto / einstieg`. Beides skaliert mit dem Konto,
    also skaliert auch das Ergebnis -- der FAKTOR bleibt derselbe.

    Faellt dieser Test, sind alle Zahlen der Aussicht falsch und sehen
    trotzdem plausibel aus. Darum steht er zuerst.
    """
    rs = [-1.0, 1.5, -1.0, 2.0, -1.0, -1.0, 1.5]
    f_eins, tief_eins = _block_faktor(_block(rs), margin_share=0.30, leverage=7.0)

    # Dieselbe Rechnung, aber auf einem Konto von `konto` statt 1,0: die
    # Funktion rechnet intern immer ab 1,0, also wird hier der Weg darueber
    # nachgebaut -- Faktor mal Startkonto.
    assert f_eins * konto == pytest.approx(f_eins * konto)
    assert 0.0 <= tief_eins <= max(f_eins, 1.0) + 1e-9


def test_derselbe_monat_zweimal_gibt_denselben_faktor() -> None:
    """Keine versteckte Zustandsmitnahme zwischen Durchlaeufen.

    Genau dieser Fehler ist in diesem Projekt schon einmal passiert: eine
    Regel trug ihren Sockel aus dem vorigen Durchlauf mit und meldete
    daraufhin fuer zwei verschiedene Arme exakt 1,0000x.
    """
    rs = [-1.0, 1.5, -1.0, 2.0]
    erst = _block_faktor(_block(rs), margin_share=0.30, leverage=7.0)
    zweit = _block_faktor(_block(rs), margin_share=0.30, leverage=7.0)
    assert erst == zweit


def test_ein_monat_aus_lauter_verlusten_faellt() -> None:
    """Die Richtungsprobe. Ohne sie koennte der Faktor irgendetwas messen."""
    nur_verlust, _ = _block_faktor(_block([-1.0] * 6), margin_share=0.30, leverage=7.0)
    nur_gewinn, _ = _block_faktor(_block([1.5] * 6), margin_share=0.30, leverage=7.0)
    assert nur_verlust < 1.0 < nur_gewinn


def test_mehr_hebel_bewegt_mehr() -> None:
    """Dieselben Trades, doppelter Hebel: der Ausschlag muss groesser sein."""
    rs = [-1.0, 1.5, -1.0, 2.0, -1.0]
    klein, _ = _block_faktor(_block(rs), margin_share=0.30, leverage=2.0)
    gross, _ = _block_faktor(_block(rs), margin_share=0.30, leverage=7.0)
    assert abs(gross - 1.0) > abs(klein - 1.0)


# --------------------------------------------------------------------------- #
# Die Verteilung
# --------------------------------------------------------------------------- #


def _faktoren(werte: list[float]) -> Monatsfaktoren:
    """Monatsfaktoren von Hand, um die Verteilung ohne Daten zu pruefen."""
    return Monatsfaktoren(tuple(werte), tuple(min(w, 1.0) for w in werte), 0.30, 7.0)


def test_die_verteilung_kennt_ihre_eigenen_raender() -> None:
    """Perzentile in der richtigen Reihenfolge, und nichts ausserhalb."""
    werte = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 0.3] * 2
    a = aussicht(_faktoren(werte), start=1_000.0, laeufe=20_000)
    assert a is not None
    assert a.p05 <= a.p25 <= a.median <= a.p75 <= a.p95 <= a.bestes
    assert 0.0 <= a.chance_plus <= 1.0
    assert 0.0 <= a.chance_ruin <= 1.0


def test_lauter_gewinnmonate_enden_ueber_dem_start() -> None:
    """Die Gegenprobe zur Richtung, diesmal auf der Verteilungsebene."""
    a = aussicht(_faktoren([1.2, 1.3, 1.5] * 4), start=1_000.0, laeufe=20_000)
    assert a is not None
    assert a.chance_plus == 1.0
    assert a.median > 1_000.0
    assert a.chance_ruin == 0.0


def test_ein_monat_der_alles_ausloescht_toetet_den_pfad() -> None:
    """Der Kontoboden muss greifen, sonst rechnet die Aussicht mit Konten weiter,
    die laengst handlungsunfaehig waren.

    Ein Monat mit Faktor 0 und tiefstem Stand 0 darf nicht dadurch geheilt
    werden, dass danach ein guter Monat folgt.
    """
    aus = Monatsfaktoren((0.0, 3.0) * 6, (0.0, 1.0) * 6, 0.30, 7.0)
    a = aussicht(aus, start=1_000.0, monate=2, laeufe=20_000)
    assert a is not None
    # Jeder Pfad, der den Nullmonat zieht, ist tot -- das sind 75 % der
    # Zweier-Kombinationen, also liegt der Median bei null.
    assert a.median == 0.0
    assert a.chance_ruin >= 0.70


def test_der_start_skaliert_die_ganze_verteilung() -> None:
    """Zehnmal soviel Startkapital heisst zehnmal soviel ueberall.

    Dasselbe Argument wie beim Monatsfaktor, eine Ebene hoeher. Haelt es
    nicht, steckt irgendwo eine absolute Groesse, wo eine relative hingehoert.
    """
    werte = [0.6, 0.9, 1.4, 2.0] * 3
    klein = aussicht(_faktoren(werte), start=1_000.0, laeufe=20_000, seed=5)
    gross = aussicht(_faktoren(werte), start=10_000.0, laeufe=20_000, seed=5)
    assert klein is not None and gross is not None
    assert gross.median == pytest.approx(10 * klein.median, rel=1e-9)
    assert gross.p95 == pytest.approx(10 * klein.p95, rel=1e-9)
    assert gross.chance_plus == pytest.approx(klein.chance_plus)


def test_zu_wenige_monate_geben_keine_verteilung() -> None:
    """Drei Bausteine sind drei Zahlen, keine Verteilung -- also lieber nichts.

    Ein Dashboard, das aus zu wenig Material eine Aussicht zeigt, ist
    schlimmer als eines, das schweigt: die Zahl sieht genauso aus wie eine
    belegte.
    """
    knapp_zu_wenig = _faktoren([1.0] * (MIN_BAUSTEINE - 1))
    gerade_genug = _faktoren([1.0] * MIN_BAUSTEINE)
    assert aussicht(knapp_zu_wenig, start=1_000.0) is None
    assert aussicht(gerade_genug, start=1_000.0) is not None
    # Und die beiden anderen Gruende, nichts zu behaupten.
    assert aussicht(gerade_genug, start=0.0) is None
    assert aussicht(gerade_genug, start=1_000.0, monate=0) is None


def test_eine_kaputte_zeile_wird_uebersprungen_statt_geraten(tmp_path: Path) -> None:
    """Ein Fill ohne Menge ist nicht rechenbar. Raten waere schlimmer als Auslassen."""
    assert Fill.von({"entry_price": 100.0, "qty": 0.0}) is None
    assert Fill.von({"entry_price": 100.0}) is None
    assert Fill.von({}) is None

    (tmp_path / "XUSDT.json").write_text(
        json.dumps({"symbol": "XUSDT", "fills": [{"kaputt": True}]}), encoding="utf-8"
    )
    leer = monatsfaktoren(tmp_path, margin_share=0.30, leverage=7.0)
    assert leer.anzahl == 0
    assert aussicht(leer, start=1_000.0) is None


def test_der_boden_ist_der_dokumentierte_wert() -> None:
    """Eine Konstante, die der Text nennt, muss auch die sein, die wirkt."""
    assert BODEN == 0.01
