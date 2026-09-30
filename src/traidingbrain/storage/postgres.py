"""The Postgres connection, and the migrations that shape it.

Plain numbered SQL files rather than a migration framework. The project's
dependency list is deliberately thin, and a framework would buy autogeneration --
which is the part of migrations worth doing by hand anyway, because a generated
diff of a trading schema is a diff nobody read.

Three properties this is built around:

**Applying twice is a no-op.** Every start-up runs the migrations. A deployment
that has to remember whether it migrated is a deployment that will forget.

**One transaction per file.** A migration either lands or does not. Postgres can
roll back DDL, unlike most databases, and it would be a waste not to use it.

**Postgres is optional.** An empty URL is a supported state, not a failure: the
SQLite stores work standalone and are what a single machine needs. This earns its
place when the collector, the engine and the dashboard stop being one process --
SQLite over a network share is how databases get corrupted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

#: `0001_proposals.sql` -- the number orders them, the name says what it does.
_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PostgresUnavailableError(RuntimeError):
    """No usable database URL, or the server refused the connection.

    Raised rather than silently falling back to SQLite. A deployment that was
    configured for Postgres and quietly used a local file instead would have two
    machines writing to two different databases and agreeing about neither.
    """


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Every migration on disk, in order.

    A file that does not match the naming pattern is an error rather than
    something to skip: a migration nobody runs because it was named wrongly is
    the worst outcome available here, and it would only surface as a missing
    column much later.
    """
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if match is None:
            raise ValueError(
                f"{path.name} does not match NNNN_name.sql, so it would be skipped "
                "silently. Rename it rather than leaving it here."
            )
        found.append(Migration(int(match.group(1)), match.group(2), path))

    versions = [m.version for m in found]
    duplicates = {v for v in versions if versions.count(v) > 1}
    if duplicates:
        raise ValueError(f"two migrations share a version number: {sorted(duplicates)}")
    return found


#: What to say when there is no database URL at all.
_NO_URL = (
    "no database URL. Set TB_POSTGRES_URL in .env, for example\n"
    "  TB_POSTGRES_URL=postgresql://postgres:PASSWORD@127.0.0.1:5432/traidingbrain"
)


def connect(url: str) -> psycopg.Connection[Any]:
    """Open a single connection, or say clearly there is nowhere to connect to.

    For one-off work: migrations, a script, a health check. Anything running per
    request or under concurrency wants `pool_for` -- see the note there for what
    happens when it does not.
    """
    if not url:
        raise PostgresUnavailableError(_NO_URL)
    try:
        return psycopg.connect(url)
    except psycopg.Error as error:
        raise PostgresUnavailableError(f"could not connect: {error}") from error


#: How many connections one process may hold.
#:
#: The server here allows twenty in total, shared by the dashboard, the live
#: loop, any running script and the tests. Four per process leaves room for all
#: of them; raising it would move the exhaustion rather than remove it.
MAX_POOL_SIZE = 4

#: How long a caller waits for a free connection before giving up.
#:
#: Long enough to outlast a slow query, short enough that a leaked connection
#: surfaces as an error somebody investigates rather than a request that hangs.
POOL_TIMEOUT_SECONDS = 10.0

_POOLS: dict[str, ConnectionPool] = {}
_POOLS_GUARD = Lock()


def pool_for(url: str) -> ConnectionPool:
    """The shared pool for one database URL, created on first use.

    **Why this exists, found by measuring rather than by design.** Every store
    method used to open its own connection. That is fine until things happen at
    once -- and the one place in this system where they happen at once *by
    design* is a hundred simultaneous confirmations of the same trade, which is
    the test guarding at-most-once execution. Sixteen worker threads, plus a
    dashboard polling every four seconds, plus a live loop, against a server
    allowing twenty connections: the test failed on connection exhaustion while
    passing in isolation.

    It failed safe -- a refused connection cannot send a duplicate order -- but
    a guarantee whose test falls over under the concurrency it exists to survive
    is a guarantee nobody is checking any more.

    One pool per URL, kept for the life of the process. A pool per store object
    would put the exhaustion back where it started.
    """
    if not url:
        raise PostgresUnavailableError(_NO_URL)
    with _POOLS_GUARD:
        existing = _POOLS.get(url)
        if existing is not None:
            return existing
        try:
            created = ConnectionPool(
                url,
                min_size=1,
                max_size=MAX_POOL_SIZE,
                timeout=POOL_TIMEOUT_SECONDS,
                open=True,
            )
            created.wait(timeout=POOL_TIMEOUT_SECONDS)
        except Exception as error:  # psycopg_pool wraps several failure kinds
            raise PostgresUnavailableError(f"could not connect: {error}") from error
        _POOLS[url] = created
        return created


def close_pools() -> None:
    """Shut every pool down. For tests and for a clean process exit."""
    with _POOLS_GUARD:
        for pool in _POOLS.values():
            pool.close()
        _POOLS.clear()


def migrate(url: str, directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Bring the database up to date. Returns what was applied this time.

    Safe to call on every start-up: already-applied versions are skipped, so the
    usual return value is an empty list.
    """
    migrations = discover(directory)
    applied: list[Migration] = []

    with connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(_LEDGER)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            done = {int(row[0]) for row in cur.fetchall()}

        for migration in migrations:
            if migration.version in done:
                continue
            # One transaction per migration: it lands whole or not at all.
            # Postgres rolls back DDL, which most databases cannot do.
            with conn.cursor() as cur:
                cur.execute(migration.sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (migration.version, migration.name),
                )
            conn.commit()
            applied.append(migration)

    return applied


def status(url: str, directory: Path = MIGRATIONS_DIR) -> tuple[list[Migration], list[Migration]]:
    """(applied, pending), for a start-up line worth printing."""
    migrations = discover(directory)
    with connect(url) as conn, conn.cursor() as cur:
        cur.execute(_LEDGER)
        cur.execute("SELECT version FROM schema_migrations")
        done = {int(row[0]) for row in cur.fetchall()}
    return (
        [m for m in migrations if m.version in done],
        [m for m in migrations if m.version not in done],
    )
