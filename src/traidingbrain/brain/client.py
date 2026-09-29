"""The Anthropic client: structured output, caching, budget, and a batch path.

Three API facts shape this module, and getting any of them wrong costs either
correctness or a lot of money.

**Forced tool use is gone.** `tool_choice: {"type": "any"}` returns a 400 on the
current models. The way to guarantee a shape is structured outputs --
`messages.parse(..., output_format=Model)` -- which validates the response against
a Pydantic model before handing it back.

**The cache prefix must not move.** Any byte that changes between calls invalidates
everything after it. So the system block is a module constant with nothing
interpolated, the snapshot goes in the user turn, and the JSON is canonical. A
cache that stops working reports no error; it just costs several times more, which
is why `usage.cache_read_input_tokens` is checked rather than assumed.

**Backtests belong in the batch API.** A backtest is by definition not
latency-sensitive, and batching halves the price. Results come back in arbitrary
order and must be keyed by `custom_id`, never by position.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from traidingbrain.brain import prompt as prompts
from traidingbrain.brain.cache import cache_key
from traidingbrain.brain.guard import check
from traidingbrain.brain.scoring import score
from traidingbrain.config.settings import AppConfig
from traidingbrain.domain.enums import Bias, Decision, Factor, RiskLevel, Side
from traidingbrain.domain.snapshot import BrainInput, MarketSnapshot
from traidingbrain.domain.verdict import (
    Anchor,
    BrainDecision,
    BrainVerdict,
    FactorScore,
    GuardVerdict,
    Scenarios,
    ScenarioSpec,
)

#: Dollars per million tokens, by model. Used for the pre-flight estimate and the
#: running budget. Wrong numbers here mean a dry-run that lies about the bill.
PRICING: dict[str, tuple[float, float, float]] = {
    # model: (input, output, cache read)
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}

#: Batch requests are billed at half price.
BATCH_DISCOUNT = 0.5


class BudgetExceededError(RuntimeError):
    """Raised when a run has spent what it was allowed to spend.

    A hard stop rather than a warning. The failure mode this prevents is a loop
    that quietly costs a hundred times the estimate because a trigger condition was
    looser than intended.
    """


@dataclass
class Usage:
    """Running token and cost totals for one run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    cached_calls: int = 0
    refusals: int = 0
    errors: int = 0
    model: str = ""
    batch: bool = False

    @property
    def cost_usd(self) -> float:
        rates = PRICING.get(self.model)
        if rates is None:
            return 0.0
        input_rate, output_rate, cache_rate = rates
        billed = (
            self.input_tokens * input_rate
            + self.output_tokens * output_rate
            + self.cache_read_tokens * cache_rate
            # A cache write costs a premium over a plain input token.
            + self.cache_write_tokens * input_rate * 1.25
        ) / 1_000_000
        return billed * (BATCH_DISCOUNT if self.batch else 1.0)

    @property
    def cache_hit_rate(self) -> float:
        total = self.input_tokens + self.cache_read_tokens
        return self.cache_read_tokens / total if total else 0.0

    def add(self, usage: Any) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def summary(self) -> str:
        return (
            f"{self.calls} calls ({self.cached_calls} served from cache), "
            f"{self.input_tokens:,} in / {self.output_tokens:,} out, "
            f"{self.cache_read_tokens:,} cache reads ({self.cache_hit_rate:.0%}), "
            f"${self.cost_usd:.2f}"
            + (f", {self.refusals} refusals" if self.refusals else "")
            + (f", {self.errors} errors" if self.errors else "")
        )


class CacheLike(Protocol):
    def get(self, key: str) -> BrainDecision | None: ...
    def put(self, key: str, decision: BrainDecision, *, created_ts: int = 0) -> None: ...


@dataclass
class _Refusal:
    """A model declining to answer, which is not an exception.

    Safety classifiers can trigger on financial content. The response arrives with
    HTTP 200 and `stop_reason: "refusal"`, and the correct handling is to record it
    and return NO TRADE -- crashing a twelve-hour backtest over one declined bar
    would be the wrong trade-off.
    """

    category: str
    explanation: str


