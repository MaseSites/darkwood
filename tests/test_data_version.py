"""Der Datenstempel muss eine Revision fangen -- sonst ist er keine Datenversion.

**Der Anlass.** In diesem Projekt ist festgehalten, dass der
Zukunfts-Mutationstest über einen Fall schweigt: eine Quelle, die ihre eigene
*Vergangenheit* umschreibt. Der Test verändert nur Balken NACH dem Index, also
kann er eine Revision nicht sehen. Ein Datenstempel, der dieselbe Blindheit hat,
würde sie fortschreiben -- und zwei Läufe über verschiedene Daten gleich
stempeln.

Darum prüft diese Datei beide Formen gegen genau diesen Fall, und zwar so, dass
die Blindheit der billigen Form **belegt** ist statt behauptet: derselbe
revidierte Rahmen bewegt `content:` und bewegt `coverage:` nicht.
"""

from __future__ import annotations

import pandas as pd
import pytest

from traidingbrain.data.dataversion import content_version, coverage_version
from traidingbrain.domain.enums import Timeframe

H1_MS = 3_600_000


def _rahmen(n: int = 50, *, ab: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": [1_700_000_000_000 + i * H1_MS for i in range(n)],
            "open": [ab + i for i in range(n)],
            "high": [ab + i + 1 for i in range(n)],
            "low": [ab + i - 1 for i in range(n)],
            "close": [ab + i + 0.5 for i in range(n)],
            "volume": [1_000.0 + i for i in range(n)],
        }
    )


def _rahmen_satz(n: int = 50, *, ab: float = 100.0) -> dict[Timeframe, pd.DataFrame]:
    return {Timeframe.H1: _rahmen(n, ab=ab), Timeframe.H4: _rahmen(n // 4, ab=ab)}


# --------------------------------------------------------------------------- #
# Die Revision -- der Fall, um den es geht
# --------------------------------------------------------------------------- #


def test_eine_revision_bewegt_den_inhaltsstempel() -> None:
    """Ein geänderter Schlusskurs IN DER VERGANGENHEIT, Fenster unverändert."""
    vorher = _rahmen_satz()
    nachher = _rahmen_satz()
    nachher[Timeframe.H1].loc[10, "close"] = 999.0

    assert content_version(vorher) != content_version(nachher)


def test_dieselbe_revision_bewegt_den_abdeckungsstempel_nicht() -> None:
    """Die Blindheit der billigen Form, belegt statt behauptet.

    Das ist kein Defekt, sondern der Grund, warum die Methode im Wert steht.
    Fällt dieser Test eines Tages, ist `coverage_version` strenger geworden --
    und dann gehört der Modultext nachgezogen, nicht der Test gelöscht.
    """
    vorher = _rahmen_satz()
    nachher = _rahmen_satz()
    nachher[Timeframe.H1].loc[10, "close"] = 999.0

    assert coverage_version(vorher) == coverage_version(nachher)


def test_die_zwei_methoden_sind_nie_verwechselbar() -> None:
    """Der Wert trägt seine Methode vorne, also kann kein Vergleich sie mischen."""
    rahmen = _rahmen_satz()
    assert content_version(rahmen).startswith("content:")
    assert coverage_version(rahmen).startswith("coverage:")
    assert content_version(rahmen) != coverage_version(rahmen)


# --------------------------------------------------------------------------- #
# Was beide Formen fangen müssen
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stempel", [content_version, coverage_version])
def test_mehr_daten_bewegen_jeden_stempel(stempel: object) -> None:
    assert stempel(_rahmen_satz(50)) != stempel(_rahmen_satz(60))  # type: ignore[operator]


@pytest.mark.parametrize("stempel", [content_version, coverage_version])
def test_eine_fehlende_zeitebene_bewegt_jeden_stempel(stempel: object) -> None:
    voll = _rahmen_satz()
    teil = {Timeframe.H1: voll[Timeframe.H1]}
    assert stempel(voll) != stempel(teil)  # type: ignore[operator]


@pytest.mark.parametrize("stempel", [content_version, coverage_version])
def test_ein_leerer_rahmen_ist_nicht_dasselbe_wie_keiner(stempel: object) -> None:
    """Sonst sähe „die Zeitebene fehlt" aus wie „sie ist da und leer"."""
    leer = {Timeframe.H1: _rahmen(0), Timeframe.H4: _rahmen(12)}
    ohne = {Timeframe.H4: _rahmen(12)}
    assert stempel(leer) != stempel(ohne)  # type: ignore[operator]


@pytest.mark.parametrize("stempel", [content_version, coverage_version])
def test_derselbe_satz_liefert_denselben_stempel(stempel: object) -> None:
    """Über Prozessgrenzen hinweg -- `hashlib`, nicht `hash()`."""
    assert stempel(_rahmen_satz()) == stempel(_rahmen_satz())  # type: ignore[operator]
    assert len(stempel(_rahmen_satz()).split(":")[1]) == 12  # type: ignore[union-attr]


def test_die_reihenfolge_der_zeitebenen_ist_belanglos() -> None:
    """Ein Stempel, der von der Einfügereihenfolge abhängt, trennt nichts."""
    a = {Timeframe.H1: _rahmen(50), Timeframe.H4: _rahmen(12)}
    b = {Timeframe.H4: _rahmen(12), Timeframe.H1: _rahmen(50)}
    assert content_version(a) == content_version(b)
    assert coverage_version(a) == coverage_version(b)
