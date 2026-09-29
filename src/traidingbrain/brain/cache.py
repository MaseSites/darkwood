"""Content-addressed store of model decisions.

This is not primarily a cost optimisation, though it is a large one. Sampling
parameters were removed from the current models -- `temperature` and `top_p` return
a 400 -- so identical input does not guarantee identical output, and there is no
setting that makes it so. That leaves this cache as the only thing that makes a
backtest reproducible.

The consequence is worth stating plainly: a backtest result is a *sample*. Run it
twice with an empty cache and the numbers move. The way to know whether a
difference between two strategies is real is to measure that movement, not to
assume it away. What the cache guarantees is that re-running the same backtest
reproduces the same run -- so a change in the numbers means a change in the code.

The key binds everything that could change the answer: the market state, the
prompt text, the model, and the schema. Get any of those wrong and the cache
serves a stale answer to a question nobody asked.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from traidingbrain.domain.verdict import BrainDecision

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS decisions (
    cache_key     TEXT PRIMARY KEY,
    snapshot_hash TEXT NOT NULL,
    model_id      TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    payload       TEXT NOT NULL,
    created_ts    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_by_snapshot ON decisions (snapshot_hash);

-- Raw responses are kept separately and never read by the engine. Models are
-- deprecated and prompts are rewritten; without the original text and request id,
-- a backtest run today cannot be explained in a year.
CREATE TABLE IF NOT EXISTS responses (
    cache_key   TEXT PRIMARY KEY,
    request_id  TEXT,
    usage       TEXT,
    raw         TEXT,
    created_ts  INTEGER NOT NULL
);
"""


def cache_key(
    snapshot_hash: str, model_id: str, prompt_version: str, schema_version: int = SCHEMA_VERSION
) -> str:
    """Everything that could change the answer, in one string.

    Deliberately readable rather than hashed again: when a cache behaves oddly, the
    first useful question is which of these four changed, and a key you can read
    answers it without a lookup.
    """
    return f"{snapshot_hash}|{model_id}|{prompt_version}|s{schema_version}"


class DecisionCache:
    """SQLite-backed store of decisions, keyed by content."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        # WAL so a reader and the writer can coexist -- a long backtest writing
        # while a report reads is the normal case, not an edge one.
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, key: str) -> BrainDecision | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM decisions WHERE cache_key = ?", (key,)
            ).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        decision = BrainDecision.model_validate_json(row[0])
        return decision.model_copy(update={"from_cache": True})

    def put(self, key: str, decision: BrainDecision, *, created_ts: int = 0) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO decisions "
                "(cache_key, snapshot_hash, model_id, prompt_version, schema_version, "
                "payload, created_ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    decision.snapshot_hash,
                    decision.model_id,
                    decision.prompt_version,
                    SCHEMA_VERSION,
                    decision.model_dump_json(),
                    created_ts,
                ),
            )
            conn.commit()

    def record_response(
        self, key: str, *, request_id: str | None, usage: dict[str, int], raw: str, created_ts: int
    ) -> None:
        """Keep the original answer, for the day the model is gone.

        Never read back by the engine. Its only purpose is to make a run
        explainable after the model that produced it has been deprecated.
        """
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO responses (cache_key, request_id, usage, raw, created_ts)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, request_id, json.dumps(usage, sort_keys=True), raw, created_ts),
            )
            conn.commit()

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return int(conn.execute("SELECT count(*) FROM decisions").fetchone()[0])

    def clear(self) -> None:
        """Wipe it. Used when measuring how much a result moves between runs."""
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM decisions")
            conn.execute("DELETE FROM responses")
            conn.commit()
        self.hits = 0
        self.misses = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


class MemoryCache:
    """In-process cache, for tests and short runs."""

    def __init__(self) -> None:
        self._store: dict[str, BrainDecision] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> BrainDecision | None:
        found = self._store.get(key)
        if found is None:
            self.misses += 1
            return None
        self.hits += 1
        return found.model_copy(update={"from_cache": True})

    def put(self, key: str, decision: BrainDecision, *, created_ts: int = 0) -> None:
        self._store[key] = decision

    def count(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
