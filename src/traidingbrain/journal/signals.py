"""Every signal the setups produced, including the ones that never traded.

The masterplan asks for this twice. Section 6: skipped signals are recorded
too, and their hypothetical outcome is simulated in a *separate* shadow journal
which must never produce real paper-account movements. Section 6 again, in the
pre-decision list: the result of the risk check and the action taken -- trade,
skip, or not enough data.

**Why it is the thing that was missing.** Six levers were measured and rejected
on 04.10.2026, and they fall into two families: re-pricing the same signals (a
tighter cost ceiling, a looser one, wider stops, a cap on the planned
reward-to-risk) and re-selecting among the same signals with features the
system already had (the liquidity-lean filter, the model as judge). Neither
family can change a sign that is already zero -- the gross expectancy of the
taken entries is -0.0102 R with an interval straddling zero, so the whole net
loss is the toll, and choosing differently among entries that average nothing
is bounded above by nothing.

What was never tried is changing the **population**. And the reason is that the
rejected signals did not exist anywhere: every refusal was a single increment
of `refused_by_risk`, so after a thousand of them there was a count and nothing
to look at. That makes the five rules in `sim/plan.py` untested hypotheses.
`scripts/study_cost_floor.py` moved the threshold of one of them across four
markets, which is a different question from whether the rule should exist, and
only this ledger can ask the second.

**Three actions, not two.** A signal can be refused by a rule, or never
examined at all because the account was already busy -- `sim/engine.py:201`
only asks the strategy while the broker is flat. Those are different
exclusions: the first is a judgement the system made, the second is an accident
of timing, and the second is exactly the confound that made every journal-based
filter result unreadable. Keeping them apart is the point.

**Append-only, and that is a correction.** `journal/store.py` upserts: re-running
a replay over a recorded period silently rewrites the stored reason and
post-mortem in place, which section 6 forbids outright ("Ändere frühere
Begründungen und ursprüngliche Entscheidungen nicht nachträglich"). Here the key
is the signal *and the configuration that judged it*, so a re-run under the same
settings is a no-op and a re-run under changed settings adds rows beside the old
ones rather than over them. Two eras can then be told apart, which
`journal/record.py:98-112` had to be added by hand to achieve once already.

**Nothing here is an account movement.** Its own file, its own table, no equity,
no fills. A shadow case cannot be mistaken for a trade because there is nowhere
in this schema to put one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from traidingbrain.domain.enums import Rule, Side
from traidingbrain.journal.record import Source
from traidingbrain.journal.version import code_version

_DDL = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id        TEXT    NOT NULL,
    run_signature    TEXT    NOT NULL,
    decided_ts       INTEGER NOT NULL,
    symbol           TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    action           TEXT    NOT NULL,
    refused_by       TEXT,
    detail           TEXT    NOT NULL,
    setup_key        TEXT    NOT NULL,
    setup_timeframe  TEXT    NOT NULL,
    signal_timeframe TEXT    NOT NULL,
    side             TEXT    NOT NULL,
    entry            REAL    NOT NULL,
    stop             REAL    NOT NULL,
    target           REAL    NOT NULL,
    reward_risk      REAL    NOT NULL,
    cost_fraction    REAL    NOT NULL,
    risk_amount      REAL    NOT NULL,
    qty              REAL    NOT NULL,
    leverage         REAL    NOT NULL,
    code_version     TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (signal_id, run_signature)
);
CREATE INDEX IF NOT EXISTS signals_by_symbol ON signals (symbol, decided_ts);
CREATE INDEX IF NOT EXISTS signals_by_action ON signals (action, refused_by);
"""

#: Columns added to `signals` after databases existed in the wild.
#:
#: Every entry needs a DEFAULT. Without one, `ALTER TABLE ADD COLUMN` on a
#: NOT NULL column is refused outright, and a writer still running the old
#: code would break on its next insert.
_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (("code_version", "TEXT NOT NULL DEFAULT ''"),)


class Action(StrEnum):
    """What became of a signal before any market moved."""

    TAKEN = "genommen"
    """An order was placed. This signal also appears in the trade journal."""

    REFUSED = "abgelehnt"
    """A risk rule said no, and `refused_by` says which one.

    The population this ledger exists for. Each of these is a trade the system
    decided against on grounds that have never been tested against outcomes."""

    OCCUPIED = "besetzt"
    """Never examined: the account already had a position or a resting order.

    Not a judgement at all -- an accident of when the signal arrived. Separated
    from `REFUSED` because mixing them is the confound that made every
    journal-based filter measurement on 04.10.2026 unreadable: removing a trade
    frees its slot, something else fills it, and the journal cannot say what the
    account would have done."""


