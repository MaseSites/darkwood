"""Die Berichte werden mitgeprüft, nicht nur geschrieben.

**Warum das ein Test ist und kein Skript, das man gelegentlich startet.** Am
10. und 11.10.2026 sind in einer einzigen Sitzung vier falsche Zahlen in die
eigenen Berichte geraten:

* eine Startzeit, die geschrieben statt gelesen wurde — in einem Bericht,
  dessen Gegenstand ein Zeitfenster ist;
* „4 von 21 Trades geblockt" als Argument für eine Bremse, ohne nachzusehen,
  **welche** — zwei davon waren die grössten Gewinner, und die Bremse hätte
  Geld gekostet statt gespart;
* „die Replay-Population ist zuverlässig negativ" auf einer Population, die
  ein abgeschaltetes Setup enthält und ein aktives nicht;
* eine Trade-Rate von 1,9/Tag aus einer alten Messung über vier Märkte,
  gemessen 2,56.

Jeder war nachrechenbar, keiner ist aufgefallen, bis zufällig jemand hinsah.
Ein Prüfer, den man von Hand startet, wäre der fünfte Fehler derselben Art:
er liefe genau dann nicht, wenn man ihn braucht.

Was er **nicht** kann, und das gehört dazu: er prüft Zahlen gegen Daten, nicht
Schlüsse gegen Zahlen. Ein falsches Argument aus richtigen Zahlen geht hier
durch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from verify_claims import FACTS, reproduction_commands  # noqa: E402


def test_every_reproduction_command_names_a_script_that_exists() -> None:
    """Ein Bericht, dessen Befehl ins Leere zeigt, ist nicht reproduzierbar."""
    commands = reproduction_commands()
    assert commands, (
        "kein einziger Reproduktionsbefehl gefunden -- entweder sind die Berichte "
        "verschwunden oder das Muster in verify_claims.py passt nicht mehr. "
        "Beides ist ein Befund."
    )
    missing = [
        (doc.name, script)
        for doc, scripts in commands.items()
        for script in sorted(scripts)
        if not (PROJECT_ROOT / script).exists()
    ]
    assert not missing, (
        "diese Berichte nennen Skripte, die es nicht gibt:\n  "
        + "\n  ".join(f"{doc} -> {script}" for doc, script in missing)
    )


@pytest.mark.parametrize("fact", FACTS, ids=lambda f: f.label)
def test_the_reports_still_match_the_data(fact) -> None:
    """Jede Zahl, die ein Bericht als Konstante führt, gegen die Daten."""
    got = fact.measure()
    if got is None:
        pytest.skip(f"{fact.label}: Datenquelle nicht vorhanden")
    if fact.fixed:
        assert got == fact.expected, (
            f"{fact.label}: die Berichte sagen {fact.expected}, gemessen ist {got}. "
            f"Fundstelle: {fact.where}. Ein Bericht, dessen Zahl nicht mehr stimmt, "
            f"ist nicht halb richtig -- er ist falsch, bis jemand ihn korrigiert."
        )
    else:
        assert isinstance(got, int) and got >= fact.expected, (
            f"{fact.label}: erwartet mindestens {fact.expected}, gemessen {got}. "
            f"Diese Groesse darf wachsen, aber nicht schrumpfen. Fundstelle: {fact.where}."
        )
