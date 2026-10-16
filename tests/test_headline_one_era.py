"""Die Schlagzeile rechnet über EINE Konfiguration, nicht über alle.

**Der Anlass, 16.10.2026.** Das Dashboard zeigte „28 Trades vorwärts ·
Mittel +0,294 R". Nachgesehen, wonach diese 28 zerfallen:

    n=18   +0.3938 R   02.10-09.10   Signatur LEER
    n= 9   -0.0956 R   08.10-13.10   ...|0.08|M15|refused-v1
    n= 1   +2.0029 R   07.10-15.10   ...refused-v1|portfolio|cap5

Drei Konfigurationen, eine davon ganz ohne aufgezeichnete Konfiguration.
Unter `portfolio` riskiert ein Trade 120 USDT, unter der Vorgängerin 10 —
ein Mittelwert darüber beantwortet keine Frage, und auf dem Bildschirm
liest er sich als Vorteil des Systems.

Die Oberfläche warnte unter 30 Trades. Bei 30 wäre die Warnung weg gewesen
und die Zahl hätte dagestanden wie ein Ergebnis. Die Warnung hing an der
Zahl der Trades, und das Problem war nie die Zahl, sondern ihre Herkunft.

Was hier festgenagelt wird, sind zwei getrennte Aussagen:

* Die Schlagzeile (`trades`, `wins`, `mean_r`, `total_r`) zählt nur, was
  dieselbe `run_signature` UND denselben `decision_version` trägt wie der
  laufende Stand.
* Der Kontostand und die Markt-Beiträge zählen weiter ALLES. Das Konto hat
  jeden dieser Trades bezahlt; eine Tabelle, die nur die laufende Epoche
  zeigt, würde den Kontostand nicht mehr erklären.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_journal_history import SIG, entry
from traidingbrain.api.portfolio import build_portfolio
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.journal.store import JournalStore
from traidingbrain.journal.version import decision_version, run_signature
from traidingbrain.live.paperstate import PaperState, PaperStateStore

HOUR = 3_600_000


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


def seed(tmp_path: Path, config: AppConfig, entries: list) -> tuple[Path, Path]:
    """Ein Zustand und ein Journal mit genau diesen Trades."""
    state_path = tmp_path / "paper.sqlite"
    states = PaperStateStore(state_path)
    for symbol in config.engine.symbols.active:
        states.save(PaperState(symbol=symbol, equity=1_000.0))

    journal_path = tmp_path / "journal.sqlite"
    journal = JournalStore(journal_path)
    journal.record(entries)
    return state_path, journal_path


def test_the_headline_counts_only_the_running_configuration(
    tmp_path: Path, config: AppConfig
) -> None:
    """Drei Epochen hinein, eine heraus.

    Die Zahlen sind so gewaehlt, dass ein Mittelwert ueber ALLE ein anderes
    Vorzeichen haette als der ueber die laufende -- sonst koennte der Test
    auch dann bestehen, wenn weiter alles gezaehlt wird.
    """
    now_sig, now_stamp = run_signature(config), decision_version()

    entries = [
        # Die laufende Konfiguration: zwei Verlierer.
        entry("live-A", run_signature=now_sig, decision_version=now_stamp,
              r_multiple=-1.0, net_pnl=-10.0),
        entry("live-B", run_signature=now_sig, decision_version=now_stamp,
              r_multiple=-0.5, net_pnl=-5.0),
        # Eine aeltere Signatur: grosse Gewinner, die nicht zaehlen duerfen.
        entry("live-C", run_signature=SIG, decision_version=now_stamp,
              r_multiple=+3.0, net_pnl=+30.0),
        entry("live-D", run_signature=SIG, decision_version=now_stamp,
              r_multiple=+3.0, net_pnl=+30.0),
        # Gar keine Signatur -- aus den Daten keiner Konfiguration zuzuordnen.
        entry("live-E", run_signature="", decision_version="",
              r_multiple=+3.0, net_pnl=+30.0),
    ]
    state_path, journal_path = seed(tmp_path, config, entries)

    view = build_portfolio(state_path, journal_path, config, now_ms=10 * HOUR)

    assert view.trades == 2, "die Schlagzeile zaehlt eine Konfiguration"
    assert view.mean_r == pytest.approx(-0.75), (
        "der Mittelwert ueber ALLE waere +1.50 und damit das andere "
        "Vorzeichen -- genau das soll die Schlagzeile nicht zeigen"
    )
    assert view.wins == 0
    assert view.trades_all == 5
    assert view.eras == 3, (
        "drei (Signatur, Codestand)-Paare: die laufende, die aeltere, und "
        "die ohne jede Aufzeichnung"
    )


def test_the_account_still_counts_every_trade(
    tmp_path: Path, config: AppConfig
) -> None:
    """Der Kontostand hat auch die alten Trades bezahlt.

    Die Einschraenkung gilt der SCHLAGZEILE. Wuerde sie auch fuer die
    Markt-Beitraege gelten, erklaerte die Tabelle den Kontostand nicht mehr,
    und `unexplained` -- die Zeile, die genau diese Luecke sichtbar macht --
    wuerde von einer Anzeige zu einem Rechenfehler.
    """
    now_sig, now_stamp = run_signature(config), decision_version()
    entries = [
        entry("live-A", run_signature=now_sig, decision_version=now_stamp,
              r_multiple=-1.0, net_pnl=-10.0),
        entry("live-B", run_signature=SIG, decision_version=now_stamp,
              r_multiple=+3.0, net_pnl=+30.0),
    ]
    state_path, journal_path = seed(tmp_path, config, entries)

    view = build_portfolio(state_path, journal_path, config, now_ms=10 * HOUR)

    beitrag = sum(row.realised for row in view.markets)
    assert beitrag == pytest.approx(20.0), (
        "beide Trades zusammen: -10 und +30. Zaehlte die Tabelle nur die "
        "laufende Epoche, stuenden hier -10 und der Rest waere 'unerklaert'"
    )
    assert view.trades == 1
    assert view.trades_all == 2


def test_one_era_means_the_headline_covers_everything(
    tmp_path: Path, config: AppConfig
) -> None:
    """Der haeufige Fall: alles unter einer Konfiguration, nichts zu trennen."""
    now_sig, now_stamp = run_signature(config), decision_version()
    entries = [
        entry(f"live-{i}", run_signature=now_sig, decision_version=now_stamp,
              r_multiple=0.5, net_pnl=5.0)
        for i in range(3)
    ]
    state_path, journal_path = seed(tmp_path, config, entries)

    view = build_portfolio(state_path, journal_path, config, now_ms=10 * HOUR)

    assert view.eras == 1
    assert view.trades == view.trades_all == 3
