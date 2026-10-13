"""What produced a row, so that two results can be told apart.

Every study in `scripts/` reads the signal ledger through a `run_signature` --
a string describing the configuration a run was made under, so that rows from
different settings cannot be averaged together. It worked, and it was copied by
hand into three scripts, where it immediately drifted: `study_refused.py`
included `max_bars` and the other two did not. A signature that differs by one
character does not return the wrong rows, it returns *no* rows, and a study that
silently reports on an empty set is worse than one that crashes.

That drift already cost something today. A 400-bar transport check shared the
full run's signature, so the full run was skipped as "already collected" and
fourteen rows nearly became the answer. `max_bars` went into the signature to
fix it -- in one script.

So the signature is computed in exactly one place here, and the scripts ask for
it rather than describing it.

**The second half is provenance, and it is what section 13 needs.** The
signature says which *configuration* produced a row. It says nothing about which
*code* produced it, and champion-versus-challenger is a comparison between two
versions of the code. Without the commit on the row there is no way to notice
that a comparison is quietly mixing two of them -- the rows look identical and
the numbers average cleanly.

`code_version()` is therefore recorded alongside each row as a fact, and
`spread()` reports how many distinct versions a result set spans. Detecting
contamination is the useful half; keying on the commit would be worse than
useless, because every unrelated edit would orphan hours of collected ledger and
force a re-collection that proves nothing.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import subprocess
from collections.abc import Iterable
from pathlib import Path

#: Bumped by hand when the *meaning* of a stored row changes.
#:
#: Not derived from anything. A column that changes interpretation without
#: changing name or type is invisible to every automatic check, and this is the
#: one thing a human has to remember.
LEDGER_SCHEMA = "refused-v1"

#: What `code_version()` reports when the question cannot be answered.
UNKNOWN = "unknown"

_GIT_TIMEOUT_S = 5

#: Der Deckelwert, unter dem die vorhandenen Zeilen geschrieben wurden.
#:
#: Kein Vorgabewert des Modells -- `LimitsConfig.max_open_positions` hat
#: keinen, die Zahl muss in der YAML-Datei stehen. Dies ist der historische
#: Anker: 2 ist der Wert, der galt, als die 12.843 Zeilen im Speicher
#: entstanden. Weicht die Konfiguration davon ab, bekommt die Signatur einen
#: Zusatz, und die alten Zeilen verwaisen nicht.
#:
#: Das ist eine Aussage ueber die Vergangenheit und keine Politik. Wer den
#: Deckel fuer richtig oder falsch haelt, aendert `config/risk.yaml`, nicht
#: diese Zeile.
_CAP_ANCHOR = 2


def run_signature(config: object, *, max_bars: int | None = None, shadow: bool = False) -> str:
    """The configuration a run was made under, as one comparable string.

    Byte-identical to what the three scripts built by hand, deliberately: the
    ledger already holds thousands of rows under these exact strings, and
    changing the format would orphan them.

    `max_bars` belongs here because a truncated run is a different run. Leaving
    it out let a 400-bar transport check occupy the rows a full replay would
    have written.

    `shadow` belongs here for the same reason and would have bitten harder. A
    shadow run writes the OCCUPIED rows a plain run has no record of, so its
    population is strictly larger. Sharing a key would have meant the plain
    rows already present made `count()` non-zero, the shadow run reported
    "Signale liegen vor" and skipped, and the shadow population would have
    stayed empty while looking collected.

    Both suffixes are appended only when set, so the plain signature stays
    byte-identical to the one the ledger's 12,843 rows are already keyed by.
    """
    engine = config.engine  # type: ignore[attr-defined]
    risk = config.risk  # type: ignore[attr-defined]
    bars = f"|{max_bars}bars" if max_bars else ""
    shade = "|shadow" if shadow else ""
    # Nur angehaengt, wenn er vom Vorgabewert abweicht, damit die 12.843
    # Zeilen, die der Speicher unter der alten Signatur haelt, nicht
    # verwaisen. Dieselbe Begruendung wie bei `bars` und `shadow`.
    basis = ("|portfolio" if risk.sizing.basis == "portfolio" else "")
    # Der Deckel auf gleichzeitig offene Positionen.
    #
    # Er gehoert hierher, seit er ueberhaupt ausloesen kann. Bis zum
    # 13.10.2026 war er im Papierhandel wirkungslos -- zwoelf getrennte Konten
    # mit je einem Einplatz-Broker spueren keinen Wert dieser Einstellung --
    # und seit dem Buch des gepoolten Kontos entscheidet er, welche Trades
    # ueberhaupt entstehen.
    #
    # Ohne diese Spur waere es genau der Fehler, der die Vorwaertsstichprobe
    # schon einmal von 18 auf 11 Trades hat schrumpfen lassen: eine
    # Konfigurationsaenderung, die das Verhalten aendert und keine Spur
    # hinterlaesst, sodass die Zugehoerigkeit nur aus der Git-Historie zu
    # erschliessen ist. `decision_version` faengt das NICHT -- der bewegt sich
    # bei Codeaenderungen, nicht bei einer Zahl in der YAML-Datei.
    cap = "" if risk.limits.max_open_positions == _CAP_ANCHOR else (
        f"|cap{risk.limits.max_open_positions}"
    )
    return (
        f"{engine.simulation.initial_equity}|{engine.setups.enabled}|"
        f"{risk.limits.max_cost_fraction_of_risk}|{engine.timeframes.signal.value}"
        f"|{LEDGER_SCHEMA}{basis}{cap}{bars}{shade}"
    )


@functools.lru_cache(maxsize=1)
def code_version() -> str:
    """The commit that produced a row, with `-dirty` when the tree was not clean.

    Cached, because it is asked once per row and the answer cannot change inside
    a process without the process having been edited underneath itself.

    A dirty tree is reported rather than rejected. Most runs here happen on an
    uncommitted working tree, and refusing to record anything would simply mean
    no provenance at all; `-dirty` says honestly that the commit alone does not
    identify this code.
    """
    root = Path(__file__).resolve().parents[3]
    head = _git("rev-parse", "--short", "HEAD", cwd=root)
    if head is None:
        return UNKNOWN
    status = _git("status", "--porcelain", cwd=root)
    if status is None:
        return f"{head}+{UNKNOWN}"
    return f"{head}-dirty" if status.strip() else head


#: Wo der Entscheidungspfad anfängt. `papertrade.py` steht nicht hier, weil es
#: ein Skript ist und kein Modul; was es importiert, steht.
DECISION_ENTRY = ("traidingbrain.live.paper", "traidingbrain.live.paperstate")

#: Länge des Entscheidungsstempels. Zwölf Hex-Zeichen sind 48 Bit; bei einigen
#: hundert Versionen über die Lebensdauer dieses Projekts ist eine Kollision
#: nicht die Sorge, die eine längere Zeichenkette wert wäre.
_STAMP = 12


@functools.lru_cache(maxsize=1)
def decision_closure() -> tuple[str, ...]:
    """Jede Projektdatei, die der Live-Entscheidungspfad transitiv erreicht.

    Berechnet statt gepflegt. Eine Liste von Hand wäre am Tag ihres Schreibens
    richtig und danach nie wieder — und genau das ist der Fehler, den diese
    Datei zu reparieren versucht.
    """
    return closure_at(Path(__file__).resolve().parents[2])


def closure_at(src: Path) -> tuple[str, ...]:
    """Derselbe Abschluss gegen einen beliebigen Quellbaum.

    Getrennt, damit ein Test den Stempel an einer *Kopie* mit einer Änderung
    darin prüfen kann, statt die Behauptung „eine Codeänderung bewegt ihn" zu
    glauben. Eine Behauptung über einen Stempel, die nur im Docstring steht,
    ist genau das, was dieses Modul abschaffen soll.
    """
    seen: set[str] = set()
    todo = list(DECISION_ENTRY)
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        seen.add(module)
        path = src / (module.replace(".", "/") + ".py")
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = ".".join(module.split(".")[: -node.level])
                    todo.append(f"{base}.{node.module}" if node.module else base)
                elif node.module and node.module.startswith("traidingbrain"):
                    todo.append(node.module)
            elif isinstance(node, ast.Import):
                todo.extend(
                    alias.name for alias in node.names
                    if alias.name.startswith("traidingbrain")
                )
    return tuple(sorted(
        module for module in seen
        if (src / (module.replace(".", "/") + ".py")).exists()
    ))


def _meaning(source: str) -> str:
    """Der Quelltext ohne Kommentare, Docstrings und Formatierung.

    `ast.parse` verliert Kommentare ohnehin, `ast.unparse` normalisiert die
    Formatierung, und die Docstrings werden hier ausdrücklich entfernt. Das ist
    der ganze Zweck: dieses Projekt schreibt sehr lange Docstrings, und ein
    Stempel, der sich bei einem umformulierten Absatz bewegt, wäre genauso
    unbrauchbar wie der Commit.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            # Ein Rumpf darf nicht leer werden, sonst ist der Baum ungültig.
            node.body = body[1:] if len(body) > 1 else [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


@functools.lru_cache(maxsize=1)
def decision_version() -> str:
    """Ein Stempel über die **Bedeutung** des entscheidenden Codes.

    Der Grund, warum es diese Funktion gibt, steht als Datum fest. Am
    09.10.2026 musste die Vorwärtsstichprobe dreimal nachgeschnitten werden
    (18 → 14 → 11 Trades), und zweimal war die Begründung falsch, weil die
    beiden vorhandenen Stempel beide die falsche Körnung haben:

    * `run_signature` deckt die **Konfiguration** — Startkapital, Setup-Liste,
      Kostendeckel, Signalebene, Ablehnungsversion — und verpasst jedes
      Verhalten, das im Code wohnt.
    * `code_version` deckt den **Commit** exakt und bewegt sich auch dann, wenn
      nur ein Bericht geschrieben wurde.

    Zu grob und zu fein. Dieser Stempel liegt dazwischen: er hasht den
    Quelltext der 59 Dateien, die der Live-Entscheidungspfad erreicht, ohne
    Kommentare, Docstrings und Formatierung. Ein Commit, der einen Bericht
    schreibt, bewegt ihn nicht. Ein Commit, der eine Setup-Schwelle ändert,
    bewegt ihn — und `run_signature` hätte das nicht gesehen.

    **Absichtlich konservativ.** Der Abschluss enthält auch Dateien, deren
    Änderung keine Entscheidung verändern kann (`journal/store.py` schreibt nur
    weg). Der Stempel bewegt sich dann, obwohl das Verhalten gleich blieb. Das
    ist die richtige Richtung für den Fehler: ein überflüssiger Schnitt kostet
    Stichprobe, ein fehlender verdirbt sie. Eine handgepflegte Ausnahmeliste
    wäre wieder ein Urteil, das verrottet.

    **Was er nicht leistet.** Er sagt *dass* sich der Entscheidungscode geändert
    hat, nicht *ob die Änderung eine Entscheidung verändert*. Das entscheidet
    nur das Lesen des Diffs — oder `tests/test_live_decision_golden.py`, der
    genau diese Frage an gefrorenen Kerzen beantwortet. Die beiden gehören
    zusammen: der Stempel trennt die Stichproben, der Golden-Test sagt, ob sie
    getrennt werden müssen.

    *Gebunden an die Python-Version:* `ast.unparse` darf seine Ausgabe zwischen
    Interpreter-Versionen ändern, und dann bewegt sich jeder Stempel auf einmal.
    Das ist nicht abzufangen, ohne wieder rohe Bytes zu hashen; es gehört
    gewusst und steht darum hier.
    """
    return version_at(Path(__file__).resolve().parents[2])


def version_at(src: Path) -> str:
    """Derselbe Stempel gegen einen beliebigen Quellbaum. Siehe `closure_at`."""
    parts: list[str] = []
    for module in closure_at(src):
        path = src / (module.replace(".", "/") + ".py")
        try:
            parts.append(f"{module}\n{_meaning(path.read_text(encoding='utf-8'))}")
        except (OSError, SyntaxError) as problem:
            # Nicht stillschweigend überspringen: eine ausgelassene Datei ist
            # ein Loch im Stempel, und ein Loch meldet sich nie.
            raise RuntimeError(
                f"{module} nicht lesbar für den Stempel: {problem}"
            ) from problem
    joined = "\n\x00\n".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:_STAMP]


def _git(*args: str, cwd: Path) -> str | None:
    """`None` on any failure, because provenance must never break a run."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Stripped here rather than at each call site: git appends a newline to
    # every answer, and a newline inside a stamp is invisible in every report
    # that prints it and breaks every comparison that does not.
    return done.stdout.strip() if done.returncode == 0 else None


def spread(versions: Iterable[str]) -> list[str]:
    """The distinct code versions in a result set, sorted, blanks folded in.

    More than one is not automatically wrong -- a refactor that cannot change a
    decision leaves the numbers comparable -- but it is never something to find
    out afterwards. Callers print it beside the result rather than deciding for
    the reader.
    """
    return sorted({version or UNKNOWN for version in versions})