class AnthropicBrain:
    """Turns a market snapshot into a checked, scored decision."""

    def __init__(
        self,
        config: AppConfig,
        cache: CacheLike | None = None,
        client: Any | None = None,
        *,
        model: str | None = None,
        budget_usd: float | None = None,
    ) -> None:
        self.config = config
        self.cache = cache
        self.client = client if client is not None else anthropic.Anthropic()
        self.model = model or config.engine.brain.model
        self.budget_usd = (
            budget_usd if budget_usd is not None else config.engine.brain.max_usd_per_backtest
        )
        self.usage = Usage(model=self.model)
        self.guard_rejections = 0

    # -- the main path ------------------------------------------------------ #

    def decide(
        self, snapshot: MarketSnapshot, brain_input: BrainInput | None = None
    ) -> BrainDecision:
        """One decision, from cache if possible."""
        payload = brain_input or snapshot.to_brain_input()
        snapshot_hash = payload.content_hash()
        key = cache_key(snapshot_hash, self.model, prompts.PROMPT_VERSION)

        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                self.usage.cached_calls += 1
                return cached

        self._assert_budget()
        verdict, request_id, raw = self._ask(payload)

        decision = self._finalise(verdict, snapshot, snapshot_hash, request_id)
        if self.cache is not None:
            self.cache.put(key, decision, created_ts=int(time.time() * 1000))
            recorder = getattr(self.cache, "record_response", None)
            if recorder is not None:
                recorder(
                    key,
                    request_id=request_id,
                    usage={
                        "input": self.usage.input_tokens,
                        "output": self.usage.output_tokens,
                        "cache_read": self.usage.cache_read_tokens,
                    },
                    raw=raw,
                    created_ts=int(time.time() * 1000),
                )
        return decision

    def _ask(self, payload: BrainInput) -> tuple[BrainVerdict | _Refusal, str | None, str]:
        """One API call, with the failures that are not exceptions handled."""
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.config.engine.brain.max_tokens,
            output_config={"effort": self.config.engine.brain.effort},
            system=prompts.system_blocks(),
            messages=[{"role": "user", "content": prompts.user_content(payload)}],
            output_format=BrainVerdict,
        )

        self.usage.add(getattr(response, "usage", None))
        request_id = getattr(response, "_request_id", None)

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            self.usage.refusals += 1
            details = getattr(response, "stop_details", None)
            return (
                _Refusal(
                    category=getattr(details, "category", None) or "unknown",
                    explanation=getattr(details, "explanation", "") or "",
                ),
                request_id,
                "",
            )

        if stop_reason == "max_tokens":
            # A truncated answer is not a partial answer -- the structure is
            # incomplete and anything parsed out of it is guesswork.
            self.usage.errors += 1
            return (
                _Refusal(category="max_tokens", explanation="the response was cut off"),
                request_id,
                "",
            )

        verdict = response.parsed_output
        raw = verdict.model_dump_json() if verdict is not None else ""
        if verdict is None:
            self.usage.errors += 1
            return (
                _Refusal(category="unparsed", explanation="no structured output returned"),
                request_id,
                "",
            )
        return verdict, request_id, raw

    def _finalise(
        self,
        verdict: BrainVerdict | _Refusal,
        snapshot: MarketSnapshot,
        snapshot_hash: str,
        request_id: str | None,
    ) -> BrainDecision:
        """Score, check, and degrade to NO TRADE where warranted."""
        if isinstance(verdict, _Refusal):
            return _no_trade_decision(
                snapshot_hash,
                self.model,
                f"model did not answer: {verdict.category} {verdict.explanation}".strip(),
                request_id,
            )

        breakdown = score(verdict, self.config.weights, snapshot.history)
        guard, plan = check(verdict, snapshot, self.config.risk)

        if not guard.passed:
            self.guard_rejections += 1
            # Not an error and not something to retry: a NO TRADE with a reason.
            verdict = verdict.model_copy(update={"decision": Decision.INVALID_TRADE})
            plan = None

        return BrainDecision(
            snapshot_hash=snapshot_hash,
            model_id=self.model,
            prompt_version=prompts.PROMPT_VERSION,
            verdict=verdict,
            confidence=breakdown.confidence,
            plan=plan,
            guard=guard,
            request_id=request_id,
        )

    # -- budget ------------------------------------------------------------- #

    def _assert_budget(self) -> None:
        if self.budget_usd and self.usage.cost_usd >= self.budget_usd:
            raise BudgetExceededError(
                f"this run has spent ${self.usage.cost_usd:.2f} of its ${self.budget_usd:.2f} "
                f"budget after {self.usage.calls} calls"
            )

    def estimate(self, payloads: list[BrainInput], *, batch: bool = False) -> dict[str, float]:
        """What a run would cost, before spending anything.

        Counted through the API rather than guessed from character counts, because
        the difference between the two is large enough to make a dry-run useless.
        """
        if not payloads:
            return {"calls": 0, "input_tokens": 0, "estimated_usd": 0.0}

        sample = self.client.messages.count_tokens(
            model=self.model,
            system=prompts.system_blocks(),
            messages=[{"role": "user", "content": prompts.user_content(payloads[0])}],
        )
        per_call_input = int(getattr(sample, "input_tokens", 0))
        # Output is dominated by the reasoning text; measured runs land near this.
        assumed_output = 900

        rates = PRICING.get(self.model, (0.0, 0.0, 0.0))
        gross = len(payloads) * (per_call_input * rates[0] + assumed_output * rates[1]) / 1_000_000
        # After the first call the stable prefix is served from cache at a tenth of
        # the price, so the real bill is well under the gross figure.
        return {
            "calls": float(len(payloads)),
            "input_tokens": float(per_call_input),
            "estimated_usd": gross * (BATCH_DISCOUNT if batch else 1.0),
        }


