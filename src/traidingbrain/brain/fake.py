"""A brain that needs no network.

Two jobs. It lets the whole test suite exercise the decision path -- scoring,
guard, cache, engine -- without a key, without a bill, and without the run
depending on a model's mood. And it gives the backtest a third yardstick: a
strategy shaped exactly like the real one, scoring exactly the same factors, but
deciding by arithmetic.

That third yardstick is the sharpest question in the project. `StructureBaseline`
answers "is the model better than a few rules?" -- but it is a different strategy,
with different entries. `FakeBrain` answers something narrower and more useful: is
the *judgement* worth anything, when everything except the judgement is held
constant?
"""

from __future__ import annotations

from dataclasses import dataclass

from traidingbrain.brain import prompt as prompts
from traidingbrain.brain.guard import check
from traidingbrain.brain.scoring import score
from traidingbrain.config.settings import AppConfig
from traidingbrain.domain.enums import (
    Bias,
    Decision,
    Factor,
    LevelKind,
    RegimeKind,
    RiskLevel,
    Side,
    Timeframe,
)
from traidingbrain.domain.snapshot import MarketSnapshot, TimeframeView
from traidingbrain.domain.verdict import (
    Anchor,
    BrainDecision,
    BrainVerdict,
    FactorScore,
    Scenarios,
    ScenarioSpec,
)

FAKE_MODEL = "fake-brain"

#: Offset beyond the anchoring level where a stop is placed, in ATR.
STOP_PADDING_ATR = 0.4

#: Target as a multiple of the stop distance.
TARGET_R = 2.2

#: Below this weighted agreement the answer is WAIT.
MIN_AGREEMENT = 0.25


def _liquidity_read(signal: TimeframeView, snapshot: MarketSnapshot) -> _Read | None:
    """Sweeps and positioning, scored as one factor.

    Positioning is not a sixth factor. Open interest and the crowd ratio are
    statements about where positions sit, which is what the liquidity factor is
    for -- and the specification fixed five factors with weights that add to one.
    Adding a sixth would silently reweight every other one.

    The two halves are combined rather than averaged: a sweep is an event, and
    positioning is a condition. A sweep with positioning agreeing is a stronger
    read than either alone, and the certainty rises to say so.
    """
    liquidity = signal.liquidity
    sweep = (1.0 if liquidity.sweep_down else 0.0) - (1.0 if liquidity.sweep_up else 0.0)
    positioning = snapshot.positioning

    parts: list[str] = []
    value = 0.0
    certainty = 0.0

    if sweep != 0.0:
        value += sweep * 0.7
        certainty = 0.6
        parts.append("sell-side taken" if sweep > 0 else "buy-side taken")

    if positioning.known and positioning.strength > 0.0:
        direction = {Bias.BULLISH: 1.0, Bias.BEARISH: -1.0, Bias.NEUTRAL: 0.0}[positioning.bias]
        # Scaled by strength, so a reading the data barely supports barely counts.
        value += direction * 0.6 * positioning.strength
        # Agreement between two independent readings is worth more than either;
        # disagreement is worth less than one, which is the honest arithmetic.
        agrees = sweep == 0.0 or (direction * sweep) > 0
        certainty = max(certainty, 0.5) + (0.15 if agrees and sweep != 0.0 else 0.0)
        if not agrees:
            certainty = max(0.2, certainty - 0.25)
        parts.append(positioning.reading.replace("_", " "))

    if not parts:
        return None
    return _Read(
        Factor.LIQUIDITY,
        max(-1.0, min(1.0, value)),
        min(1.0, certainty),
        ", ".join(parts),
    )


def _view(snapshot: MarketSnapshot, timeframe: Timeframe) -> TimeframeView | None:
    return next((v for v in snapshot.frames if v.timeframe is timeframe), None)


def _pick_level(
    snapshot: MarketSnapshot, kinds: set[LevelKind], *, below: bool, fallback_atr: float
) -> str:
    """Nearest level of a kind on one side, or the current price as a last resort."""
    candidates = [
        level
        for level in snapshot.levels
        if level.kind in kinds and ((level.distance_atr < 0) == below)
    ]
    if candidates:
        return min(candidates, key=lambda level: abs(level.distance_atr)).id
    current = next((level for level in snapshot.levels if level.kind is LevelKind.CURRENT), None)
    return current.id if current else snapshot.levels[0].id


