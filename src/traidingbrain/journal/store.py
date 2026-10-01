"""Where paper trades are kept.

SQLite, one row per trade, appended forever. The journal is the one thing in
this project that gets more valuable the longer it runs, so it is deliberately
the dullest storage available: a single file, no migrations to forget, readable
by anything.

**Replay and live trades share a table and never share an average.** The column
is indexed because every report filters on it. Mixing a replay of 2023 with a
week of forward trades produces a number that describes neither, and the only
reliable way to stop that is to make the split cheap and obvious.

**Writing the same trade twice is a no-op.** The id is the proposal id, which
is the symbol and the decision bar -- so re-running a replay over a period
already recorded corrects it rather than doubling it. A journal that grew every
time somebody re-ran a script would quietly inflate every count in it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from traidingbrain.journal.record import JournalEntry, Source

_DDL = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id     TEXT PRIMARY KEY,
    source       TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    strategy     TEXT    NOT NULL,
    opened_ts    INTEGER NOT NULL,
    closed_ts    INTEGER NOT NULL,
    r_multiple   REAL    NOT NULL,
    net_pnl      REAL    NOT NULL,
    rating       INTEGER NOT NULL,
    payload      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS trades_by_source ON trades (source, opened_ts);
CREATE INDEX IF NOT EXISTS trades_by_rating ON trades (rating);
"""


class JournalStore:
    """Every paper trade this system has made."""

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

    def record(self, entries: Iterable[JournalEntry]) -> int:
        """Store trades, replacing any already held under the same id."""
        rows = [
            (
                entry.trade_id,
                str(entry.source),
                entry.symbol,
                entry.strategy,
                entry.opened_ts,
                entry.closed_ts,
                entry.r_multiple,
                entry.net_pnl,
                entry.reason.rating,
                entry.to_json(),
            )
            for entry in entries
        ]
        if not rows:
            return 0
        with closing(self._connect()) as conn:
            conn.executemany(
                "INSERT INTO trades (trade_id, source, symbol, strategy, opened_ts, "
                "closed_ts, r_multiple, net_pnl, rating, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(trade_id) DO UPDATE SET "
                "source=excluded.source, r_multiple=excluded.r_multiple, "
                "net_pnl=excluded.net_pnl, rating=excluded.rating, "
                "payload=excluded.payload",
                rows,
            )
            conn.commit()
        return len(rows)

    def all(self, *, source: Source | None = None, symbol: str | None = None) -> list[JournalEntry]:
        """Every trade, oldest first, optionally narrowed."""
        where: list[str] = []
        args: list[str] = []
        if source is not None:
            where.append("source = ?")
            args.append(str(source))
        if symbol is not None:
            where.append("symbol = ?")
            args.append(symbol)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT payload FROM trades{clause} ORDER BY opened_ts", args
            ).fetchall()
        return [JournalEntry.from_json(row[0]) for row in rows]

    def count(self, *, source: Source | None = None) -> int:
        clause = " WHERE source = ?" if source is not None else ""
        args = [str(source)] if source is not None else []
        with closing(self._connect()) as conn:
            row = conn.execute(f"SELECT count(*) FROM trades{clause}", args).fetchone()
        return int(row[0])
