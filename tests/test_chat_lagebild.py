"""Lagebild des Chats: aus den Terminal-Quellen, Ausfall wird `unbekannt`."""

from __future__ import annotations

from types import SimpleNamespace

import sqlite3

import pytest
import yaml
from fastapi import HTTPException

# Beim Einsammeln importieren: der Import von `api.app` probt IPv6 per Socket
# (urllib3), und das soll nicht mitten in einem Test den Socket-Waechter wecken.
# Dasselbe tut tests/test_api.py in Zeile 25 -- vorbestehend, app.py bleibt unberuehrt.
import traidingbrain.api.app  # noqa: F401
from traidingbrain.api import terminal

from traidingbrain.api.chat import lagebild
from traidingbrain.api.chat.lagebild import Holer, LageNichtVerfuegbar, baue_lage
from traidingbrain.api.chat.modelle import Regelwerte, Vorschlag
from traidingbrain.api.chat.pruefung import pruefe
from traidingbrain.config.settings import load_config
from traidingbrain.risk.limits import RiskLimits

JETZT = 1_800_000_000_000
PREIS = 82_597.0


@pytest.fixture(autouse=True)
def _ohne_echte_dateien(tmp_path, monkeypatch):
    """Kein Test liest das echte manuelle Konto oder Journal."""
    monkeypatch.setattr(lagebild, "MANUELL_DB", tmp_path / "manuell.sqlite")
    monkeypatch.setattr(lagebild, "_journal_zeilen", lambda services, symbol: [])


def _services():
    return SimpleNamespace(config=load_config(), state_name="gibt_es_nicht.sqlite")


def _setup(side="short"):
    return SimpleNamespace(side=side, entry=PREIS, stop=83_700.0, target=81_400.0)


def _holer(*, kopf=None, score=None, markt=None, kalender=None) -> Holer:
    def _kopf(symbol):
        return SimpleNamespace(last=PREIS, mark=PREIS, funding_rate=0.0001)

    def _score(services, symbol):
        return SimpleNamespace(
            direction="short", rating=61, band="gut", regime="Trend", headline="Abwaerts"
        )

    def _markt(services, symbol, timeframe):
        setups = [_setup()] if timeframe == "H4" else []
        return SimpleNamespace(setups=setups)

    def _kalender():
        return SimpleNamespace(events=[], high_within_24h=0, next_high_hours=None, risk_pct=0.0)

    return Holer(
        kopf=kopf or _kopf,
        score=score or _score,
        markt=markt or _markt,
        kalender=kalender or _kalender,
    )


def test_lage_liest_bild_und_setups():
    lage = baue_lage(_services(), "BTCUSDT", "H4", jetzt_ms=JETZT, holer=_holer())
    assert lage.bild == "short"
    assert lage.preis == PREIS
    assert [s.timeframe for s in lage.setups] == ["H4"]
    assert lage.folgt is True
    assert lage.kontext["score"]["rating"] == 61


def test_ausgefallene_quelle_wird_unbekannt():
    def kaputt(symbol):
        raise HTTPException(503, "Boerse nicht erreichbar")

    lage = baue_lage(_services(), "BTCUSDT", "H4", jetzt_ms=JETZT, holer=_holer(kopf=kaputt))
    assert lage.preis is None
    assert lage.quellen["kurs"].startswith("unbekannt")
    # Die anderen Quellen bleiben unberuehrt.
    assert lage.bild == "short"


def test_alle_ebenen_ausgefallen_gibt_setups_none():
    def kaputt(services, symbol, timeframe):
        raise HTTPException(503, "keine Daten")

    lage = baue_lage(_services(), "BTCUSDT", "H4", jetzt_ms=JETZT, holer=_holer(markt=kaputt))
    assert lage.setups is None
    assert lage.quellen["setups"].startswith("unbekannt")


