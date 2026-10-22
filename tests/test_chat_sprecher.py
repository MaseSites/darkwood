"""Der Sprecher: liest Claudes Antwort, urteilt nie, fragt hoechstens einmal nach."""
import json

from traidingbrain.api.chat.modelle import Lage
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
    assert "meine Frage" in inhalt and "urteilst nicht" in inhalt


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
