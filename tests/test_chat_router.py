"""Endpunkte des Chats: Karte nur aus der Pruefung, Ausfuehren genau einmal, neu geprueft."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Beim Einsammeln importieren (IPv6-Probe von urllib3, siehe test_chat_lagebild.py).
import traidingbrain.api.app  # noqa: F401
from tests.factories import make_symbol_spec
from traidingbrain.api import terminal
from traidingbrain.api.app import Services
from traidingbrain.api.chat import lagebild
from traidingbrain.api.chat import router as router_modul
from traidingbrain.api.chat.lagebild import Holer
from traidingbrain.api.chat.modelle import Vorschlag
from traidingbrain.api.chat.router import router
from traidingbrain.api.chat.speicher import ChatSpeicher
from traidingbrain.api.chat.sprecher import Antwort
from traidingbrain.config.settings import load_config
from traidingbrain.journal.store import JournalStore
from traidingbrain.proposals.builder import ProposalBuilder
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import KillSwitch, RiskLimits

pytestmark = pytest.mark.allow_hosts(["127.0.0.1", "::1"])

START_S = 1_800_000_000.0
PREIS = 82_597.0
ECHTE_DATEN = Path(__file__).resolve().parent.parent / "data"


class Kurs:
    """Ein verstellbarer Kurs fuer Lagebild und `order_oeffnen` zugleich."""

    def __init__(self, wert: float) -> None:
        self.wert = wert
        self.stop = 83_700.0  # Stop des H4-Setups

    def kopf(self, symbol: str) -> SimpleNamespace:
        return SimpleNamespace(last=self.wert, mark=self.wert, funding_rate=0.0001)


class Uhr:
    def __init__(self) -> None:
        self.s = START_S

    def __call__(self) -> float:
        return self.s


class FesterSprecher:
    def __init__(self, antwort: Antwort) -> None:
        self.antwort = antwort
        self.aufrufe: list[tuple[str, list]] = []

    def sprich(self, nachricht, lage, verlauf) -> Antwort:
        self.aufrufe.append((nachricht, verlauf))
        return self.antwort

    def status(self) -> str:
        return "bereit"


class VerbotenerSprecher:
    def sprich(self, nachricht, lage, verlauf) -> Antwort:
        raise AssertionError("der Formular-Modus darf Claude nicht fragen")


def _holer(kurs: Kurs) -> Holer:
    def _score(services, symbol):
        return SimpleNamespace(
            direction="short", rating=61, band="gut", regime="Trend", headline="Abwaerts"
        )

    def _markt(services, symbol, timeframe):
        setups = (
            [SimpleNamespace(side="short", entry=PREIS, stop=kurs.stop, target=81_400.0)]
            if timeframe == "H4"
            else []
        )
        return SimpleNamespace(setups=setups)

    def _kalender():
        return SimpleNamespace(events=[])

    return Holer(kopf=kurs.kopf, score=_score, markt=_markt, kalender=_kalender)


def _bot_dateien(data_dir: Path) -> None:
    """Kopien der Bot-Dateien; ohne echte Daten (CI) gleich gebaute Ersatzdateien."""
    for name in ("plan_paper.sqlite", "journal.sqlite"):
        quelle = ECHTE_DATEN / name
        if quelle.exists():
            shutil.copyfile(quelle, data_dir / name)
    if not (data_dir / "journal.sqlite").exists():
        JournalStore(data_dir / "journal.sqlite")
    if not (data_dir / "plan_paper.sqlite").exists():
        with closing(sqlite3.connect(data_dir / "plan_paper.sqlite")) as con:
            con.execute("CREATE TABLE accounts (symbol TEXT PRIMARY KEY, position TEXT)")
            con.commit()


@pytest.fixture
def umgebung(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _bot_dateien(data_dir)
    basis = load_config()
    pfade = basis.engine.paths.model_copy(update={"data_dir": data_dir})
    config = basis.model_copy(update={"engine": basis.engine.model_copy(update={"paths": pfade})})
    kill_switch = KillSwitch(tmp_path / "KILL")
    limits = RiskLimits(config.risk.limits, kill_switch)
    services = Services(
        config=config,
        store=ProposalStore(tmp_path / "proposals.sqlite"),
        builder=ProposalBuilder(config, limits),
        limits=limits,
        kill_switch=kill_switch,
        specs={"BTCUSDT": make_symbol_spec()},
        state_name="plan_paper.sqlite",
    )
    plan = tmp_path / "plan.yaml"
    plan.write_text(
        yaml.safe_dump({"margin_share": 0.3, "leverage": 7.0, "risk_cap_share": 0.015}),
        encoding="utf-8",
    )
    manuell = tmp_path / "manual_paper.sqlite"
    kurs = Kurs(PREIS)
    monkeypatch.setattr(terminal, "PLAN_YAML", plan)
    monkeypatch.setattr(terminal, "MANUELL_DB", manuell)
    monkeypatch.setattr(lagebild, "MANUELL_DB", manuell)
    monkeypatch.setattr(terminal, "kopf", kurs.kopf)
    return SimpleNamespace(
        services=services,
        kurs=kurs,
        uhr=Uhr(),
        manuell=manuell,
        speicher=ChatSpeicher(tmp_path / "chat.sqlite"),
        data_dir=data_dir,
    )


def _client(u, sprecher) -> TestClient:
    app = FastAPI()
    app.include_router(
        router(
            u.services, sprecher=sprecher, speicher=u.speicher, holer=_holer(u.kurs), jetzt=u.uhr
        )
    )
    return TestClient(app)


SHORT = Vorschlag(symbol="BTCUSDT", side="short", sl=83_700.0)


def _karte_annehmen(u) -> tuple[TestClient, str]:
    sprecher = FesterSprecher(Antwort(text="Short passt zum Bild.", vorschlag=SHORT))
    c = _client(u, sprecher)
    r = _frage(c, "short?")
    assert r.status_code == 200, r.text
    karte = r.json()["karte"]
    assert karte["urteil"]["angenommen"] is True
    return c, karte["id"]


def _frage(c: TestClient, text: str, symbol: str = "BTCUSDT"):
    return c.post(
        "/api/terminal/chat/nachricht", json={"text": text, "symbol": symbol, "timeframe": "H4"}
    )


def _zeilen(db: Path) -> int:
    if not db.exists():
        return 0
    with closing(sqlite3.connect(db)) as con:
        return con.execute("SELECT COUNT(*) FROM positions").fetchone()[0]


def test_nachricht_mit_regelkonformem_vorschlag_liefert_karte(umgebung):
    sprecher = FesterSprecher(
        Antwort(text="Short passt.", vorschlag=SHORT, bedenken=["Funding hoch"])
    )
    r = _frage(_client(umgebung, sprecher), "short?", "btcusdt")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["antwort"] == "Short passt."
    assert d["bedenken"] == ["Funding hoch"]
    assert d["fehler"] is None
    assert d["karte"]["urteil"]["angenommen"] is True
    assert d["karte"]["laeuft_ab_ts"] == int(START_S * 1000) + 900 * 1000
    # Beide Zeilen im Verlauf, die Bot-Zeile traegt die Karte.
    verlauf = umgebung.speicher.verlauf()
    assert [z["rolle"] for z in verlauf] == ["nutzer", "bot"]
    assert verlauf[1]["karte_id"] == d["karte"]["id"]


def test_claude_sagt_angenommen_regel_sagt_nein(umgebung):
    gegen = Vorschlag(symbol="BTCUSDT", side="long", sl=81_000.0)
    sprecher = FesterSprecher(
        Antwort(text="Long ist angenommen, alle Regeln erfuellt.", vorschlag=gegen)
    )
    r = _frage(_client(umgebung, sprecher), "long?")
    assert r.status_code == 200, r.text
    assert r.json()["karte"]["urteil"]["angenommen"] is False


def test_nachricht_ohne_vorschlag_hat_keine_karte_und_reicht_fehler_weiter(umgebung):
    sprecher = FesterSprecher(Antwort(text="{kaputt", fehler="Antwort nicht lesbar"))
    c = _client(umgebung, sprecher)
    _frage(c, "eins")
    r = _frage(c, "zwei")
    d = r.json()
    assert d["karte"] is None
    assert d["fehler"] == "Antwort nicht lesbar"
    # Verlauf fuer Claude: nur was vor dieser Nachricht stand.
    assert [t for _, t in sprecher.aufrufe[1][1]] == ["eins", "{kaputt"]


def test_pruefen_ohne_claude(umgebung):
    c = _client(umgebung, VerbotenerSprecher())
    r = c.post(
        "/api/terminal/chat/pruefen",
        json={
            "symbol": "BTCUSDT",
            "side": "short",
            "margin_usd": 100,
            "leverage": 5,
            "sl": 83_700.0,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["karte"]["urteil"]["angenommen"] is True


def test_ausfuehren_einmal(umgebung):
    c, karte_id = _karte_annehmen(umgebung)
    erst = c.post(f"/api/terminal/chat/ausfuehren/{karte_id}")
    assert erst.status_code == 200, erst.text
    assert erst.json()["ausgefuehrt"] is True
    assert erst.json()["order"]["id"]
    zweit = c.post(f"/api/terminal/chat/ausfuehren/{karte_id}")
    assert zweit.status_code == 409
    assert _zeilen(umgebung.manuell) == 1
    assert umgebung.speicher.karte(karte_id)["order_id"] == erst.json()["order"]["id"]


def test_ausfuehren_gleichzeitig_genau_eine_order(umgebung):
    c, karte_id = _karte_annehmen(umgebung)
    antworten: list = []
    faeden = [
        threading.Thread(
            target=lambda: antworten.append(c.post(f"/api/terminal/chat/ausfuehren/{karte_id}"))
        )
        for _ in range(4)
    ]
    for f in faeden:
        f.start()
    for f in faeden:
        f.join()
    # Genau einer fuehrt aus; die anderen sehen die markierte Karte (409) oder,
    # je nach Zeitpunkt, schon die offene Position in der Neupruefung (abgelehnt).
    ausgefuehrt = [a for a in antworten if a.status_code == 200 and a.json()["ausgefuehrt"] is True]
    assert len(ausgefuehrt) == 1
    assert all(
        a.status_code == 409 or a.json()["ausgefuehrt"] is False
        for a in antworten
        if a is not ausgefuehrt[0]
    )
    assert _zeilen(umgebung.manuell) == 1


def test_ausfuehren_unbekannt(umgebung):
    c = _client(umgebung, VerbotenerSprecher())
    assert c.post("/api/terminal/chat/ausfuehren/gibtesnicht").status_code == 404


def test_ausfuehren_abgelaufen(umgebung):
    c, karte_id = _karte_annehmen(umgebung)
    umgebung.uhr.s += 901
    assert c.post(f"/api/terminal/chat/ausfuehren/{karte_id}").status_code == 410
    assert _zeilen(umgebung.manuell) == 0


def test_abgelehnte_karte_wird_nie_ausgefuehrt(umgebung):
    c = _client(umgebung, VerbotenerSprecher())
    r = c.post(
        "/api/terminal/chat/pruefen", json={"symbol": "BTCUSDT", "side": "long", "sl": 81_000.0}
    )
    karte = r.json()["karte"]
    assert karte["urteil"]["angenommen"] is False
    assert c.post(f"/api/terminal/chat/ausfuehren/{karte['id']}").status_code == 409
    assert _zeilen(umgebung.manuell) == 0


def test_ausfuehren_neu_geprueft_und_abgelehnt(umgebung):
    c, karte_id = _karte_annehmen(umgebung)
    umgebung.services.kill_switch.engage("Test")
    r = c.post(f"/api/terminal/chat/ausfuehren/{karte_id}")
    assert r.status_code == 200
    assert r.json()["ausgefuehrt"] is False
    assert r.json()["grund"].startswith("Verlustbremsen")
    assert _zeilen(umgebung.manuell) == 0


def test_ausfuehren_kursdrift(umgebung):
    # Margin und Hebel genannt und unter dem Risikodeckel: die Order haengt nicht
    # vom Kurs ab, so dass die Neupruefung dieselbe Order liefert und nur die Drift greift.
    fest = Vorschlag(symbol="BTCUSDT", side="short", sl=83_700.0, margin_usd=100.0, leverage=5.0)
    c = _client(umgebung, FesterSprecher(Antwort(text="Short.", vorschlag=fest)))
    karte = _frage(c, "short?").json()["karte"]
    assert karte["urteil"]["angenommen"] is True
    assert karte["urteil"]["order"]["margin_usd"] == 100.0  # nicht gekuerzt
    # -0.2 %: beim Short wird der Stop weiter, alle acht Regeln bleiben erfuellt.
    umgebung.kurs.wert = PREIS * 0.998
    r = c.post(f"/api/terminal/chat/ausfuehren/{karte['id']}")
    assert r.status_code == 200
    assert r.json()["ausgefuehrt"] is False
    assert "bp" in r.json()["grund"]
    assert _zeilen(umgebung.manuell) == 0


def test_ausfuehren_gekuerzte_margin_folgt_dem_kurs(umgebung):
    """Ruling 15: die vom Risikodeckel gekuerzte Margin haengt am Kurs; schon 1 bp
    Bewegung aendert sie um mehr als 0.01 USD, und die Karte wird nicht ausgefuehrt."""
    c, karte_id = _karte_annehmen(umgebung)
    umgebung.kurs.wert = PREIS * 0.9999
    r = c.post(f"/api/terminal/chat/ausfuehren/{karte_id}")
    assert r.json()["ausgefuehrt"] is False
    assert r.json()["felder"] == ["margin_usd"]
    assert _zeilen(umgebung.manuell) == 0


def test_order_fehler_nach_markierung_gibt_502_und_kein_zweiter_versuch(umgebung, monkeypatch):
    c, karte_id = _karte_annehmen(umgebung)

    def kaputt(w):
        raise RuntimeError("Boerse weg")

    monkeypatch.setattr(terminal, "order_oeffnen", kaputt)
    r = c.post(f"/api/terminal/chat/ausfuehren/{karte_id}")
    assert r.status_code == 502
    assert "Boerse weg" in r.json()["detail"]
    assert c.post(f"/api/terminal/chat/ausfuehren/{karte_id}").status_code == 409


def test_bot_dateien_bleiben_unberuehrt(umgebung):
    def hashes() -> dict[str, str]:
        return {
            n: hashlib.sha256((umgebung.data_dir / n).read_bytes()).hexdigest()
            for n in ("plan_paper.sqlite", "journal.sqlite")
        }

    vorher = hashes()
    c, karte_id = _karte_annehmen(umgebung)
    assert c.post(f"/api/terminal/chat/ausfuehren/{karte_id}").json()["ausgefuehrt"] is True
    assert hashes() == vorher


def test_zweite_nachricht_waehrend_claude_denkt(umgebung):
    begonnen, weiter = threading.Event(), threading.Event()

    class Langsam:
        def sprich(self, nachricht, lage, verlauf):
            begonnen.set()
            assert weiter.wait(10)
            return Antwort(text="fertig")

    c = _client(umgebung, Langsam())
    erste: list = []
    faden = threading.Thread(target=lambda: erste.append(_frage(c, "a")))
    faden.start()
    assert begonnen.wait(10)
    zweite = _frage(c, "b")
    weiter.set()
    faden.join()
    assert zweite.status_code == 409
    assert zweite.json()["detail"] == "Claude antwortet noch"
    assert erste[0].status_code == 200
    # Die Sperre ist wieder frei.
    weiter.set()
    assert _frage(c, "c").status_code == 200


def test_fehlende_plandatei_gibt_503(umgebung, tmp_path, monkeypatch):
    monkeypatch.setattr(terminal, "PLAN_YAML", tmp_path / "fehlt.yaml")
    r = _client(umgebung, VerbotenerSprecher()).post(
        "/api/terminal/chat/pruefen", json={"symbol": "BTCUSDT", "side": "short", "sl": 83_700.0}
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "config_offen/plan.yaml fehlt oder ist unvollstaendig"


def test_verlauf_mit_karten_und_status(umgebung):
    c, karte_id = _karte_annehmen(umgebung)
    v = c.get("/api/terminal/chat/verlauf").json()
    assert v[-1]["karte"]["id"] == karte_id
    assert v[-1]["karte"]["urteil"]["angenommen"] is True
    assert c.get("/api/terminal/chat/status").json() == {"claude": "bereit"}


# -- Schlussreview: Karte = Order, Fehler nach der Nutzerzeile, kaputter Plan -- #

OHNE_STOP = Vorschlag(symbol="BTCUSDT", side="short")  # Stop kommt vom H4-Setup


def _karte_mit_bot_stop(u) -> tuple[TestClient, str, dict]:
    c = _client(u, FesterSprecher(Antwort(text="Short.", vorschlag=OHNE_STOP)))
    karte = _frage(c, "short?").json()["karte"]
    assert karte["urteil"]["angenommen"] is True
    assert karte["urteil"]["stop_vom_bot"] is True
    assert karte["urteil"]["order"]["sl"] == 83_700.0
    return c, karte["id"], karte["urteil"]["order"]


def test_ausfuehren_setup_stop_geaendert_wird_abgelehnt(umgebung):
    c, karte_id, _ = _karte_mit_bot_stop(umgebung)
    umgebung.kurs.stop = 83_800.0  # z. B. nach einem H4-Schluss
    r = c.post(f"/api/terminal/chat/ausfuehren/{karte_id}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ausgefuehrt"] is False
    assert d["grund"] == "Vorschlag hat sich geaendert - bitte neu pruefen"
    assert "sl" in d["felder"]  # der Stop; die gekuerzte Margin folgt ihm
    assert _zeilen(umgebung.manuell) == 0
    # Nicht beansprucht: die Karte ist weder ausgefuehrt noch mit einer Order-ID versehen.
    karte = umgebung.speicher.karte(karte_id)
    assert karte["ausgefuehrt_ts"] is None and karte["order_id"] is None


def test_ausfuehren_gibt_genau_die_gespeicherte_order_auf(umgebung, monkeypatch):
    c, karte_id, gezeigt = _karte_mit_bot_stop(umgebung)
    # Innerhalb der Toleranz (1e-9 relativ): gleich -- aufgegeben wird der gezeigte Wert.
    umgebung.kurs.stop = 83_700.0 * (1 + 1e-12)
    gesehen: list = []
    echt = terminal.order_oeffnen

    def merken(w):
        gesehen.append(w)
        return echt(w)

    monkeypatch.setattr(terminal, "order_oeffnen", merken)
    r = c.post(f"/api/terminal/chat/ausfuehren/{karte_id}")
    assert r.status_code == 200, r.text
    assert r.json()["ausgefuehrt"] is True
    assert len(gesehen) == 1
    assert gesehen[0].model_dump(mode="json") == gezeigt
    assert gesehen[0].sl == 83_700.0
    assert _zeilen(umgebung.manuell) == 1


def test_sprecher_wirft_bot_zeile_und_fehler(umgebung):
    class Kaputt:
        def sprich(self, nachricht, lage, verlauf):
            raise RuntimeError("CLI abgestuerzt")

    r = _frage(_client(umgebung, Kaputt()), "hallo")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["karte"] is None
    assert "CLI abgestuerzt" in d["fehler"]
    verlauf = umgebung.speicher.verlauf()
    assert [z["rolle"] for z in verlauf] == ["nutzer", "bot"]
    assert verlauf[1]["text"].startswith("Konnte nicht antworten: ")
    assert "CLI abgestuerzt" in verlauf[1]["text"]


def test_lage_fuer_anderen_markt_fehlt_bot_zeile_und_503(umgebung, monkeypatch):
    echt = router_modul.baue_lage

    def baue(services, symbol, *a, **k):
        if symbol == "ETHUSDT":
            raise lagebild.LageNichtVerfuegbar("Kontostand nicht lesbar (Test)")
        return echt(services, symbol, *a, **k)

    monkeypatch.setattr(router_modul, "baue_lage", baue)
    eth = Vorschlag(symbol="ETHUSDT", side="short", sl=4_000.0)
    r = _frage(_client(umgebung, FesterSprecher(Antwort(text="ETH short.", vorschlag=eth))), "eth?")
    assert r.status_code == 503
    assert "Kontostand nicht lesbar (Test)" in r.json()["detail"]
    verlauf = umgebung.speicher.verlauf()
    assert [z["rolle"] for z in verlauf] == ["nutzer", "bot"]
    assert verlauf[1]["text"].startswith("Konnte nicht antworten: ")
    assert verlauf[1]["karte_id"] is None


@pytest.mark.parametrize(
    "plan",
    [
        pytest.param("yaml", id="yaml-fehler"),
        pytest.param({"margin_share": 0.3, "leverage": 7.0, "risk_cap_share": None}, id="null"),
        pytest.param({"margin_share": "viel", "leverage": 7.0, "risk_cap_share": 0.015}, id="text"),
    ],
)
def test_kaputte_plandatei_gibt_503(umgebung, monkeypatch, plan):
    def lesen():
        if plan == "yaml":
            raise yaml.YAMLError("kaputt")
        return plan

    monkeypatch.setattr(terminal, "_lese_plan_yaml", lesen)
    r = _client(umgebung, VerbotenerSprecher()).post(
        "/api/terminal/chat/pruefen", json={"symbol": "BTCUSDT", "side": "short", "sl": 83_700.0}
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "config_offen/plan.yaml fehlt oder ist unvollstaendig"
