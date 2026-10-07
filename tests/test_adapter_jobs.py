"""The job registry: one at a time, no duplicates, and a log that cannot deadlock.

These run real subprocesses, short ones. A fake would prove the bookkeeping and
miss the three things that actually matter here -- that a second heavy job is
refused, that a retry does not start a second copy, and that a child writing
more output than a pipe buffer holds does not hang forever.

That last one is why the log goes to a file. A subprocess writing to a pipe
nobody drains fills the buffer and blocks, and it blocks on exactly the
long-running jobs the registry exists for. `test_a_chatty_child_does_not_hang`
is the test that would catch a regression to pipes, and it is the reason it
produces more output than any pipe buffer.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from traidingbrain.adapter.jobs import DEFAULT_LIMIT_SECONDS, Registry, State

PY = sys.executable

#: A child that exits immediately.
QUICK = [PY, "-c", "print('fertig')"]

#: A child that lives long enough to be observed as running.
SLOW = [PY, "-c", "import time; time.sleep(30)"]

#: A child that writes far more than any pipe buffer holds. 64 KiB is the
#: usual Windows pipe and 64 KiB the usual POSIX one; this is about 2 MiB.
CHATTY = [PY, "-c", "print('x' * 200)\n" * 1 or "x"]
CHATTY = [PY, "-c", "for _ in range(10000): print('x' * 200)"]


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "jobs.json", log_dir=tmp_path / "logs")


def wait_until_done(registry: Registry, job_id: str, *, seconds: float = 60.0) -> None:
    """Warten, bis ein echtes Kind fertig ist -- mit einem lesbaren Scheitern.

    Das Budget war 20 s und ist 60 s, und der Grund gehoert hierher statt in
    eine Commit-Zeile. Diese Tests starten echte Prozesse. Am 07.10.2026 fiel
    `test_the_job_id_is_derived_from_the_command` im Gesamtlauf, waehrend
    parallel ein FreqAI-Backtest lief -- 18 python.exe-Prozesse auf der
    Maschine. Dieselbe Datei lief unmittelbar danach dreimal hintereinander
    gruen, allein und unter derselben Last.

    Ein `print()`-Kind braucht unter einer Sekunde. 60 s sind also weiter
    sechzigfach grosszuegig und erkennen einen wirklich haengenden Job
    immer noch. Was sich aendert, ist die Lesbarkeit des Scheiterns: ein
    rotes Ergebnis, das "die Maschine war beschaeftigt" bedeutet, erzieht
    dazu, rote Ergebnisse zu ignorieren -- und das ist teurer als der Test
    wert ist.
    """
    started = time.time()
    deadline = started + seconds
    while time.time() < deadline:
        job = registry.get(job_id)
        if job is not None and job.state != State.RUNNING:
            return
        time.sleep(0.2)
    waited = time.time() - started
    job = registry.get(job_id)
    pytest.fail(
        f"{job_id} lief nach {waited:.1f}s noch (Zustand "
        f"{job.state if job else 'nicht gefunden'}).\n"
        f"Das ist eine Wanduhr-Zusicherung auf einem echten Unterprozess. Bevor "
        f"dies als Defekt gelesen wird: laeuft noch etwas Grosses auf der "
        f"Maschine? Ein Backtest neben dem Gesamtlauf hat genau das hier schon "
        f"einmal ausgeloest. Diese Datei allein laufen lassen -- bleibt sie rot, "
        f"ist es der Code."
    )


def test_a_job_starts_and_reports_itself(registry: Registry, tmp_path: Path) -> None:
    job, note = registry.start(kind="quick", command=QUICK, cwd=tmp_path)
    assert "Gestartet" in note
    assert job.job_id.startswith("quick-")
    assert job.pid > 0
    wait_until_done(registry, job.job_id)
    assert registry.get(job.job_id).state == State.DONE  # type: ignore[union-attr]


def test_the_same_command_does_not_start_a_second_copy(
    registry: Registry, tmp_path: Path
) -> None:
    """The protection a caller retrying on a timeout depends on.

    Without it, a client that gives up waiting and asks again doubles the load
    on a machine the research order limits to one job.
    """
    first, _ = registry.start(kind="slow", command=SLOW, cwd=tmp_path)
    second, note = registry.start(kind="slow", command=SLOW, cwd=tmp_path)

    assert second.job_id == first.job_id
    assert second.pid == first.pid
    assert "laeuft schon" in note.lower()
    assert len(registry.running()) == 1
    registry.stop(first.job_id)


def test_a_different_job_is_refused_while_one_runs(
    registry: Registry, tmp_path: Path
) -> None:
    """One at a time, which the research order fixes.

    Two twelve-market runs at once do not finish in half the time; they thrash
    the machine and both take longer.
    """
    first, _ = registry.start(kind="slow", command=SLOW, cwd=tmp_path)
    with pytest.raises(RuntimeError, match="laeuft schon ein Job"):
        registry.start(
            kind="other",
            command=[PY, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
        )
    assert len(registry.running()) == 1
    registry.stop(first.job_id)


def test_the_job_id_is_derived_from_the_command(registry: Registry, tmp_path: Path) -> None:
    """Deterministic, which is what makes duplicate detection possible at all."""
    one, _ = registry.start(kind="quick", command=QUICK, cwd=tmp_path)
    wait_until_done(registry, one.job_id)
    again, _ = registry.start(kind="quick", command=QUICK, cwd=tmp_path)
    assert again.job_id == one.job_id, "Gleicher Befehl, gleiche Kennung"
    wait_until_done(registry, again.job_id)

    other, _ = registry.start(kind="quick", command=[PY, "-c", "print('anders')"], cwd=tmp_path)
    assert other.job_id != one.job_id
    wait_until_done(registry, other.job_id)


def test_the_registry_survives_a_restart(tmp_path: Path) -> None:
    """A status lookup after a reload must find the record.

    An in-memory dictionary would lose every job the moment the adapter
    reloaded, which for hour-long jobs is the common case and not the edge.
    """
    path = tmp_path / "jobs.json"
    logs = tmp_path / "logs"
    first = Registry(path, log_dir=logs)
    job, _ = first.start(kind="quick", command=QUICK, cwd=tmp_path)
    wait_until_done(first, job.job_id)

    fresh = Registry(path, log_dir=logs)
    found = fresh.get(job.job_id)
    assert found is not None
    assert found.command == QUICK
    assert found.state != State.RUNNING


def test_a_job_whose_process_vanished_is_reconciled(tmp_path: Path) -> None:
    """Nobody reaped it, so the record must be corrected on the next read.

    This is the restart case: the adapter went away, the child finished, and
    the stored state still says RUNNING. A registry that believed itself would
    refuse every new job forever.
    """
    path = tmp_path / "jobs.json"
    registry = Registry(path, log_dir=tmp_path / "logs")
    job, _ = registry.start(kind="quick", command=QUICK, cwd=tmp_path)
    wait_until_done(registry, job.job_id)

    # Forge the stored state back to RUNNING with a pid that cannot exist.
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw[job.job_id]["state"] = State.RUNNING.value
    raw[job.job_id]["finished_ms"] = None
    raw[job.job_id]["pid"] = 999_999_999
    path.write_text(json.dumps(raw), encoding="utf-8")

    reconciled = Registry(path, log_dir=tmp_path / "logs").get(job.job_id)
    assert reconciled is not None
    assert reconciled.state == State.DONE
    assert reconciled.finished_ms is not None
    # And a new job may start again.
    assert Registry(path, log_dir=tmp_path / "logs").running() == []


def test_a_chatty_child_does_not_hang(registry: Registry, tmp_path: Path) -> None:
    """About 2 MiB of output, far past any pipe buffer.

    If the log ever goes back to `subprocess.PIPE` without a reader, this test
    hangs instead of failing -- which is itself the signal, and why the timeout
    here is generous rather than absent.
    """
    job, _ = registry.start(kind="chatty", command=CHATTY, cwd=tmp_path)
    wait_until_done(registry, job.job_id, seconds=60.0)

    log = Path(job.log)
    assert log.is_file()
    assert log.stat().st_size > 1_000_000, "Das Kind hat wirklich viel geschrieben"


def test_the_tail_reads_the_end_without_reading_everything(
    registry: Registry, tmp_path: Path
) -> None:
    """A FreqAI run writes tens of megabytes; showing sixty lines must stay cheap."""
    job, _ = registry.start(kind="chatty", command=CHATTY, cwd=tmp_path)
    wait_until_done(registry, job.job_id, seconds=60.0)

    tail = registry.tail(job.job_id, lines=10)
    assert len(tail.splitlines()) <= 10
    assert "x" in tail
    # A byte budget, not the whole file.
    assert len(tail) < 100_000


def test_the_tail_of_an_unknown_job_says_so(registry: Registry) -> None:
    assert "Keine Job-Kennung" in registry.tail("quick-0123456789ab")


def test_stopping_a_running_job_marks_it_stopped(registry: Registry, tmp_path: Path) -> None:
    job, _ = registry.start(kind="slow", command=SLOW, cwd=tmp_path)
    message = registry.stop(job.job_id)
    assert "abgebrochen" in message
    assert registry.get(job.job_id).state == State.STOPPED  # type: ignore[union-attr]


def test_stopping_a_finished_job_is_not_an_error(registry: Registry, tmp_path: Path) -> None:
    job, _ = registry.start(kind="quick", command=QUICK, cwd=tmp_path)
    wait_until_done(registry, job.job_id)
    assert "laeuft nicht mehr" in registry.stop(job.job_id)


def test_stopping_an_unknown_job_says_so(registry: Registry) -> None:
    assert "Keine Job-Kennung" in registry.stop("quick-0123456789ab")


def test_an_overdue_job_is_flagged_but_not_killed(tmp_path: Path) -> None:
    """A long run is the point; an overdue one is only reported.

    Killing it automatically would end a four-hour collection at the three-hour
    mark because somebody set a limit for a different job.
    """
    registry = Registry(tmp_path / "jobs.json", log_dir=tmp_path / "logs")
    job, _ = registry.start(kind="slow", command=SLOW, cwd=tmp_path, limit_seconds=0)
    time.sleep(1.1)
    found = registry.get(job.job_id)
    assert found is not None
    assert found.overdue
    assert found.state == State.RUNNING, "Gemeldet, nicht beendet"
    registry.stop(job.job_id)


def test_the_default_limit_is_the_orders_five_hours() -> None:
    assert DEFAULT_LIMIT_SECONDS == 5 * 3600


def test_the_environment_can_be_narrowed_for_a_child(
    registry: Registry, tmp_path: Path
) -> None:
    """Thread caps reach the child, which is how the two-thread rule is enforced."""
    command = [
        PY,
        "-c",
        "import os; print('OMP=' + os.environ.get('OMP_NUM_THREADS', 'unset'))",
    ]
    job, _ = registry.start(
        kind="quick", command=command, cwd=tmp_path, env={"OMP_NUM_THREADS": "2"}
    )
    wait_until_done(registry, job.job_id)
    assert "OMP=2" in registry.tail(job.job_id)


def test_a_corrupt_registry_does_not_block_new_jobs(tmp_path: Path) -> None:
    """The jobs it described are gone either way.

    Refusing to start anything because an old file is truncated is the worse
    failure: it turns a lost record into a dead adapter.
    """
    path = tmp_path / "jobs.json"
    path.write_text("{not json", encoding="utf-8")
    registry = Registry(path, log_dir=tmp_path / "logs")
    assert registry.all() == []
    job, note = registry.start(kind="quick", command=QUICK, cwd=tmp_path)
    assert "Gestartet" in note
    wait_until_done(registry, job.job_id)


def test_the_summary_counts_what_is_running_and_overdue(
    registry: Registry, tmp_path: Path
) -> None:
    job, _ = registry.start(kind="slow", command=SLOW, cwd=tmp_path, limit_seconds=0)
    time.sleep(1.1)
    summary = registry.summary()
    assert summary["jobs_total"] == 1
    assert summary["laufend"] == 1
    assert summary["ueberfaellig"] == 1
    assert len(summary["zuletzt"]) == 1
    registry.stop(job.job_id)
