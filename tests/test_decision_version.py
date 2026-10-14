"""Der Entscheidungsstempel — und der Nachweis, dass er die richtige Körnung hat.

`decision_version()` behauptet im Docstring drei Dinge. Eine Behauptung über
einen Stempel, die nur im Docstring steht, ist genau das, was dieses Modul
abschaffen soll — also stehen sie hier als Tests:

1. Ein Commit, der **nur einen Bericht oder einen Docstring** schreibt, bewegt
   ihn nicht. (`code_version` bewegt sich dabei, und das macht ihn als
   Stichprobenschnitt unbrauchbar.)
2. Eine Änderung an **Code im Entscheidungspfad** bewegt ihn.
3. Eine Änderung **ausserhalb** des Pfades bewegt ihn nicht.

Dazu die Eigenschaften, ohne die er als Schlüssel nichts taugt: er ist über
Prozessgrenzen stabil, und sein Abschluss enthält wirklich die Module, die
entscheiden.

Anlass, als Datum: am 09.10.2026 wurde die Vorwärtsstichprobe dreimal
nachgeschnitten (18 → 14 → 11 Trades), und zweimal war die Begründung falsch —
die Commits waren nach ihren *Titeln* ausgewählt. Die echte Grenze trug einen
Buchhaltungstitel. Beide vorhandenen Stempel hätten die Frage nicht beantwortet:
`run_signature` deckt nur Konfiguration, `code_version` bewegt sich bei jedem
Bericht.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from traidingbrain.journal.version import (
    DECISION_ENTRY,
    closure_at,
    decision_closure,
    decision_version,
    version_at,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"

#: Module, die zwingend im Abschluss stehen müssen. Jedes davon kann
#: verändern, welche Trades entstehen; fehlte eines, hätte der Stempel ein
#: Loch und würde eine Änderung dort verschweigen.
MUST_COVER = (
    "traidingbrain.live.paper",
    "traidingbrain.strategies.guide",
    "traidingbrain.strategy.setups",
    "traidingbrain.sim.plan",
    "traidingbrain.sim.broker",
    "traidingbrain.risk.sizing",
    "traidingbrain.risk.leverage",
    "traidingbrain.analysis.pipeline",
    "traidingbrain.journal.build",
    "traidingbrain.config.settings",
)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Eine Kopie von `src/`, auf der sich gefahrlos mutieren lässt."""
    copy = tmp_path / "src"
    shutil.copytree(SRC, copy, ignore=shutil.ignore_patterns("__pycache__"))
    return copy


def _edit(tree: Path, module: str, old: str, new: str) -> None:
    path = tree / (module.replace(".", "/") + ".py")
    source = path.read_text(encoding="utf-8")
    assert old in source, f"{module}: {old!r} nicht gefunden -- der Test zielt ins Leere"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def test_the_closure_reaches_everything_that_decides() -> None:
    """Ein Loch im Abschluss wäre ein Stempel, der eine Änderung verschweigt."""
    closure = decision_closure()
    missing = [module for module in MUST_COVER if module not in closure]
    assert not missing, (
        f"diese Module entscheiden mit, stehen aber nicht im Abschluss: {missing}. "
        "Entweder importiert der Live-Pfad sie nicht mehr -- das wäre selbst der "
        "Befund -- oder die Abschlussberechnung hat eine Lücke."
    )
    assert len(closure) >= 40, (
        f"nur {len(closure)} Module im Abschluss. Der Live-Pfad erreichte beim "
        "Anlegen dieses Tests 56; ein plötzlich kleiner Abschluss heisst eher, "
        "dass die Berechnung bricht, als dass das System schrumpfte."
    )
    for entry in DECISION_ENTRY:
        assert entry in closure


def test_a_docstring_change_does_not_move_the_stamp(tree: Path) -> None:
    """Punkt 1, die Hälfte, die `code_version` falsch macht."""
    before = version_at(tree)
    _edit(
        tree,
        "traidingbrain.strategies.guide",
        '"""',
        '"""Ein Absatz, den jemand umformuliert hat, und sonst nichts.\n\n    ',
    )
    assert version_at(tree) == before, (
        "ein umformulierter Docstring hat den Stempel bewegt. Dann ist er so "
        "unbrauchbar wie der Commit: jeder Bericht würde die Stichprobe schneiden."
    )


def test_an_attribute_docstring_change_does_not_move_the_stamp(tree: Path) -> None:
    """Die Prosa-Art, die dieses Projekt tatsächlich schreibt.

    **Dieser Test fehlte, und die Lücke war genau die Lücke im Stempel.** Der
    Test darüber formuliert einen MODUL-Docstring um; `_meaning` entfernte bis
    zum 14.10.2026 nur die erste Anweisung eines Rumpfes, also den Docstring
    im engen Sinn, und war damit grün. Die langen Absätze dieses Projekts
    stehen aber unter FELDZUWEISUNGEN — in `record.py`, `settings.py`,
    `broker.py` — und das sind keine ersten Anweisungen. Sie blieben stehen,
    `ast.unparse` schrieb sie mit, und ein umformulierter Absatz schnitt die
    Vorwärtsstichprobe.

    Gemessen am 14.10.2026: der Stempel sprang von 2ec5d4ac3738 auf
    37955d5c8bb9, und dazwischen lagen ausschliesslich Prosa-Korrekturen.

    Der Test zielt bewusst auf eine Datei im Abschluss — bewegt sich der
    Stempel bei einer Datei ausserhalb nicht, beweist das nichts.
    """
    before = version_at(tree)
    _edit(
        tree,
        "traidingbrain.journal.record",
        '"""How far it ran in our favour before it ended, in units of the risk."""',
        '"""Derselbe Gedanke, völlig anders aufgeschrieben, und sonst nichts."""',
    )
    assert version_at(tree) == before, (
        "ein umformulierter ATTRIBUT-Docstring hat den Stempel bewegt. Dieses "
        "Projekt schreibt seine Prosa dort; ein Stempel, der sich daran "
        "bewegt, schneidet die Stichprobe bei jeder Korrektur eines Absatzes."
    )


