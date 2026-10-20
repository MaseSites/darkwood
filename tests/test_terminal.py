"""Das Darkwood Terminal: die reinen Rechnungen, ohne Netz.

Die Endpunkte, die Binance oder den Kalender fragen, werden hier NICHT
geprueft -- ein Test, der vom Netz abhaengt, ist mal gruen und mal rot und sagt
beides Mal nichts. Geprueft wird, was aus gegebenen Zahlen folgt: die Sterne,
die Richtung, die Zuordnung der sieben Familien zu den acht Karten, und das
Verhalten bei fehlenden Quellen (ehrlich "noch keine Messung" statt einer
erfundenen Null).
"""

from __future__ import annotations

from traidingbrain.api.terminal import Kalender, Orderbuch, _richtung, _sterne, score


def _score_read(**over):
    fams = [
        {"family": "trend", "direction": "aufwärts", "contribution": 0.20, "agreement": 0.6, "silent": False},
        {"family": "momentum", "direction": "aufwärts", "contribution": 0.10, "agreement": 0.5, "silent": False},
        {"family": "volatility", "direction": "aufwärts", "contribution": 0.10, "agreement": 0.5, "silent": False},
        {"family": "volume", "direction": "aufwärts", "contribution": 0.15, "agreement": 0.6, "silent": False},
        {"family": "structure", "direction": "aufwärts", "contribution": 0.0, "agreement": 0.2, "silent": True},
        {"family": "location", "direction": "abwärts", "contribution": -0.40, "agreement": 0.7, "silent": False},
        {"family": "liquidity", "direction": "aufwärts", "contribution": 0.30, "agreement": 0.8, "silent": False},
    ]
    base = {"families": fams, "bullish": 0.85, "bearish": 0.40, "rating": 52, "band": "gemischt",
            "regime": "Seitwärts", "headline": "x"}
    base.update(over)
    return base


def test_sterne_und_richtung_sind_monoton() -> None:
    assert _sterne(0.0) == 0 and _sterne(1.0) == 5 and _sterne(0.5) in (2, 3)
    assert _sterne(7.0) == 5, "ueber 1 wird gedeckelt, nicht ueberlaufen"
    assert _richtung(50) == "long" and _richtung(-50) == "short" and _richtung(3) == "neutral"


def test_acht_karten_und_vier_chartkarten_aus_sieben_familien() -> None:
    buch = Orderbuch(symbol="BTCUSDT", bids=[[1, 2]], asks=[[2, 1]], bid_total=2, ask_total=1,
                     bid_share_pct=66.7, spread_bp=0.5, ts=0)
    kal = Kalender(events=[], high_within_24h=0, next_high_hours=None, risk_pct=0, note="")
    s = score("BTCUSDT", _score_read(), {"setups": [], "gate": {}, "events": [], "bands": []}, buch, kal, [])
    assert [k.key for k in s.cards] == ["kalender", "orderbuch", "chart", "liquiditaet", "volumen",
                                        "priceaction", "entry", "history"]
    assert [k.key for k in s.chart_cards] == ["zonen", "chartpattern", "candles", "trend"]
    # 0.85 gegen 0.40 -> 68 % long.
    assert s.long_pct == 68 and s.short_pct == 32 and s.direction == "long"
    # Die Lage-Familie zeigt abwaerts: ihre Karte traegt ein negatives Prozent.
    zonen = next(k for k in s.chart_cards if k.key == "zonen")
    assert zonen.pct < 0 and zonen.direction == "short"
    # 66.7 % Gebote -> Orderbuch positiv.
    ob = next(k for k in s.cards if k.key == "orderbuch")
    assert ob.pct > 0 and ob.direction == "long"


def test_fehlende_quellen_sind_keine_null_sondern_keine_messung() -> None:
    s = score("ETHUSDT", _score_read(), {"setups": [], "gate": {}, "events": [], "bands": []}, None, None, [])
    kal = next(k for k in s.cards if k.key == "kalender")
    ob = next(k for k in s.cards if k.key == "orderbuch")
    hist = next(k for k in s.cards if k.key == "history")
    assert kal.measured is False and ob.measured is False and hist.measured is False
    assert kal.pct == 0 and ob.stars == 0


def test_entry_karte_folgt_dem_setup() -> None:
    chart = {"setups": [{"key": "A", "side": "short", "reward_risk": 1.5}], "gate": {"would_ask": True},
             "events": [], "bands": []}
    s = score("SOLUSDT", _score_read(), chart, None, None, [])
    entry = next(k for k in s.cards if k.key == "entry")
    assert entry.direction == "short" and entry.pct == -100 and "A" in entry.text


def test_history_karte_rechnet_treffer_und_summe() -> None:
    rows = [{"symbol": "LTCUSDT", "r_multiple": -1.2}, {"symbol": "LTCUSDT", "r_multiple": 1.3},
            {"symbol": "BTCUSDT", "r_multiple": 2.0}]
    s = score("LTCUSDT", _score_read(), {"setups": [], "gate": {}, "events": [], "bands": []}, None, None, rows)
    h = next(k for k in s.cards if k.key == "history")
    assert h.measured and "2 Trades" in h.text and "50 % Treffer" in h.text and "+0.10 R" in h.text


def test_dashboard_und_haendler_bilden_denselben_signaturzusatz() -> None:
    """Der Fehler vom 20.10. mittags, mechanisch ausgeschlossen.

    Das Dashboard suchte seine Trades unter `plan30x7`, waehrend der Haendler --
    nach einem Apply im Terminal -- unter `plan50x10` schreiben kann. Beide
    muessen denselben Zusatz aus derselben Funktion bilden, sonst ist die
    Trade-Ansicht nach dem ersten Apply leer und die Verlustbremsen blind.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import plantrade
    import run_dashboard

    assert plantrade.signatur_zusatz(0.30, 7.0) == "plan30x7"
    assert plantrade.signatur_zusatz(0.50, 10.0) == "plan50x10"
    assert plantrade.signatur_zusatz(0.25, 7.5) == "plan25x7.5"
    speicher, zusatz, etikett, _port, _einsatz = run_dashboard.KONTEN["plan"]
    assert speicher == plantrade.STATE_NAME
    assert zusatz == plantrade.SIGNATUR_ZUSATZ
    assert str(int(round(plantrade.MARGIN_ANTEIL * 100))) in etikett


def test_orderbuchtiefe_rastet_auf_eine_erlaubte_zahl_ein() -> None:
    """Binance nimmt nur 5/10/20/50/100/500/1000; alles andere ist HTTP 400.

    Am 20.10. fragte das Terminal mit `limit=40` (aus `min(50, depth)`), bekam
    400 und meldete es als 502 "Quelle nicht erreichbar" -- es sah aus, als
    waere die Boerse weg, und war ein falscher Parameter. Die Liste ersetzt
    den Bereich, weil ein Bereich genau diese Luecke laesst.
    """
    from traidingbrain.api.terminal import BINANCE_TIEFEN

    def einrasten(depth: int) -> int:
        return min((t for t in BINANCE_TIEFEN if t >= depth), default=BINANCE_TIEFEN[-1])

    assert einrasten(40) == 50, "40 ist keine erlaubte Tiefe und muss aufgerundet werden"
    assert einrasten(10) == 10
    assert einrasten(1) == 5
    assert einrasten(99) == 100
    assert einrasten(5000) == 1000
    for d in range(1, 120):
        assert einrasten(d) in BINANCE_TIEFEN