@dataclass(frozen=True)
class SignalRecord:
    """One signal, as it stood before the market answered.

    No outcome field. The outcome belongs to `learn/labels.py`, which replays
    the barriers against minute data and is deliberately scale-free, so it can
    be recomputed for every row here at any time without this table having to
    commit to a horizon.
    """

    signal_id: str
    run_signature: str
    decided_ts: int
    symbol: str
    source: Source
    action: Action
    refused_by: Rule | None
    detail: str
    setup_key: str
    setup_timeframe: str
    signal_timeframe: str
    side: Side
    entry: float
    stop: float
    target: float
    reward_risk: float
    cost_fraction: float
    risk_amount: float
    qty: float
    leverage: float

    #: Which code wrote this row. Empty on rows written before the column
    #: existed, which `version.spread()` reports as unknown rather than
    #: folding in with a real commit.
    #:
    #: Not in `as_row()`: the store stamps it, so no call site can forget
    #: to. A record is a description of a decision; which code computed it
    #: is something only the moment of writing knows.
    code_version: str = ""

    @property
    def stop_distance_pct(self) -> float:
        return 100.0 * abs(self.entry - self.stop) / self.entry if self.entry else 0.0

    @property
    def tradeable(self) -> bool:
        return self.action is Action.TAKEN

    def as_row(self) -> tuple[object, ...]:
        return (
            self.signal_id,
            self.run_signature,
            self.decided_ts,
            self.symbol,
            self.source.value,
            self.action.value,
            self.refused_by.value if self.refused_by is not None else None,
            self.detail,
            self.setup_key,
            self.setup_timeframe,
            self.signal_timeframe,
            self.side.value,
            self.entry,
            self.stop,
            self.target,
            self.reward_risk,
            self.cost_fraction,
            self.risk_amount,
            self.qty,
            self.leverage,
        )

    @classmethod
    def from_row(cls, row: Sequence[object]) -> SignalRecord:
        return cls(
            signal_id=str(row[0]),
            run_signature=str(row[1]),
            decided_ts=int(row[2]),  # type: ignore[call-overload]
            symbol=str(row[3]),
            source=Source(str(row[4])),
            action=Action(str(row[5])),
            refused_by=Rule(str(row[6])) if row[6] is not None else None,
            detail=str(row[7]),
            setup_key=str(row[8]),
            setup_timeframe=str(row[9]),
            signal_timeframe=str(row[10]),
            side=Side(str(row[11])),
            entry=float(row[12]),  # type: ignore[arg-type]
            stop=float(row[13]),  # type: ignore[arg-type]
            target=float(row[14]),  # type: ignore[arg-type]
            reward_risk=float(row[15]),  # type: ignore[arg-type]
            cost_fraction=float(row[16]),  # type: ignore[arg-type]
            risk_amount=float(row[17]),  # type: ignore[arg-type]
            qty=float(row[18]),  # type: ignore[arg-type]
            leverage=float(row[19]),  # type: ignore[arg-type]
            # Always present: the only caller selects `_COLUMNS`, and the column
            # is NOT NULL DEFAULT '' on migrated databases as well as new ones.
            code_version=str(row[20]),
        )


_COLUMNS = (
    "signal_id, run_signature, decided_ts, symbol, source, action, refused_by, detail, "
    "setup_key, setup_timeframe, signal_timeframe, side, entry, stop, target, reward_risk, "
    "cost_fraction, risk_amount, qty, leverage, code_version"
)


