"""Post-trade review, and the restraint it needs.

The risk in this part of the system is not that it fails. It is that it always
succeeds: a post-mortem on a losing trade will always find something to blame, and
at a 35% win rate two trades in three are losses. If each one produces a change,
the rules chase noise until nothing is left of them.

So the tests here mostly assert restraint. A loss must be allowed to be blameless.
Suggestions must stay in a queue. And a pattern must not be claimed from a handful
of reviews.
"""

from __future__ import annotations

from pathlib import Path

from tests.factories import make_snapshot
from traidingbrain.brain import prompt as prompts
from traidingbrain.brain.postmortem import (
    MIN_REVIEWS_FOR_A_PATTERN,
    ReviewQueue,
    RuleBasedReviewer,
    StoredReview,
    find_pattern,
    review_prompt,
)
from traidingbrain.domain.enums import ExitReason, Factor, Side, TradeState
from traidingbrain.domain.verdict import PostTradeReview
from traidingbrain.sim.broker import Fill

NOW = 1_700_000_000_000


def flat(blocks: list) -> str:
    """Collapse a prompt to one line, so a hard-wrapped phrase still matches."""
    return " ".join("".join(b["text"] for b in blocks).split())


def fill(r: float, reason: ExitReason = ExitReason.STOP, proposal_id: str = "p1") -> Fill:
    return Fill(
        proposal_id=proposal_id,
        snapshot_hash="h",
        side=Side.LONG,
        state=TradeState.CLOSED_TARGET if r > 0 else TradeState.CLOSED_STOP,
        reason=reason,
        entry_price=42_000.0,
        exit_price=42_000.0 + r * 100,
        qty=0.1,
        leverage=5.0,
        opened_ts=NOW,
        closed_ts=NOW + 3_600_000,
        gross_pnl=r * 100,
        fees=1.0,
        funding=0.0,
        risk_amount=100.0,
    )


def review(**overrides: object) -> PostTradeReview:
    defaults: dict[str, object] = {
        "schema_version": 1,
        "trade_evaluation": "LOSS -1.00R",
        "main_reason": "the stop was reached",
        "failing_factor": None,
        "timing_was_wrong": False,
        "regime_was_misread": False,
        "lesson": "nothing specific",
        "system_update_suggestion": "no change suggested",
    }
    return PostTradeReview.model_validate(defaults | overrides)


def stored(r: float, **overrides: object) -> StoredReview:
    return StoredReview(
        id=1,
        proposal_id="p",
        symbol="BTCUSDT",
        r_multiple=r,
        exit_reason="stop",
        review=review(**overrides),
        created_ts=NOW,
    )


# --------------------------------------------------------------------------- #
# Restraint
# --------------------------------------------------------------------------- #


def test_a_loss_is_allowed_to_be_blameless() -> None:
    """The most common correct answer, and the one a confabulating review never gives.

    At a 35% win rate most losses are a correct process losing money. A reviewer
    that cannot say so will invent a fault every time.
    """
    result = RuleBasedReviewer().review(fill(-1.0), make_snapshot(), bars_held=18)

    assert result.failing_factor is None
    assert result.timing_was_wrong is False
    assert "correct process" in result.lesson


def test_a_quick_loss_is_called_a_timing_problem() -> None:
    result = RuleBasedReviewer().review(fill(-1.0), make_snapshot(), bars_held=1)

    assert result.timing_was_wrong is True
    assert "timing" in result.lesson


def test_a_liquidation_is_called_what_it_is() -> None:
    result = RuleBasedReviewer().review(
        fill(-1.0, ExitReason.LIQUIDATION), make_snapshot(), bars_held=5
    )

    assert "LIQUIDATED" in result.trade_evaluation
    assert "leverage" in result.lesson


def test_a_win_suggests_nothing() -> None:
    result = RuleBasedReviewer().review(fill(2.0, ExitReason.TARGET), make_snapshot(), bars_held=9)

    assert "WIN" in result.trade_evaluation
    assert result.system_update_suggestion == "no change suggested"


# --------------------------------------------------------------------------- #
# Suggestions stay in a queue
# --------------------------------------------------------------------------- #


