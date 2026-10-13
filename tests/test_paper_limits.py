"""Dass die Kontogrenzen auf dem Pfad greifen, der wirklich handelt.

**Warum diese Datei getrennt von `test_proposals.py` existiert.** Dort werden
die drei Verlustsicherungen seit jeher geprüft, und sie sind grün — an einem
`AccountState`, der von Hand gebaut wird. Bis zum 13.10.2026 rief der
Papierhandel `RiskLimits.check` **überhaupt nicht** auf. Die Tests
bestätigten also eine Mechanik, die in keinem laufenden Prozess existierte.

Und die Tests, die den Papierhändler fahren — `test_live_decision_golden.py`
und `test_papertrade.py` — übergeben **keine** Grenzen, also ist
`self.limits is None` und der neue Code läuft dort nicht. Sie blieben nach
dem Umbau grün, was richtig ist und nichts beweist.

Hier also das echte Objekt mit echten Grenzen und echtem Journal:
schreiben, lesen, urteilen. Plus ein Wächter, dass `papertrade.py` die
Grenzen wirklich übergibt — denn der Defekt war nie eine falsche Rechnung,
sondern eine Stelle, die etwas nicht weitergab.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.factories import make_symbol_spec
from tests.test_journal_history import SIG, entry
from traidingbrain.clock import FixedClock
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Rule, Side
from traidingbrain.journal.signals import Action, SignalStore
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.paper import PaperTrader
from traidingbrain.live.paperstate import PaperStateStore
from traidingbrain.risk.limits import KillSwitch, RiskLimits
from traidingbrain.sim.plan import Assessment, TradeIntent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOUR = 3_600_000
NOW = 1_700_000_000_000


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config(PROJECT_ROOT / "config")


def trader_with(
    tmp_path: Path,
    config: AppConfig,
    *,
    limits: RiskLimits | None,
    history: list[object] | None = None,
) -> PaperTrader:
    """Ein echter `PaperTrader` mit echtem Journal, ohne Band.

    Kein `FrozenTape`: `_blocked_by_limits` braucht keine Kurse, nur den
    Kontostand und die Historie. Was hier geprueft wird, ist genau die
    Verdrahtung, die der Golden-Test nicht anfasst.
    """
    journal = JournalStore(tmp_path / "journal.sqlite")
    if history:
        journal.record(history)  # type: ignore[arg-type]
    return PaperTrader(
        "BTCUSDT",
        config,
        source=None,
        store=ParquetStore(tmp_path / "ohlcv"),
        state=PaperStateStore(tmp_path / "paper.sqlite"),
        journal=journal,
        spec=make_symbol_spec(),
        clock=FixedClock(NOW),
        signals=SignalStore(tmp_path / "signals.sqlite"),
        run_signature=SIG,
        limits=limits,
    )


def limits_with(config: AppConfig, *, kill: Path | None = None, **overrides: object) -> RiskLimits:
    shipped = config.risk.limits.model_copy(update=overrides)
    return RiskLimits(shipped, KillSwitch(kill) if kill is not None else None)


def losses(count: int) -> list[object]:
    return [
        entry(f"live-BTCUSDT-{i}", symbol="BTCUSDT", closed_ts=NOW - (count - i) * HOUR,
              net_pnl=-10.0, run_signature=SIG)
        for i in range(count)
    ]


# --------------------------------------------------------------------------- #
# Die Bremse greift, und nur wenn sie soll
# --------------------------------------------------------------------------- #


def test_a_clean_history_blocks_nothing(tmp_path: Path, config: AppConfig) -> None:
    trader = trader_with(tmp_path, config, limits=limits_with(config))

    assert trader._blocked_by_limits(NOW) is None


def test_a_loss_streak_blocks_the_next_signal(tmp_path: Path, config: AppConfig) -> None:
    """Der Fall, den die Konfiguration seit immer behauptet und der nie eintrat."""
    trader = trader_with(
        tmp_path, config,
        limits=limits_with(config, cooldown_after_consecutive_losses=3, cooldown_hours=24),
        history=losses(3),
    )
    blocked = trader._blocked_by_limits(NOW)

    assert blocked is not None
    assert "losses in a row" in blocked


def test_the_day_cap_blocks_on_the_real_object(tmp_path: Path, config: AppConfig) -> None:
    """Sechs Verluste an einem Tag reissen den 5-%-Deckel eines 1.000er-Kontos."""
    trader = trader_with(
        tmp_path, config,
        limits=limits_with(config, max_daily_loss_pct=0.05,
                           cooldown_after_consecutive_losses=99),
        history=losses(6),
    )
    blocked = trader._blocked_by_limits(NOW)

    assert blocked is not None
    assert "daily limit" in blocked


def test_the_kill_switch_stops_everything(tmp_path: Path, config: AppConfig) -> None:
    """Eine Datei, die ein anderer Prozess anlegt, und der Haendler oeffnet nichts.

    Das Wichtigste der vier Grenzen, und es war auf diesem Pfad ebenso tot:
    `RiskLimits.check` prueft den Schalter als Erstes, aber niemand rief
    `check` auf.
    """
    switch = tmp_path / "KILL_SWITCH"
    trader = trader_with(tmp_path, config, limits=limits_with(config, kill=switch))
    assert trader._blocked_by_limits(NOW) is None

    KillSwitch(switch).engage("von Hand, im Test")
    blocked = trader._blocked_by_limits(NOW)

    assert blocked is not None
    assert "kill switch" in blocked


def test_rows_of_another_configuration_do_not_block(tmp_path: Path, config: AppConfig) -> None:
    """Drei Verluste aus einer fremden Epoche sind keine Verlustserie."""
    foreign = [
        entry(f"live-BTCUSDT-{i}", closed_ts=NOW - (3 - i) * HOUR, net_pnl=-10.0,
              run_signature="1000.0|['A']|0.15|H1|refused-v1")
        for i in range(3)
    ]
    trader = trader_with(
        tmp_path, config,
        limits=limits_with(config, cooldown_after_consecutive_losses=3),
        history=foreign,
    )

    assert trader._blocked_by_limits(NOW) is None


def test_without_limits_nothing_changes(tmp_path: Path, config: AppConfig) -> None:
    """`limits=None` bleibt moeglich, und dann greift nichts.

    Das ist der Pfad, den der Golden-Test faehrt -- und der Grund, warum er
    nach dem Umbau gruen blieb. Festgehalten, damit das eine Eigenschaft ist
    und keine Zufaelligkeit.
    """
    trader = trader_with(tmp_path, config, limits=None, history=losses(9))

    assert trader._blocked_by_limits(NOW) is None


# --------------------------------------------------------------------------- #
# Die blockierte Zeile im Signalspeicher
# --------------------------------------------------------------------------- #


def assessment(*, taken: bool) -> Assessment:
    return Assessment(
        entry=object() if taken else None,  # type: ignore[arg-type]
        refused_by=None if taken else Rule.COSTS,
        detail="" if taken else "zu teuer",
        reward_risk=2.0,
        cost_fraction=0.02,
        risk_amount=10.0,
        qty=1.0,
        leverage=5.0,
    )


def test_a_blocked_signal_is_recorded_with_its_reason(
    tmp_path: Path, config: AppConfig
) -> None:
    """`action=REFUSED` UND `refused_by` gesetzt -- beides, nicht eines.

    `scripts/study_meta_label.py:465` entscheidet "genommen" mit
    `refused_by is None` und nicht am Feld `action`. Eine abgelehnte Zeile
    ohne Grund wird dort als genommene gelesen, und genau daran ist der
    erste Entwurf dieses Eingriffs gescheitert.
    """
    trader = trader_with(tmp_path, config, limits=limits_with(config))
    intent = TradeIntent(side=Side.LONG, entry=100.0, stop=98.0, target=104.0,
                         confidence=70.0, reason="A Momentum-Breakout (V08): x")

    trader._record_signal(intent, assessment(taken=True), decided_ts=NOW,
                          blocked_by="3 losses in a row; cooling off for another 20.0h")

    assert trader.signals is not None
    rows = trader.signals.all(symbol="BTCUSDT")
    assert len(rows) == 1
    assert rows[0].action is Action.REFUSED
    assert rows[0].refused_by is Rule.LIMITS
    assert "losses in a row" in rows[0].detail


def test_an_unblocked_signal_is_still_recorded_as_taken(
    tmp_path: Path, config: AppConfig
) -> None:
    trader = trader_with(tmp_path, config, limits=limits_with(config))
    intent = TradeIntent(side=Side.LONG, entry=100.0, stop=98.0, target=104.0,
                         confidence=70.0, reason="A Momentum-Breakout (V08): x")

    trader._record_signal(intent, assessment(taken=True), decided_ts=NOW)

    assert trader.signals is not None
    rows = trader.signals.all(symbol="BTCUSDT")
    assert rows[0].action is Action.TAKEN
    assert rows[0].refused_by is None


def test_a_signal_refused_by_cost_keeps_its_own_reason(
    tmp_path: Path, config: AppConfig
) -> None:
    """Die Reihenfolge: hat `assess` abgelehnt, ist DAS der Grund.

    Sonst wuerde jede Kostenablehnung als Kontogrenze erscheinen, und die
    Frage "verdient die Kostenregel ihren Platz" waere nicht mehr
    beantwortbar.
    """
    trader = trader_with(tmp_path, config, limits=limits_with(config))
    intent = TradeIntent(side=Side.LONG, entry=100.0, stop=98.0, target=104.0,
                         confidence=70.0, reason="A Momentum-Breakout (V08): x")

    trader._record_signal(intent, assessment(taken=False), decided_ts=NOW)

    assert trader.signals is not None
    rows = trader.signals.all(symbol="BTCUSDT")
    assert rows[0].action is Action.REFUSED
    assert rows[0].refused_by is Rule.COSTS
    assert rows[0].detail == "zu teuer"


# --------------------------------------------------------------------------- #
# Der Waechter: gibt papertrade.py die Grenzen weiter?
# --------------------------------------------------------------------------- #


def papertrader_calls(files: list[Path]) -> list[tuple[Path, ast.Call]]:
    found: list[tuple[Path, ast.Call]] = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "PaperTrader"
            ):
                found.append((path, node))
    return found


def test_the_guard_below_can_find_a_call() -> None:
    """Zuerst der Waechter gegen sich selbst.

    Am 12.10.2026 war ein gleichartiger Waechter gruen, weil er NULL
    Aufrufstellen fand -- er haette auch bei geloeschtem Baum bestanden.
    Also wird hier erst gezeigt, dass er etwas findet.
    """
    found = papertrader_calls([PROJECT_ROOT / "scripts" / "papertrade.py"])

    assert found, "kein PaperTrader-Aufruf in papertrade.py gefunden -- Waechter blind"


def test_the_paper_trader_is_handed_its_limits() -> None:
    """Der eigentliche Defekt als Regel: die Stelle, die nichts weitergab."""
    naked = []
    for path, call in papertrader_calls([PROJECT_ROOT / "scripts" / "papertrade.py"]):
        if "limits" not in {keyword.arg for keyword in call.keywords}:
            naked.append(f"{path.name}:{call.lineno}")

    assert not naked, (
        "PaperTrader ohne `limits=` gebaut -- Tagesverlust, Wochenverlust, "
        f"Abkuehlung und Kill-Switch koennen dort nicht ausloesen: {naked}"
    )
