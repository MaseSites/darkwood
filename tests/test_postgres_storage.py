"""The migration runner, and the parts of Postgres storage that are not the store.

The store itself is covered by running `test_proposals.py` against both
implementations, which is the only proof of equivalence worth having. What is
left here is the machinery around it: whether migrations apply once, whether a
misnamed file is caught, and whether a missing database says so rather than
falling back to something that looks like it worked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from traidingbrain.config.settings import load_secrets
from traidingbrain.storage.postgres import (
    PostgresUnavailableError,
    connect,
    discover,
    migrate,
    status,
)


def url_or_skip() -> str:
    value = load_secrets().postgres_url.get_secret_value()
    if not value:
        pytest.skip("no TB_POSTGRES_URL configured")
    return value


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def test_every_shipped_migration_is_named_so_it_will_be_found() -> None:
    """A file named wrongly is skipped silently, which is the worst outcome.

    It would not fail; it would simply never run, and the absence would surface
    much later as a missing column in something unrelated.
    """
    found = discover()

    assert found, "no migrations found at all"
    assert [m.version for m in found] == sorted(m.version for m in found)


def test_a_misnamed_migration_is_an_error_not_a_skip(tmp_path: Path) -> None:
    (tmp_path / "proposals.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(ValueError, match=r"NNNN_name.sql"):
        discover(tmp_path)


def test_two_migrations_sharing_a_version_are_refused(tmp_path: Path) -> None:
    """Which of them ran would depend on filesystem ordering."""
    (tmp_path / "0001_one.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0001_two.sql").write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(ValueError, match="share a version"):
        discover(tmp_path)


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #


def test_migrating_twice_applies_nothing_the_second_time() -> None:
    """Every start-up runs this. One that has to remember will forget."""
    url = url_or_skip()
    migrate(url)

    assert migrate(url) == []


def test_the_shipped_schema_is_fully_applied() -> None:
    url = url_or_skip()
    migrate(url)
    applied, pending = status(url)

    assert applied
    assert pending == []


def test_the_tables_the_store_needs_exist() -> None:
    url = url_or_skip()
    migrate(url)
    with connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cur.fetchall()}

    assert {"proposals", "tokens", "schema_migrations"} <= tables


def test_the_payload_is_queryable_json_not_text() -> None:
    """jsonb, so a field in the proposal can be filtered on without parsing rows.

    Stored as text it would still work and would quietly rule out every query
    anyone will eventually want.
    """
    url = url_or_skip()
    migrate(url)
    with connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'proposals' AND column_name = 'payload'"
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == "jsonb"


# --------------------------------------------------------------------------- #
# Absence
# --------------------------------------------------------------------------- #


def test_no_url_says_so_rather_than_falling_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment configured for Postgres must not quietly use something else.

    Falling back to a local file would leave two machines writing to two
    different databases and agreeing about neither -- and nothing would report it.
    """
    with pytest.raises(PostgresUnavailableError, match="TB_POSTGRES_URL"):
        connect("")


def test_an_unreachable_server_is_reported_not_swallowed() -> None:
    """connect_timeout is not optional here.

    Without it this test hung: a TCP connect to a closed port on Windows waits
    for the OS timeout rather than being refused, so the suite stalled instead of
    failing. The same would happen to a deployment pointed at a wrong host --
    which is worth knowing, and is why the timeout belongs in the URL rather than
    only in the test.
    """
    with pytest.raises(PostgresUnavailableError, match="could not connect"):
        connect("postgresql://nobody:nothing@10.255.255.1:59999/nowhere?connect_timeout=2")
