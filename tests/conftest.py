"""Shared test setup.

Two standing rules for this suite:

1. The network is off. Any test that reaches out has to say so with a marker, and
   those are deselected by default. A test suite that quietly hits an exchange or
   the Anthropic API is a suite that fails for reasons unrelated to the code and
   costs money doing it.
2. The brain is faked. Model answers come from recorded fixtures, so the suite is
   deterministic and free.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest

from traidingbrain.config.settings import load_secrets

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Cut the network for every test that has not explicitly asked for it.

    `allow_hosts` is the narrow exception, used by the API tests: FastAPI's test
    client runs the app in-process and makes no external request, but asyncio
    still needs a local socket pair for its own event loop. Permitting loopback
    keeps the guarantee that matters -- nothing reaches an exchange or an API --
    while letting those tests run.
    """
    for item in items:
        if "live" in item.keywords or "costs_money" in item.keywords:
            continue
        if "allow_hosts" in item.keywords:
            continue
        item.add_marker(pytest.mark.disable_socket)


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def config_dir(project_root: Path) -> Path:
    return project_root / "config"


GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"


@pytest.fixture
def golden() -> Callable[[str, Any], None]:
    """Compare a payload against a frozen reference file.

    Regenerate deliberately with `UPDATE_GOLDEN=1 pytest`. Deliberately is the
    operative word: these files pin what the analysis reports, and the decision
    cache is keyed on exactly that text. Updating one without meaning to throws
    away every cached model answer and makes the next backtest cost full price.
    """

    def compare(name: str, payload: Any) -> None:
        path = GOLDEN_DIR / f"{name}.json"
        rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)

        if os.environ.get("UPDATE_GOLDEN"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered + "\n", encoding="utf-8")
            return

        if not path.exists():
            pytest.fail(
                f"no golden file at {path.relative_to(PROJECT_ROOT)}. "
                f"Create it with: UPDATE_GOLDEN=1 pytest -k {name}"
            )

        expected = json.loads(path.read_text(encoding="utf-8"))
        assert payload == expected, (
            f"{name} no longer matches its frozen reference.\n"
            f"If the change is intended, regenerate with UPDATE_GOLDEN=1 pytest -- and "
            f"note that it invalidates every cached model decision."
        )

    return compare


# --------------------------------------------------------------------------- #
# The test database
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def pg_test_url() -> str:
    """The test database URL, as a fixture so no test file has to import this."""
    return postgres_test_url()


def postgres_test_url() -> str:
    """The URL the Postgres tests may use, or a skip.

    **Why this is not just `postgres_url`.** The proposal tests truncate before
    every case, which is the right way to run them against a shared server and
    the wrong thing to do to the database the live loop writes proposals into.
    While no Postgres was reachable, every one of those tests skipped and the
    hazard was invisible. The first working database made it real.

    So the tests get their own database, and pointing them at the production one
    is refused rather than permitted with a warning. A warning in a test suite is
    read once.
    """
    secrets = load_secrets()
    test_url = secrets.postgres_test_url.get_secret_value()
    if not test_url:
        pytest.skip("no TB_POSTGRES_TEST_URL configured")

    live_url = secrets.postgres_url.get_secret_value()
    if live_url and test_url == live_url:
        pytest.fail(
            "TB_POSTGRES_TEST_URL is the same database as TB_POSTGRES_URL. These "
            "tests truncate; running them here would delete real proposals. Point "
            "the test URL at a separate database (e.g. traidingbrain_test)."
        )

    unreachable = _unreachable(test_url)
    if unreachable:
        pytest.skip(unreachable)
    return test_url


#: How long to wait for the test database to answer before giving up on it.
#:
#: Short on purpose. This is a yes-or-no question about a machine on the local
#: network, and the only thing a longer wait buys is a longer wait.
PROBE_TIMEOUT_SECONDS = 3.0

#: The probe's answer, taken once. `None` means not asked yet.
_PROBE: list[str | None] = [None]


def _unreachable(url: str) -> str | None:
    """Why the test database cannot be used, or None if it can.

    **Why this exists.** The database moved onto the Raspberry Pi, and the Pi is
    not always on. With it off, every Postgres test spent over two minutes
    retrying a connection that was never going to arrive, and a full run sat
    there for forty minutes before reporting six failures that said nothing
    about the code. The honest answer -- these tests need a database and there
    is not one -- was always available in under a second.

    Asked once per session and remembered. Probing per test would put the same
    wait back, multiplied.
    """
    if _PROBE[0] is not None:
        return _PROBE[0] or None

    try:
        psycopg.connect(url, connect_timeout=int(PROBE_TIMEOUT_SECONDS)).close()
    except Exception as error:  # any failure to reach it is the same answer here
        host = urlsplit(url).hostname or "the configured host"
        _PROBE[0] = (
            f"no Postgres answering at {host}: {error}. "
            f"These tests need a database; start it, or point TB_POSTGRES_TEST_URL "
            f"at one that is running."
        )
    else:
        _PROBE[0] = ""
    return _PROBE[0] or None
