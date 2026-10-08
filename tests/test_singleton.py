"""Der Lock gegen doppelte Prozesse, gegen echte Prozesse getestet.

Ein Lock, der nur innerhalb eines Prozesses geprüft wird, beweist nichts --
genau der Fall, der schiefging, war ein **zweiter Prozess**. Darum startet der
entscheidende Test hier einen echten Subprozess.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from traidingbrain.storage.singleton import AlreadyRunningError, SingleInstance


def test_acquires_and_writes_its_pid(tmp_path: Path) -> None:
    with SingleInstance("rolle", directory=tmp_path) as lock:
        assert lock.path.is_file()
        content = lock.path.read_text(encoding="utf-8")
        assert f"pid={os.getpid()}" in content
        assert "seit=" in content


def test_second_acquire_in_same_process_is_refused(tmp_path: Path) -> None:
    with SingleInstance("rolle", directory=tmp_path), pytest.raises(AlreadyRunningError):
        SingleInstance("rolle", directory=tmp_path).acquire()


def test_different_roles_do_not_collide(tmp_path: Path) -> None:
    with (
        SingleInstance("papertrade", directory=tmp_path),
        SingleInstance("collector", directory=tmp_path),
    ):
        pass


def test_released_lock_can_be_taken_again(tmp_path: Path) -> None:
    first = SingleInstance("rolle", directory=tmp_path)
    first.acquire()
    first.release()
    second = SingleInstance("rolle", directory=tmp_path)
    second.acquire()
    second.release()


def _child_script(directory: Path) -> str:
    """Ein Kind, das die Sperre nimmt und auf ein Signal über stdin wartet."""
    root = Path(__file__).resolve().parents[1] / "src"
    return textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(root)!r})
        from pathlib import Path
        from traidingbrain.storage.singleton import SingleInstance
        import os
        lock = SingleInstance("rolle", directory=Path({str(directory)!r}))
        lock.acquire()
        print(f"gesperrt {{os.getpid()}}", flush=True)
        sys.stdin.readline()
        lock.release()
    """)


def test_a_real_second_process_is_refused(tmp_path: Path) -> None:
    """Der Fall, der wirklich passiert ist: zwei Prozesse, nicht zwei Objekte."""
    child = subprocess.Popen(
        [sys.executable, "-c", _child_script(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        word, _, child_pid = child.stdout.readline().strip().partition(" ")
        assert word == "gesperrt"

        with pytest.raises(AlreadyRunningError) as refusal:
            SingleInstance("rolle", directory=tmp_path).acquire()
        # Die Meldung muss sagen, WER hält -- sonst steht man vor einer
        # Verweigerung ohne Anhaltspunkt.
        #
        # Verglichen wird gegen die PID, die das Kind SELBST meldet, nicht
        # gegen `child.pid`: unter Windows ist das venv-`python.exe` ein
        # Starter, der den eigentlichen Interpreter als weiteren Prozess
        # startet. `child.pid` ist dann der Starter. Dieselbe Falle hat in
        # diesem Projekt schon einmal "vier Prozesse = zwei Haendler" ergeben.
        assert f"pid={child_pid}" in str(refusal.value)
    finally:
        assert child.stdin is not None
        child.stdin.write("weiter\n")
        child.stdin.flush()
        child.wait(timeout=10)


def test_lock_survives_a_killed_holder(tmp_path: Path) -> None:
    """Abgestürzter Halter: das Betriebssystem gibt frei, nicht wir.

    Das ist der Grund für `flock`/`msvcrt` statt einer PID-Prüfung. Eine
    selbstgebaute Sperre müsste hier erkennen, dass die Datei verwaist ist --
    und genau diese Erkennung ist die Stelle, an der solche Locks falsch
    werden.

    **Getötet wird der gemeldete Halter, nicht `child.pid`.** Das venv-
    `python.exe` ist unter Windows ein Starter, und ein Kill auf den Starter
    schliesst nur dessen stdin-Pipe -- der echte Halter läuft dann auf EOF in
    sein `release()` und beendet sich *ordentlich*. Der Test wäre grün und
    hätte die Freigabe durch das Betriebssystem nie geprüft.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", _child_script(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        word, _, holder_pid = child.stdout.readline().strip().partition(" ")
        assert word == "gesperrt"

        _hard_kill(int(holder_pid))

        # Keine verwaiste Sperre: der nächste Start darf übernehmen.
        _acquire_within(tmp_path, timeout=10.0)
    finally:
        child.kill()
        child.wait(timeout=10)


def _hard_kill(pid: int) -> None:
    """Prozess ohne Aufräumpfad beenden -- ein Absturz, keine Beendigung."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            check=False, capture_output=True,
        )
    else:
        os.kill(pid, signal.SIGKILL)


def _acquire_within(directory: Path, *, timeout: float) -> None:
    """Die Sperre muss binnen `timeout` frei werden.

    Geprüft wird die Eigenschaft selbst, nicht der Umweg über eine
    Prozessliste. Ein `tasklist`-Aufruf hing an der Konsolen-Kodierung und
    scheiterte dort, ohne über die Sperre etwas zu sagen -- eine Messung, die
    das Messgerät beschreibt. Ein Kill ist zudem nicht augenblicklich fertig,
    darum die Wiederholung statt eines einzelnen Versuchs.
    """
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        taken = SingleInstance("rolle", directory=directory)
        try:
            taken.acquire()
        except AlreadyRunningError as problem:
            last = problem
            time.sleep(0.1)
            continue
        taken.release()
        return
    raise AssertionError(f"Sperre nach {timeout}s noch gehalten: {last}")


def test_refusal_does_not_destroy_the_holders_diagnosis(tmp_path: Path) -> None:
    """Ein verweigerter Start darf die Sperrdatei nicht leeren.

    Wer die Datei kürzt, bevor er weiss, ob er sie halten darf, löscht die
    Angabe, wer sie hält -- und die Fehlermeldung des nächsten Versuchs sagt
    dann nichts mehr.
    """
    with SingleInstance("rolle", directory=tmp_path) as held:
        before = held.path.read_text(encoding="utf-8")
        with pytest.raises(AlreadyRunningError):
            SingleInstance("rolle", directory=tmp_path).acquire()
        assert held.path.read_text(encoding="utf-8") == before
