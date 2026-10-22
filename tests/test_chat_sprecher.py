"""Der Sprecher: liest Claudes Antwort, urteilt nie, fragt hoechstens einmal nach."""
import json
from pathlib import Path

from traidingbrain.api.chat import sprecher as modul
from traidingbrain.api.chat.modelle import Lage, MarktZeile, Setup
from traidingbrain.api.chat.sprecher import Antwort, ClaudeSprecher
from traidingbrain.brain.subscription import SubscriptionUnavailableError, unwrap
from traidingbrain.domain.enums import Side
from traidingbrain.domain.proposal import Position
from traidingbrain.risk.limits import AccountState

JETZT = 1_700_000_000_000


def _lage() -> Lage:
    pos = Position(
        symbol="ETHUSDT",
        side=Side.LONG,
        qty=1.0,
        entry_price=1.0,
        leverage=1.0,
        liquidation_price=1.0,
        opened_ts=JETZT,
    )
    konto = AccountState.from_history(
        equity=1_234.5, history=[], now_ms=JETZT, open_positions=[pos]
    )
    return Lage(
        symbol="BTCUSDT",
        timeframe="H4",
        preis=84_000.0,
        bild="short",
        setups=[],
        folgt=True,
        konto=konto,
        quellen={},
        kontext={},
    )


class _Lauf:
    """Attrappe fuer die CLI: liefert die Antworten der Reihe nach, merkt sich die Eingaben."""

    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.inhalte: list[str] = []

    def __call__(self, content):
        self.inhalte.append(content)
        return self.antworten.pop(0), "sid"


GUELTIG = json.dumps(
    {"antwort": "ok", "vorschlag": {"symbol": "btc", "side": "short"}, "bedenken": ["x"]}
)


def test_vorschlag_wird_gelesen():
    a = ClaudeSprecher(lauf=_Lauf(GUELTIG)).sprich("short btc?", _lage(), [])
    assert a.text == "ok"
    assert a.vorschlag.symbol == "BTCUSDT"
    assert a.vorschlag.side == "short"
    assert a.bedenken == ["x"]
    assert a.fehler is None


def test_ungueltig_dann_eine_nachfrage():
    lauf = _Lauf("kein json", GUELTIG)
    a = ClaudeSprecher(lauf=lauf).sprich("hi", _lage(), [])
    assert len(lauf.inhalte) == 2
    assert "no JSON object" in lauf.inhalte[1]
    assert a.vorschlag is not None and a.fehler is None


def test_zweimal_ungueltig_ohne_vorschlag():
    lauf = _Lauf("kein json", "immer noch nicht")
    a = ClaudeSprecher(lauf=lauf).sprich("hi", _lage(), [])
    assert len(lauf.inhalte) == 2
    assert a.vorschlag is None
    assert a.fehler == "Antwort nicht lesbar"


def test_feld_angenommen_wird_ignoriert():
    roh = json.dumps(
        {"antwort": "ok", "vorschlag": {"symbol": "eth", "side": "long"}, "angenommen": True}
    )
    a = ClaudeSprecher(lauf=_Lauf(roh)).sprich("hi", _lage(), [])
    assert not hasattr(a, "angenommen")
    assert "angenommen" not in Antwort.__dataclass_fields__
    assert a.vorschlag.symbol == "ETHUSDT"


def test_attrappe_hat_echte_cli_form():
    innen = json.dumps({"antwort": "ok", "vorschlag": None, "bedenken": []})
    huelle = json.dumps(
        {
            "type": "result",
            "is_error": False,
            "result": innen,
            "session_id": "abc-123",
            "usage": {"input_tokens": 1500, "output_tokens": 400},
        }
    )
    text, sid = unwrap(huelle)
    assert text == innen and sid == "abc-123"
    a = ClaudeSprecher(lauf=lambda c: unwrap(huelle)).sprich("hi", _lage(), [])
    assert a.text == "ok" and a.vorschlag is None


def test_eingabe_enthaelt_lage_ohne_konto_aber_mit_equity_und_verlauf():
    lauf = _Lauf(GUELTIG)
    verlauf = [("user", f"z{i}") for i in range(12)]
    ClaudeSprecher(lauf=lauf).sprich("meine Frage", _lage(), verlauf)
    inhalt = lauf.inhalte[0]
    assert "1234.5" in inhalt and "ETHUSDT" in inhalt
    assert "starting_equity_today" not in inhalt
    assert "z1\n" not in inhalt and "z2" in inhalt and "z11" in inhalt  # nur die letzten 10
    assert "meine Frage" in inhalt
    # Der Systemtext kommt als Datei (--system-prompt-file), nicht noch einmal in der Eingabe.
    assert "urteilst nicht" not in inhalt


