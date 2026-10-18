"""Die Marke wird gerechnet, nicht getragen — und Prosa darf nicht abweichen.

**Der Anlass ist ein eigener Fehler, am 18.10.2026 von einem unabhängigen
Prüfer gefunden.** Ich habe einen ganzen Arbeitsabend mit **+0.42 R** als
Anforderung für das 20x-Sechsmonatsziel gerechnet. Die Zahl gehört zu einem
anderen Ziel und einem anderen Fenster:

    Faktor 1,25 (12.000 -> 15.000) über 51 Trades bei 1 %  =  +0.4385 R
    Faktor 20    über sechs Monate (662 Trades) bei 1 %     =  +0.4537 R
    Faktor 20    über 51 Trades bei 1 %                     =  +6.0499 R

Die ersten beiden sehen fast gleich aus, und genau das war die Falle. Die 51
Gelegenheiten sind das kurze Fenster bis 30.10.2026; die sechs Monate sind 662.

Dazu zwei Folgefehler, **beide in der günstigen Richtung**:

* „+0.42 R liegt beim 5-fachen der oberen Intervallgrenze" — richtig ist das
  7,07-fache gegen meine eigene Zahl, das 8,35-fache gegen die korrekte Marke
  und das operative Intervall.
* `scripts/study_venue_fee.py` trug eine dritte Marke: +0.3216 R aus
  20x / 312 Trades / **3 %** Risiko.

**Warum ein Test und nicht nur ein korrigierter Satz.** Drei unverträgliche
Marken sind an einem Abend entstanden, weil die Zahl in Prosa wanderte. Ein
Dokument, das eine Zahl nennt, kann von der Arithmetik abdriften, ohne dass
etwas rot wird. Diese Datei nagelt die Zahlen fest, die in den Auditdokumenten
stehen — ändert sich eine Annahme, fällt der Test, und dann gehören die
Dokumente nachgezogen.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from traidingbrain.learn.target import required_mean_r, sustainable_rate

FILLS = Path("data/replay_fills")

#: Platzdeckel aus `config/risk.yaml`, und die Horizonte der zwei Ziele.
SLOTS = 5
TAGE_6M = 182.0
TRADES_FRIST = 51.0


def _halte_und_r() -> tuple[list[float], list[float]]:
    if not FILLS.exists():
        pytest.skip(f"{FILLS} fehlt -- scripts/replay_all_markets.py zuerst")
    halte: list[float] = []
    r: list[float] = []
    for path in sorted(FILLS.glob("*.json")):
        for row in json.loads(path.read_text(encoding="utf-8"))["fills"]:
            halte.append((int(row["closed_ts"]) - int(row["opened_ts"])) / 3_600_000.0)
            r.append(float(row["r_multiple"]))
    if not halte:
        pytest.skip("keine Fills")
    return halte, r


# --------------------------------------------------------------------------- #
# 1. Die Marken, gegeneinander festgenagelt
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("ziel", "trades", "risiko", "erwartet"),
    [
        # Die RICHTIGE Marke fuer das Sechsmonatsziel.
        (20.0, 662.0, 0.01, 0.4536),
        # Woher meine +0.42 R wirklich kamen: anderes Ziel, anderes Fenster.
        (1.25, 51.0, 0.01, 0.4385),
        # Was ich implizit behauptet habe, als ich die beiden verknuepfte.
        (20.0, 51.0, 0.01, 6.0499),
        # Die dritte Marke aus study_venue_fee.py.
        (20.0, 312.0, 0.03, 0.3216),
        # Und der Kandidat A auf D1+H4 an SEINER Kadenz.
        (20.0, 401.0, 0.01, 0.7499),
    ],
)
def test_die_marken_sind_die_dokumentierten(
    ziel: float, trades: float, risiko: float, erwartet: float
) -> None:
    assert required_mean_r(growth=ziel, trades=trades, risk=risiko) == pytest.approx(
        erwartet, abs=5e-5
    )


def test_die_beiden_aehnlichen_marken_gehoeren_zu_verschiedenen_zielen() -> None:
    """Der Kern des Fehlers: +0.4385 und +0.4536 sehen gleich aus.

    Sie unterscheiden sich um 3 %, und ihre Ziele um Faktor 16. Wer die eine
    fuer die andere nimmt, hat sich nicht um 3 % geirrt.
    """
    frist = required_mean_r(growth=1.25, trades=TRADES_FRIST, risk=0.01)
    sechs_monate = required_mean_r(growth=20.0, trades=662.0, risk=0.01)
    assert abs(frist - sechs_monate) < 0.02, (
        "die beiden Marken liegen nahe beieinander -- das ist der Grund, warum "
        "dieser Test existiert"
    )
    assert pytest.approx(16.0) == 20.0 / 1.25, "und ihre Ziele um Faktor 16"


def test_weniger_trades_heissen_eine_hoehere_marke() -> None:
    """Die Kopplung, die eine geringere Frequenz wie eine Verbesserung aussehen laesst.

    Setup A auf D1+H4 hat weniger Trades als der Gesamtpool. Seine Marke ist
    darum HOEHER, nicht gleich -- und an der Gesamtmarke gemessen saehe es
    besser aus, als es ist.
    """
    pool = required_mean_r(growth=20.0, trades=662.0, risk=0.01)
    kandidat = required_mean_r(growth=20.0, trades=401.0, risk=0.01)
    assert kandidat > pool
    assert kandidat / pool == pytest.approx(1.653, abs=0.01)


def test_eine_marke_erreicht_ihr_ziel_und_nicht_mehr() -> None:
    """Die Gegenprobe in die andere Richtung, sonst ist die Formel nur geglaubt."""
    marke = required_mean_r(growth=20.0, trades=662.0, risk=0.01)
    assert (1.0 + marke * 0.01) ** 662.0 == pytest.approx(20.0, rel=1e-6)
    # Und was +0.42 R wirklich erreicht:
    assert pytest.approx(16.01, abs=0.05) == (1.0 + 0.42 * 0.01) ** 662.0
    assert pytest.approx(1.238, abs=0.002) == (1.0 + 0.42 * 0.01) ** 51.0


# --------------------------------------------------------------------------- #
# 2. Die Kadenz kommt aus den Daten, nicht aus einer Konstante
# --------------------------------------------------------------------------- #


def test_die_kadenz_stimmt_mit_der_dokumentierten() -> None:
    """3,64 Trades/Tag und 662 Trades, aus den Fills gerechnet.

    Faellt dieser Test, hat sich die Population geaendert -- und dann gehoeren
    die Marken in jedem Auditdokument nachgezogen, nicht dieser Test gelockert.
    """
    halte, _ = _halte_und_r()
    pro_tag = sustainable_rate(slots=SLOTS, holds_h=halte)

    assert statistics.fmean(halte) == pytest.approx(33.0, abs=0.5)
    assert pro_tag == pytest.approx(3.64, abs=0.05)
    assert pro_tag * TAGE_6M == pytest.approx(662.0, abs=10.0)


def test_der_median_gaebe_eine_fuenffach_zu_kleine_marke() -> None:
    """Warum Little's Law den Mittelwert braucht, als Zahl.

    Dieser Fehler ist in diesem Projekt schon einmal passiert und hat die
    Anforderung von +0.42 R auf +0.081 R gedrueckt.
    """
    halte, _ = _halte_und_r()
    mit_mittel = sustainable_rate(slots=SLOTS, holds_h=halte)
    mit_median = SLOTS / statistics.median(halte) * 24.0

    marke_mittel = required_mean_r(growth=20.0, trades=mit_mittel * TAGE_6M, risk=0.01)
    marke_median = required_mean_r(growth=20.0, trades=mit_median * TAGE_6M, risk=0.01)

    assert mit_median > 4.0 * mit_mittel
    assert marke_mittel > 4.0 * marke_median, (
        f"der Median gibt {marke_median:+.4f} R, der Mittelwert "
        f"{marke_mittel:+.4f} R -- der Unterschied ist die ganze Frage"
    )


# --------------------------------------------------------------------------- #
# 3. Und das Gemessene liegt darunter
# --------------------------------------------------------------------------- #


def test_das_gemessene_liegt_unter_jeder_marke() -> None:
    """Die eine Zusicherung, die das Ergebnis traegt.

    Keine der fuenf Marken ist erreicht, und der gemessene Punktwert ist
    negativ. Sollte dieser Test eines Tages fallen, ist das die wichtigste
    Nachricht des Projekts -- dann gehoert er gelesen und nicht repariert.
    """
    _, r = _halte_und_r()
    gemessen = statistics.fmean(r)
    assert gemessen < 0.0, f"gemessen {gemessen:+.4f} R"
    for ziel, trades, risiko in (
        (20.0, 662.0, 0.01),
        (1.25, 51.0, 0.01),
        (20.0, 401.0, 0.01),
        (20.0, 312.0, 0.03),
    ):
        assert gemessen < required_mean_r(growth=ziel, trades=trades, risk=risiko)
