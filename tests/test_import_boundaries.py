"""Layer discipline, enforced by the compiler of last resort: a test.

Architecture diagrams drift. Import graphs do not, if something checks them. This
test is the Stage 0 acceptance criterion and it protects three properties that the
rest of the design leans on:

* `domain` stays dependency-free, so the contracts do not move when an
  implementation does.
* The exchange client and the model client each live in exactly one place, so
  "who can talk to the outside world" is answerable by reading one line.
* `sim` and `execution` never import each other. They are twins driving the same
  state machine through the same protocol; the moment one reaches into the other,
  the backtest stops testing what runs live.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "traidingbrain"

#: Package -> the third-party modules only it may import.
EXCLUSIVE_IMPORTS: dict[str, frozenset[str]] = {
    "ccxt": frozenset({"data", "execution"}),
    "anthropic": frozenset({"brain"}),
    "fastapi": frozenset({"api"}),
    "duckdb": frozenset({"data"}),
}

#: `domain` is the contract layer and must stay light.
DOMAIN_FORBIDDEN = frozenset(
    {"pandas", "numpy", "ccxt", "anthropic", "duckdb", "fastapi", "pyarrow", "sqlite3"}
)

#: Packages that must not import each other, in either direction.
MUTUALLY_BLIND = [("sim", "execution")]


def _iter_modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py"))


def _package_of(path: Path) -> str:
    rel = path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else "<root>"


def _imported_roots(path: Path) -> set[str]:
    """Top-level names imported by a module, for both `import x` and `from x import`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _internal_packages(path: Path) -> set[str]:
    """Which sibling packages of traidingbrain this module imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    packages: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[0] == "traidingbrain" and len(parts) > 1:
                packages.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "traidingbrain" and len(parts) > 1:
                    packages.add(parts[1])
    return packages


@pytest.mark.parametrize("module", _iter_modules(), ids=lambda p: str(p.name))
def test_exclusive_imports_stay_in_their_package(module: Path) -> None:
    package = _package_of(module)
    roots = _imported_roots(module)
    for library, allowed in EXCLUSIVE_IMPORTS.items():
        if library in roots and package not in allowed:
            pytest.fail(
                f"{module.relative_to(SRC)} imports {library!r}, which belongs to "
                f"{sorted(allowed)}. Route it through a domain protocol instead."
            )


def test_domain_has_no_heavy_dependencies() -> None:
    offenders: list[str] = []
    for module in (SRC / "domain").rglob("*.py"):
        forbidden = _imported_roots(module) & DOMAIN_FORBIDDEN
        if forbidden:
            offenders.append(f"{module.relative_to(SRC)} -> {sorted(forbidden)}")
    assert not offenders, (
        "domain must depend on nothing but pydantic and the standard library:\n  "
        + "\n  ".join(offenders)
    )


def test_domain_imports_no_other_package() -> None:
    offenders: list[str] = []
    for module in (SRC / "domain").rglob("*.py"):
        siblings = _internal_packages(module) - {"domain"}
        if siblings:
            offenders.append(f"{module.relative_to(SRC)} -> {sorted(siblings)}")
    assert not offenders, "domain must not depend on any other package:\n  " + "\n  ".join(
        offenders
    )


@pytest.mark.parametrize(("left", "right"), MUTUALLY_BLIND)
def test_twin_packages_do_not_see_each_other(left: str, right: str) -> None:
    for a, b in ((left, right), (right, left)):
        directory = SRC / a
        if not directory.exists():
            continue
        for module in directory.rglob("*.py"):
            if b in _internal_packages(module):
                pytest.fail(
                    f"{module.relative_to(SRC)} imports {b!r}. {left} and {right} are twins "
                    f"behind the Broker protocol; coupling them means the backtest stops "
                    f"exercising the live path."
                )
