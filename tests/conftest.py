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
