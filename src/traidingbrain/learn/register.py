"""The ratchet: a champion, every challenger ever tried, and a rationed holdout.

Severin asked how to trade so that it only gets better from here. No strategy
can promise that. A *process* can, and this is the process.

**Why it is needed, from this project's own record.** Eight hypotheses were
measured on 05.10.2026 and all eight failed: the fee schedule, a wider stop, a
target cap, a learned signal filter, hit-rate selection, loosening either
refusal rule, more concurrent slots, and a forward score over 5-10 hours in two
separate feature families. Had the best-looking of the eight been shipped, noise
would have been shipped -- with eight attempts the best of eight looks good by
construction. The same effect was visible inside a single report: one decile row
in ten excluded zero, and it *moved* between two adjacent runs.

Three parts, and each fails without the others.

**The champion.** One frozen arm that a challenger has to beat. Without it every
measurement is against a moving target and "better" has no referent.

**The register.** Append-only, one row per challenger ever tried, including the
failures. It exists to make the number of attempts *countable*, because that
count is what a threshold has to be corrected for. A register that only holds
winners is worse than none: it reports a selected sample as if it were the
whole.

**The holdout, and the fact that it is consumable.** `walk_forward` has taken
`holdout_days` since it was written and returns `Plan.holdout`, and every study
in this project passed zero -- the yardstick was built and never used. The
subtle part is that a holdout is destroyed by being looked at. Consult it twenty
times and pick the best, and it has become a validation fold with extra steps.
So every consultation is recorded here, and the significance a challenger must
clear is corrected by how many consultations have happened. That is the one
mechanism that makes "only better" an arithmetic statement rather than a hope.

**What this module does not do.** It does not run anything, fit anything or
decide what to try next. It records, and it answers one question: given this
challenger's result and everything already tried, is the evidence strong enough
to replace the champion? Keeping that judgement in one tested place is the
point; spread across study scripts it would be re-derived slightly differently
each time, which is how eight attempts become one accidental success story.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from traidingbrain.journal.version import code_version

_DDL = """
CREATE TABLE IF NOT EXISTS experiments (
    arm             TEXT    NOT NULL,
    recorded_ts     INTEGER NOT NULL,
    run_signature   TEXT    NOT NULL,
    code_version    TEXT    NOT NULL,
    stage           TEXT    NOT NULL,
    n               INTEGER NOT NULL,
    mean_r          REAL    NOT NULL,
    low             REAL    NOT NULL,
    high            REAL    NOT NULL,
    unit            TEXT    NOT NULL DEFAULT 'R',
    champion_mean_r REAL    NOT NULL,
    verdict         TEXT    NOT NULL,
    note            TEXT    NOT NULL,
    PRIMARY KEY (arm, stage, run_signature, code_version)
);
CREATE INDEX IF NOT EXISTS experiments_by_stage ON experiments (stage, recorded_ts);

CREATE TABLE IF NOT EXISTS champion (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    arm             TEXT    NOT NULL,
    crowned_ts      INTEGER NOT NULL,
    run_signature   TEXT    NOT NULL,
    code_version    TEXT    NOT NULL,
    mean_r          REAL    NOT NULL,
    n               INTEGER NOT NULL,
    note            TEXT    NOT NULL
);
"""


class Stage(StrEnum):
    """Which data a result came from, because they are not interchangeable."""

    EXPLORE = "explore"
    """Train and validation folds. Free to consult as often as wanted, and
    worth nothing as evidence -- this is where ideas are generated."""

    TEST = "test"
    """The pooled walk-forward test folds. Honest per fold, but these have been
    read many times across many arms, so a result here is a candidate."""

    HOLDOUT = "holdout"
    """The reserved stretch no exploration touches. Consumable: every read
    spends some of its value, and `consultations` counts the spending."""


class Verdict(StrEnum):
    RECORDED = "aufgenommen"
    """Measured and filed. Says nothing about whether it won."""

    BEATS_CHAMPION = "schlaegt_champion"
    """Cleared the corrected threshold on the holdout. The only verdict that
    may change what ships."""

    INSIDE_NOISE = "im_rauschen"
    """Did not separate from the champion once the number of attempts was
    accounted for."""

    WORSE = "schlechter"


#: Confidence the whole family of challengers must share, not each one.
#:
#: With one test at 95% the chance of a false winner is one in twenty. With
#: twenty tests it is about two in three. Dividing the error budget by the
#: number of attempts -- Bonferroni -- is the crude correction, and crude is
#: the right register here: it is conservative, it needs no assumption about
#: how the attempts relate, and it cannot be argued into looking better.
FAMILY_CONFIDENCE = 0.95

#: Fewest realised trades before a holdout verdict is allowed at all.
#:
#: Not a statistical threshold. It is the point below which an interval says
#: more about the handful of trades in it than about the arm.
MIN_HOLDOUT_TRADES = 30


@dataclass(frozen=True)
class Result:
    """One arm's measured outcome on one stage."""

    arm: str
    stage: Stage
    n: int
    mean_r: float
    low: float
    high: float
    note: str = ""

    #: What the three numbers above are measured in.
    #:
    #: "R" by default, because that is the scale a trade is judged on. Not
    #: every attempt produces one: the forward-score arms were measured as a
    #: rank correlation, and writing 0.004 into a column of R multiples
    #: would be a number nobody could read back correctly. Only R-scale
    #: results on the holdout can replace a champion, so a foreign unit is
    #: recorded as an attempt and never as a verdict.
    unit: str = "R"