def test_a_suggestion_lands_in_the_queue_and_nowhere_else(tmp_path: Path) -> None:
    """A system that rewrites its own trading rules from its own post-mortems is
    exactly what the confirm-before-execute rule exists to prevent."""
    queue = ReviewQueue(tmp_path / "reviews.sqlite")
    queue.add(fill(-1.0), review(system_update_suggestion="widen the entry window"))

    suggestions = queue.open_suggestions()

    assert len(suggestions) == 1
    assert suggestions[0][1] == "widen the entry window"


def test_a_suggestion_is_resolved_by_a_person(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "reviews.sqlite")
    queue.add(fill(-1.0), review())
    suggestion_id = queue.open_suggestions()[0][0]

    queue.resolve_suggestion(suggestion_id, "declined")

    assert queue.open_suggestions() == []


def test_reviews_are_kept(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "reviews.sqlite")
    for i in range(3):
        queue.add(fill(-1.0, proposal_id=f"p{i}"), review())

    assert queue.count() == 3
    assert len(queue.all()) == 3


# --------------------------------------------------------------------------- #
# Patterns, and refusing to see one too early
# --------------------------------------------------------------------------- #


def test_a_handful_of_reviews_establishes_no_pattern() -> None:
    """Individual post-mortems are noise. Three of them are three coin flips."""
    pattern = find_pattern([stored(-1.0) for _ in range(4)])

    assert not pattern.has_enough
    assert "too few" in pattern.report()


def test_an_aggregate_reports_how_often_nothing_was_wrong() -> None:
    reviews = [stored(-1.0) for _ in range(20)] + [stored(2.0) for _ in range(10)]

    pattern = find_pattern(reviews)

    assert pattern.has_enough
    assert pattern.losses == 20
    assert pattern.nothing_was_wrong == 20
    assert "expected outcome" in pattern.report()


def test_a_review_that_always_finds_a_fault_is_flagged() -> None:
    """The failure mode this module is built around, made visible rather than acted on."""
    reviews = [
        stored(-1.0, failing_factor=Factor.INDICATORS, timing_was_wrong=True) for _ in range(30)
    ]

    report = find_pattern(reviews).report()

    assert "confabulating" in report


def test_blamed_factors_are_counted() -> None:
    reviews = (
        [stored(-1.0, failing_factor=Factor.LIQUIDITY) for _ in range(12)]
        + [stored(-1.0, failing_factor=Factor.STRUCTURE) for _ in range(8)]
        + [stored(-1.0) for _ in range(10)]
    )

    pattern = find_pattern(reviews)

    assert pattern.factor_blamed == {"liquidity": 12, "structure": 8}
    assert "liquidity 12" in pattern.report()


def test_the_pattern_threshold_is_not_trivial() -> None:
    """A guard against the threshold being quietly lowered to make a report read well."""
    assert MIN_REVIEWS_FOR_A_PATTERN >= 25


# --------------------------------------------------------------------------- #
# The prompt
# --------------------------------------------------------------------------- #


def test_the_review_prompt_carries_the_outcome_but_not_the_symbol() -> None:
    """Normalised the same way as the pre-trade one.

    A review that could see which asset and which month it was looking at would be
    partly recalling what happened next rather than reading the state at entry.
    """
    system, user = review_prompt(make_snapshot(), fill(-1.0), bars_held=6)

    assert system, "no system blocks"
    # The result carries fees, so the figure is near -1R rather than exactly it.
    assert "R after 6 bars" in user
    assert "closed by stop" in user
    assert "BTCUSDT" not in user
    assert "42000" not in user.replace(",", "")


def test_the_review_prompt_is_separate_from_the_trading_one() -> None:
    """Two prompts rather than a mode flag: two cache prefixes, two smaller
    schemas, and evaluations that do not interfere."""
    # Whitespace-normalised: the prompt is hard-wrapped, and a phrase that spans
    # a line break should not make the test brittle.
    review_system = flat(prompts.post_trade_system_blocks())
    trade_system = flat(prompts.system_blocks())

    assert review_system != trade_system
    assert "never applied automatically" in review_system
    assert "Nothing was wrong" in review_system


def test_the_review_schema_is_strict() -> None:
    schema = PostTradeReview.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"])


def test_a_review_may_name_no_failing_factor() -> None:
    """The field is required but nullable, so "nothing misled us" is expressible.

    If it were merely optional the model could omit it, and an omission reads as an
    oversight rather than as an answer.
    """
    assert "failing_factor" in PostTradeReview.model_json_schema()["required"]
    assert review(failing_factor=None).failing_factor is None
