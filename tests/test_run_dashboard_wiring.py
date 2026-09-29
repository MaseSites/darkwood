"""The dashboard entry point, checked for the mistakes an entry point makes.

Scripts usually escape testing because they end in `uvicorn.run`. That is exactly
why a flag can exist, appear in `--help`, be documented, and do nothing: every
other test in the suite exercises the app object directly and never touches the
wiring that decides what goes into it.

This happened. `--execute` was added, `_arm` was written, both were documented,
and the call between them was missing. The full suite stayed green because no
test ran the script.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_dashboard.py"


def _main_function() -> ast.FunctionDef:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("run_dashboard.py has no main()")


def _called_names(node: ast.AST) -> set[str]:
    return {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }


def test_the_execute_flag_actually_reaches_the_arming_code() -> None:
    """A flag that parses but is never read is worse than no flag.

    It reports success, prints the banner, serves the dashboard -- and silently
    cannot trade, which is the one thing the person who typed it was relying on.
    """
    assert "_arm" in _called_names(_main_function()), (
        "--execute is parsed but _arm() is never called from main(), so arming "
        "the executor does nothing"
    )


def test_arming_failure_stops_startup_rather_than_serving_unarmed() -> None:
    """Falling back to the safe mode is still the wrong answer here.

    Someone who asked for `--execute` and got a working dashboard will believe
    their confirmations reach the exchange. Refusing to start is the only outcome
    that cannot be misread.
    """
    guards = [
        node
        for node in ast.walk(_main_function())
        if isinstance(node, ast.If)
        and "execute" in ast.unparse(node.test)
        and "_arm" in ast.unparse(node.test)
    ]
    assert guards, "nothing in main() branches on both --execute and _arm()"
    assert any(
        isinstance(statement, ast.Return)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value != 0
        for guard in guards
        for statement in guard.body
    ), "a failed arming does not stop startup with a non-zero exit"


def test_the_banner_tells_the_truth_about_what_is_connected() -> None:
    """The line printed at startup is the only place the mode is visible."""
    source = ast.unparse(_main_function())
    assert "services.executor is None" in source, (
        "the startup banner is unconditional, so an armed dashboard would still "
        "announce that no exchange is connected"
    )
