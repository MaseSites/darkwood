"""Welche Commits können verändert haben, welche Trades entstehen?

    python scripts/live_path_changes.py --since "2026-10-04 12:30"

**Anlass.** Am 09.10.2026 habe ich die Vorwärtsstichprobe zweimal
nachträglich geschnitten und beide Male die Commits **nach ihren Titeln**
ausgewählt. Das Ergebnis war richtig und die Begründung falsch:

* *„Prefer a target that gets hit over one that pays more"* — klingt
  strategiewirksam, ist ein Beschriftungsfeld plus eine Strategie, die live
  nicht läuft.
* *„Open a second strategy family"* — klingt strategiewirksam, legt eine
  neue Datei an, die nur `challenge.py` erreicht.
* *„Stop losing forward evidence while it is being recorded"* — klingt nach
  Buchhaltung, setzt `MAX_DECISION_ATTEMPTS = 3` und verändert damit,
  **welche Balken überhaupt entschieden werden**. Das war die echte Grenze.

Ein Commit-Titel ist Prosa, keine Signatur. Dieses Skript ersetzt das Raten
durch die zwei Schritte, die sich automatisieren lassen:

1. **Den Import-Abschluss** des Live-Einstiegs bilden — welche Dateien der
   Entscheidungspfad überhaupt erreicht. Alles ausserhalb kann nicht wirken,
   egal wie der Commit heisst.
2. **Die Commits auf genau diese Dateien** auflisten, mit Diff-Umfang, damit
   jeder einzeln gelesen und eingeordnet werden kann.

**Den dritten Schritt macht das Skript nicht.** Ob eine Änderung verändert,
welche Trades entstehen, entscheidet nur das Lesen des Diffs — ein neues Feld
mit Default ist harmlos, eine Wiederholungsschleife nicht, und ein
Zeitausstieg, der in `settings.yaml` nicht eingeschaltet ist, auch nicht. Das
Skript liefert die **Kandidatenliste**, nicht das Urteil. Wer seine Ausgabe
als Urteil liest, hat denselben Fehler nur eine Ebene höher gemacht.

Nur lesen: `git log` und der Quelltext. Kein Netz, keine Börse.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: Der Einstieg des Prozesses, der Vorwärts-Evidenz erzeugt. `papertrade.py`
#: selbst steht nicht hier, weil es ein Skript ist; was es importiert, steht.
ENTRY = ("traidingbrain.live.paper", "traidingbrain.live.paperstate")

#: Der letzte Schnitt, der gemessen und begründet ist. Siehe
#: `audit/DIE_VORWAERTSSTICHPROBE.md`.
DEFAULT_SINCE = "2026-10-04 21:52"


def import_closure(entry: tuple[str, ...]) -> list[str]:
    """Alle Projektdateien, die der Einstieg transitiv erreicht."""
    seen: set[str] = set()
    todo = list(entry)
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        seen.add(module)
        path = SRC / (module.replace(".", "/") + ".py")
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
                todo.extend(a.name for a in node.names if a.name.startswith("traidingbrain"))
    return sorted(
        "src/" + m.replace(".", "/") + ".py"
        for m in seen
        if (SRC / (m.replace(".", "/") + ".py")).exists()
    )


def git(*args: str) -> str:
    """`git` im Projektverzeichnis, ohne Zeilenende-Überraschungen.

    Die Pfade gehen als Argumente und nie über eine Datei: eine Liste, die
    Python mit `write_text` schreibt, trägt unter Windows `\\r\\n`, und ein
    Pfadmuster mit `\\r` am Ende passt auf nichts. `git log` meldet dann
    **keine Commits** -- was aussieht wie „keine Änderungen" und es nicht ist.
    Genau so ist mir dieser Lauf schon einmal lautlos leer zurückgekommen.
    """
    done = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return done.stdout


def changes(paths: list[str], since: str) -> list[tuple[str, str, str, list[str]]]:
    out = git(
        "log", "--format=%h|%ad|%s", "--date=format:%d.%m. %H:%M", f"--since={since}",
        "--", *paths,
    )
    found = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, when, subject = line.split("|", 2)
        touched = [
            f for f in git("show", "--name-only", "--format=", sha).splitlines()
            if f.strip() in paths
        ]
        found.append((sha, when, subject, touched))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default=DEFAULT_SINCE,
        help=f"Zeitpunkt des letzten Schnitts (Default {DEFAULT_SINCE}, Ortszeit wie git)",
    )
    args = parser.parse_args()

    paths = import_closure(ENTRY)
    print("=" * 78)
    print("Was den Live-Entscheidungspfad seit dem Schnitt berührt hat")
    print("=" * 78)
    print(f"\n  Einstieg        : {', '.join(ENTRY)}")
    print(f"  Import-Abschluss: {len(paths)} Dateien")
    print(f"  Schnitt         : {args.since}\n")

    found = changes(paths, args.since)
    if not found:
        print("  Kein Commit berührt den Live-Pfad seit diesem Zeitpunkt.")
        print("  Die Stichprobe ab hier ist in dieser Hinsicht homogen.\n")
        return 0

    print(f"  {len(found)} Commits, jeder einzeln zu lesen:\n")
    for sha, when, subject, touched in found:
        stat = git("show", "--shortstat", "--format=", sha).strip().splitlines()
        print(f"  {sha}  {when}  {subject}")
        print(f"      {', '.join(touched)}")
        if stat:
            print(f"      {stat[-1].strip()}")
        print()

    print("  Das ist die KANDIDATENLISTE, nicht das Urteil. Für jeden Commit:")
    print("  verändert er, welche Trades entstehen oder wie sie aufgehen?")
    print("  Ein Feld mit Default: nein. Eine Wiederholungsschleife: ja.")
    print("  Ein Schalter, der in settings.yaml aus ist: nein.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
