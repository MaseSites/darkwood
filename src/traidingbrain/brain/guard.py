"""The last thing between a model answer and real money.

The level-id design already makes a hallucinated price impossible to express -- the
model names a level it was shown and an offset, and Python resolves it. This module
is the layer behind that: defence in depth for everything the schema cannot rule
out.

The checks are not about catching a model behaving badly. They are about the
ordinary case where an answer is internally reasonable and still unusable: a stop
placed a fraction of an ATR away that noise will take out within the hour, a
reward-to-risk that cannot pay for the losing trades, a bias that contradicts the
scenario it points at.

A failed check is not an error and not something to retry. It is a NO TRADE with a
recorded reason, and the rejection rate is itself a metric: a prompt whose answers
keep failing here is a prompt that needs fixing, not a guard that needs loosening.
"""

from __future__ import annotations

from traidingbrain.config.settings import RiskConfig
from traidingbrain.domain.enums import Bias, Decision, Side
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.domain.verdict import (
    Anchor,
    BrainVerdict,
    GuardVerdict,
    ResolvedPlan,
    ScenarioSpec,
)

#: Closest a stop may sit to the entry, in ATR.
#:
#: Below this the stop is inside the ordinary noise of a single bar. It would be
#: hit almost immediately, and because position size is risk divided by stop
#: distance, it would also produce an enormous position -- the two failures
#: compound.
MIN_STOP_DISTANCE_ATR = 0.25

#: Furthest a stop may sit. Beyond this the trade is a directional bet with a
#: nominal stop attached, and the liquidation check will refuse it anyway.
MAX_STOP_DISTANCE_ATR = 8.0

#: How far outside the level ladder a resolved price may land. The ladder spans
#: roughly five ATR, and an offset is capped at ten, so anything past this is a
#: sign the anchor and the offset disagree about what they are describing.
MAX_PRICE_DISTANCE_ATR = 12.0


def resolve(anchor: Anchor, snapshot: MarketSnapshot) -> float | None:
    return snapshot.resolve(anchor.level_id, anchor.offset_atr)


def resolve_plan(scenario: ScenarioSpec, snapshot: MarketSnapshot) -> ResolvedPlan | None:
    """Turn a scenario into prices, or nothing if any anchor is unknown."""
    entry = resolve(scenario.entry, snapshot)
    stop = resolve(scenario.stop, snapshot)
    target = resolve(scenario.target, snapshot)
    if entry is None or stop is None or target is None:
        return None
    if entry <= 0 or stop <= 0 or target <= 0:
        return None
    return ResolvedPlan(side=scenario.side, entry=entry, stop=stop, target=target)


def check(
    verdict: BrainVerdict,
    snapshot: MarketSnapshot,
    risk: RiskConfig,
) -> tuple[GuardVerdict, ResolvedPlan | None]:
    """Validate a verdict against the market it was made about.

    Returns the verdict of the guard and the resolved plan when there is one. A
    verdict with `decision != VALID TRADE` still gets its anchors checked, because
    an answer that cannot even name real levels is worth knowing about whatever it
    concluded.
    """
    violations: list[str] = []

    for label, anchor in _all_anchors(verdict):
        if snapshot.level_by_id(anchor.level_id) is None:
            violations.append(f"{label} points at {anchor.level_id}, which is not in the ladder")

    scenario = verdict.active_scenario
    if scenario is None:
        if verdict.decision is Decision.VALID_TRADE:
            violations.append(
                f"decision is VALID TRADE but bias is {verdict.bias.value}, so no scenario "
                f"is being argued for"
            )
        return GuardVerdict(passed=not violations, violations=violations), None

    plan = resolve_plan(scenario, snapshot)
    if plan is None:
        violations.append("the chosen scenario anchors to a level that does not exist")
        return GuardVerdict(passed=False, violations=violations), None

    violations.extend(_check_geometry(plan, snapshot))
    violations.extend(_check_distances(plan, snapshot))
    violations.extend(_check_reward(plan, risk))
    violations.extend(_check_direction(verdict, plan))

    return GuardVerdict(passed=not violations, violations=violations), plan


def _all_anchors(verdict: BrainVerdict) -> list[tuple[str, Anchor]]:
    scenarios = verdict.scenarios
    return [
        ("bullish entry", scenarios.bullish.entry),
        ("bullish stop", scenarios.bullish.stop),
        ("bullish target", scenarios.bullish.target),
        ("bearish entry", scenarios.bearish.entry),
        ("bearish stop", scenarios.bearish.stop),
        ("bearish target", scenarios.bearish.target),
        ("invalidation", scenarios.invalidation),
    ]


def _check_geometry(plan: ResolvedPlan, snapshot: MarketSnapshot) -> list[str]:
    """Stop below entry below target for a long, and the mirror for a short."""
    if plan.side is Side.LONG:
        if not plan.stop < plan.entry:
            return [f"long stop {plan.stop:,.2f} is not below the entry {plan.entry:,.2f}"]
        if not plan.entry < plan.target:
            return [f"long target {plan.target:,.2f} is not above the entry {plan.entry:,.2f}"]
    else:
        if not plan.stop > plan.entry:
            return [f"short stop {plan.stop:,.2f} is not above the entry {plan.entry:,.2f}"]
        if not plan.entry > plan.target:
            return [f"short target {plan.target:,.2f} is not below the entry {plan.entry:,.2f}"]
    return []


def _check_distances(plan: ResolvedPlan, snapshot: MarketSnapshot) -> list[str]:
    atr = snapshot.atr
    found: list[str] = []

    stop_atr = plan.stop_distance / atr
    if stop_atr < MIN_STOP_DISTANCE_ATR:
        found.append(
            f"the stop is {stop_atr:.2f} ATR from the entry, inside a single bar of noise "
            f"(minimum {MIN_STOP_DISTANCE_ATR})"
        )
    if stop_atr > MAX_STOP_DISTANCE_ATR:
        found.append(
            f"the stop is {stop_atr:.2f} ATR away, which is a directional bet rather than "
            f"a stop (maximum {MAX_STOP_DISTANCE_ATR})"
        )

    for label, price in (("entry", plan.entry), ("stop", plan.stop), ("target", plan.target)):
        distance = abs(price - snapshot.price) / atr
        if distance > MAX_PRICE_DISTANCE_ATR:
            found.append(
                f"the {label} resolves {distance:.1f} ATR from the current price, far outside "
                f"the level ladder"
            )
    return found


def _check_reward(plan: ResolvedPlan, risk: RiskConfig) -> list[str]:
    """Reward-to-risk, computed here and never taken from the model."""
    minimum = risk.limits.min_reward_risk
    if plan.reward_risk < minimum:
        return [
            f"reward-to-risk is {plan.reward_risk:.2f}, below the {minimum:.2f} needed to pay "
            f"for the losing trades"
        ]
    return []


def _check_direction(verdict: BrainVerdict, plan: ResolvedPlan) -> list[str]:
    expected = Side.LONG if verdict.bias is Bias.BULLISH else Side.SHORT
    if plan.side is not expected:
        return [f"bias is {verdict.bias.value} but the chosen scenario is a {plan.side.value}"]
    return []
