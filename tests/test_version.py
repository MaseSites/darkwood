"""What stamps a stored row, and why the format is frozen.

The signature is the key every study reads the signal ledger by. Two properties
matter and neither is obvious from reading the function:

* **The format cannot change silently.** Thousands of collected rows are keyed
  by these exact strings. A one-character change does not return wrong rows, it
  returns none, and a study over an empty set prints a confident nothing. So the
  expected string is written out literally here rather than built the same way
  twice, which would agree with any mistake.
* **`max_bars` is part of it.** A truncated run is a different run. Leaving it
  out let a 400-bar transport check occupy the rows a full replay would have
  written, and the full replay was then skipped as already collected.
"""

from __future__ import annotations

from types import SimpleNamespace

from traidingbrain.config.settings import load_config
from traidingbrain.journal.version import (
    LEDGER_SCHEMA,
    UNKNOWN,
    code_version,
    run_signature,
    spread,
)


def _stub() -> SimpleNamespace:
    """The handful of fields the signature reads, and nothing else."""
    return SimpleNamespace(
        engine=SimpleNamespace(
            simulation=SimpleNamespace(initial_equity=1000.0),
            setups=SimpleNamespace(enabled=["A", "B"]),
            timeframes=SimpleNamespace(signal=SimpleNamespace(value="M15")),
        ),
        risk=SimpleNamespace(limits=SimpleNamespace(max_cost_fraction_of_risk=0.15)),
    )


def test_the_signature_format_is_frozen() -> None:
    """Against a made-up config, so the golden survives editing the real one.

    A literal built from `load_config()` would fail the moment somebody changes
    a setting, which is a legitimate thing to do -- a different configuration
    *should* get a different key. What must never change silently is the shape:
    reordering the fields or changing the separator orphans every collected row
    while looking like a tidy-up.
    """
    assert run_signature(_stub()) == "1000.0|['A', 'B']|0.15|M15|refused-v1"
    assert run_signature(_stub(), max_bars=400) == "1000.0|['A', 'B']|0.15|M15|refused-v1|400bars"


def test_the_real_config_fills_every_field_in_order() -> None:
    """The named fields, in the named order, and no others."""
    config = load_config()
    parts = run_signature(config).split("|")

    assert len(parts) == 5, "a field was added or removed; every collected row is now orphaned"
    assert parts[0] == str(config.engine.simulation.initial_equity)
    assert parts[1] == str(config.engine.setups.enabled)
    assert parts[2] == str(config.risk.limits.max_cost_fraction_of_risk)
    assert parts[3] == config.engine.timeframes.signal.value
    assert parts[4] == LEDGER_SCHEMA


def test_a_truncated_run_gets_its_own_signature() -> None:
    config = load_config()

    full = run_signature(config)
    short = run_signature(config, max_bars=400)

    assert short != full
    assert short.startswith(full)
    assert short.endswith("|400bars")


def test_no_bars_is_the_same_as_a_full_run() -> None:
    """`None` and 0 both mean "everything", and must not key differently."""
    config = load_config()

    assert run_signature(config, max_bars=None) == run_signature(config)
    assert run_signature(config, max_bars=0) == run_signature(config)


def test_the_schema_marker_is_in_the_signature() -> None:
    """So that changing the meaning of a column can retire the old rows."""
    assert LEDGER_SCHEMA in run_signature(load_config())


def test_the_code_version_is_a_commit_and_says_when_it_is_not_enough() -> None:
    version = code_version()

    assert version
    assert version == code_version(), "not cached, so rows in one run could differ"
    if version != UNKNOWN:
        head = version.removesuffix("-dirty")
        assert head.isalnum(), f"not a commit hash: {head!r}"


def test_the_spread_folds_blanks_into_unknown() -> None:
    """Rows written before the column existed are honestly unknown, not equal."""
    assert spread(["abc123", "", "abc123"]) == ["abc123", UNKNOWN]


def test_one_version_reads_as_one_version() -> None:
    assert spread(["abc123", "abc123"]) == ["abc123"]


def test_a_shadow_run_gets_its_own_signature() -> None:
    """Its population is strictly larger, so sharing a key would have been worse
    than wrong.

    The plain rows already in the ledger would have made `count()` non-zero,
    the shadow run would have reported "Signale liegen vor" and skipped, and
    the shadow population would have stayed empty while appearing collected --
    exactly the failure `max_bars` caused once already.
    """
    config = load_config()

    plain = run_signature(config)
    shaded = run_signature(config, shadow=True)

    assert shaded != plain
    assert shaded.startswith(plain), "the plain key is no longer a prefix"
    assert shaded.endswith("|shadow")


def test_the_plain_signature_is_unchanged_by_the_new_option() -> None:
    """12,843 collected rows are keyed by it."""
    config = load_config()

    assert run_signature(config, shadow=False) == run_signature(config)
    assert run_signature(config, max_bars=400, shadow=True).endswith("|400bars|shadow")
