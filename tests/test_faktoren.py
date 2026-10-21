"""Die Zusicherungen der Aufschlüsselung — als Test, nicht als Kommentar.

Jede dieser Prüfungen steht für einen Satz, den die Oberfläche behauptet. Ein
Satz im Docstring, der nirgends geprüft wird, ist ein Vorsatz; geprüft ist er
eine Eigenschaft.
"""

from __future__ import annotations

import pytest

from traidingbrain.api import faktoren as F
from traidingbrain.journal.lehren import muster
from traidingbrain.score.engine import DEFAULT_FAMILY_WEIGHTS, REGIME_MODIFIERS
from traidingbrain.score.findings import TIMEFRAME_WEIGHTS


def test_gewichte_kommen_aus_der_engine_und_sind_keine_kopie() -> None:
    """Die Aufschlüsselung importiert die Tabellen, sie schreibt sie nicht ab.

    Wäre hier eine Kopie, zeigte die Oberfläche nach der ersten Änderung an der
    Engine einen Rechenweg, der das daneben stehende Rating nicht mehr erklärt.
    Dieser Test prüft Identität, nicht Gleichheit: dasselbe Objekt.
    """
    assert F.DEFAULT_FAMILY_WEIGHTS is DEFAULT_FAMILY_WEIGHTS
    assert F.REGIME_MODIFIERS is REGIME_MODIFIERS
    assert F.TIMEFRAME_WEIGHTS is TIMEFRAME_WEIGHTS


def test_kein_unterfaktor_traegt_eine_beitragszahl() -> None:
    """Eine Familie nimmt den Median, also gibt es keinen Beitrag je Mitglied.

    Das ist die naheliegendste Lüge dieses Bildschirms: eine Spalte „Beitrag"
    neben jeder Zeile, die sich zu etwas aufsummieren liesse. Sie existiert
    nicht, und dieser Test hält sie draussen.
    """
    felder = set(F.Unterfaktor.model_fields)
    assert "beitrag" not in felder
    assert "contribution" not in felder
    # Die FAMILIE hat einen Beitrag -- dort ist er echt.
    assert "beitrag" in F.FamilieZeile.model_fields


def test_jede_schwaeche_der_registry_ist_uebersetzt() -> None:
    """Sonst steht englischer Fliesstext unter deutscher Beschriftung."""
    from traidingbrain.score.registry import SPECS

    alle = {m for spec in SPECS.values() for m in spec.failure_modes}
    fehlend = alle - set(F.SCHWAECHE_DE)
    assert not fehlend, f"ohne Übersetzung: {sorted(fehlend)}"


def _band(lo: float, hi: float, von: int) -> dict:
    return {"low": lo, "high": hi, "kind": "equal_lows", "label": "gleiche Tiefs", "from_ts": von}


def _kerzen(n: int, lo: float, hi: float, schluss: float) -> list[dict]:
    return [{"ts": i * 1000, "low": lo, "high": hi, "close": schluss, "open": schluss}
            for i in range(n)]


def test_eine_zerschnittene_zone_wiegt_weniger_als_eine_unberuehrte() -> None:
    """Das ist der ganze Zweck der Bewertung: Zonen zu unterscheiden."""
    atr, preis = 10.0, 100.0
    kerzen = []
    # Zehn Kerzen, die abwechselnd ueber und unter der Zone schliessen:
    # jeder Wechsel ist ein Durchbruch.
    for i in range(10):
        s = 105.0 if i % 2 == 0 else 95.0
        kerzen.append({"ts": i * 1000, "low": 94.0, "high": 106.0, "close": s, "open": s})

    zerschnitten = F._zonen_messung(_band(99.0, 101.0, 0), kerzen, preis, atr)
    unberuehrt = F._zonen_messung(_band(99.0, 101.0, 0), [], preis, atr)

    assert zerschnitten["durchbrueche"] >= 8
    assert unberuehrt["beruehrungen"] == 0
    # Halt ist der Teil, der sie trennt.
    halt_zer = 1.0 - zerschnitten["durchbrueche"] / zerschnitten["beruehrungen"]
    assert halt_zer < 0.3