def test_status_nicht_installiert_bereit_und_nicht_angemeldet():
    s = ClaudeSprecher(lauf=_Lauf(), which=lambda _n: None)
    assert s.status() == "nicht_installiert"

    aufrufe = []
    uhr = [0.0]
    s = ClaudeSprecher(
        lauf=_Lauf(),
        which=lambda _n: "claude",
        probe=lambda _p: aufrufe.append(1) or True,
        uhr=lambda: uhr[0],
    )
    assert s.status() == "bereit"
    uhr[0] = 59.0
    assert s.status() == "bereit"
    assert len(aufrufe) == 1  # gecacht
    uhr[0] = 61.0
    s.status()
    assert len(aufrufe) == 2


def test_anmeldefehler_wird_zu_nicht_angemeldet():
    def lauf(_c):
        raise SubscriptionUnavailableError("not signed in")

    s = ClaudeSprecher(lauf=lauf, which=lambda _n: "claude", probe=lambda _p: True)
    a = s.sprich("hi", _lage(), [])
    assert a.vorschlag is None and a.fehler
    assert s.status() == "nicht_angemeldet"


def test_bedenken_null_wird_leere_liste_ohne_nachfrage():
    roh = json.dumps(
        {"antwort": "ok", "vorschlag": {"symbol": "btc", "side": "long"}, "bedenken": None}
    )
    lauf = _Lauf(roh)
    a = ClaudeSprecher(lauf=lauf).sprich("hi", _lage(), [])
    assert len(lauf.inhalte) == 1
    assert a.fehler is None
    assert a.bedenken == []
    assert a.vorschlag is not None and a.vorschlag.symbol == "BTCUSDT"


def test_cli_bekommt_systemtext_als_datei(monkeypatch):
    aufrufe: list[tuple[str, dict]] = []

    def falsches_run_cli(content, **kwargs):
        aufrufe.append((content, kwargs))
        return GUELTIG, "sid"

    monkeypatch.setattr(modul, "run_cli", falsches_run_cli)
    a = ClaudeSprecher().sprich("hi", _lage(), [])
    assert a.fehler is None
    assert len(aufrufe) == 1
    inhalt, kwargs = aufrufe[0]
    datei = Path(kwargs["system_file"])
    assert datei == Path(modul.__file__).with_name("system_prompt.md")
    assert datei.is_file()
    assert "urteilst nicht" not in inhalt and "## Lagebild" in inhalt


def test_lage_json_enthaelt_uebersicht_kompakt():
    lang = "unbekannt: HTTPException: no analysable data for SOLUSDT; run scripts/backfill.py"
    zeilen = [
        MarktZeile(
            symbol="ETHUSDT", preis=4_000.0, veraenderung_pct=2.5, richtung="long",
            rating=70, regime="Trend",
            setups=[
                Setup(timeframe="H4", side="long", entry=4e3, stop=3.9e3, target=4.2e3)
            ],
            letzte_trades=[{"side": "long", "r_multiple": 1.2}], quellen={},
        ),
        MarktZeile(
            symbol="SOLUSDT", preis=None, veraenderung_pct=None, richtung=None,
            rating=None, regime=None, setups=None, letzte_trades=[],
            quellen={"kurs": lang, "score": "unbekannt: nicht rechtzeitig berechnet"},
        ),
    ]  # fmt: skip
    daten = json.loads(modul._lage_json(_lage().model_copy(update={"uebersicht": zeilen})))
    eth, sol = daten["uebersicht"]
    assert eth == {
        "symbol": "ETHUSDT",
        "preis": 4_000.0,
        "veraenderung_pct": 2.5,
        "richtung": "long",
        "rating": 70,
        "regime": "Trend",
        "setups": [
            {"timeframe": "H4", "side": "long", "entry": 4e3, "stop": 3.9e3, "target": 4.2e3}
        ],
        "letzte_trades": [{"side": "long", "r_multiple": 1.2}],
        "unbekannt": [],
    }
    assert sol["unbekannt"] == ["kurs", "score"]
    assert "quellen" not in sol
    assert "backfill" not in json.dumps(daten["uebersicht"])
    # Ohne Uebersicht bleibt das Feld da, als null.
    assert json.loads(modul._lage_json(_lage()))["uebersicht"] is None
