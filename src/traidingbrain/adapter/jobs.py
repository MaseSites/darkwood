"""Long jobs with identifiers, status, one-at-a-time and no duplicates.

A backtest takes minutes and a research round takes hours, so an MCP tool
cannot wait for one and return its result. It starts a job, hands back an
identifier, and a second tool reads the status. That is the shape the order
asks for, and the parts that make it safe rather than merely asynchronous:

* **One at a time.** The research order sets a ceiling of one concurrent job
  and two CPU threads per model. Two twelve-market runs at once do not finish
  in half the time, they thrash a 22-core machine and both take longer.
* **No duplicates.** A job is keyed by what it actually runs -- the command
  list, hashed. Asking twice for the same backtest returns the running job's
  identifier instead of starting a second one. Without this, a caller that
  retries on a timeout silently doubles the load.
* **Fixed arguments.** `start` takes a command list that the caller has already
  validated. Nothing here builds a command from free text, and `shell=False`
  is not the protection -- the allowlists in `validate.py` are.
* **Survives this process.** The registry is a JSON file, so a status lookup
  after a restart finds the record. A dictionary in memory would lose every
  job the moment the adapter reloaded, which for hour-long jobs is the common
  case rather than the edge case.

**Why the log goes to a file and not a pipe.** A subprocess writing to a pipe
nobody reads fills the pipe buffer and blocks forever. That is the classic way
a job manager deadlocks on exactly the long-running jobs it exists for.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

#: How long a job may run before `poll` reports it overdue. It is not killed
#: automatically -- a long run is the point -- but an overdue job is flagged so
#: a caller is not left waiting on something hung.
DEFAULT_LIMIT_SECONDS = 5 * 3600

#: Characters of the command hash that become the job id. Twelve hex digits is
#: 48 bits: enough that two different commands colliding is not a concern, and
#: short enough to read back over a chat.
ID_LENGTH = 12

#: Seconds to wait for a terminated job to exit before reporting that it did
#: not. Short, because the only thing waiting longer buys is a blocked tool.
STOP_GRACE = 5.0


class State(StrEnum):
    RUNNING = "laeuft"
    DONE = "fertig"
    FAILED = "fehlgeschlagen"
    STOPPED = "abgebrochen"


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    kind: str
    command: list[str]
    log: str
    pid: int
    started_ms: int
    limit_seconds: int
    label: str = ""
    finished_ms: int | None = None
    returncode: int | None = None
    state: str = State.RUNNING

    @property
    def runtime_seconds(self) -> float:
        end = self.finished_ms if self.finished_ms is not None else int(time.time() * 1000)
        return (end - self.started_ms) / 1000.0

    @property
    def overdue(self) -> bool:
        return self.state == State.RUNNING and self.runtime_seconds > self.limit_seconds

    def describe(self) -> str:
        minutes = self.runtime_seconds / 60.0
        note = "  (ueberfaellig)" if self.overdue else ""
        code = "" if self.returncode is None else f", Code {self.returncode}"
        return f"{self.job_id}  {self.kind:20s} {self.state:14s} {minutes:6.1f} min{code}{note}"


class Registry:
    """Jobs on disk, with the concurrency and duplicate rules enforced here.

    Not thread-safe and deliberately not made so: the adapter runs one asyncio
    loop and the whole design is one job at a time, so a lock would guard
    against a concurrency this module exists to prevent.
    """

    def __init__(self, path: Path, *, log_dir: Path) -> None:
        self._path = path
        self._log_dir = log_dir
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Job]:
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A truncated registry is recoverable -- the jobs it described are
            # gone either way, and refusing to start new ones because an old
            # file is corrupt is the worse failure.
            return {}
        return {key: Job(**value) for key, value in raw.items()}

    def _write(self, jobs: dict[str, Job]) -> None:
        payload = {key: asdict(job) for key, job in jobs.items()}
        # Written beside the target and renamed: a crash mid-write then leaves
        # the previous registry intact rather than half of a new one.
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self._path)

    @staticmethod
    def _identify(kind: str, command: list[str]) -> str:
        digest = hashlib.sha256("\x00".join(command).encode("utf-8")).hexdigest()
        return f"{kind}-{digest[:ID_LENGTH]}"

    @staticmethod
    def _alive(pid: int) -> bool:
        """Whether the process is still running, without reaping it.

        `os.kill(pid, 0)` is the portable existence check and works on Windows
        under Python's emulation. A `PermissionError` means the pid exists and
        belongs to someone else, which still answers the question asked.
        """
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def refresh(self) -> dict[str, Job]:
        """Reconcile recorded state against the processes actually running.

        Needed because this registry does not own the child after it starts:
        the adapter may have restarted, in which case nothing called `wait`
        and a finished job would otherwise sit at `RUNNING` forever.

        A job whose process is gone is marked finished. Its return code is not
        recoverable after a restart -- nobody reaped it -- so it is recorded as
        unknown rather than guessed, and the log is where the outcome is.
        """
        jobs = self._read()
        changed = False
        for key, job in list(jobs.items()):
            if job.state != State.RUNNING or self._alive(job.pid):
                continue
            jobs[key] = Job(
                **{
                    **asdict(job),
                    "state": State.DONE,
                    "finished_ms": int(time.time() * 1000),
                }
            )
            changed = True
        if changed:
            self._write(jobs)
        return jobs

    def running(self) -> list[Job]:
        return [job for job in self.refresh().values() if job.state == State.RUNNING]

    def all(self) -> list[Job]:
        return sorted(self.refresh().values(), key=lambda j: j.started_ms, reverse=True)

    def get(self, job_id: str) -> Job | None:
        return self.refresh().get(job_id)

    def start(
        self,
        *,
        kind: str,
        command: list[str],
        cwd: Path,
        label: str = "",
        limit_seconds: int = DEFAULT_LIMIT_SECONDS,
        env: dict[str, str] | None = None,
    ) -> tuple[Job, str]:
        """Launch a job, or return the equivalent one already running.

        Returns the job and a note saying which of the two happened, because a
        caller that cannot distinguish "started" from "already running" will
        report a duplicate as new work.
        """
        jobs = self.refresh()
        job_id = self._identify(kind, command)

        existing = jobs.get(job_id)
        if existing is not None and existing.state == State.RUNNING:
            return existing, "Dieser Lauf laeuft schon; keine zweite Instanz gestartet."

        active = [job for job in jobs.values() if job.state == State.RUNNING]
        if active:
            names = ", ".join(job.job_id for job in active)
            raise RuntimeError(
                f"Es laeuft schon ein Job ({names}). Der Forschungsauftrag erlaubt einen "
                f"gleichzeitig. Mit stop_job abbrechen oder auf das Ende warten."
            )

        log_path = self._log_dir / f"{job_id}.log"
        # Opened for the child and never read from this process: a pipe that
        # nobody drains is how a job manager deadlocks on long jobs.
        handle = log_path.open("w", encoding="utf-8", errors="replace")
        try:
            merged = {**os.environ, **(env or {})}
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=merged,
            )
        finally:
            # The child holds its own duplicate of the descriptor.
            handle.close()

        job = Job(
            job_id=job_id,
            kind=kind,
            command=list(command),
            log=str(log_path),
            pid=process.pid,
            started_ms=int(time.time() * 1000),
            limit_seconds=limit_seconds,
            label=label,
        )
        jobs[job_id] = job
        self._write(jobs)
        return job, "Gestartet."

    def stop(self, job_id: str) -> str:
        jobs = self.refresh()
        job = jobs.get(job_id)
        if job is None:
            return f"Keine Job-Kennung {job_id} im Register."
        if job.state != State.RUNNING:
            return f"{job_id} laeuft nicht mehr ({job.state})."

        try:
            os.kill(job.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            return f"{job_id} liess sich nicht beenden: {exc}"

        deadline = time.time() + STOP_GRACE
        while time.time() < deadline and self._alive(job.pid):
            time.sleep(0.2)

        gone = not self._alive(job.pid)
        jobs[job_id] = Job(
            **{
                **asdict(job),
                "state": State.STOPPED if gone else State.RUNNING,
                "finished_ms": int(time.time() * 1000) if gone else None,
            }
        )
        self._write(jobs)
        return f"{job_id} abgebrochen." if gone else f"{job_id} reagiert nicht auf SIGTERM."

    def tail(self, job_id: str, *, lines: int = 60) -> str:
        """The end of a job's log, which is where its outcome is.

        Read with a byte budget rather than by splitting the whole file: a
        FreqAI run writes tens of megabytes and reading all of it to show
        sixty lines is how a status call becomes slow.
        """
        job = self.get(job_id)
        if job is None:
            return f"Keine Job-Kennung {job_id} im Register."
        path = Path(job.log)
        if not path.is_file():
            return "(noch keine Ausgabe)"

        budget = max(4096, lines * 400)
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - budget))
            chunk = handle.read()
        text = chunk.decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])

    def summary(self) -> dict[str, Any]:
        jobs = self.all()
        return {
            "jobs_total": len(jobs),
            "laufend": sum(1 for j in jobs if j.state == State.RUNNING),
            "ueberfaellig": sum(1 for j in jobs if j.overdue),
            "zuletzt": [j.describe() for j in jobs[:10]],
        }