@dataclass
class _Read:
    factor: Factor
    score: float
    confidence: float
    reason: str


class FakeBrain:
    """Scores the same five factors as the real prompt, by rule.

    Deterministic, free, and offline. Every answer still goes through the real
    scoring and the real guard, so the surrounding machinery is genuinely
    exercised rather than bypassed.
    """

    name = "fake-brain"

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.calls = 0
        self.guard_rejections = 0
        #: Which question this yardstick stands in for.
        #:
        #: Settable for the same reason as on the real brain: a judging run and
        #: a scanning run are different measurements, and a decision recorded
        #: under the wrong version would be compared against answers to another
        #: question.
        self.prompt_version = prompts.PROMPT_VERSION

    def decide(self, snapshot: MarketSnapshot, brain_input: object | None = None) -> BrainDecision:
        self.calls += 1
        reads = self._read(snapshot)
        bias = self._bias(reads)
        verdict = self._verdict(snapshot, reads, bias)

        breakdown = score(verdict, self.config.weights, snapshot.history)
        guard, plan = check(verdict, snapshot, self.config.risk)
        if not guard.passed:
            self.guard_rejections += 1
            verdict = verdict.model_copy(update={"decision": Decision.INVALID_TRADE})
            plan = None

        return BrainDecision(
            snapshot_hash=snapshot.to_brain_input().content_hash(),
            model_id=FAKE_MODEL,
            prompt_version=self.prompt_version,
            verdict=verdict,
            confidence=breakdown.confidence,
            plan=plan,
            guard=guard,
        )

    # -- the five factors --------------------------------------------------- #

    def _read(self, snapshot: MarketSnapshot) -> list[_Read]:
        higher = _view(snapshot, Timeframe.H4)
        signal = _view(snapshot, snapshot.signal_timeframe)
        reads: list[_Read] = []

        if higher is not None and signal is not None:
            direction = {Bias.BULLISH: 1.0, Bias.BEARISH: -1.0, Bias.NEUTRAL: 0.0}
            # Agreement between the frames is the signal; disagreement halves it,
            # which is the honest reading of two timeframes pointing apart.
            agreement = direction[higher.trend] + direction[signal.trend]
            regime_bonus = {
                RegimeKind.TREND_UP: 0.4,
                RegimeKind.TREND_DOWN: -0.4,
                RegimeKind.RANGE: 0.0,
                RegimeKind.MANIPULATION: 0.0,
                RegimeKind.UNKNOWN: 0.0,
            }[higher.regime]
            value = max(-1.0, min(1.0, agreement / 2.0 + regime_bonus))
            certainty = 0.8 if higher.trend is signal.trend else 0.4
            if signal.structure.bos:
                certainty = min(1.0, certainty + 0.15)
            reads.append(
                _Read(
                    Factor.STRUCTURE,
                    value,
                    certainty,
                    f"H4 {higher.trend.value} / {snapshot.signal_timeframe.value} "
                    f"{signal.trend.value}, regime {higher.regime.value}",
                )
            )

        if signal is not None and signal.indicators:
            direction = {Bias.BULLISH: 1.0, Bias.BEARISH: -1.0, Bias.NEUTRAL: 0.0}
            weighted = sum(
                direction[reading.bias] * reading.strength for reading in signal.indicators
            )
            value = max(-1.0, min(1.0, weighted / max(1, len(signal.indicators))))
            reads.append(
                _Read(
                    Factor.INDICATORS,
                    value,
                    0.5,
                    f"{len(signal.indicators)} readings, net {value:+.2f}",
                )
            )

        if signal is not None:
            read = _liquidity_read(signal, snapshot)
            if read is not None:
                reads.append(read)

        history = snapshot.history
        if history.similar_situations_found > 0 and history.historical_winrate is not None:
            edge = (history.historical_winrate - 0.5) * 2.0
            reads.append(
                _Read(
                    Factor.HISTORY,
                    max(-1.0, min(1.0, edge)),
                    0.6 if history.sample_is_sufficient else 0.2,
                    f"{history.similar_situations_found} similar cases at "
                    f"{history.historical_winrate:.0%}",
                )
            )

        return reads

    def _bias(self, reads: list[_Read]) -> Bias:
        if not reads:
            return Bias.NEUTRAL
        weights = self.config.weights.effective_weights()
        total = sum(weights.get(r.factor, 0.0) for r in reads)
        if total <= 0:
            return Bias.NEUTRAL
        aggregate = sum(weights.get(r.factor, 0.0) * r.score * r.confidence for r in reads) / total
        if aggregate >= MIN_AGREEMENT:
            return Bias.BULLISH
        if aggregate <= -MIN_AGREEMENT:
            return Bias.BEARISH
        return Bias.NEUTRAL

    # -- turning a read into a plan ----------------------------------------- #

    def _verdict(self, snapshot: MarketSnapshot, reads: list[_Read], bias: Bias) -> BrainVerdict:
        long_plan = self._scenario(snapshot, Side.LONG)
        short_plan = self._scenario(snapshot, Side.SHORT)
        invalidation = Anchor(
            level_id=_pick_level(
                snapshot,
                {LevelKind.SWING_LOW, LevelKind.EQUAL_LOWS}
                if bias is Bias.BULLISH
                else {LevelKind.SWING_HIGH, LevelKind.EQUAL_HIGHS},
                below=bias is Bias.BULLISH,
                fallback_atr=1.0,
            ),
            offset_atr=-0.6 if bias is Bias.BULLISH else 0.6,
        )

        decision = Decision.VALID_TRADE if bias is not Bias.NEUTRAL else Decision.WAIT
        risk = RiskLevel.MEDIUM
        if any(v.volatility.value in ("high", "extreme") for v in snapshot.frames):
            risk = RiskLevel.HIGH

        return BrainVerdict(
            schema_version=1,
            bias=bias,
            decision=decision,
            risk=risk,
            factor_scores=[
                FactorScore(
                    factor=read.factor,
                    score=read.score,
                    confidence=read.confidence,
                    reasoning=read.reason,
                )
                for read in reads
            ]
            or [
                FactorScore(
                    factor=Factor.STRUCTURE,
                    score=0.0,
                    confidence=0.0,
                    reasoning="nothing scoreable in this state",
                )
            ],
            scenarios=Scenarios(
                bullish=long_plan,
                bearish=short_plan,
                invalidation=invalidation,
                invalidation_note="acceptance beyond the anchoring level ends the read",
            ),
            reasoning=[read.reason for read in reads] or ["no factor produced a reading"],
            market_commentary=f"weighted read is {bias.value}",
        )

    def _scenario(self, snapshot: MarketSnapshot, side: Side) -> ScenarioSpec:
        """Anchor a plan to structure, the way the prompt asks the real model to."""
        current = next(
            (level for level in snapshot.levels if level.kind is LevelKind.CURRENT),
            snapshot.levels[0],
        )
        if side is Side.LONG:
            stop_id = _pick_level(
                snapshot, {LevelKind.SWING_LOW, LevelKind.EQUAL_LOWS}, below=True, fallback_atr=1.2
            )
            target_id = _pick_level(
                snapshot,
                {LevelKind.SWING_HIGH, LevelKind.EQUAL_HIGHS},
                below=False,
                fallback_atr=2.0,
            )
            stop_offset, target_offset = -STOP_PADDING_ATR, 0.0
        else:
            stop_id = _pick_level(
                snapshot,
                {LevelKind.SWING_HIGH, LevelKind.EQUAL_HIGHS},
                below=False,
                fallback_atr=1.2,
            )
            target_id = _pick_level(
                snapshot, {LevelKind.SWING_LOW, LevelKind.EQUAL_LOWS}, below=True, fallback_atr=2.0
            )
            stop_offset, target_offset = STOP_PADDING_ATR, 0.0

        return ScenarioSpec(
            side=side,
            entry=Anchor(level_id=current.id, offset_atr=-0.2 if side is Side.LONG else 0.2),
            stop=Anchor(level_id=stop_id, offset_atr=stop_offset),
            target=Anchor(level_id=target_id, offset_atr=target_offset),
            rationale=f"{side.value} anchored to the nearest structure either side",
        )
