"""Die Vorwärtsrichtung macht das Risiko sichtbar — das ist ihr ganzer Zweck.

**Der Anlass.** „300 Franken von 1.000, 7-facher Hebel" ist eine vollständige
Anweisung und eine unvollständige Beschreibung. Was sie verschweigt, hat dieses
Projekt am 19.10.2026 über 7.335 Trades gemessen:

    Verlust am Stop, als Anteil des Kontos
      Median           4,38 %
      95. Perzentil   15,07 %
      99. Perzentil   30,62 %
    Trades mit Stop JENSEITS der Liquidation: 88 von 7.335 (1,20 %)

Keine dieser Zahlen steht in „300 CHF bei 7x". Alle stehen in `PlanSize`, und
diese Tests nageln fest, dass sie dort stehen **und stimmen**.
"""

from __future__ import annotations

import pytest

from traidingbrain.domain.enums import Side
from traidingbrain.risk.plansize import (
    UnsizeablePlanError,
    plan_size,
    portfolio_load,
)

#: Severins Plan, wörtlich: 300 von 1.000 Franken, siebenfacher Hebel.
KONTO, ANTEIL, HEBEL = 1_000.0, 0.30, 7.0


def _plan(**ueberschreiben: object):
    felder: dict[str, object] = {
        "equity": KONTO,
        "margin_share": ANTEIL,
        "leverage": HEBEL,
        "entry": 100.0,
        "stop": 98.0,          # 2 % entfernt, nahe am gemessenen Median
        "side": Side.LONG,
    }
    felder.update(ueberschreiben)
    return plan_size(**felder)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. Die Zahl, die in der Anweisung fehlt
# --------------------------------------------------------------------------- #


def test_der_plan_wird_vollstaendig_beschrieben() -> None:
    p = _plan()
    assert p.margin == pytest.approx(300.0)
    assert p.margin_share == pytest.approx(0.30)
    assert p.notional == pytest.approx(2_100.0)
    assert p.stop_fraction == pytest.approx(0.02)


def test_das_risiko_ist_ein_ergebnis_und_keine_eingabe() -> None:
    """Der Kern des Moduls.

    2 % Stopabstand auf 2.100 Nominal sind 42 Franken -- also **4,2 % des
    Kontos**, nicht die 1 %, die die Konfiguration sonst setzt. Die Zahl kommt
    in „300 CHF bei 7x" nicht vor und ist trotzdem das, worauf es ankommt.
    """
    p = _plan()
    assert p.loss_at_stop == pytest.approx(42.0)
    assert p.loss_at_stop_share == pytest.approx(0.042)


def test_ein_weiterer_stop_riskiert_mehr_bei_gleicher_margin() -> None:
    """Dieselbe Anweisung, anderer Markt -- und viermal so viel Risiko.

    Das ist der Grund, warum eine Grössenregel nicht aus Margin und Hebel
    allein bestehen darf: die Stopweite entscheidet mit, und sie schwankt im
    gemessenen Bestand zwischen 1,36 % und 14,58 %.
    """
    eng = _plan(stop=98.0)      # 2 %
    weit = _plan(stop=92.0)     # 8 %
    assert eng.loss_at_stop_share == pytest.approx(0.042)
    assert weit.loss_at_stop_share == pytest.approx(0.168)
    assert weit.loss_at_stop_share == pytest.approx(4 * eng.loss_at_stop_share)


# --------------------------------------------------------------------------- #
# 2. Die Börse schliesst manchmal zuerst
# --------------------------------------------------------------------------- #


def test_die_liquidation_wird_mitgerechnet() -> None:
    """Bei 7x und 0,5 % Wartungsmarge liegt sie 13,79 % entfernt."""
    p = _plan()
    assert p.liquidation_fraction == pytest.approx(1 / 7 - 0.005)
    assert p.liquidation_fraction == pytest.approx(0.13786, abs=1e-5)
    assert p.liquidation_price == pytest.approx(100.0 * (1 - p.liquidation_fraction))
    assert not p.stop_beyond_liquidation


def test_ein_stop_jenseits_der_liquidation_wird_gemeldet() -> None:
    """Die 88 von 7.335 Trades (1,20 %), bei denen der Plan eine Fiktion ist.

    Der Stop liegt 15 % entfernt, die Liquidation bei 13,79 % -- die Börse
    schliesst zuerst, und verloren ist die ganze Margin, nicht der geplante
    Betrag.
    """
    p = _plan(stop=85.0)
    assert p.stop_beyond_liquidation
    assert p.loss_at_stop == pytest.approx(315.0)   # der PLAN
    assert p.effective_loss == pytest.approx(300.0)  # das ERGEBNIS
    assert p.effective_loss_share == pytest.approx(0.30)


