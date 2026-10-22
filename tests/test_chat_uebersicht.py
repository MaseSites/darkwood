"""Marktuebersicht: alle beobachteten Maerkte, Ausfaelle als unbekannt, Zeitlimit, 60 s Speicher."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

# Beim Einsammeln importieren (IPv6-Probe von urllib3, siehe test_chat_lagebild.py).
import traidingbrain.api.app  # noqa: F401
from traidingbrain.api.chat import uebersicht as modul
from traidingbrain.api.chat.uebersicht import UebersichtHoler, baue_uebersicht

SYMBOLE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT",
]  # fmt: skip


def _services(symbole=SYMBOLE) -> SimpleNamespace:
    engine = SimpleNamespace(
        symbols=SimpleNamespace(active=list(symbole)),
        setups=SimpleNamespace(timeframes=None),
    )
    return SimpleNamespace(config=SimpleNamespace(engine=engine))


class Zaehler:
    """Attrappen fuer Kurs, Score und Marktansicht; zaehlt jeden Aufruf."""

    def __init__(self, richtung: dict[str, str] | None = None) -> None:
        self.aufrufe = 0
        self.richtung = richtung or {}
        self._sperre = threading.Lock()

    def _zaehle(self) -> None:
        with self._sperre:
            self.aufrufe += 1

    def kopf(self, symbol):
        self._zaehle()
        return SimpleNamespace(last=100.0 + SYMBOLE.index(symbol), change_pct=-1.5)

    def score(self, services, symbol):
        self._zaehle()
        return {
            "direction": self.richtung.get(symbol, "aufwärts"),
            "rating": 61,
            "regime": "Trend",
        }

    def markt(self, services, symbol, tf):
        self._zaehle()
        setups = (
            [SimpleNamespace(side="short", entry=100.0, stop=105.0, target=90.0)]
            if tf == "H4"
            else []
        )
        return SimpleNamespace(setups=setups)

    def holer(self) -> UebersichtHoler:
        return UebersichtHoler(kopf=self.kopf, score=self.score, markt=self.markt)


@pytest.fixture(autouse=True)
def _leer(monkeypatch):
    """Leerer Zwischenspeicher je Test; das Journal ist eine Attrappe mit fuenf Trades."""
    modul._ZWISCHENSPEICHER.clear()
    fuenf = [{"side": "long", "n": i} for i in range(5)]
    monkeypatch.setattr(modul, "_journal_zeilen", lambda services, symbol: fuenf)
    yield
    modul._ZWISCHENSPEICHER.clear()


def test_alle_maerkte_in_reihenfolge():
    zeilen = baue_uebersicht(_services(), holer=Zaehler().holer())
    assert [z.symbol for z in zeilen] == SYMBOLE
    btc = zeilen[0]
    assert btc.preis == 100.0
    assert btc.veraenderung_pct == -1.5
    assert btc.rating == 61 and btc.regime == "Trend"
    assert [(s.timeframe, s.side) for s in btc.setups] == [("H4", "short")]
    assert len(btc.letzte_trades) == 3
    assert btc.quellen == {}


def test_richtung_wird_abgebildet():
    z = Zaehler({"BTCUSDT": "aufwärts", "ETHUSDT": "abwärts", "SOLUSDT": "gemischt"})
    zeilen = baue_uebersicht(_services(SYMBOLE[:3]), holer=z.holer())
    assert [r.richtung for r in zeilen] == ["long", "short", "neutral"]


def test_ausgefallene_quelle_wird_unbekannt():
    z = Zaehler()
    echt = z.kopf

    def kopf(symbol):
        if symbol == "ETHUSDT":
            raise RuntimeError("Boerse weg")
        return echt(symbol)

    holer = UebersichtHoler(kopf=kopf, score=z.score, markt=z.markt)
    zeilen = {r.symbol: r for r in baue_uebersicht(_services(), holer=holer)}
    eth = zeilen["ETHUSDT"]
    assert eth.preis is None and eth.veraenderung_pct is None
    assert eth.quellen["kurs"].startswith("unbekannt")
    assert "Boerse weg" in eth.quellen["kurs"]
    assert eth.rating == 61  # die anderen Quellen desselben Markts bleiben
    assert zeilen["BTCUSDT"].preis == 100.0 and zeilen["BTCUSDT"].quellen == {}


def test_zeitlimit_markiert_langsame_maerkte():
    z = Zaehler()
    los = threading.Event()

    def score(services, symbol):
        if symbol == "SOLUSDT":
            los.wait(10)
        return z.score(services, symbol)

    holer = UebersichtHoler(kopf=z.kopf, score=score, markt=z.markt)
    try:
        start = time.monotonic()
        zeilen = {r.symbol: r for r in baue_uebersicht(_services(), holer=holer, zeitlimit_s=0.5)}
        dauer = time.monotonic() - start
    finally:
        los.set()
    assert dauer < 2.0
    sol = zeilen["SOLUSDT"]
    assert sol.rating is None and sol.richtung is None and sol.regime is None
    assert sol.quellen["score"] == "unbekannt: nicht rechtzeitig berechnet"
    assert sol.preis is not None
    assert zeilen["BTCUSDT"].rating == 61


def test_zwischenspeicher_60s():
    uhr = SimpleNamespace(t=1_000.0)
    z = Zaehler()
    baue_uebersicht(_services(), holer=z.holer(), jetzt=lambda: uhr.t)
    erst = z.aufrufe
    assert erst > 0
    uhr.t += 59
    baue_uebersicht(_services(), holer=z.holer(), jetzt=lambda: uhr.t)
    assert z.aufrufe == erst  # aus dem Speicher
    uhr.t += 2  # 61 s nach dem ersten Lauf
    baue_uebersicht(_services(), holer=z.holer(), jetzt=lambda: uhr.t)
    assert z.aufrufe == 2 * erst


def test_lauf_mit_zeitueberschreitung_wird_nicht_gespeichert():
    uhr = SimpleNamespace(t=1_000.0)
    z = Zaehler()
    los = threading.Event()

    def score(services, symbol):
        if symbol == "SOLUSDT" and not los.is_set():
            los.wait(10)
        return z.score(services, symbol)

    holer = UebersichtHoler(kopf=z.kopf, score=score, markt=z.markt)
    try:
        langsam = baue_uebersicht(_services(), holer=holer, zeitlimit_s=0.5, jetzt=lambda: uhr.t)
    finally:
        los.set()
    assert next(r for r in langsam if r.symbol == "SOLUSDT").rating is None
    vorher = z.aufrufe
    uhr.t += 1
    frisch = baue_uebersicht(_services(), holer=holer, jetzt=lambda: uhr.t)
    assert z.aufrufe > vorher  # neu berechnet, nicht aus dem Speicher
    assert next(r for r in frisch if r.symbol == "SOLUSDT").rating == 61
