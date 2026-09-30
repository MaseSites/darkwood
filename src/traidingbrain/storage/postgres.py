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
from typing import Any

import psycopg

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


def connect(url: str) -> psycopg.Connection[Any]:
    """Open a connection, or say clearly that there is nowhere to connect to."""
    if not url:
        raise PostgresUnavailableError(
            "no database URL. Set TB_POSTGRES_URL in .env, for example\n"
            "  TB_POSTGRES_URL=postgresql://postgres:PASSWORD@127.0.0.1:5432/traidingbrain"
        )
    try:
        return psycopg.connect(url)
    except psycopg.Error as error:
        raise PostgresUnavailableError(f"could not connect: {error}") from error


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
