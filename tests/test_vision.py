"""Das Chartbild: gezeichnet ohne Blick in die Zukunft, im Schatten beurteilt, im Chat gezeigt."""
import io
import json
from types import SimpleNamespace

import pandas as pd
from PIL import Image

from tests.test_chat_sprecher import GUELTIG, _Lauf, _lage
from traidingbrain.api.chat import bild as chat_bild
from traidingbrain.api.chat.sprecher import ClaudeSprecher
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.vision import frage, schatten
from traidingbrain.vision.render import (
    BREITE,
    PANEL_HOEHE,
    Linie,
    Panel,
    _verteile,
    nur_bis,
    zeichne,
)
from traidingbrain.vision.schatten import Schatten, SchattenSpeicher

START = 1_760_000_000_000


def _kerzen(tf: Timeframe, n: int = 200, start: int = START) -> pd.DataFrame:
    schritt = timeframe_ms(tf)
    ts = [start + i * schritt for i in range(n)]
    close = [100.0 + (i % 17) - (i % 5) for i in range(n)]
    return pd.DataFrame({
        "ts": ts,
        "open": [c - 0.5 for c in close],
        "high": [c + 1.0 for c in close],
        "low": [c - 1.5 for c in close],
        "close": close,
        "volume": [10.0 + i % 7 for i in range(n)],
    })


# -- Zeichnen ------------------------------------------------------------------ #


def test_nur_bis_laesst_keine_offene_kerze_durch():
    """Eine H4-Kerze, die vor der Entscheidung begann und danach schloss, bleibt draussen."""
    h4 = _kerzen(Timeframe.H4, 10)
    schritt = timeframe_ms(Timeframe.H4)
    entscheidung = START + 5 * schritt + schritt // 2  # mitten in Kerze 5
    sichtbar = nur_bis(h4, entscheidung, bar_ms=schritt)
    assert int(sichtbar["ts"].max()) == START + 4 * schritt
    assert (sichtbar["ts"] + schritt <= entscheidung).all()


def test_nur_bis_nimmt_die_kerze_die_genau_zur_entscheidung_schliesst():
    m15 = _kerzen(Timeframe.M15, 10)
    schritt = timeframe_ms(Timeframe.M15)
    sichtbar = nur_bis(m15, START + 5 * schritt, bar_ms=schritt)
    assert int(sichtbar["ts"].max()) == START + 4 * schritt


def test_zeichne_liefert_ein_png_in_der_erwarteten_groesse():
    panels = [
        Panel("A M15", _kerzen(Timeframe.M15).tail(120), [Linie(105, "Einstieg", "entry")]),
        Panel("A H4", _kerzen(Timeframe.H4).tail(120), [Linie(90, "Stop", "stop")]),
    ]
    png = zeichne(panels, titel="Test")
    bild = Image.open(io.BytesIO(png))
    assert bild.format == "PNG"
    assert bild.size == (BREITE, 36 + 2 * PANEL_HOEHE)


def test_ein_leeres_panel_bricht_nicht():
    png = zeichne([Panel("leer", _kerzen(Timeframe.H1).iloc[0:0])])
    assert png.startswith(b"\x89PNG")


def test_beschriftungen_ueberdecken_sich_nicht():
    marken = _verteile([(100.0, "a", "x"), (101.0, "b", "x"), (102.0, "c", "x")], 0, 500)
    ys = [m[0] for m in marken]
    assert all(b - a >= 15 for a, b in zip(ys, ys[1:], strict=False))


# -- CLI mit Bild ---------------------------------------------------------------- #


def test_nachricht_traegt_bild_und_text():
    zeile = json.loads(frage.nachricht("Frage?", [b"\x89PNGabc"]))
    inhalt = zeile["message"]["content"]
    assert zeile["type"] == "user"
    assert inhalt[0]["type"] == "image"
    assert inhalt[0]["source"]["media_type"] == "image/png"
    assert inhalt[-1] == {"type": "text", "text": "Frage?"}


def test_aus_dem_strom_wird_die_ergebniszeile_gelesen():
    strom = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {}}),
        json.dumps({"type": "result", "is_error": False, "result": "Rot", "session_id": "s"}),
    ])
    assert json.loads(frage.ergebnis_zeile(strom))["result"] == "Rot"


# -- Schatten ------------------------------------------------------------------- #


def _pending(created_ts: int, pid: str = "BTCUSDT-1"):
    return SimpleNamespace(
        side=Side.LONG, limit_price=105.0, stop=98.0, target=115.0,
        created_ts=created_ts, proposal_id=pid, setup="A", timeframe="H1",
    )


def _haendler(pending, frames: dict[Timeframe, pd.DataFrame]):
    return SimpleNamespace(
        symbol="BTCUSDT",
        run_signature="sig|plan",
        broker=SimpleNamespace(pending=pending),
        store=SimpleNamespace(read=lambda _s, tf: frames[tf]),
        config=SimpleNamespace(
            engine=SimpleNamespace(timeframes=SimpleNamespace(signal=Timeframe.M15))
        ),
    )


def _frames():
    return {tf: _kerzen(tf, 400) for tf in schatten.EBENEN}


URTEIL = json.dumps({
    "urteil": "auslassen", "konfidenz": 62, "begruendung": "Ziel hinter Widerstand.",
    "muster": ["Widerstand"],
})


class _Fragen:
    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.aufrufe: list[tuple[str, list[bytes]]] = []

    def __call__(self, text, bilder):
        self.aufrufe.append((text, bilder))
        return self.antworten.pop(0), "sid"


def _schatten(tmp_path, fragen):
    return Schatten(
        SchattenSpeicher(tmp_path / "v.sqlite"), tmp_path / "bilder", fragen,
        modell="m", im_hintergrund=False,
    )


