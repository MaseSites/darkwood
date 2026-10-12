"""Dass die Risikobremsen eine echte Historie bekommen — am echten Objekt.

**Warum es diese Datei braucht.** `tests/test_proposals.py` prüft die drei
Verlustsicherungen seit jeher und ist grün. Es baut dafür einen
`AccountState` von Hand und setzt `account.recent_trades = [...]`. Die
Produktion baute nie so einen: alle Stellen übergaben `[]`, also konnte
keine der drei Bremsen in irgendeinem Prozess auslösen, während die Tests
bestätigten, dass sie funktionieren.

Das ist dasselbe Muster wie am 09.10.2026, als sechs grüne Tests einen
Absturz im echten Objekt verdeckten. Ein Test, der nur eine Vorrichtung
anfasst, prüft die Vorrichtung.

Hier also zwei Sorten:

* **Die Kette durch das echte sqlite** — Journal schreiben, Historie lesen,
  Zustand bauen, Bremse urteilen lassen. Keine Vorrichtung dazwischen.
* **Ein Quelltext-Wächter** gegen die nächste vergessene Aufrufstelle. Der
  Defekt war nicht, dass jemand falsch rechnete, sondern dass drei Stellen
  eine leere Liste einsetzten und niemand nachsah.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.test_journal_history import SIG, entry
from traidingbrain.config.settings import load_config
from traidingbrain.journal.history import closed_trades
from traidingbrain.journal.store import JournalStore
from traidingbrain.risk.limits import AccountState, RiskLimits

ROOT = Path(__file__).resolve().parents[1]
HOUR = 3_600_000
DAY = 24 * HOUR
NOW = 1_700_000_000_000


def limits(**overrides: object) -> RiskLimits:
    shipped = load_config().risk.limits
    return RiskLimits(shipped.model_copy(update=overrides))


def state_from(store: JournalStore, *, equity: float = 1_000.0) -> AccountState:
    return AccountState.from_history(
        equity=equity,
        history=closed_trades(store, signature=SIG),
        now_ms=NOW,
    )


# --------------------------------------------------------------------------- #
# Die Kette, durch das echte sqlite
# --------------------------------------------------------------------------- #


def test_the_cooldown_fires_on_a_history_read_from_disk(tmp_path: Path) -> None:
    """Drei Verluste, geschrieben und wieder gelesen, loesen die Abkuehlung aus.

    Das ist der Fall, den die Produktion bis zum 12.10.2026 nicht erreichen
    konnte -- nicht weil die Bremse falsch war, sondern weil ihr niemand
    etwas zu lesen gab.
    """
    store = JournalStore(tmp_path / "journal.sqlite")
    store.record([
        entry(f"live-BTCUSDT-{i}", closed_ts=NOW - (3 - i) * HOUR, net_pnl=-10.0)
        for i in range(3)
    ])
    verdict = limits(cooldown_after_consecutive_losses=3, cooldown_hours=24).check(
        state_from(store), symbol="BTCUSDT"
    )

    assert not verdict.allowed
    assert "losses in a row" in verdict.reason


def test_a_win_at_the_end_breaks_the_streak_through_the_same_chain(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite")
    store.record([
        entry("live-BTCUSDT-1", closed_ts=NOW - 3 * HOUR, net_pnl=-10.0),
        entry("live-BTCUSDT-2", closed_ts=NOW - 2 * HOUR, net_pnl=-10.0),
        entry("live-BTCUSDT-3", closed_ts=NOW - 1 * HOUR, net_pnl=-10.0),
        entry("live-BTCUSDT-4", closed_ts=NOW - 30 * 60_000, net_pnl=+14.0),
    ])
    verdict = limits(cooldown_after_consecutive_losses=3, cooldown_hours=24).check(
        state_from(store), symbol="BTCUSDT"
    )

    assert verdict.allowed, verdict.reason


def test_the_daily_cap_measures_against_the_start_of_the_day(tmp_path: Path) -> None:
    """Der Freibetrag haengt am Tagesbeginn, nicht am gesunkenen Stand.

    Mit `starting_equity_today = equity` -- was vorher dastand -- waere der
    Freibetrag 5 % von 940 = 47, und ein Verlust von 60 laege darueber. Das
    klingt strenger und ist es nicht: es ist dieselbe Verschiebung, die bei
    kleineren Verlusten dafuer sorgt, dass die Grenze dem Verlust davonlaeuft.
    Richtig ist 5 % von 1.000 = 50.
    """
    store = JournalStore(tmp_path / "journal.sqlite")
    store.record([entry("live-BTCUSDT-1", closed_ts=NOW - 2 * HOUR, net_pnl=-60.0)])
    account = state_from(store, equity=940.0)

    assert account.starting_equity_today == pytest.approx(1_000.0)
    assert account.realised_today() == pytest.approx(-60.0)

    verdict = limits(max_daily_loss_pct=0.05).check(account, symbol="BTCUSDT")
    assert not verdict.allowed
    assert "daily limit" in verdict.reason


def test_a_loss_outside_the_window_does_not_count(tmp_path: Path) -> None:
    """Die Fenster sind rollend, nicht kalendarisch -- und `now_ms` entscheidet."""
    store = JournalStore(tmp_path / "journal.sqlite")
    store.record([entry("live-BTCUSDT-alt", closed_ts=NOW - 2 * DAY, net_pnl=-500.0)])
    account = state_from(store)

    assert account.realised_today() == pytest.approx(0.0)
    assert account.realised_this_week() == pytest.approx(-500.0)


def test_rows_of_another_configuration_cannot_trip_a_breaker(tmp_path: Path) -> None:
    """Der Filter, bis in das Urteil durchgezogen.

    Drei Verluste aus einer anderen Epoche duerfen die Abkuehlung nicht
    ausloesen. Ohne den Filter waeren es am 12.10. zwei echte Konten
    gewesen, die wegen fremder Zeilen einen Verlust vor dem Halt standen.
    """
    store = JournalStore(tmp_path / "journal.sqlite")
    store.record([
        entry(f"live-BTCUSDT-{i}", closed_ts=NOW - (3 - i) * HOUR, net_pnl=-10.0,
              run_signature="1000.0|['A']|0.15|H1|refused-v1")
        for i in range(3)
    ])
    verdict = limits(cooldown_after_consecutive_losses=3).check(
        state_from(store), symbol="BTCUSDT"
    )

    assert verdict.allowed, verdict.reason
    assert state_from(store).recent_trades == []


# --------------------------------------------------------------------------- #
# Der Waechter gegen die naechste vergessene Aufrufstelle
# --------------------------------------------------------------------------- #


def production_files() -> list[Path]:
    return sorted(
        path for folder in ("src", "scripts") for path in (ROOT / folder).rglob("*.py")
    )


def _account_state_calls(files: list[Path]) -> list[tuple[Path, ast.Call]]:
    """Jeder direkte `AccountState(...)`-Aufruf in den gegebenen Dateien.

    Attributaufrufe wie `AccountState.from_history(...)` zaehlen absichtlich
    nicht: das ist der Weg, der keine leere Historie erzeugen kann.
    """
    found: list[tuple[Path, ast.Call]] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "AccountState"
            ):
                found.append((path, node))
    return found


def test_the_guard_below_can_actually_find_something(tmp_path: Path) -> None:
    """Der Waechter, gegen sich selbst geprueft.

    **Und das war noetig.** Nach dem Umbau gibt es in `src/` und `scripts/`
    keinen einzigen direkten `AccountState(...)`-Aufruf mehr -- beide Stellen
    rufen `AccountState.from_history`. Die beiden Pruefungen unten liefen
    damit ueber eine leere Liste und waeren gruen gewesen, auch wenn jemand
    den halben Baum geloescht haette. Ein Waechter, der nichts scannt,
    besteht leer; das ist dieselbe Fehlerklasse wie der Defekt, den er
    bewacht.

    Hier bekommt er eine Datei, in der genau das steht, was er finden soll.
    """
    planted = tmp_path / "forgotten_site.py"
    planted.write_text(
        '''AccountState(
    equity=1.0,
    starting_equity_today=1.0,
    starting_equity_this_week=1.0,
    open_positions=[],
    recent_trades=[],
    now_ms=0,
)
''',
        encoding="utf-8",
    )
    found = _account_state_calls([planted])

    assert len(found) == 1
    names = {k.arg for k in found[0][1].keywords}
    assert {"recent_trades", "now_ms"} <= names


def test_the_guard_reads_the_whole_production_tree() -> None:
    """Und es muss wirklich der Baum sein, nicht eine leere Liste."""
    files = production_files()

    assert len(files) > 100, f"nur {len(files)} Dateien gescannt -- das ist nicht der Baum"
    assert any(f.name == "limits.py" for f in files)
    assert any(f.name == "run_live.py" for f in files)
    assert any(f.name == "run_dashboard.py" for f in files)


def test_no_production_site_hands_a_breaker_an_empty_history() -> None:
    """Der eigentliche Defekt, als Regel statt als Erinnerung.

    Nicht "jemand hat falsch gerechnet", sondern "drei Stellen setzten eine
    leere Liste ein und niemand sah nach". Ein Quelltext-Waechter faengt die
    vierte. `AccountState.from_history` ist der Weg, der nicht leer sein
    kann -- ein direkter Aufruf mit `recent_trades=[]` ist ab jetzt ein
    Testfehler.
    """
    offenders = []
    for path, call in _account_state_calls(production_files()):
        for keyword in call.keywords:
            if keyword.arg != "recent_trades":
                continue
            if isinstance(keyword.value, ast.List) and not keyword.value.elts:
                offenders.append(f"{path.relative_to(ROOT)}:{call.lineno}")

    assert not offenders, (
        "AccountState mit leerer Historie gebaut -- die drei Verlustsicherungen "
        f"koennen dort nicht ausloesen: {offenders}. "
        "AccountState.from_history(...) benutzen."
    )


def test_the_dashboard_does_not_build_its_state_at_the_epoch() -> None:
    """`now_ms=0` legt jeden Trade ausserhalb jedes Fensters.

    Der stillste Teil des Defekts: die Fensterschnitte in `realised_today`
    und die Restzeit der Abkuehlung haengen an `now_ms`, und mit 0 rechnet
    die Abkuehlung gegen den 01.01.1970.
    """
    offenders = []
    for path, call in _account_state_calls(production_files()):
        for keyword in call.keywords:
            if keyword.arg != "now_ms":
                continue
            if isinstance(keyword.value, ast.Constant) and keyword.value.value == 0:
                offenders.append(f"{path.relative_to(ROOT)}:{call.lineno}")

    assert not offenders, f"AccountState mit now_ms=0 gebaut: {offenders}"