@dataclass(frozen=True)
class Champion:
    arm: str
    crowned_ts: int
    run_signature: str
    code_version: str
    mean_r: float
    n: int
    note: str

    def describe(self) -> str:
        when = datetime.fromtimestamp(self.crowned_ts / 1000, tz=UTC).strftime("%d.%m.%Y")
        return (
            f"Champion: {self.arm} (seit {when}, Code {self.code_version}) "
            f"{self.mean_r:+.4f} R ueber {self.n} Trades"
        )


@dataclass(frozen=True)
class Judgement:
    """Whether a challenger may replace the champion, and why or why not."""

    verdict: Verdict
    attempts: int
    required_confidence: float
    margin: float
    reason: str

    @property
    def replaces(self) -> bool:
        return self.verdict is Verdict.BEATS_CHAMPION


class Register:
    """The append-only record, and the one place a replacement is decided."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- recording ---------------------------------------------------------- #

    def record(self, result: Result, *, run_signature: str, now_ms: int) -> Verdict:
        """File a result. Never an update: a measurement already taken stands.

        `INSERT OR IGNORE`, so re-running the same arm under the same settings
        and the same code is a no-op rather than a second attempt. Otherwise
        the attempt count -- the thing the correction depends on -- would grow
        every time somebody pressed enter.
        """
        champion = self.champion()
        base = champion.mean_r if champion is not None else 0.0
        verdict = Verdict.RECORDED
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO experiments (arm, recorded_ts, run_signature, "
                "code_version, stage, n, mean_r, low, high, unit, champion_mean_r, "
                "verdict, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.arm,
                    now_ms,
                    run_signature,
                    code_version(),
                    result.stage.value,
                    result.n,
                    result.mean_r,
                    result.low,
                    result.high,
                    result.unit,
                    base,
                    verdict.value,
                    result.note,
                ),
            )
            conn.commit()
        return verdict

    def attempts(self, *, stage: Stage | None = None) -> int:
        """How many distinct arms have been tried.

        Counted by arm rather than by row, because measuring one arm at two
        horizons is one idea examined twice, not two ideas. Over-counting would
        make the correction punitive for no reason; under-counting would make
        it decorative.
        """
        query = "SELECT COUNT(DISTINCT arm) FROM experiments"
        params: tuple[str, ...] = ()
        if stage is not None:
            query += " WHERE stage = ?"
            params = (stage.value,)
        with closing(self._connect()) as conn:
            return int(conn.execute(query, params).fetchone()[0])

    def _has_consulted(self, arm: str) -> bool:
        """Has this arm already been taken to the holdout?"""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM experiments WHERE arm = ? AND stage = ? LIMIT 1",
                (arm, Stage.HOLDOUT.value),
            ).fetchone()
        return row is not None

    def consultations(self) -> int:
        """How many arms have been taken to the holdout.

        The number the correction uses, and the reason the holdout is rationed
        rather than free. Each consultation spends some of its value.
        """
        return self.attempts(stage=Stage.HOLDOUT)

    def all(self, *, stage: Stage | None = None) -> list[tuple[str, ...]]:
        query = (
            "SELECT arm, stage, n, mean_r, low, high, unit, champion_mean_r, verdict, "
            "code_version, note FROM experiments"
        )
        params: tuple[str, ...] = ()
        if stage is not None:
            query += " WHERE stage = ?"
            params = (stage.value,)
        query += " ORDER BY recorded_ts"
        with closing(self._connect()) as conn:
            return [tuple(str(value) for value in row) for row in conn.execute(query, params)]

    # -- the champion ------------------------------------------------------- #

    def champion(self) -> Champion | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT arm, crowned_ts, run_signature, code_version, mean_r, n, note "
                "FROM champion WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        return Champion(
            arm=str(row[0]),
            crowned_ts=int(row[1]),
            run_signature=str(row[2]),
            code_version=str(row[3]),
            mean_r=float(row[4]),
            n=int(row[5]),
            note=str(row[6]),
        )

    def crown(self, result: Result, *, run_signature: str, now_ms: int, note: str = "") -> Champion:
        """Install a champion. The only write in this module that replaces.

        Called for the first champion, and afterwards only when `judge` returned
        `BEATS_CHAMPION`. It does not check that itself on purpose: a function
        that both decides and acts invites a caller to pass the decision it
        wanted.
        """
        champion = Champion(
            arm=result.arm,
            crowned_ts=now_ms,
            run_signature=run_signature,
            code_version=code_version(),
            mean_r=result.mean_r,
            n=result.n,
            note=note or result.note,
        )
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO champion (id, arm, crowned_ts, run_signature, code_version, "
                "mean_r, n, note) VALUES (1, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET arm=excluded.arm, crowned_ts=excluded.crowned_ts, "
                "run_signature=excluded.run_signature, code_version=excluded.code_version, "
                "mean_r=excluded.mean_r, n=excluded.n, note=excluded.note",
                (
                    champion.arm,
                    champion.crowned_ts,
                    champion.run_signature,
                    champion.code_version,
                    champion.mean_r,
                    champion.n,
                    champion.note,
                ),
            )
            conn.commit()
        return champion

    # -- the decision ------------------------------------------------------- #

    def judge(self, result: Result) -> Judgement:
        """May this arm replace the champion?

        Four conditions, and failing any one is a refusal:

        1. The result is from the holdout. A test-fold number is a candidate,
           not a verdict -- those folds have been read across every arm ever
           tried here.
        2. There are enough realised trades to interpret an interval.
        3. The arm's interval excludes the champion's mean. Not "the mean is
           higher": a point estimate above another point estimate is what every
           one of the eight rejected hypotheses looked like at first.
        4. The interval was computed at a confidence corrected for how many
           arms have consulted the holdout. The caller is told what confidence
           to use *before* measuring, by `required_confidence`, because
           choosing it afterwards is choosing it to pass.
        """
        # This arm counts too, unless it has consulted the holdout before.
        # Judging an arm *is* a consultation, so leaving it out would let the
        # last attempt in a family escape the correction the others paid --
        # and the last attempt is exactly the one somebody is hoping about.
        # Re-judging an already recorded arm adds nothing, so repeating a
        # measurement cannot inflate the bar.
        attempts = max(1, self.consultations() + (0 if self._has_consulted(result.arm) else 1))
        required = 1.0 - (1.0 - FAMILY_CONFIDENCE) / attempts
        champion = self.champion()
        base = champion.mean_r if champion is not None else 0.0
        margin = result.mean_r - base

        if result.unit != "R":
            return Judgement(
                verdict=Verdict.RECORDED,
                attempts=attempts,
                required_confidence=required,
                margin=margin,
                reason=(
                    f"In {result.unit} gemessen, nicht in R. Ein Arm kann den Champion nur "
                    "auf der Skala schlagen, auf der ein Trade beurteilt wird; alles andere "
                    "ist ein Versuch und zaehlt als solcher."
                ),
            )
        if result.stage is not Stage.HOLDOUT:
            return Judgement(
                verdict=Verdict.RECORDED,
                attempts=attempts,
                required_confidence=required,
                margin=margin,
                reason=(
                    f"{result.stage.value} ist kein Urteil. Die Testfenster sind ueber "
                    "jeden bisher versuchten Arm gelesen worden; nur das zurueckbehaltene "
                    "Fenster kann entscheiden."
                ),
            )
        if result.n < MIN_HOLDOUT_TRADES:
            return Judgement(
                verdict=Verdict.INSIDE_NOISE,
                attempts=attempts,
                required_confidence=required,
                margin=margin,
                reason=(
                    f"{result.n} Trades im Prueffenster, {MIN_HOLDOUT_TRADES} gebraucht. "
                    "Darunter sagt das Intervall mehr ueber die paar Trades als ueber den Arm."
                ),
            )
        if margin <= 0:
            return Judgement(
                verdict=Verdict.WORSE,
                attempts=attempts,
                required_confidence=required,
                margin=margin,
                reason=f"{margin:+.4f} R gegen den Champion. Kein Grund zu wechseln.",
            )
        if result.low <= base:
            return Judgement(
                verdict=Verdict.INSIDE_NOISE,
                attempts=attempts,
                required_confidence=required,
                margin=margin,
                reason=(
                    f"Das Intervall [{result.low:+.4f}, {result.high:+.4f}] enthaelt den "
                    f"Champion ({base:+.4f}). Ein hoeherer Punktwert allein ist genau das, "
                    f"wie alle acht verworfenen Hypothesen zuerst aussahen. "
                    f"Bei {attempts} Konsultationen des Prueffensters muesste das Intervall "
                    f"auf {100 * required:.2f}% gerechnet sein und den Champion ausschliessen."
                ),
            )
        return Judgement(
            verdict=Verdict.BEATS_CHAMPION,
            attempts=attempts,
            required_confidence=required,
            margin=margin,
            reason=(
                f"{margin:+.4f} R besser, Intervall [{result.low:+.4f}, {result.high:+.4f}] "
                f"schliesst den Champion ({base:+.4f}) aus, bei {attempts} Konsultationen "
                f"und {100 * required:.2f}% gefordertem Niveau."
            ),
        )
