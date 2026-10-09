"""Der Fehlerquoten-Alarm des Papierhandels.

**Anlass, gemessen.** Am 09.10.2026 lief der Papierhandel rund zweieinhalb
Stunden mit etwa 47 % Fehlerquote -- alle zwölf Märkte scheiterten wiederholt
an `fetch_ohlcv(..., W1)`, dem ersten Abruf jedes Zyklus, mit einem
ccxt-Timeout. Die Zähler standen danach bei 5 043 Fehlschlägen auf 46 096
Zyklen, und **nichts hat das gemeldet**: gefunden wurde es, weil jemand die
Datenbank abgefragt hat.

Diese Tests prüfen den Melder erzwungen, nicht erst nach zwei Stunden Laufzeit
zum ersten Mal. Genau daran ist in diesem Projekt schon ein Elf-Stunden-Lauf
gestorben: ein Codepfad, dessen Auslöser länger ist als der Test, ist
ungetestet.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from scripts.papertrade import FAILURE_ALARM, FAILURE_WINDOW, FailureWatch


@dataclass
class _Counters:
    cycles: int = 0
    failures: int = 0


class _Trader:
    def __init__(self) -> None:
        self.tally = _Counters()


@pytest.fixture
def fleet() -> list[_Trader]:
    return [_Trader() for _ in range(12)]


def advance(fleet: list[_Trader], watch: FailureWatch, *, cycles: int, failures: int) -> None:
    for trader in fleet:
        trader.tally.cycles += cycles
        trader.tally.failures += failures
    watch.check()


def test_silent_while_everything_works(fleet, capsys) -> None:
    watch = FailureWatch(fleet)
    for _ in range(5):
        advance(fleet, watch, cycles=FAILURE_WINDOW, failures=0)
    assert capsys.readouterr().err == ""


def test_alarms_once_when_the_rate_rises(fleet, capsys) -> None:
    watch = FailureWatch(fleet)
    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=0)
    capsys.readouterr()

    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=FAILURE_WINDOW // 2)
    first = capsys.readouterr().err
    assert "FEHLERQUOTE" in first
    # Die Meldung muss sagen, was das BEDEUTET -- sonst steht da eine Zahl und
    # der Leser weiss nicht, ob gerade Trades verloren gehen.
    assert "spaeter aufgeloest" in first

    # Derselbe Zustand darf nicht jede Runde erneut schreien.
    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=FAILURE_WINDOW // 2)
    assert capsys.readouterr().err == ""


def test_gives_the_all_clear_exactly_once(fleet, capsys) -> None:
    """Ein Alarm ohne Entwarnung laesst offen, ob der Zustand noch besteht."""
    watch = FailureWatch(fleet)
    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=FAILURE_WINDOW // 2)
    capsys.readouterr()

    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=0)
    assert "wieder normal" in capsys.readouterr().err

    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=0)
    assert capsys.readouterr().err == ""


def test_says_nothing_before_the_window_is_full(fleet, capsys) -> None:
    """Ein einzelner Fehlschlag ist normal. Gemeldet gehoert ein ZUSTAND."""
    watch = FailureWatch(fleet)
    advance(fleet, watch, cycles=1, failures=1)
    assert capsys.readouterr().err == ""


def test_the_threshold_is_the_one_that_was_declared(fleet, capsys) -> None:
    """Knapp darunter schweigt es, knapp darueber meldet es."""
    watch = FailureWatch(fleet)
    below = int(FAILURE_WINDOW * (FAILURE_ALARM - 0.05))
    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=below)
    assert capsys.readouterr().err == ""

    above = int(FAILURE_WINDOW * (FAILURE_ALARM + 0.05)) + 1
    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=above)
    assert "FEHLERQUOTE" in capsys.readouterr().err


def test_the_real_episode_would_have_been_reported(fleet, capsys) -> None:
    """Der gemessene Fall vom 09.10.2026, nachgespielt.

    Rund 3.000 Fehlschlaege auf rund 6.400 Zyklen ueber zweieinhalb Stunden.
    Ohne Melder blieb das unsichtbar.
    """
    watch = FailureWatch(fleet)
    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=0)
    capsys.readouterr()

    # Rund 47 % ueber ein Fenster, so wie es wirklich lief. Die erwartete
    # Zahl wird aus dem gerechnet, was der Test TATSAECHLICH erzeugt -- eine
    # fest hingeschriebene 47 waere an der Ganzzahl-Teilung gescheitert und
    # haette den Code beschuldigt statt den Test.
    broke = int(FAILURE_WINDOW * 0.47)
    advance(fleet, watch, cycles=FAILURE_WINDOW, failures=broke)
    expected = round(100 * broke / FAILURE_WINDOW)
    reported = capsys.readouterr().err
    assert f"FEHLERQUOTE {expected}%" in reported
    assert expected >= 100 * FAILURE_ALARM
