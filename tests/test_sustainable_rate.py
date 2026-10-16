"""Die Obergrenze des Taktes rechnet mit dem Mittelwert, nicht mit dem Median.

**Der Anlass.** `scripts/goal.py` rechnete `cap * 24 / np.median(holds_h)`,
waehrend sein eigener Docstring und die Beschriftung seiner Ausgabe beide
„mittlere Haltedauer" sagten. Bei dieser Verteilung ist der Unterschied kein
Detail: ueber 7.335 Replay-Trades Mittel 33,0 h gegen Median 6,7 h, Faktor
4,9. Daran hingen die Obergrenze (17,9 gegen 3,64 Trades/Tag), die Chancen
bis zur Frist (269 gegen 51) und das noetige Ergebnis je Trade.

Der erste Test ist der, der zaehlt: eine Verteilung, bei der Median und
Mittelwert weit auseinanderliegen, und die Zusicherung nennt beide Zahlen.
Ein Test auf einer symmetrischen Stichprobe waere unter der alten Formel
genauso gruen gewesen.
"""

from __future__ import annotations

import pytest

from traidingbrain.learn.target import sustainable_rate

#: Neun kurze Trades und einer, der zwei Wochen laeuft. Median 2 h,
#: Mittelwert 10 h -- genau die Form, die die Replay-Verteilung hat (90 %
#: -Quantil bei Setup B auf D1: 1.831 h).
SCHIEF = [2.0] * 9 + [82.0]


def test_die_formel_nimmt_den_mittelwert() -> None:
    rate = sustainable_rate(slots=5, holds_h=SCHIEF)
    assert rate == pytest.approx(5 * 24 / 10.0), "Mittelwert 10 h erwartet"
    assert rate != pytest.approx(5 * 24 / 2.0), "der Median waere 60/Tag"
    assert rate == pytest.approx(12.0)


def test_der_median_wuerde_hier_das_fuenffache_sagen() -> None:
    """Die Groesse des Fehlers, nicht nur sein Vorhandensein."""
    mit_mittel = sustainable_rate(slots=5, holds_h=SCHIEF)
    median_formel = 5 * 24 / 2.0
    assert median_formel / mit_mittel == pytest.approx(5.0)


def test_der_live_verlauf_bestaetigt_den_mittelwert() -> None:
    """Die Messung, die zwischen beiden Formeln entschieden hat.

    28 abgeschlossene Trades vom 02.10. bis 15.10.2026 ueber 13,04 Tage sind
    2,15 Abschluesse je Tag. Haltedauer Median 9,8 h, Mittel 19,6 h, Deckel
    ueberwiegend 2. Der Mittelwert trifft auf 12 %, der Median liegt um
    128 % zu hoch -- das ist kein Rundungsunterschied, sondern eine
    Entscheidung.
    """
    gemessen = 28 / 13.04

    mit_mittel = sustainable_rate(slots=2, holds_h=[19.6])
    assert mit_mittel == pytest.approx(2.449, abs=0.01)
    assert abs(mit_mittel / gemessen - 1) < 0.15, "der Mittelwert trifft"

    mit_median = 2 * 24 / 9.8
    assert abs(mit_median / gemessen - 1) > 1.0, "der Median liegt um >100 % zu hoch"


def test_mehr_plaetze_heben_die_grenze_linear() -> None:
    eins = sustainable_rate(slots=1, holds_h=SCHIEF)
    fuenf = sustainable_rate(slots=5, holds_h=SCHIEF)
    assert fuenf == pytest.approx(5 * eins)


@pytest.mark.parametrize(
    ("slots", "holds"),
    [
        (5, []),        # keine Haltedauer bekannt
        (0, SCHIEF),    # kein Platz
        (-1, SCHIEF),   # unsinniger Deckel
        (5, [0.0]),     # Dauer null
    ],
)
def test_ohne_grundlage_null_statt_unendlich(slots: int, holds: list[float]) -> None:
    """Keine Division durch null und keine erfundene Obergrenze.

    Eine Obergrenze von `inf` waere die gefaehrlichste Ausgabe dieser
    Funktion: sie wuerde jede Frist erreichbar aussehen lassen.
    """
    assert sustainable_rate(slots=slots, holds_h=holds) == 0.0