def test_bei_kleinem_hebel_liegt_die_liquidation_weit_weg() -> None:
    p = _plan(leverage=1.0, margin_share=1.0)
    assert p.liquidation_fraction == pytest.approx(0.995)
    assert not p.stop_beyond_liquidation


def test_ein_short_liquidiert_nach_oben() -> None:
    p = _plan(entry=100.0, stop=102.0, side=Side.SHORT)
    assert p.liquidation_price > p.entry
    assert p.loss_at_stop_share == pytest.approx(0.042)


# --------------------------------------------------------------------------- #
# 3. Kosten gegen Risiko
# --------------------------------------------------------------------------- #


def test_die_kosten_stehen_als_anteil_des_risikos() -> None:
    """Der Deckel, den `max_cost_fraction_of_risk` prüft, steht mit in der Zeile."""
    p = _plan(cost_fraction=0.0011)      # maker ein, taker aus, grob
    assert p.cost == pytest.approx(2_100.0 * 0.0011)
    assert p.cost_share_of_risk == pytest.approx(p.cost / 42.0)


def test_ein_engerer_stop_macht_die_kosten_teurer_relativ_zum_risiko() -> None:
    """Warum der Kostendeckel enge Stops ablehnt -- in einer Zeile sichtbar."""
    eng = _plan(stop=99.0, cost_fraction=0.0011)
    weit = _plan(stop=92.0, cost_fraction=0.0011)
    assert eng.cost_share_of_risk > weit.cost_share_of_risk


# --------------------------------------------------------------------------- #
# 4. Mehrere Positionen sind nicht mehrere Wetten
# --------------------------------------------------------------------------- #


def test_zwoelf_positionen_riskieren_zwoelfmal() -> None:
    """Der Gleichlauf, als Zahl.

    Zwölf Positionen zu je 4,2 % riskieren nicht 4,2 %, sondern **50,4 %** --
    und bei einem gemessenen Beta von 1,0 zu BTC ist das kein Randfall, sondern
    der Normalfall an einem roten Tag.
    """
    last = portfolio_load([_plan() for _ in range(12)], equity=KONTO)
    assert last.positions == 12
    assert last.correlated_loss_share == pytest.approx(0.504)
    assert last.bound_margin == pytest.approx(3_600.0)
    assert last.bound_margin_share == pytest.approx(3.6)
    assert last.free_margin == pytest.approx(-2_600.0)
    assert last.is_overcommitted


def test_eine_einzelne_position_ist_nicht_ueberzogen() -> None:
    last = portfolio_load([_plan()], equity=KONTO)
    assert last.bound_margin_share == pytest.approx(0.30)
    assert last.free_margin == pytest.approx(700.0)
    assert not last.is_overcommitted


def test_ein_liquidierter_plan_zaehlt_mit_seinem_echten_verlust() -> None:
    """Sonst meldete das Portfolio einen Verlust, den es nicht geben kann."""
    last = portfolio_load([_plan(stop=85.0), _plan()], equity=KONTO)
    assert last.correlated_loss == pytest.approx(300.0 + 42.0)


# --------------------------------------------------------------------------- #
# 5. Was keine Position ist, wird abgelehnt
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("felder", "text"),
    [
        ({"margin_share": 0.0}, "margin_share"),
        ({"margin_share": 1.5}, "margin_share"),
        ({"leverage": 0.0}, "Hebel"),
        ({"stop": 100.0}, "kein Risiko"),
        ({"stop": 102.0}, "Long mit Stop"),
        ({"stop": 98.0, "side": Side.SHORT}, "Short mit Stop"),
    ],
)
def test_unmoegliche_eingaben_werden_abgelehnt(
    felder: dict[str, object], text: str
) -> None:
    with pytest.raises(UnsizeablePlanError, match=text):
        _plan(**felder)


def test_die_beschreibung_nennt_die_entscheidende_zahl() -> None:
    """Ein Satz, der nicht verschweigt, was „300 bei 7x" verschweigt."""
    zeile = _plan().describe()
    assert "4.20% des Kontos" in zeile or "4,20" in zeile.replace(".", ",")
    assert "Liquidation" in zeile


def test_die_beschreibung_warnt_bei_liquidation_vor_dem_stop() -> None:
    assert "ACHTUNG" in _plan(stop=85.0).describe()