def test_eine_neue_order_wird_einmal_beurteilt_und_aufgeschrieben(tmp_path):
    fragen = _Fragen(URTEIL)
    s = _schatten(tmp_path, fragen)
    entscheidung = START + 300 * timeframe_ms(Timeframe.M15)
    h = _haendler(_pending(entscheidung), _frames())

    assert s.beobachte([h]) == 1
    assert s.beobachte([h]) == 0  # dieselbe Order, kein zweites Mal
    assert len(fragen.aufrufe) == 1
    text, bilder = fragen.aufrufe[0]
    assert "LONG" in text and bilder[0].startswith(b"\x89PNG")

    [zeile] = s.speicher.alle()
    assert zeile["urteil"] == "auslassen"
    assert zeile["konfidenz"] == 62
    assert zeile["run_signature"] == "sig|plan"
    assert zeile["fehler"] is None
    assert (tmp_path / "bilder" / "BTCUSDT-1.png").exists()


def test_nach_neustart_wird_dieselbe_order_nicht_neu_gefragt(tmp_path):
    entscheidung = START + 300 * timeframe_ms(Timeframe.M15)
    h = _haendler(_pending(entscheidung), _frames())
    _schatten(tmp_path, _Fragen(URTEIL)).beobachte([h])
    zweiter = _Fragen()
    assert _schatten(tmp_path, zweiter).beobachte([h]) == 0
    assert zweiter.aufrufe == []


def test_ohne_order_wird_nichts_gefragt(tmp_path):
    fragen = _Fragen()
    assert _schatten(tmp_path, fragen).beobachte([_haendler(None, _frames())]) == 0
    assert fragen.aufrufe == []


def test_unlesbare_antwort_wird_einmal_nachgefragt(tmp_path):
    fragen = _Fragen("kein json", URTEIL)
    s = _schatten(tmp_path, fragen)
    s.beobachte([_haendler(_pending(START + 300 * 900_000), _frames())])
    assert len(fragen.aufrufe) == 2
    assert "nicht lesbar" in fragen.aufrufe[1][0]
    assert s.speicher.alle()[0]["urteil"] == "auslassen"


def test_ein_ausfall_wird_als_fehler_aufgeschrieben_und_nie_geworfen(tmp_path):
    s = _schatten(tmp_path, _Fragen(None))
    s.beobachte([_haendler(_pending(START + 300 * 900_000), _frames())])
    [zeile] = s.speicher.alle()
    assert zeile["urteil"] is None
    assert "nicht geantwortet" in zeile["fehler"]


def test_kaputte_kerzen_halten_den_haendler_nicht_an(tmp_path):
    h = _haendler(_pending(START), {})  # jede Zeitebene fehlt -> KeyError beim Lesen
    assert _schatten(tmp_path, _Fragen()).beobachte([h]) == 0


def test_das_bild_endet_an_der_entscheidung(monkeypatch):
    gezeichnet: list[Panel] = []
    monkeypatch.setattr(schatten, "zeichne", lambda panels, **_: gezeichnet.extend(panels) or b"")
    entscheidung = START + 300 * timeframe_ms(Timeframe.M15) + 1
    frames = _frames()
    schatten.zeichne_auftrag(
        lies=lambda tf: frames[tf], pending=_pending(entscheidung),
        symbol="BTCUSDT", signal=Timeframe.M15, run_signature="",
    )
    assert [p.titel for p in gezeichnet] == ["BTCUSDT M15", "BTCUSDT H1", "BTCUSDT H4"]
    for panel, tf in zip(gezeichnet, schatten.EBENEN, strict=True):
        assert (panel.kerzen["ts"] + timeframe_ms(tf) <= entscheidung).all()


# -- Chat ----------------------------------------------------------------------- #


def test_chat_ebenen_sind_drei_von_fein_nach_grob():
    assert chat_bild.ebenen("M15") == [Timeframe.M15, Timeframe.H4, Timeframe.D1]
    assert chat_bild.ebenen("H4") == [Timeframe.H1, Timeframe.H4, Timeframe.D1]
    assert chat_bild.ebenen("quatsch") == [Timeframe.H1, Timeframe.H4, Timeframe.D1]


def test_chat_bild_aus_dem_speicher():
    frames = {tf: _kerzen(tf, 300) for tf in (Timeframe.H1, Timeframe.H4, Timeframe.D1)}
    png = chat_bild.chart_bild(
        lambda _s, tf: frames[tf], _lage(), jetzt_ms=START + 10**12
    )
    assert png is not None and png.startswith(b"\x89PNG")


def test_der_chat_schickt_das_bild_mit():
    bild_lauf = _Fragen(GUELTIG)
    text_lauf = _Lauf()
    a = ClaudeSprecher(
        lauf=text_lauf, bild=lambda _l: b"\x89PNGx", bild_lauf=bild_lauf
    ).sprich("wie sieht btc aus?", _lage(), [])
    assert a.fehler is None
    assert text_lauf.inhalte == []
    eingabe, bilder = bild_lauf.aufrufe[0]
    assert bilder == [b"\x89PNGx"]
    assert eingabe.startswith("## Chart")


def test_faellt_das_bild_aus_antwortet_der_chat_ohne():
    def kaputt(_l):
        raise OSError("kein Speicher")

    text_lauf = _Lauf(GUELTIG)
    bild_lauf = _Fragen()
    a = ClaudeSprecher(lauf=text_lauf, bild=kaputt, bild_lauf=bild_lauf).sprich("hi", _lage(), [])
    assert a.fehler is None
    assert bild_lauf.aufrufe == []
    assert "## Chart" not in text_lauf.inhalte[0]