class SignalStore:
    """Where signals are kept, taken or not."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)
            self._add_missing_columns(conn)
            conn.commit()

    @staticmethod
    def _add_missing_columns(conn: sqlite3.Connection) -> None:
        """SQLite has no `ADD COLUMN IF NOT EXISTS`, and the DDL above only
        creates the table when it is absent -- so a column added to it never
        reaches a database that already exists.

        The column is appended with a default rather than backfilled. Rows
        written before it existed were produced by code nobody recorded, and
        `version.spread()` reports that as unknown instead of guessing a commit.
        """
        have = {row[1] for row in conn.execute("PRAGMA table_info(signals)")}
        for column, kind in _ADDED_COLUMNS:
            if column not in have:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {column} {kind}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def record(self, records: Iterable[SignalRecord]) -> int:
        """Append signals, ignoring ones already written for this configuration.

        `INSERT OR IGNORE`, never an upsert. A replay re-run under unchanged
        settings must be a no-op rather than a rewrite -- section 6 forbids
        amending an earlier decision in place, and the trade journal next door
        does exactly that, which is a defect this table is not going to copy.

        Returns how many rows were actually new, so a caller can tell a fresh
        run from a repeat instead of assuming.
        """
        # Stamped here, not at the call site, so it cannot be forgotten by one.
        stamp = code_version()
        rows = [(*record.as_row(), stamp) for record in records]
        if not rows:
            return 0
        placeholders = ", ".join(["?"] * len(rows[0]))
        with closing(self._connect()) as conn:
            before = conn.total_changes
            conn.executemany(
                f"INSERT OR IGNORE INTO signals ({_COLUMNS}) VALUES ({placeholders})", rows
            )
            conn.commit()
            return conn.total_changes - before

    def all(
        self,
        *,
        symbol: str | None = None,
        source: Source | None = None,
        action: Action | None = None,
        run_signature: str | None = None,
    ) -> list[SignalRecord]:
        """Signals in decision order, which is the order every interval needs."""
        where: list[str] = []
        args: list[object] = []
        for column, value in (
            ("symbol", symbol),
            ("source", source.value if source is not None else None),
            ("action", action.value if action is not None else None),
            ("run_signature", run_signature),
        ):
            if value is not None:
                where.append(f"{column} = ?")
                args.append(value)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                f"SELECT {_COLUMNS} FROM signals{clause} ORDER BY decided_ts, signal_id", args
            )
            return [SignalRecord.from_row(row) for row in cursor]

    def signatures(self) -> list[tuple[str, int]]:
        """Every stored run signature with its signal count, largest first.

        Needed because the signature includes the risk configuration, so
        changing a single cap orphans every stored signal from every study.
        That is the mechanism working -- signals decided under one rule set
        must not be averaged with another's -- but on 05.10.2026 lowering
        `max_cost_fraction_of_risk` from 0.15 to 0.08 made four studies print
        "keine genommenen Signale" and one advise re-running a backfill that
        had already run. The data was there; nothing could say so.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT run_signature, COUNT(*) FROM signals "
                "GROUP BY run_signature ORDER BY COUNT(*) DESC"
            ).fetchall()
        return [(str(row[0]), int(row[1])) for row in rows]

    def resolve(self, wanted: str, *, fallback: bool = False) -> tuple[str, str]:
        """The signature to read, and a line saying which and why.

        Returns `wanted` untouched when signals exist under it. Otherwise, with
        `fallback`, the largest stored signature and a note naming the
        substitution -- never silently, because a study that quietly measures a
        different run than it claims is worse than one that finds nothing.
        """
        stored = self.signatures()
        counts = dict(stored)
        if counts.get(wanted):
            return wanted, f"{counts[wanted]:,} Signale unter der aktuellen Signatur."

        if not stored:
            return wanted, "Das Signalprotokoll ist leer."

        listing = "\n".join(f"    {sig[:40]}...  {n:,} Signale" for sig, n in stored[:4])
        if not fallback:
            return wanted, (
                "Keine Signale unter der AKTUELLEN Signatur -- die Konfiguration hat\n"
                "  sich geaendert, die Daten sind aber da. Gespeichert:\n"
                f"{listing}\n"
                "  Mit --any die groesste davon lesen, oder die Konfiguration\n"
                "  zurueckstellen. Neu erzeugen ist NICHT noetig."
            )
        chosen, count = stored[0]
        return chosen, (
            f"ERSATZ-SIGNATUR: {count:,} Signale aus einem Lauf mit ANDERER\n"
            f"  Konfiguration ({chosen[:40]}...). Jede Zahl daraus beschreibt jenen\n"
            "  Lauf, nicht den heutigen."
        )

    def count(self, **filters: object) -> int:
        return len(self.all(**filters))  # type: ignore[arg-type]

    def by_rule(self, **filters: object) -> dict[str, int]:
        """How many signals each rule refused, plus the taken and occupied counts.

        The first table worth printing from this ledger: it says which rule is
        responsible for most of the population the system never traded, and
        therefore which hypothesis is worth testing first.
        """
        tally: dict[str, int] = {}
        for record in self.all(**filters):  # type: ignore[arg-type]
            key = record.refused_by.value if record.refused_by is not None else record.action.value
            tally[key] = tally.get(key, 0) + 1
        return dict(sorted(tally.items(), key=lambda kv: -kv[1]))
