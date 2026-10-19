"""Gegen WELCHEN Kontostand das Dashboard seine Verlustsicherungen rechnet.

Die drei Sicherungen -- Tagesverlust, Wochenverlust, Verlustserie -- sind
Prozente vom Konto. Bekommen sie die falsche Bezugsgroesse, bleiben sie
formal in Kraft und sind trotzdem wertlos: zu eng blockieren sie dauerhaft,
zu weit greifen sie nie. Beides sieht auf dem Bildschirm gleich aus.

**Der Fehler, den diese Datei festnagelt.** `run_dashboard.py` uebergab
`config.engine.simulation.initial_equity` -- den Startwert EINES Marktes.
Das bestehende Konto haelt 11.775 USDT; gerechnet wurde gegen 1.000. Der
Tagesdeckel stand damit bei 54 statt bei rund 589, und das Dashboard meldete
dauerhaft "A risk limit is blocking new trades".

**Warum es so lange unsichtbar war.** Ein zweiter Fehler hielt den ersten
verdeckt: `/api/state` las `services.account`, das statische Feld, das im
Betrieb niemand setzt. Der Endpunkt bekam also nie ein Urteil zu sehen und
meldete stattdessen "kein Kontostand" -- dieselbe gelbe Warnung, aus einem
ganz anderen Grund. Erst als der eine behoben war, wurde der andere sichtbar.

Gemessen wird hier gegen einen **echten** `PaperStateStore` auf der Platte,
nicht gegen eine Nachbildung: der Unterschied zwischen geteilter Kasse und
Summe der Einzelkonten steckt in genau diesem Objekt, und eine Attrappe haette
ihn nachgebaut statt geprueft.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_dashboard  # noqa: E402

from traidingbrain.api.app import Services  # noqa: E402
from traidingbrain.config.settings import AppConfig, load_config  # noqa: E402
from traidingbrain.live.paperstate import PaperState, PaperStateStore  # noqa: E402
from traidingbrain.proposals.builder import ProposalBuilder  # noqa: E402
from traidingbrain.proposals.store import ProposalStore  # noqa: E402
from traidingbrain.risk.limits import KillSwitch, RiskLimits  # noqa: E402

#: Zwoelf Maerkte mal 1.000 -- so ist das bestehende Konto entstanden.
MAERKTE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
JE_MARKT = 1_000.0

#: Was die geteilte Kasse wirklich haelt. Bewusst keine glatte Zahl und
#: bewusst nicht `len(MAERKTE) * JE_MARKT`, damit ein Test, der die Summe
#: der Einzelkonten liest, nicht zufaellig richtig liegt.
GETEILT = 11_775.26


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    """Die echte Konfiguration, aber mit `data_dir` im Testverzeichnis."""
    echt = load_config()
    pfade = echt.engine.paths.model_copy(update={"data_dir": tmp_path})
    motor = echt.engine.model_copy(update={"paths": pfade})
    return echt.model_copy(update={"engine": motor})


def _services(config: AppConfig, tmp_path: Path, *, state_name: str) -> Services:
    kill_switch = KillSwitch(tmp_path / "KILL")
    limits = RiskLimits(config.risk.limits, kill_switch)
    return Services(
        config=config,
        store=ProposalStore(tmp_path / "proposals.sqlite"),
        builder=ProposalBuilder(config, limits),
        limits=limits,
        kill_switch=kill_switch,
        state_name=state_name,
    )


def _speicher(config: AppConfig, name: str) -> PaperStateStore:
    return PaperStateStore(config.engine.paths.data_dir / name)


def test_der_kontostand_kommt_aus_der_geteilten_kasse(
    config: AppConfig, tmp_path: Path
) -> None:
    """Unter geteilter Kasse ist die `portfolio`-Zeile die Wahrheit.

    Die zwoelf Kontozeilen tragen daneben jeweils den GANZEN Stand -- wer sie
    summiert, bekommt das Zwoelffache. Darum traegt jede Zeile hier denselben
    Wert wie die Kasse: ein Leser, der die falsche Quelle nimmt, landet
    sichtbar daneben statt zufaellig richtig.
    """
    assert config.risk.sizing.basis == "portfolio", (
        "Dieser Test beschreibt die geteilte Kasse. Steht die Konfiguration "
        "auf Einzelkonten, prueft er etwas anderes als er behauptet."
    )
    speicher = _speicher(config, "paper.sqlite")
    speicher.save_portfolio(GETEILT, GETEILT + 300.30)
    for symbol in MAERKTE:
        speicher.save(PaperState(symbol=symbol, equity=GETEILT))

    services = _services(config, tmp_path, state_name="paper.sqlite")

    assert run_dashboard.kontostand(services) == pytest.approx(GETEILT)


def test_nicht_der_startwert_eines_marktes(config: AppConfig, tmp_path: Path) -> None:
    """Der eigentliche Regressionstest: NICHT `initial_equity`.

    Das ist der Wert, der vorher uebergeben wurde. Er steht hier ausdruecklich
    als Gegenprobe, weil der Fehler nicht wie ein Fehler aussah -- 1.000 ist
    eine plausible Zahl fuer ein Papierkonto, und auf dem Plankonto, das
    wirklich bei 1.000 startet, war er sogar unsichtbar richtig.
    """
    speicher = _speicher(config, "paper.sqlite")
    speicher.save_portfolio(GETEILT, GETEILT)

    services = _services(config, tmp_path, state_name="paper.sqlite")
    gelesen = run_dashboard.kontostand(services)

    assert gelesen != pytest.approx(config.engine.simulation.initial_equity)
    assert gelesen == pytest.approx(GETEILT)


def test_jedes_konto_liest_seinen_eigenen_speicher(
    config: AppConfig, tmp_path: Path
) -> None:
    """Zwei Konten, zwei Dateien, zwei Zahlen.

    `state_name` ist das Einzige, was sie trennt. Lese der eine den Speicher
    des anderen, wuerden die Verlustsicherungen des Plankontos gegen das
    Kapital des bestehenden rechnen -- und umgekehrt. Das Plankonto riskiert
    je Trade ein Vielfaches; dieser Zahlendreher waere nicht kosmetisch.
    """
    _speicher(config, "paper.sqlite").save_portfolio(GETEILT, GETEILT)
    _speicher(config, "plan_paper.sqlite").save_portfolio(1_000.0, 1_000.0)

    bestehend = _services(config, tmp_path, state_name="paper.sqlite")
    plan = _services(config, tmp_path, state_name="plan_paper.sqlite")

    assert run_dashboard.kontostand(bestehend) == pytest.approx(GETEILT)
    assert run_dashboard.kontostand(plan) == pytest.approx(1_000.0)