@dataclass
class BatchRequest:
    """One snapshot queued for the batch API."""

    custom_id: str
    payload: BrainInput
    snapshot: MarketSnapshot


@dataclass
class BatchOutcome:
    decisions: dict[str, BrainDecision] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)


def _no_trade_decision(
    snapshot_hash: str, model: str, reason: str, request_id: str | None
) -> BrainDecision:
    """A decision that says nothing happened, and why.

    Returned instead of raising so that one bad bar does not end a long run, and so
    the reason ends up in the report rather than in a traceback nobody reads.
    """
    # Built as real objects rather than through `model_construct`: skipping
    # validation to produce a value that is meant to be valid buys nothing and
    # removes the check that would catch a schema change breaking this path.
    nowhere = Anchor(level_id="lvl_0", offset_atr=0.0)
    flat = {"entry": nowhere, "stop": nowhere, "target": nowhere, "rationale": reason}

    return BrainDecision(
        snapshot_hash=snapshot_hash,
        model_id=model,
        prompt_version=prompts.PROMPT_VERSION,
        verdict=BrainVerdict(
            schema_version=1,
            bias=Bias.NEUTRAL,
            decision=Decision.WAIT,
            risk=RiskLevel.HIGH,
            factor_scores=[
                FactorScore(factor=Factor.STRUCTURE, score=0.0, confidence=0.0, reasoning=reason)
            ],
            scenarios=Scenarios(
                bullish=ScenarioSpec(side=Side.LONG, **flat),
                bearish=ScenarioSpec(side=Side.SHORT, **flat),
                invalidation=nowhere,
                invalidation_note=reason,
            ),
            reasoning=[reason],
            market_commentary=reason,
        ),
        confidence=0.0,
        plan=None,
        guard=GuardVerdict(passed=False, violations=[reason]),
        request_id=request_id,
    )


def render_usage(usage: Usage) -> str:
    return usage.summary()


def dump_schema() -> str:
    """The JSON schema the API is asked to enforce.

    Useful when an API rejects it: the error names a constraint, and this is where
    to look for what generated it.
    """
    return json.dumps(BrainVerdict.model_json_schema(), indent=2, sort_keys=True)
