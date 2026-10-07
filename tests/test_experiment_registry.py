"""Die Vorab-Registrierung gegen stille Änderungen schützen.

`audit/EXPERIMENTS_NEXT.yaml` schreibt Arme, Merkmale, Fenster, Kennzahlen und
die Gesamtzahl der Vergleiche fest, **bevor** ein Ergebnis gelesen wird. Ihr
ganzer Wert liegt in diesem "bevor". Eine Datei, an der man nachträglich eine
Zelle entfernen oder die Vergleichszahl senken kann, ist keine Registrierung,
sondern eine Erzählung -- man korrigiert dann auf die Zellen, die man am Ende
zeigen möchte, statt auf die, die man angesehen hat.

Diese Tests sind deshalb bewusst stumpf. Sie prüfen Buchhaltung, nicht
Statistik:

* Die deklarierte Vergleichszahl **ist** die Summe der Arme. Eine Abweichung
  heisst, dass jemand einen Arm hinzugefügt und die Korrektur nicht
  mitgezogen hat -- genau die Lücke, durch die eine Mehrfachkorrektur
  stillschweigend zu schwach wird.
* Jedes Experiment nennt Arme, eine primäre Kennzahl und eine Abnahmebedingung.
  Ein Arm ohne vorab festgelegte Kennzahl lässt sich nach dem Ergebnis
  bewerten, und das ist der häufigste Weg zu einem Scheinfund.
* Verbotene Merkmale stehen in keiner Erlaubt-Liste. Das Projekt hat schon
  einmal eine Vergleichsgrösse auf eine Grösse gestützt, die das Ergebnis
  mitbestimmt (Haltedauer, Korrelation +0.52) -- dieser Test macht die
  Wiederholung zu einem roten Test statt zu einer Entdeckung in drei Wochen.
* Die harten Grenzen stehen drin und sind nicht aufgeweicht.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from traidingbrain.config.settings import load_config
from traidingbrain.learn.register import Register

REGISTRY = Path(__file__).resolve().parents[1] / "audit" / "EXPERIMENTS_NEXT.yaml"

#: Jedes Experiment braucht diese Felder, sonst ist es keine Registrierung.
REQUIRED = ("id", "title", "priority", "status", "arms", "comparisons", "acceptance")

#: Grössen, die das Ergebnis mitbestimmen. Sie dürfen in keiner
#: `features_allowed`-Liste auftauchen, egal in welchem Experiment.
NEVER_A_FEATURE = (
    "max_favourable_r",
    "max_adverse_r",
    "exit_reason",
    "r_multiple",
    "net_pnl",
    "realized",
    "haltezeit",
    "holding_time",
    "trade_duration",
)

#: Die Grenzen aus Abschnitt 1 des Forschungsauftrags. Jede muss als Zeile in
#: `meta.hard_limits` stehen; geprüft wird auf das Schlüsselwort, nicht auf den
#: Wortlaut, damit eine Umformulierung erlaubt und ein Weglassen rot ist.
HARD_LIMIT_KEYWORDS = (
    "1,2",            # die gehaltene Bestätigung
    "allow_live",     # zwei unabhängige Signale
    "Auszahlungsrecht",
    "absolute_max_risk_pct",
    "Secrets",
)


@pytest.fixture(scope="module")
def registry() -> dict[str, Any]:
    if not REGISTRY.is_file():
        pytest.fail(f"{REGISTRY} fehlt -- ohne Registrierung keine Charge.")
    loaded = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_the_declared_comparison_count_is_the_sum_of_the_arms(registry: dict) -> None:
    """Die Zahl, auf die korrigiert wird, muss die Zahl der Zellen sein.

    Das ist die wichtigste Zeile dieser Datei. Ein neuer Arm, dessen Vergleich
    nicht in `total_comparisons` landet, schwächt jede Korrektur, ohne dass es
    irgendwo auffällt -- und die Schwäche zeigt sich erst, wenn eine Zelle
    überlebt, die es nicht sollte.
    """
    counted = sum(int(e["comparisons"]) for e in registry["experiments"])
    declared = int(registry["meta"]["total_comparisons"])
    assert counted == declared, (
        f"{len(registry['experiments'])} Experimente ergeben {counted} Vergleiche, "
        f"deklariert sind {declared}. Wer einen Arm hinzufuegt, zieht die Korrektur mit."
    )


def test_every_experiment_declares_what_it_will_be_judged_by(registry: dict) -> None:
    for experiment in registry["experiments"]:
        missing = [field for field in REQUIRED if field not in experiment]
        assert not missing, f"{experiment.get('id', '?')} ohne {missing}"
        assert experiment["arms"], f"{experiment['id']} hat keine Arme"
        assert len(experiment["arms"]) == len({a["id"] for a in experiment["arms"]}), (
            f"{experiment['id']} hat doppelte Arm-Kennungen"
        )


def test_no_experiment_allows_a_feature_that_knows_the_outcome(registry: dict) -> None:
    """Ein Merkmal, das den Ausgang kennt, macht jeden Arm beliebig gut.

    Konkreter Anlass: die Haltedauer korreliert in diesem Projekt mit +0.52 zum
    Ergebnis (`scripts/study_stop_path.py`). Eine Vergleichsgrösse darauf zu
    stützen hiess, auf das Ergebnis zu bedingen.
    """
    for experiment in registry["experiments"]:
        allowed = [str(f).lower() for f in experiment.get("features_allowed", [])]
        for forbidden in NEVER_A_FEATURE:
            hits = [f for f in allowed if forbidden in f]
            assert not hits, f"{experiment['id']} erlaubt '{forbidden}' ueber {hits}"


def test_the_hard_limits_are_present_and_not_softened(registry: dict) -> None:
    text = "\n".join(registry["meta"]["hard_limits"])
    for keyword in HARD_LIMIT_KEYWORDS:
        assert keyword in text, f"Harte Grenze zu '{keyword}' fehlt in meta.hard_limits"


def test_the_risk_ceiling_matches_the_shipped_config(registry: dict) -> None:
    """Die Registrierung darf keine andere Obergrenze behaupten als die Konfiguration.

    Zwei Zahlen für dieselbe Grenze sind schlimmer als eine falsche: man liest
    die freundlichere.
    """
    shipped = load_config().risk.sizing.absolute_max_risk_pct
    text = "\n".join(registry["meta"]["hard_limits"])
    assert f"{shipped:.3f}" in text, (
        f"Konfiguration erlaubt maximal {shipped:.3f}; die Registrierung nennt das nicht."
    )


def test_the_champion_in_the_registry_is_the_one_in_the_experiment_file(registry: dict) -> None:
    """"Besser als der Champion" ist nur ohne Zahlendrift eine Bedingung."""
    store = load_config().engine.paths.data_dir / "experiments.sqlite"
    if not store.is_file():
        pytest.skip("Kein Register auf dieser Maschine")
    champion = Register(store).champion()
    if champion is None:
        pytest.skip("Noch kein Champion registriert")
    claimed = float(registry["meta"]["prior_search"]["champion_mean_r"])
    assert abs(champion.mean_r - claimed) < 5e-4, (
        f"Register sagt {champion.mean_r:+.4f} R, die Registrierung {claimed:+.4f} R"
    )


def test_amendments_carry_a_reason_when_they_exist(registry: dict) -> None:
    """Leer sein ist der gute Zustand; eingetragen sein braucht Datum und Grund."""
    for entry in registry.get("amendments") or []:
        assert "date" in entry and "reason" in entry, f"Nachtrag ohne Datum/Grund: {entry}"