def test_ein_docht_ist_eine_beruehrung_und_kein_bruch() -> None:
    """Anders herum haette jeder Volatilitätsschub alle Zonen gebrochen."""
    # Die Kerze reicht durch die Zone, schliesst aber darunter -- und bleibt
    # dort. Also genau EINE Seite, kein Wechsel, kein Bruch.
    kerzen = [{"ts": 0, "low": 90.0, "high": 110.0, "close": 95.0, "open": 95.0},
              {"ts": 1000, "low": 92.0, "high": 108.0, "close": 94.0, "open": 94.0}]
    m = F._zonen_messung(_band(99.0, 101.0, 0), kerzen, 100.0, 10.0)
    assert m["beruehrungen"] == 2
    assert m["durchbrueche"] == 0


def test_die_breite_zone_ist_keine_zone() -> None:
    """Über eine ganze ATR hinaus ist es eine Gegend, und die Schärfe faellt auf null."""
    schmal = F._zonen_messung(_band(99.5, 100.5, 0), [], 100.0, 10.0)
    breit = F._zonen_messung(_band(80.0, 120.0, 0), [], 100.0, 10.0)
    assert schmal["breite_atr"] < 0.2
    assert breit["breite_atr"] > 1.0


@pytest.mark.parametrize(("serie", "erwartet"), [(3, 12.5), (5, 3.125), (7, 0.78125)])
def test_die_serienwahrscheinlichkeit_ist_die_muenze(serie: int, erwartet: float) -> None:
    """Drei Verluste in Folge sind jeder achte Fall — und das muss danebenstehen."""
    zeilen = [
        {"setup": "X", "setup_name": "X", "r_multiple": -1.0, "net_pnl": -10.0, "closed_ts": i}
        for i in range(serie)
    ]
    m = muster(zeilen)[0]
    assert m.serie == -serie
    assert m.zufall_pct == pytest.approx(erwartet, abs=0.01)


def test_das_journal_schlaegt_keine_parameteraenderung_vor() -> None:
    """Eine laufende Hypothese wegen einer Verlustserie abzuschalten waere
    dieselbe Sünde wie eine gescheiterte nachträglich zu retten."""
    zeilen = [
        {"setup": "G", "setup_name": "G", "r_multiple": -1.0, "net_pnl": -20.0, "closed_ts": i}
        for i in range(8)
    ]
    befund = muster(zeilen)[0].befund.lower()
    for verboten in ("abschalten", "deaktivier", "stopp", "nicht mehr handeln", "aussetzen"):
        assert verboten not in befund, f"das Journal empfiehlt etwas: {verboten!r}"


def test_der_widerspruch_zwischen_r_und_geld_wird_benannt() -> None:
    """Positiv in R und negativ in Geld sieht aus wie ein Fehler und ist keiner."""
    zeilen = [
        # Zwei kleine Gewinner, ein grosser Verlierer: in R positiv, in Geld negativ.
        {"setup": "B", "setup_name": "B", "r_multiple": +1.5, "net_pnl": +5.0, "closed_ts": 1},
        {"setup": "B", "setup_name": "B", "r_multiple": +1.5, "net_pnl": +5.0, "closed_ts": 2},
        {"setup": "B", "setup_name": "B", "r_multiple": -1.0, "net_pnl": -50.0, "closed_ts": 3},
        {"setup": "B", "setup_name": "B", "r_multiple": +1.5, "net_pnl": +5.0, "closed_ts": 4},
        {"setup": "B", "setup_name": "B", "r_multiple": -1.0, "net_pnl": -40.0, "closed_ts": 5},
    ]
    m = muster(zeilen)[0]
    assert m.mittel_r > 0 and m.summe_usd < 0
    assert "Widerspruch" in m.befund
    assert "risikonormiert" in m.befund or "normiert" in m.befund


def test_wenige_trades_nennen_keine_quote() -> None:
    """Unter fünf ist eine Trefferquote eine Aufzählung."""
    zeilen = [{"setup": "C", "setup_name": "C", "r_multiple": -1.0, "net_pnl": -5.0, "closed_ts": i}
              for i in range(2)]
    befund = muster(zeilen)[0].befund
    assert "%" not in befund.split("Treffer")[0] or "Treffer" not in befund
    assert "Zu wenige" in befund
