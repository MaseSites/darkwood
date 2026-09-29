"""The subscription path, proved without a subscription.

A stub stands in for the CLI, so these run offline and in CI. What they check is
everything between the snapshot and the decision -- the request that goes out, the
parsing of what comes back, and the two failures that matter: an answer that does
not validate, and a login that has expired.

That last one earns its test. The CLI reports an expired session with exit code 0
and `is_error` inside the JSON envelope, so the obvious implementation turns a
lapsed subscription into a run of NO TRADE decisions that is indistinguishable
from a run of cautious ones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.factories import make_snapshot
from traidingbrain.brain.subscription import (
    SubscriptionBrain,
    SubscriptionUnavailableError,
    _extract_json,
)
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Bias, Decision, Factor, RiskLevel, Side

VALID_VERDICT = {
    "schema_version": 1,
    "bias": Bias.BEARISH.value,
    "decision": Decision.WAIT.value,
    "risk": RiskLevel.HIGH.value,
    "factor_scores": [
        {
            "factor": Factor.STRUCTURE.value,
            "score": -0.4,
            "confidence": 0.6,
            "reasoning": "lower highs on the daily",
        }
    ],
    "scenarios": {
        "bullish": {
            "side": Side.LONG.value,
            "entry": {"level_id": "lvl_1", "offset_atr": 0.0},
            "stop": {"level_id": "lvl_2", "offset_atr": 0.0},
            "target": {"level_id": "lvl_3", "offset_atr": 0.0},
            "rationale": "reclaim and hold",
        },
        "bearish": {
            "side": Side.SHORT.value,
            "entry": {"level_id": "lvl_3", "offset_atr": 0.0},
            "stop": {"level_id": "lvl_1", "offset_atr": 0.0},
            "target": {"level_id": "lvl_2", "offset_atr": 0.0},
            "rationale": "continuation lower",
        },
        "invalidation": {"level_id": "lvl_1", "offset_atr": 0.5},
        "invalidation_note": "a close above invalidates the read",
    },
    "reasoning": ["structure is not supporting a long here"],
    "market_commentary": "Distribution under a broken level, with nothing reclaimed.",
}


def _stub_cli(tmp_path: Path, name: str, payload: str) -> str:
    """A fake `claude` that prints one envelope and exits.

    Written as a Python script and invoked through this interpreter, so the test
    needs neither a shell nor an executable bit.
    """
    script = tmp_path / f"{name}.py"
    script.write_text(
        "import sys\nsys.stdin.read()\nprint(r'''" + payload + "''')\n",
        encoding="utf-8",
    )
    launcher = tmp_path / f"{name}.cmd"
    launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    return str(launcher) if sys.platform == "win32" else f"{sys.executable} {script}"


def _envelope(result: str, *, is_error: bool = False) -> str:
    return json.dumps(
        {
            "type": "result",
            "is_error": is_error,
            "result": result,
            "session_id": "abc-123",
            "usage": {"input_tokens": 1500, "output_tokens": 400, "cache_read_input_tokens": 800},
        }
    )


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


@pytest.mark.skipif(sys.platform != "win32", reason="the stub launcher is a .cmd shim")
def test_a_well_formed_answer_becomes_a_decision(tmp_path: Path, config: AppConfig) -> None:
    cli = _stub_cli(tmp_path, "ok", _envelope(json.dumps(VALID_VERDICT)))
    brain = SubscriptionBrain(config, cli=cli)

    decision = brain.decide(make_snapshot())

    assert decision.verdict.bias is Bias.BEARISH
    assert decision.model_id == brain.model
    # Token counts come back in the envelope and are worth carrying: they are what
    # the same run would have cost on the API, which is how you know whether the
    # subscription is the right home for a given workload.
    assert brain.usage.input_tokens == 1500
    assert brain.usage.output_tokens == 400


@pytest.mark.skipif(sys.platform != "win32", reason="the stub launcher is a .cmd shim")
def test_an_answer_wrapped_in_prose_is_still_read(tmp_path: Path, config: AppConfig) -> None:
    """Without server-side schema enforcement this is normal, not exceptional."""
    chatty = "Here is my read:\n```json\n" + json.dumps(VALID_VERDICT) + "\n```\nHope that helps."
    cli = _stub_cli(tmp_path, "chatty", _envelope(chatty))

    decision = SubscriptionBrain(config, cli=cli).decide(make_snapshot())

    assert decision.verdict.bias is Bias.BEARISH


@pytest.mark.skipif(sys.platform != "win32", reason="the stub launcher is a .cmd shim")
def test_an_answer_that_never_validates_becomes_no_trade(
    tmp_path: Path, config: AppConfig
) -> None:
    """A bad answer must not stall a run, and must not become a trade."""
    cli = _stub_cli(tmp_path, "junk", _envelope('{"bias": "sideways", "nonsense": true}'))
    brain = SubscriptionBrain(config, cli=cli)

    decision = brain.decide(make_snapshot())

    assert decision.verdict.decision is not Decision.VALID_TRADE
    assert decision.plan is None
    assert brain.usage.errors == 1


@pytest.mark.skipif(sys.platform != "win32", reason="the stub launcher is a .cmd shim")
def test_an_expired_login_stops_the_run_instead_of_refusing_quietly(
    tmp_path: Path, config: AppConfig
) -> None:
    """The test this file exists for.

    The CLI exits 0 and puts the failure inside the envelope, so nothing about the
    process signals a problem. A run that silently produced NO TRADE for every bar
    would look exactly like a cautious model, and the mistake would only surface
    once someone wondered why the brain never had an opinion.
    """
    cli = _stub_cli(
        tmp_path,
        "expired",
        _envelope("Failed to authenticate: OAuth session expired", is_error=True),
    )

    with pytest.raises(SubscriptionUnavailableError, match="setup-token"):
        SubscriptionBrain(config, cli=cli).decide(make_snapshot())


def test_a_missing_cli_is_an_error_not_a_refusal(config: AppConfig) -> None:
    brain = SubscriptionBrain(config, cli="definitely-not-installed-anywhere")

    with pytest.raises(SubscriptionUnavailableError, match="PATH"):
        brain.decide(make_snapshot())


def test_estimating_cost_refuses_rather_than_reporting_zero(config: AppConfig) -> None:
    """There is no bill to estimate, and a confident zero would imply there was."""
    with pytest.raises(SubscriptionUnavailableError):
        SubscriptionBrain(config).estimate([make_snapshot().to_brain_input()])


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('Sure! {"a": 1} -- let me know.', '{"a": 1}'),
    ],
)
def test_json_is_found_in_the_shapes_a_model_actually_replies_in(
    reply: str, expected: str
) -> None:
    assert json.loads(_extract_json(reply)) == json.loads(expected)


def test_a_reply_with_no_json_at_all_is_rejected() -> None:
    with pytest.raises(ValueError, match="no JSON object"):
        _extract_json("I would rather not answer that.")