def test_eine_ebene_ausgefallen_wird_uebersprungen_und_vermerkt():
    def teils(services, symbol, timeframe):
        if timeframe == "D1":
            raise KeyError("D1")
        return SimpleNamespace(setups=[_setup()] if timeframe == "H4" else [])

    lage = baue_lage(_services(), "BTCUSDT", "H4", jetzt_ms=JETZT, holer=_holer(markt=teils))
    assert [s.timeframe for s in lage.setups] == ["H4"]
    assert "D1" in lage.quellen["setups"]


def test_score_ausfall_gibt_bild_none():
    def kaputt(services, symbol):
        raise HTTPException(502, "kein Score")

    lage = baue_lage(_services(), "BTCUSDT", "H4", jetzt_ms=JETZT, holer=_holer(score=kaputt))
    assert lage.bild is None
    assert lage.quellen["bild"].startswith("unbekannt")


def test_fremder_markt_folgt_nicht():
    lage = baue_lage(_services(), "PEPEUSDT", "H4", jetzt_ms=JETZT, holer=_holer())
    assert lage.folgt is False
    werte = Regelwerte(
        require_agreement=True,
        timeframes=["D1", "H4", "H1"],
        margin_share=0.3,
        leverage=7.0,
        risk_cap_share=0.015,
        max_cost_fraction=0.08,
        max_leverage=10.0,
        kosten_roundtrip=0.001,
    )
    urteil = pruefe(
        Vorschlag(symbol="PEPEUSDT", side="short"),
        lage,
        werte,
        RiskLimits(load_config().risk.limits),
    )
    regel3 = next(r for r in urteil.regeln if r.nr == 3)
    assert regel3.status == "unbekannt"
    assert regel3.hinweis == "Markt wird nicht beobachtet"
    assert urteil.angenommen is False


def test_kopf_mit_valueerror_wird_unbekannt():
    def kaputt(symbol):
        raise ValueError("kein Preis")

    lage = baue_lage(_services(), "BTCUSDT", "H4", jetzt_ms=JETZT, holer=_holer(kopf=kaputt))
    assert lage.preis is None
    assert lage.quellen["kurs"].startswith("unbekannt")
    assert "ValueError" in lage.quellen["kurs"]


def test_kaputter_plan_stuerzt_nicht_ab(monkeypatch):
    def kaputt():
        raise yaml.YAMLError("kaputt")

    monkeypatch.setattr(lagebild, "_lese_plan_yaml", kaputt)
    lage = baue_lage(_services(), "BTCUSDT", "H4", jetzt_ms=JETZT, holer=_holer())
    assert lage.quellen["plan"].startswith("unbekannt")
    assert lage.kontext["plan"] is None


def test_gesperrter_bot_zustand_ist_lage_nicht_verfuegbar(monkeypatch):
    def gesperrt(pfad, symbole):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(lagebild, "bot_positionen", gesperrt)
    with pytest.raises(LageNichtVerfuegbar, match="OperationalError"):
        baue_lage(_services(), "BTCUSDT", "H4", jetzt_ms=JETZT, holer=_holer())


def test_fehlendes_journal_wird_nicht_angelegt(tmp_path, monkeypatch):
    journal = tmp_path / "unterordner" / "journal.sqlite"
    services = SimpleNamespace(config=load_config(), state_name="x.sqlite")
    import traidingbrain.api.app as app

    monkeypatch.setattr(
        app, "_score_read_dict", lambda s, sym: {"setups": [], "direction": "neutral"}
    )
    monkeypatch.setattr(app, "_chart_dict", lambda s, sym: {})
    monkeypatch.setattr(terminal, "orderbuch", lambda sym, n: None)
    monkeypatch.setattr(terminal, "kalender", lambda: None)
    monkeypatch.setattr(terminal, "score", lambda *a: "ok")
    assert terminal.terminal_score(services, "BTCUSDT", lambda s: journal, lambda s: None) == "ok"
    assert not journal.exists()
    assert not journal.parent.exists()