def test_a_bare_string_anywhere_is_prose(tree: Path) -> None:
    """Auch mitten in einem Funktionsrumpf, wo niemand sie erwartet.

    `Expr(Constant(str))` hat in Python keine Wirkung, also kann eine solche
    Zeile nur Prosa oder toter Text sein — egal, an welcher Stelle sie steht.
    Eine Regel, die nur die erste Anweisung prüft, ist eine Regel über die
    POSITION und nicht über die Bedeutung, und das war der Defekt.
    """
    before = version_at(tree)
    path = tree / "traidingbrain/journal/version.py"
    source = path.read_text(encoding="utf-8")
    needle = "    tree = ast.parse(source)\n"
    assert needle in source, "der Test zielt ins Leere"
    path.write_text(
        source.replace(needle, needle + '    "Eine nackte Zeichenkette."\n', 1),
        encoding="utf-8",
    )

    assert version_at(tree) == before


def test_a_comment_change_does_not_move_the_stamp(tree: Path) -> None:
    """Dieselbe Hälfte, für Kommentare."""
    before = version_at(tree)
    path = tree / "traidingbrain/strategy/setups.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n# Ein Kommentar am Ende der Datei.\n",
        encoding="utf-8",
    )
    assert version_at(tree) == before, "ein Kommentar hat den Stempel bewegt"


def test_reformatting_does_not_move_the_stamp(tree: Path) -> None:
    """Auch Formatierung darf keine Stichprobe schneiden."""
    before = version_at(tree)
    _edit(
        tree,
        "traidingbrain.risk.leverage",
        "from __future__ import annotations",
        "from __future__ import annotations\n\n",
    )
    assert version_at(tree) == before, "eine Leerzeile hat den Stempel bewegt"


@pytest.mark.parametrize(
    ("module", "old", "new"),
    [
        # Das geplante Chance-Risiko von Setup A -- verändert unmittelbar,
        # welches Ziel ein Trade bekommt.
        ("traidingbrain.strategy.setups", "BREAKOUT_FIRST_TARGET_R = 1.5",
         "BREAKOUT_FIRST_TARGET_R = 1.6"),
        # Die Zahl der Entscheidungsversuche je Balken. GENAU die Änderung vom
        # 04.10. 21:52 UTC, die die Vorwärtsstichprobe geschnitten hat und die
        # `run_signature` nicht gesehen hat.
        ("traidingbrain.live.paper", "MAX_DECISION_ATTEMPTS = 3",
         "MAX_DECISION_ATTEMPTS = 4"),
        # Die feste Zuversicht der Setups, aus der das Risiko-Budget folgt.
        ("traidingbrain.strategies.guide", "FIXED_CONFIDENCE = 60.0",
         "FIXED_CONFIDENCE = 65.0"),
    ],
)
def test_a_code_change_in_the_decision_path_moves_the_stamp(
    tree: Path, module: str, old: str, new: str
) -> None:
    """Punkt 2, und der mittlere Fall ist der historische.

    `MAX_DECISION_ATTEMPTS` ist die Konstante, die am 04.10.2026 um 21:52 UTC
    die homogene Stichprobe begrenzt hat. `run_signature` bewegte sich dabei
    nicht, und darum wurde der Schnitt erst vier Tage später aus neunzehn Diffs
    rekonstruiert. Dieser Test ist der Beleg, dass derselbe Fall heute auffiele.
    """
    before = version_at(tree)
    _edit(tree, module, old, new)
    assert version_at(tree) != before, (
        f"eine Änderung an {old!r} in {module} hat den Stempel NICHT bewegt. "
        "Dann trennt er die Stichproben nicht, und genau dafür existiert er."
    )


def test_a_change_outside_the_decision_path_does_not_move_the_stamp(
    tree: Path,
) -> None:
    """Punkt 3. Sonst wäre der Stempel nur ein langsamer `code_version`."""
    before = version_at(tree)
    outside = tree / "traidingbrain" / "nur_fuer_den_test.py"
    outside.write_text(
        "X = 1\n", encoding="utf-8"
    )
    assert version_at(tree) == before, (
        "eine neue Datei ausserhalb des Entscheidungspfades hat den Stempel "
        "bewegt -- dann schneidet er Stichproben ohne Grund."
    )
    assert "traidingbrain.nur_fuer_den_test" not in closure_at(tree)


def test_the_stamp_survives_a_fresh_process() -> None:
    """Kein `hash()`: der ist je Prozess gesalzen, und ein Schlüssel, der sich
    beim Neustart ändert, teilt eine Stichprobe in so viele Teile wie es
    Neustarts gab."""
    code = (
        "import sys; sys.path.insert(0, r'" + str(SRC) + "');"
        "from traidingbrain.journal.version import decision_version;"
        "print(decision_version())"
    )
    runs = [
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, check=True, cwd=PROJECT_ROOT,
        ).stdout.strip()
        for _ in range(2)
    ]
    assert runs[0] == runs[1] != "", f"Stempel instabil über Prozesse: {runs}"
    assert runs[0] == decision_version(), (
        f"der Unterprozess meldet {runs[0]}, dieser Prozess {decision_version()}"
    )
