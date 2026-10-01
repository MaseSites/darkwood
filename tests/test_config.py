"""Configuration is validated once, loudly, at startup.

A misconfigured risk tier or an embargo shorter than the outcome horizon does not
crash anything -- it quietly produces a system that takes bigger positions than
intended, or a backtest that knows the future. Both are worth a hard failure at
load time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from tests.conftest import PROJECT_ROOT
from traidingbrain.config.settings import (
    AppConfig,
    HistoryConfig,
    Secrets,
    SizingConfig,
    SymbolsConfig,
    TimeframesConfig,
    WeightsConfig,
    load_config,
)
from traidingbrain.data.venue import SUPPORTED
from traidingbrain.domain import Factor, Timeframe


@pytest.fixture
def app_config(config_dir: Path) -> AppConfig:
    return load_config(config_dir)


def test_shipped_config_loads(app_config: AppConfig) -> None:
    # Which venue is a choice and may change; that it is one the code can build
    # is the invariant. test_venue.py checks the name resolves.
    assert app_config.engine.exchange.name in SUPPORTED
    assert app_config.engine.exchange.testnet is True, (
        "testnet must stay the default; live trading is a stage 10 decision"
    )
    # Which symbols are active is a choice too -- all four are on now that the
    # dashboard shows them side by side. The invariant is that every active one
    # is a symbol the venue actually offers, which the config validates.
    assert app_config.engine.symbols.active
    assert set(app_config.engine.symbols.active) <= set(app_config.engine.symbols.available)


def test_paths_are_absolute_after_loading(app_config: AppConfig) -> None:
    assert app_config.engine.paths.db_path.is_absolute()
    assert app_config.engine.paths.parquet_dir.is_absolute()


# --------------------------------------------------------------------------- #
# Weights
# --------------------------------------------------------------------------- #


def test_inactive_factors_are_dropped_and_the_rest_renormalised(app_config: AppConfig) -> None:
    """News is off in stage 1, and the remaining four must still sum to one.

    Leaving it in at weight zero would quietly pull every confidence toward the
    middle by 15%. Dropping and renormalising says what is actually happening.
    """
    effective = app_config.weights.effective_weights()
    assert Factor.NEWS not in effective
    assert sum(effective.values()) == pytest.approx(1.0)
    # 0.30 / (1 - 0.15) == 0.3529...
    assert effective[Factor.STRUCTURE] == pytest.approx(0.30 / 0.85)


def test_weights_must_declare_every_factor() -> None:
    with pytest.raises(ValidationError, match="must declare every factor"):
        WeightsConfig.model_validate(
            {
                "weights": {"structure": 1.0},
                "active": {"structure": True},
                "confidence": {},
            }
        )


def test_at_least_one_factor_must_be_active() -> None:
    with pytest.raises(ValidationError, match="at least one factor must be active"):
        WeightsConfig.model_validate(
            {
                "weights": dict.fromkeys([f.value for f in Factor], 0.2),
                "active": dict.fromkeys([f.value for f in Factor], False),
                "confidence": {},
            }
        )


# --------------------------------------------------------------------------- #
# Risk
# --------------------------------------------------------------------------- #


def test_risk_tiers_ascend_together(app_config: AppConfig) -> None:
    tiers = app_config.risk.sizing.tiers
    assert [t.min_confidence for t in tiers] == sorted(t.min_confidence for t in tiers)
    assert [t.risk_pct for t in tiers] == sorted(t.risk_pct for t in tiers)


def test_a_tier_that_pays_more_for_less_confidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must ascend"):
        SizingConfig.model_validate(
            {
                "min_confidence": 60,
                "tiers": [
                    {"min_confidence": 60, "risk_pct": 0.03},
                    {"min_confidence": 80, "risk_pct": 0.01},
                ],
                "uncalibrated_cap_risk_pct": 0.01,
                "min_samples_for_uncap": 200,
                "absolute_max_risk_pct": 0.03,
            }
        )


def test_a_tier_above_the_absolute_ceiling_is_rejected() -> None:
    with pytest.raises(ValidationError, match="absolute_max_risk_pct"):
        SizingConfig.model_validate(
            {
                "min_confidence": 60,
                "tiers": [{"min_confidence": 60, "risk_pct": 0.04}],
                "uncalibrated_cap_risk_pct": 0.01,
                "min_samples_for_uncap": 200,
                "absolute_max_risk_pct": 0.03,
            }
        )


def test_shipped_risk_starts_capped_at_one_percent(app_config: AppConfig) -> None:
    """Until the history engine earns it, no tier above 1% is reachable.

    A model's stated confidence is not a calibrated probability on day one, and an
    uncalibrated number must not be allowed to size a position.
    """
    sizing = app_config.risk.sizing
    assert sizing.uncalibrated_cap_risk_pct == pytest.approx(0.01)
    assert sizing.min_samples_for_uncap > 0


def test_liquidation_buffer_is_demanded(app_config: AppConfig) -> None:
    assert app_config.risk.leverage.min_liquidation_buffer_r >= MIN_SANE_LIQUIDATION_BUFFER_R
    assert app_config.risk.leverage.allow_user_increase is False


# --------------------------------------------------------------------------- #
# Timeframes and history windows
# --------------------------------------------------------------------------- #


def test_signal_frame_must_be_analysed() -> None:
    with pytest.raises(ValidationError, match="must appear in context frames"):
        TimeframesConfig.model_validate(
            {"context": ["D1", "H4"], "signal": "H1", "execution": "M1"}
        )


def test_execution_frame_must_not_be_analysed() -> None:
    """M1 is for resolving intrabar ordering, not for reading the market."""
    with pytest.raises(ValidationError, match="must not be analysed"):
        TimeframesConfig.model_validate(
            {"context": ["H1", "M1"], "signal": "H1", "execution": "M1"}
        )


def test_embargo_shorter_than_the_outcome_horizon_is_rejected() -> None:
    """A neighbour whose outcome window overlaps the present bar encodes it.

    This is the leak that makes a similarity index look brilliant in a backtest and
    useless live.
    """
    with pytest.raises(ValidationError, match="embargo_hours"):
        HistoryConfig.model_validate(
            {
                "k_neighbours": 25,
                "outcome_horizon_hours": 48,
                "embargo_hours": 6,
                "min_samples_for_stats": 30,
            }
        )


def test_active_symbols_must_be_known() -> None:
    with pytest.raises(ValidationError, match="not in available"):
        SymbolsConfig.model_validate({"active": ["DOGEUSDT"], "available": ["BTCUSDT"]})


def test_all_needed_frames_include_the_execution_frame(app_config: AppConfig) -> None:
    needed = app_config.engine.timeframes.all_needed
    assert Timeframe.M1 in needed
    assert Timeframe.W1 in needed


# --------------------------------------------------------------------------- #
# The config files themselves
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["settings.yaml", "weights.yaml", "risk.yaml"])
def test_config_files_are_valid_yaml_mappings(config_dir: Path, name: str) -> None:
    with (config_dir / name).open(encoding="utf-8") as fh:
        assert isinstance(yaml.safe_load(fh), dict)


#: A stop that can be reached before liquidation is the whole point of deriving
#: leverage; anything under this buffer is not a safety margin.
MIN_SANE_LIQUIDATION_BUFFER_R = 2.0

#: Shortest string length that starts to look like a key rather than a word.
OPAQUE_STRING_LENGTH = 24

SECRET_KEY_NAMES = frozenset(
    {"api_key", "api_secret", "secret", "secret_key", "token", "password", "passphrase"}
)


def _walk(node: object, path: str = "") -> list[tuple[str, str, object]]:
    """Flatten a YAML tree into (dotted path, leaf key, value) triples."""
    found: list[tuple[str, str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            found.append((here, str(key), value))
            found.extend(_walk(value, here))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found.extend(_walk(value, f"{path}[{i}]"))
    return found


def test_no_credentials_in_committed_config(config_dir: Path) -> None:
    """Credentials come from .env. This catches the day someone pastes one here.

    Matched on the exact key name and on the shape of the value, not on substrings
    -- `confirmation_token_ttl_seconds` is a perfectly good setting and a test that
    trips over it would just get disabled.
    """
    offenders: list[str] = []
    for path in config_dir.glob("*.yaml"):
        with path.open(encoding="utf-8") as fh:
            tree = yaml.safe_load(fh)
        for dotted, key, value in _walk(tree):
            if key.lower() in SECRET_KEY_NAMES and isinstance(value, str) and value.strip():
                offenders.append(f"{path.name}:{dotted} looks like a credential")
            elif isinstance(value, str) and len(value) >= OPAQUE_STRING_LENGTH and value.isalnum():
                offenders.append(f"{path.name}:{dotted} holds a long opaque string")
    assert not offenders, "secrets belong in .env:\n  " + "\n  ".join(offenders)


def test_a_threshold_a_lookup_can_never_meet_is_refused() -> None:
    """The bug this exists to prevent shipped, and was invisible.

    A lookup returns at most `k_neighbours`. With k at 25 and the threshold at 30,
    `sample_is_sufficient` was false on every one of seventy-one thousand lookups
    -- no error, no warning, and a symptom (the history factor silent, the
    confidence cap never lifting) identical to a genuine shortage of data. Two
    numbers in a YAML file will not stay consistent on their own.
    """
    with pytest.raises(ValidationError, match="below min_samples_for_stats"):
        HistoryConfig(
            k_neighbours=25,
            outcome_horizon_hours=48,
            embargo_hours=48,
            min_samples_for_stats=30,
        )


def test_the_shipped_configuration_can_actually_reach_its_threshold() -> None:
    """Deduplication only removes neighbours, so equality would not be enough."""
    history = load_config().engine.history

    assert history.k_neighbours > history.min_samples_for_stats


def test_a_credential_is_read_under_its_own_name_as_well_as_the_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`.env.example` has always said ANTHROPIC_API_KEY, and that was never read.

    Every field in this model picks up a TB_ prefix, so the plain spelling -- the
    one Anthropic's own tooling uses, and the one the example file has always
    told people to write -- was silently ignored. A credential that is present,
    correct and unread is worse than a missing one: nothing reports it, and the
    symptom is identical to not having filled it in.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "plain")
    monkeypatch.delenv("TB_ANTHROPIC_API_KEY", raising=False)

    assert Secrets().anthropic_api_key.get_secret_value() == "plain"


def test_the_prefixed_spelling_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both, not one instead of the other: existing .env files must keep working."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TB_ANTHROPIC_API_KEY", "prefixed")

    assert Secrets().anthropic_api_key.get_secret_value() == "prefixed"


def test_the_cli_token_is_read_under_the_name_the_cli_itself_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`claude setup-token` prints a token for CLAUDE_CODE_OAUTH_TOKEN.

    Accepting any other spelling as the only option would mean copying a value
    out of one tool and renaming it on the way in, which is exactly where a
    credential gets mistyped.
    """
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")

    assert Secrets().claude_code_oauth_token.get_secret_value() == "tok"


def test_every_name_in_the_example_file_is_actually_read() -> None:
    """The example file is the instructions. A line nothing reads is a wrong one.

    Checked against the model rather than by eye, because this drifts silently:
    the file said ANTHROPIC_API_KEY for months while the loader wanted
    TB_ANTHROPIC_API_KEY, and nothing in the project noticed.
    """
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    names = {
        line.split("=", 1)[0].strip()
        for line in example.splitlines()
        if "=" in line and not line.strip().startswith("#")
    }

    readable: set[str] = set()
    for field in Secrets.model_fields.values():
        alias = field.validation_alias
        if alias is None:
            continue
        readable.update(str(choice) for choice in getattr(alias, "choices", []))

    nested = {name for name in names if name.startswith("TB_") and "__" in name}
    unread = names - readable - nested - {"TB_KILL_SWITCH_FILE"}
    assert not unread, f".env.example names variables nothing reads: {sorted(unread)}"
