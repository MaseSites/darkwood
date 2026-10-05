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

import functools
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
    return (
        f"{engine.simulation.initial_equity}|{engine.setups.enabled}|"
        f"{risk.limits.max_cost_fraction_of_risk}|{engine.timeframes.signal.value}"
        f"|{LEDGER_SCHEMA}{bars}{shade}"
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
