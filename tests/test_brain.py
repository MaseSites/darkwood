"""The decision layer: scoring, the guard, the cache, and the gate.

None of these tests touch the network. The model's judgement is not what is being
checked here -- what is being checked is everything wrapped around it, which is
where a mistake is silent rather than obvious.

The guard tests are adversarial on purpose. They feed verdicts that are internally
coherent and still unusable, because that is the realistic failure: not a model
producing nonsense, but a model producing something reasonable that would lose
money for a reason the schema cannot express.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.factories import make_snapshot, make_timeframe_view, make_verdict
from traidingbrain.brain.cache import DecisionCache, MemoryCache, cache_key
from traidingbrain.brain.fake import FakeBrain
from traidingbrain.brain.guard import MIN_STOP_DISTANCE_ATR, check, resolve_plan
from traidingbrain.brain.scoring import NEUTRAL_CONFIDENCE, score
from traidingbrain.brain.trigger import Trigger
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Bias, Decision, Factor, RegimeKind, Side
from traidingbrain.domain.snapshot import (
    HistoryStats,
    MarketSnapshot,
    NewsItem,
    SessionStats,
)
from traidingbrain.domain.verdict import Anchor, BrainVerdict, FactorScore


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


def scores(**by_factor: tuple[float, float]) -> list[FactorScore]:
    return [
        FactorScore(factor=factor, score=value, confidence=certainty, reasoning="because")
        for factor, (value, certainty) in (
            (Factor[name.upper()], pair) for name, pair in by_factor.items()
        )
    ]


SUFFICIENT = HistoryStats(
    similar_situations_found=400,
    historical_winrate=0.55,
    regime=RegimeKind.TREND_UP,
    sample_is_sufficient=True,
)
THIN = HistoryStats(similar_situations_found=3, sample_is_sufficient=False)


# --------------------------------------------------------------------------- #
# Confidence is arithmetic, not an opinion
# --------------------------------------------------------------------------- #


def test_factors_that_cancel_out_give_the_midpoint(config: AppConfig) -> None:
    """Zero net evidence is a 50, not a 0.

    A verdict with nothing behind it should read as "no information", and a zero
    would read as "confidently wrong".
    """
    verdict = make_verdict(
        bias=Bias.BULLISH,
        factor_scores=scores(structure=(1.0, 1.0), indicators=(-1.0, 1.0)),
    )
    breakdown = score(verdict, config.weights, SUFFICIENT)

    # Structure carries more weight than indicators, so this is not exactly 50 --
    # but it should sit close, and on the side the heavier factor points.
    assert abs(breakdown.confidence - NEUTRAL_CONFIDENCE) < 15


def test_total_agreement_reaches_the_top(config: AppConfig) -> None:
    verdict = make_verdict(
        bias=Bias.BULLISH,
        factor_scores=scores(
            structure=(1.0, 1.0), indicators=(1.0, 1.0), liquidity=(1.0, 1.0), history=(1.0, 1.0)
        ),
    )
    assert score(verdict, config.weights, SUFFICIENT).confidence == pytest.approx(100.0)


def test_evidence_against_the_stated_bias_lands_below_the_midpoint(config: AppConfig) -> None:
    """A verdict whose own factors contradict its conclusion is not confident.

    This falls out of the arithmetic rather than needing a special case, which is
    part of why the arithmetic is here and not in the prompt.
    """
    verdict = make_verdict(
        bias=Bias.BULLISH,
        factor_scores=scores(structure=(-1.0, 1.0), liquidity=(-1.0, 1.0)),
    )
    assert score(verdict, config.weights, SUFFICIENT).confidence < NEUTRAL_CONFIDENCE


def test_a_factor_the_model_is_unsure_of_counts_for_less(config: AppConfig) -> None:
    certain = make_verdict(bias=Bias.BULLISH, factor_scores=scores(structure=(0.8, 1.0)))
    unsure = make_verdict(bias=Bias.BULLISH, factor_scores=scores(structure=(0.8, 0.2)))

    assert (
        score(certain, config.weights, SUFFICIENT).confidence
        > score(unsure, config.weights, SUFFICIENT).confidence
    )


def test_unscored_factors_are_dropped_rather_than_counted_as_zero(config: AppConfig) -> None:
    """Counting a missing factor as zero drags every incomplete answer toward the
    middle, making it look more uncertain than the evidence that is present."""
    partial = make_verdict(bias=Bias.BULLISH, factor_scores=scores(structure=(1.0, 1.0)))
    breakdown = score(partial, config.weights, SUFFICIENT)

    assert breakdown.confidence == pytest.approx(100.0)
    assert Factor.LIQUIDITY in breakdown.missing_factors
    assert breakdown.weights_used[Factor.STRUCTURE] == pytest.approx(1.0)


def test_confidence_is_capped_while_the_history_sample_is_thin(config: AppConfig) -> None:
    """The system may be confident; it may not act as though that is evidence."""
    verdict = make_verdict(
        bias=Bias.BULLISH,
        factor_scores=scores(structure=(1.0, 1.0), liquidity=(1.0, 1.0)),
    )
    capped = score(verdict, config.weights, THIN)

    assert capped.capped_by_history is True
    assert capped.confidence == pytest.approx(config.weights.confidence.cap_without_history)
    assert "capped" in capped.explain()


def test_news_carries_no_weight_in_this_configuration(config: AppConfig) -> None:
    """News is off for stage 1, so scoring it must change nothing."""
    without = make_verdict(bias=Bias.BULLISH, factor_scores=scores(structure=(0.6, 0.8)))
    with_news = make_verdict(
        bias=Bias.BULLISH, factor_scores=scores(structure=(0.6, 0.8), news=(-1.0, 1.0))
    )

    assert score(without, config.weights, SUFFICIENT).confidence == pytest.approx(
        score(with_news, config.weights, SUFFICIENT).confidence
    )


def test_a_neutral_bias_produces_no_conviction(config: AppConfig) -> None:
    verdict = make_verdict(bias=Bias.NEUTRAL, factor_scores=scores(structure=(1.0, 1.0)))
    assert score(verdict, config.weights, SUFFICIENT).confidence == pytest.approx(
        NEUTRAL_CONFIDENCE
    )


# --------------------------------------------------------------------------- #
# The guard
# --------------------------------------------------------------------------- #


def test_a_sound_verdict_passes(config: AppConfig) -> None:
    guard, plan = check(make_verdict(), make_snapshot(), config.risk)
    assert guard.passed, guard.violations
    assert plan is not None
    assert plan.side is Side.LONG


def test_an_anchor_to_a_level_that_does_not_exist_is_caught(config: AppConfig) -> None:
    """The level-id design makes an invented price unrepresentable; this catches
    an invented *level*, which is the remaining way to point at nothing."""
    verdict = make_verdict()
    broken = verdict.scenarios.bullish.model_copy(
        update={"entry": Anchor(level_id="lvl_99", offset_atr=0.0)}
    )
    verdict = verdict.model_copy(
        update={"scenarios": verdict.scenarios.model_copy(update={"bullish": broken})}
    )

    guard, plan = check(verdict, make_snapshot(), config.risk)

    assert not guard.passed
    assert plan is None
    assert any("lvl_99" in v for v in guard.violations)


def test_a_stop_on_the_wrong_side_is_caught(config: AppConfig) -> None:
    snapshot = make_snapshot()
    verdict = make_verdict()
    inverted = verdict.scenarios.bullish.model_copy(
        update={"stop": Anchor(level_id="lvl_1", offset_atr=0.0)}
    )
    verdict = verdict.model_copy(
        update={"scenarios": verdict.scenarios.model_copy(update={"bullish": inverted})}
    )

    guard, _ = check(verdict, snapshot, config.risk)

    assert not guard.passed
    assert any("not below the entry" in v for v in guard.violations)


def test_a_stop_inside_a_single_bar_of_noise_is_caught(config: AppConfig) -> None:
    """Two failures compound here: the stop gets hit by nothing in particular, and
    because size is risk over stop distance, the position is enormous."""
    snapshot = make_snapshot()
    verdict = make_verdict()
    hair = verdict.scenarios.bullish.model_copy(
        update={
            "entry": Anchor(level_id="lvl_0", offset_atr=0.0),
            "stop": Anchor(level_id="lvl_0", offset_atr=-0.05),
        }
    )
    verdict = verdict.model_copy(
        update={"scenarios": verdict.scenarios.model_copy(update={"bullish": hair})}
    )

    guard, _ = check(verdict, snapshot, config.risk)

    assert not guard.passed
    assert any(str(MIN_STOP_DISTANCE_ATR) in v for v in guard.violations)


def test_a_reward_that_cannot_pay_for_the_losses_is_caught(config: AppConfig) -> None:
    snapshot = make_snapshot()
    verdict = make_verdict()
    thin = verdict.scenarios.bullish.model_copy(
        update={
            "entry": Anchor(level_id="lvl_0", offset_atr=0.0),
            "stop": Anchor(level_id="lvl_0", offset_atr=-1.0),
            "target": Anchor(level_id="lvl_0", offset_atr=0.5),
        }
    )
    verdict = verdict.model_copy(
        update={"scenarios": verdict.scenarios.model_copy(update={"bullish": thin})}
    )

    guard, _ = check(verdict, snapshot, config.risk)

    assert not guard.passed
    assert any("reward-to-risk" in v for v in guard.violations)


def test_a_bias_that_contradicts_its_own_scenario_is_caught(config: AppConfig) -> None:
    """VALID TRADE with a neutral bias argues for nothing in particular."""
    guard, plan = check(
        make_verdict(bias=Bias.NEUTRAL, decision=Decision.VALID_TRADE),
        make_snapshot(),
        config.risk,
    )

    assert not guard.passed
    assert plan is None
    assert any("no scenario" in v for v in guard.violations)


def test_a_wait_verdict_still_has_its_anchors_checked(config: AppConfig) -> None:
    """An answer that cannot name real levels is worth knowing about whatever it
    concluded."""
    guard, plan = check(make_verdict(decision=Decision.WAIT), make_snapshot(), config.risk)
    assert guard.passed
    assert plan is None


def test_resolve_turns_anchors_into_prices() -> None:
    snapshot = make_snapshot()
    plan = resolve_plan(make_verdict().scenarios.bullish, snapshot)

    assert plan is not None
    level = snapshot.level_by_id("lvl_3")
    assert level is not None
    assert plan.entry == pytest.approx(level.price)
    assert plan.reward_risk > 0


# --------------------------------------------------------------------------- #
# The cache
# --------------------------------------------------------------------------- #


def test_the_key_binds_everything_that_could_change_the_answer() -> None:
    """Market state, prompt, model, schema. Miss one and the cache serves a stale
    answer to a question nobody asked."""
    base = cache_key("abc", "claude-opus-5-5", "v1")
    assert base != cache_key("abd", "claude-opus-5-5", "v1")
    assert base != cache_key("abc", "claude-sonnet-5-5", "v1")
    assert base != cache_key("abc", "claude-opus-5-5", "v2")
    assert base != cache_key("abc", "claude-opus-5-5", "v1", schema_version=2)


def test_a_cached_decision_comes_back_identical(tmp_path: Path, config: AppConfig) -> None:
    """With sampling parameters gone from the current models, this cache is the
    only thing that makes a backtest reproducible."""
    cache = DecisionCache(tmp_path / "decisions.sqlite")
    snapshot = make_snapshot()
    decision = FakeBrain(config).decide(snapshot)
    key = cache_key(decision.snapshot_hash, decision.model_id, decision.prompt_version)

    assert cache.get(key) is None
    cache.put(key, decision)
    restored = cache.get(key)

    assert restored is not None
    assert restored.from_cache is True
    assert restored.confidence == pytest.approx(decision.confidence)
    assert restored.verdict.model_dump() == decision.verdict.model_dump()


def test_the_cache_survives_being_reopened(tmp_path: Path, config: AppConfig) -> None:
    """The key is content-addressed, not process-addressed.

    A cache keyed on Python's salted `hash()` misses on every restart, silently,
    while appearing to work.
    """
    path = tmp_path / "decisions.sqlite"
    decision = FakeBrain(config).decide(make_snapshot())
    key = cache_key(decision.snapshot_hash, decision.model_id, decision.prompt_version)

    DecisionCache(path).put(key, decision)
    assert DecisionCache(path).get(key) is not None


def test_the_memory_cache_behaves_the_same(config: AppConfig) -> None:
    cache = MemoryCache()
    decision = FakeBrain(config).decide(make_snapshot())
    key = "k"

    assert cache.get(key) is None
    cache.put(key, decision)
    assert cache.get(key) is not None
    assert cache.hit_rate == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


def test_the_gate_skips_a_bar_with_no_structural_event(config: AppConfig) -> None:
    quiet = make_timeframe_view(
        structure={"sequence": "HH HL", "bos": False, "choch": False},  # type: ignore[arg-type]
    )
    snapshot = make_snapshot(frames=[quiet])
    trigger = Trigger(config.engine.trigger)

    assert trigger.should_ask(snapshot, bar_index=100) is False
    assert trigger.stats.no_structure_event == 1


def test_the_gate_waits_between_calls(config: AppConfig) -> None:
    """One developing setup must not be re-priced on every bar of its formation."""
    snapshot = make_snapshot()
    trigger = Trigger(config.engine.trigger)

    assert trigger.should_ask(snapshot, bar_index=100) is True
    assert trigger.should_ask(snapshot, bar_index=101) is False
    assert trigger.stats.too_soon == 1

    spacing = config.engine.trigger.min_bars_between_calls
    assert trigger.should_ask(snapshot, bar_index=100 + spacing) is True


def test_the_gate_reports_why_it_skipped(config: AppConfig) -> None:
    """A gate nobody measures is a gate nobody trusts -- and it is a confounder in
    every result the system produces."""
    trigger = Trigger(config.engine.trigger)
    snapshot = make_snapshot()
    for bar in range(50):
        trigger.should_ask(snapshot, bar)

    assert trigger.stats.seen == 50
    assert 0 < trigger.stats.fired < 50
    assert "passed the gate" in trigger.stats.summary()


# --------------------------------------------------------------------------- #
# The fake brain, end to end
# --------------------------------------------------------------------------- #


def test_the_fake_brain_produces_a_checked_decision(config: AppConfig) -> None:
    decision = FakeBrain(config).decide(make_snapshot())

    assert decision.model_id == "fake-brain"
    assert 0.0 <= decision.confidence <= 100.0
    assert decision.verdict.scenarios.bullish.side is Side.LONG
    assert decision.verdict.scenarios.bearish.side is Side.SHORT


def test_the_fake_brain_is_deterministic(config: AppConfig) -> None:
    snapshot = make_snapshot()
    first = FakeBrain(config).decide(snapshot)
    second = FakeBrain(config).decide(snapshot)

    assert first.confidence == pytest.approx(second.confidence)
    assert first.verdict.model_dump() == second.verdict.model_dump()


def test_a_tradeable_decision_carries_a_resolved_plan(config: AppConfig) -> None:
    decision = FakeBrain(config).decide(make_snapshot())
    if decision.is_tradeable:
        assert decision.plan is not None
        assert decision.plan.reward_risk >= config.risk.limits.min_reward_risk
    else:
        assert decision.plan is None or decision.verdict.decision is not Decision.VALID_TRADE


def test_every_verdict_states_all_three_scenarios(config: AppConfig) -> None:
    """Including when the answer is WAIT. A plan that cannot say how it would be
    wrong is not a plan."""
    verdict = FakeBrain(config).decide(make_snapshot()).verdict
    assert verdict.scenarios.bullish is not None
    assert verdict.scenarios.bearish is not None
    assert verdict.scenarios.invalidation is not None
    assert verdict.scenarios.invalidation_note


def test_the_verdict_schema_is_acceptable_to_a_strict_api() -> None:
    """Every field required, no extra keys anywhere.

    Both are required for the API to accept the schema at all, and both are what
    turn a malformed answer into a hard failure instead of a silent default.
    """
    schema = BrainVerdict.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"])
    for name, definition in schema.get("$defs", {}).items():
        if definition.get("type") == "object":
            assert definition.get("additionalProperties") is False, name
            assert set(definition.get("properties", {})) == set(definition.get("required", [])), (
                name
            )


# --------------------------------------------------------------------------- #
# The gate's newer refusals
# --------------------------------------------------------------------------- #


def _gate(config: AppConfig, **overrides: object) -> Trigger:
    return Trigger(config.engine.trigger.model_copy(update=overrides))


def _passing_snapshot(**overrides: object) -> MarketSnapshot:
    """A snapshot the default gate already accepts, so a refusal is attributable.

    Without this every one of these tests could pass because some unrelated
    check fired first, which is the way a filter test quietly stops testing
    anything.
    """
    snapshot = make_snapshot()
    assert Trigger(load_config().engine.trigger).should_ask(snapshot, 100), (
        "the fixture no longer passes the default gate, so these tests prove nothing"
    )
    return snapshot.model_copy(update=overrides) if overrides else snapshot


def test_a_high_impact_release_inside_the_window_stops_the_ask(config: AppConfig) -> None:
    """Both halves of the window are the same problem.

    Before a release the book thins as market makers step back; after it the
    first move is frequently reversed. A stop placed on a swing low means
    nothing to either.
    """
    gate = _gate(config, news_blackout_minutes=30)
    snapshot = _passing_snapshot(
        news=[NewsItem(event="CPI", impact="high", sentiment=Bias.NEUTRAL, minutes_until=20)]
    )

    assert gate.should_ask(snapshot, 100) is False
    assert gate.stats.news_blackout == 1


def test_the_blackout_is_symmetric(config: AppConfig) -> None:
    gate = _gate(config, news_blackout_minutes=30)
    snapshot = _passing_snapshot(
        news=[NewsItem(event="CPI", impact="high", sentiment=Bias.NEUTRAL, minutes_until=-20)]
    )

    assert gate.should_ask(snapshot, 100) is False


def test_an_event_outside_the_window_does_not_stop_anything(config: AppConfig) -> None:
    gate = _gate(config, news_blackout_minutes=30)
    snapshot = _passing_snapshot(
        news=[NewsItem(event="CPI", impact="high", sentiment=Bias.NEUTRAL, minutes_until=200)]
    )

    assert gate.should_ask(snapshot, 100) is True


def test_only_high_impact_counts(config: AppConfig) -> None:
    """Treating every scheduled item as a blackout would close most of the week.

    The restriction would then never be tested against anything, because there
    would be almost nothing left to test it on.
    """
    gate = _gate(config, news_blackout_minutes=30)
    snapshot = _passing_snapshot(
        news=[NewsItem(event="minor", impact="low", sentiment=Bias.NEUTRAL, minutes_until=5)]
    )

    assert gate.should_ask(snapshot, 100) is True


def test_the_blackout_is_off_unless_configured(config: AppConfig) -> None:
    """A restriction nobody measured only narrows the sample."""
    assert config.engine.trigger.news_blackout_minutes == 0

    gate = _gate(config)
    snapshot = _passing_snapshot(
        news=[NewsItem(event="CPI", impact="high", sentiment=Bias.NEUTRAL, minutes_until=1)]
    )

    assert gate.should_ask(snapshot, 100) is True


def test_a_quiet_hour_can_be_refused(config: AppConfig) -> None:
    """Thin books move further on the same order."""
    gate = _gate(config, require_active_session=True)
    snapshot = _passing_snapshot(session=SessionStats(active=[]))

    assert gate.should_ask(snapshot, 100) is False
    assert gate.stats.wrong_session == 1


def test_a_session_allowlist_refuses_everything_outside_it(config: AppConfig) -> None:
    gate = _gate(config, allowed_sessions=["london", "new_york"])
    snapshot = _passing_snapshot(session=SessionStats(active=["tokyo"]))

    assert gate.should_ask(snapshot, 100) is False


def test_one_allowed_desk_among_several_is_enough(config: AppConfig) -> None:
    """Sessions overlap by construction, so requiring all of them means none."""
    gate = _gate(config, allowed_sessions=["london"])
    snapshot = _passing_snapshot(session=SessionStats(active=["tokyo", "london"]))

    assert gate.should_ask(snapshot, 100) is True


def test_an_empty_allowlist_allows_every_session(config: AppConfig) -> None:
    gate = _gate(config, allowed_sessions=[])
    snapshot = _passing_snapshot(session=SessionStats(active=["tokyo"]))

    assert gate.should_ask(snapshot, 100) is True


def test_the_summary_stays_quiet_about_filters_nobody_enabled(config: AppConfig) -> None:
    """A line of permanent zeroes reads as a filter that never fires."""
    gate = _gate(config)
    gate.should_ask(_passing_snapshot(), 100)

    assert "news blackout" not in gate.stats.summary()
    assert "wrong session" not in gate.stats.summary()
