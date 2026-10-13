"""Die Umschaltung von zwölf Konten auf eines — und die Falle darin.

**Die Falle.** Beim ersten Lauf unter `basis: portfolio` halten die zwölf
Zustandszeilen je ein Zwölftel des Kapitals (~1.006 USDT). Danach halten sie
je den geteilten Stand (~12.075). Dieselbe Spalte bedeutet also einmal „ein
Zwölftel" und einmal „das Ganze", und welche Lesart gilt, stünde nirgends.

Wer sie beim Umschalten summiert und danach weiter summiert, bekommt 144.900
statt 12.075. Wer sie beim Umschalten einzeln liest, bekommt 1.006 statt
12.075. Beides ist ein Faktor-12-Fehler, der wie eine Zahl aussieht — und in
einem Risikosystem bedeutet er zwölfmal zu grosse oder zwölfmal zu kleine
Positionen.

Darum hat die geteilte Kasse ihre **eigene Zeile**: fehlt sie, ist es der
erste Lauf und der Startwert ist die Summe; steht sie da, wird sie gelesen.
Diese Datei hält beide Fälle fest, weil der Unterschied nicht zu sehen ist,
wenn man ihn nicht prüft.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from papertrade import shared_ledger  # noqa: E402

from traidingbrain.config.settings import AppConfig, load_config  # noqa: E402
from traidingbrain.journal.version import run_signature  # noqa: E402
from traidingbrain.live.paperstate import PaperState, PaperStateStore  # noqa: E402

ACCOUNTS = 12
PER_ACCOUNT = 1_006.30


@pytest.fixture(scope="module")
def base() -> AppConfig:
    return load_config(PROJECT_ROOT / "config")


def with_basis(config: AppConfig, basis: str) -> AppConfig:
    return config.model_copy(
        update={"risk": config.risk.model_copy(
            update={"sizing": config.risk.sizing.model_copy(update={"basis": basis})}
        )}
    )


def twelve_accounts(tmp_path: Path) -> PaperStateStore:
    store = PaperStateStore(tmp_path / "paper.sqlite")
    for index in range(ACCOUNTS):
        store.save(PaperState(symbol=f"SYM{index}USDT", equity=PER_ACCOUNT))
    return store


# --------------------------------------------------------------------------- #
# Der Vorgabefall bleibt unberührt
# --------------------------------------------------------------------------- #


def test_account_basis_hands_out_no_shared_ledger(tmp_path: Path, base: AppConfig) -> None:
    """`account` ist der Vorgabewert, und dann aendert sich nichts.

    Jeder Broker baut seine eigene Kasse, die Groesse bemisst sich am
    Einzelkonto, und der Vorwaertslauf bleibt mit allem vergleichbar, was
    bisher gemessen wurde.
    """
    # Der VORGABEWERT des Feldes, nicht der ausgelieferte Wert.
    #
    # Die erste Fassung prueefte `base.risk.sizing.basis == "account"` und
    # fiel, als die Konfiguration am 13.10. auf `portfolio` umgestellt wurde
    # -- sie verwechselte "was das Modell vorgibt" mit "was heute
    # eingetragen ist". Das Erste ist eine Eigenschaft des Codes und gehoert
    # in einen Test; das Zweite ist eine Entscheidung und darf sich aendern.
    default = type(base.risk.sizing).model_fields["basis"].default
    assert default == "account", (
        "der Vorgabewert muss account bleiben: wer die Konfiguration nicht "
        "anfasst, soll die alte Groessenbemessung und die alte Signatur haben"
    )
    assert shared_ledger(with_basis(base, "account"), twelve_accounts(tmp_path)) is None


# --------------------------------------------------------------------------- #
# Die Umschaltung
# --------------------------------------------------------------------------- #


def test_the_first_portfolio_run_sums_the_accounts(tmp_path: Path, base: AppConfig) -> None:
    """Keine Portfoliozeile heisst erster Lauf heisst Summe."""
    store = twelve_accounts(tmp_path)
    assert store.load_portfolio() is None

    ledger = shared_ledger(with_basis(base, "portfolio"), store)

    assert ledger is not None
    assert ledger.equity == pytest.approx(ACCOUNTS * PER_ACCOUNT)
    assert ledger.peak_equity == pytest.approx(ACCOUNTS * PER_ACCOUNT)


def test_the_second_run_reads_the_row_and_does_not_sum_again(
    tmp_path: Path, base: AppConfig
) -> None:
    """Der Faktor-12-Fehler, als Test.

    Nach dem ersten Lauf halten die zwoelf Kontozeilen je den GETEILTEN
    Stand. Wer dann wieder summiert, bekommt das Zwoelffache.
    """
    store = twelve_accounts(tmp_path)
    pooled = ACCOUNTS * PER_ACCOUNT
    store.save_portfolio(pooled, pooled)
    # So, wie der laufende Haendler es tut: jede Kontozeile traegt den
    # geteilten Stand.
    for index in range(ACCOUNTS):
        store.save(PaperState(symbol=f"SYM{index}USDT", equity=pooled))

    ledger = shared_ledger(with_basis(base, "portfolio"), store)

    assert ledger is not None
    assert ledger.equity == pytest.approx(pooled), (
        f"erwartet {pooled:,.2f}, nicht die Summe der zwoelf Zeilen "
        f"({ACCOUNTS * pooled:,.2f})"
    )
    assert store.equity_sum() == pytest.approx(ACCOUNTS * pooled), (
        "die Summe IST zwoelfmal zu gross -- genau deshalb darf sie nach dem "
        "ersten Lauf nicht mehr benutzt werden"
    )


def test_a_loss_survives_the_restart(tmp_path: Path, base: AppConfig) -> None:
    store = twelve_accounts(tmp_path)
    store.save_portfolio(11_000.0, 12_075.6)

    ledger = shared_ledger(with_basis(base, "portfolio"), store)

    assert ledger is not None
    assert ledger.equity == pytest.approx(11_000.0)
    assert ledger.peak_equity == pytest.approx(12_075.6), (
        "der Hoechststand gehoert mitgefuehrt, sonst misst der Drawdown ab "
        "dem Neustart statt ab dem Hoechststand"
    )


def test_an_empty_store_falls_back_to_the_configured_start(
    tmp_path: Path, base: AppConfig
) -> None:
    """Ohne jedes Konto gibt es nichts zu summieren."""
    empty = PaperStateStore(tmp_path / "leer.sqlite")

    ledger = shared_ledger(with_basis(base, "portfolio"), empty)

    assert ledger is not None
    assert ledger.equity == pytest.approx(base.engine.simulation.initial_equity)


# --------------------------------------------------------------------------- #
# Die Signatur muss den Schalter tragen
# --------------------------------------------------------------------------- #


def test_the_signature_separates_the_two_bases(base: AppConfig) -> None:
    """Sonst sind 10-USDT- und 120-USDT-Trades ein Schluessel.

    Genau das hat die Vorwaertsstichprobe schon einmal von 18 auf 11 Trades
    schrumpfen lassen: eine Konfigurationsaenderung, die keine Spur in der
    Signatur hinterliess, und die Zugehoerigkeit war nur noch aus der
    Git-Historie zu erschliessen.
    """
    account = run_signature(with_basis(base, "account"))
    portfolio = run_signature(with_basis(base, "portfolio"))

    assert account != portfolio
    assert portfolio.endswith("|portfolio")
    assert not account.endswith("|portfolio"), (
        "die alte Signatur muss byte-identisch bleiben, sonst verwaisen die "
        "Zeilen, die der Speicher schon unter ihr haelt"
    )
