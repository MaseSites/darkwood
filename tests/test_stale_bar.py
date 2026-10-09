"""Ein veralteter Signalbalken darf nichts entscheiden und den Zeiger nicht bewegen.

**Woher die Frage kam.** Der Forschungsauftrag verlangt in Phase 1: *„Erkenne
veraltete Daten und sperre daraus abgeleitete Signale."* Beim Nachsehen, ob
das fehlt, zeigte sich erst, dass der naheliegende Pfad schon sicher ist: bei
einem **Abruffehler** wird `self._newest` in `settle()` nie gesetzt, weil die
Zuweisung erst nach einem vollständig gelungenen `refresh_data()` passiert.
Der Zeiger bleibt stehen, und `decide()` tut nichts.

Nicht sicher war der andere Fall: eine Abfrage, die **gelingt** und einen
**alten** Balken zurückgibt -- eine zwischengespeicherte oder gespiegelte
Antwort. Dass das kein Hirngespinst ist, belegt derselbe Tag: auf
`stream.binancefuture.com` waren die Preise auf den Cent richtig und der
Kennraum um Faktor 11 falsch. Eine Antwort kann richtig aussehen und alt sein.

`decide()` verglich `newest == last_decided_ts`. Ein Rückschritt ist ungleich,
also wäre er durchgegangen -- und hätte zwei Dinge getan: einen längst
entschiedenen Balken erneut entscheiden, und den Zeiger **rückwärts** setzen,
womit jeder Balken dazwischen zum zweiten Mal entschieden worden wäre.

Diese Tests prüfen den Vergleich, nicht die Börse. Sie setzen den Zeiger
direkt, weil genau das die Grösse ist, um die es geht.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from traidingbrain.live.paper import PaperTrader


@dataclass
class _Tally:
    cycles: int = 0
    bars_seen: int = 0
    stale_bars: int = 0
    failures: int = 0
    abandoned_bars: int = 0


@dataclass
class _Stats:
    tally: _Tally = field(default_factory=_Tally)


@dataclass
class _State:
    last_decided_ts: int = 0


class _Trader:
    """Nur die Felder, die `decide()` anfasst.

    Ein echter `PaperTrader` bräuchte Börse, Speicher und Broker. Die Frage
    hier ist ein Vergleich zweier Zahlen, und dafür ist das die ehrlichere
    Vorrichtung: was der Test nicht stellt, kann das Ergebnis nicht tragen.
    """

    def __init__(self, *, newest: int, decided: int) -> None:
        self._newest = newest
        self.state = _State(last_decided_ts=decided)
        self.stats = _Stats()
        self.opened_with: list[int] = []
        self.persisted = 0
        self.failures: list[str] = []
        self._attempts = (0, 0)

    # Die beiden Mitspieler, die `decide()` aufruft.
    def _maybe_open(self, bar_ts: int) -> None:
        self.opened_with.append(bar_ts)

    def _persist(self) -> None:
        self.persisted += 1

    def _failed(self, message: str) -> None:
        self.failures.append(message)
        self.stats.tally.failures += 1

    decide = PaperTrader.decide
    wants_decision = PaperTrader.wants_decision


def test_a_newer_bar_is_decided() -> None:
    trader = _Trader(newest=2_000, decided=1_000)
    trader.decide()
    assert trader.opened_with == [2_000]
    assert trader.state.last_decided_ts == 2_000
    assert trader.stats.tally.bars_seen == 1


def test_the_same_bar_is_not_decided_twice() -> None:
    trader = _Trader(newest=1_000, decided=1_000)
    trader.decide()
    assert trader.opened_with == []
    assert trader.stats.tally.stale_bars == 0
    assert trader.failures == []


def test_an_older_bar_decides_nothing(caplog) -> None:
    """Der Fall, der mit `!=` durchgegangen waere."""
    trader = _Trader(newest=1_000, decided=2_000)
    trader.decide()
    assert trader.opened_with == []
    assert trader.stats.tally.bars_seen == 0


def test_an_older_bar_does_not_move_the_cursor_backwards() -> None:
    """Das Teuerste am Rueckschritt: alles dazwischen wuerde erneut entschieden."""
    trader = _Trader(newest=1_000, decided=2_000)
    trader.decide()
    assert trader.state.last_decided_ts == 2_000


def test_an_older_bar_is_counted_and_said_out_loud() -> None:
    """Still verwerfen waere derselbe Fehler wie still entscheiden.

    Ein Zustand, den man nur durch Nachsehen findet, hat dieses Projekt schon
    zwoelf Stunden Aufnahme gekostet.
    """
    trader = _Trader(newest=1_000, decided=2_000)
    trader.decide()
    assert trader.stats.tally.stale_bars == 1
    assert len(trader.failures) == 1
    assert "Veralteter Signalbalken" in trader.failures[0]
    # Der Vermerk muss BEIDE Zahlen nennen, sonst ist er nicht nachvollziehbar.
    assert "1000" in trader.failures[0]
    assert "2000" in trader.failures[0]
    assert trader.persisted == 1


def test_no_bar_at_all_does_nothing_and_says_nothing() -> None:
    trader = _Trader(newest=0, decided=2_000)
    trader.decide()
    assert trader.opened_with == []
    assert trader.stats.tally.stale_bars == 0
    assert trader.failures == []


@pytest.mark.parametrize(
    ("newest", "decided", "expected"),
    [(2_000, 1_000, True), (1_000, 1_000, False), (1_000, 2_000, False), (0, 0, False)],
)
def test_wants_decision_agrees_with_decide(newest: int, decided: int, expected: bool) -> None:
    """Die Vorschau darf nicht etwas versprechen, das `decide()` dann ablehnt.

    Beide benutzten `!=`. Haette nur eine davon auf `>` gewechselt, haette ein
    Laeufer die teure Analyse fuer einen Balken angestossen, den `decide()`
    danach verwirft -- und das sahe wie ein haengender Lauf aus.
    """
    trader = _Trader(newest=newest, decided=decided)
    assert trader.wants_decision is expected
