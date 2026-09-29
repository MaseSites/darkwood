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

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Cut the network for every test that has not explicitly asked for it."""
    for item in items:
        if "live" not in item.keywords and "costs_money" not in item.keywords:
            item.add_marker(pytest.mark.disable_socket)


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def config_dir(project_root: Path) -> Path:
    return project_root / "config"
