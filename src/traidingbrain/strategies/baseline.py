"""Two strategies that exist to be beaten.

Neither of these is meant to be traded. They are the yardsticks, and without them
the question "does the model add anything?" has no answer -- a backtest of the
model alone produces a number with nothing to compare it to, and any number looks
like something.

`RandomEntry` is the null hypothesis. Same risk management, same stops and targets,
entry direction decided by a coin. A surprising number of published strategies do
not beat it, because most of what looks like edge is actually the risk management.

`StructureBaseline` is the rules-only version of the setup the model is being asked
to judge: trade with the higher-timeframe trend after structure breaks and
liquidity is taken. If the model cannot beat this, it is an expensive way to
reproduce four `if` statements.
"""

from __future__ import annotations

import numpy as np

from traidingbrain.domain.enums import Bias, LevelKind, RegimeKind, Side, Timeframe
from traidingbrain.domain.snapshot import MarketSnapshot, TimeframeView
from traidingbrain.sim.engine import TradeIntent

#: Stop distance, in ATR, placed beyond the anchoring level. Wide enough that
#: ordinary noise does not reach it, tight enough that the position is meaningful.
STOP_PADDING_ATR = 0.35

#: Target as a multiple of the stop distance. Fixed rather than chosen per trade,
#: so that what is being compared between strategies is entry selection and not
#: two different exit policies.
TARGET_R = 2.0

#: Entry offset from the current price, in ATR. Both strategies wait for a small
#: pullback rather than buying the close -- and the unfilled ones are counted,
#: which is the honest version of "wait for a better price".
ENTRY_PULLBACK_ATR = 0.25

#: A coin lands heads half the time.
COIN = 0.5

#: Minimum strength before an indicator counts as agreeing. Below this it is
#: leaning, and a lean is not confluence.
MIN_AGREEING_STRENGTH = 0.3

#: Agreeing indicators needed for the indicator factor to count once.
MIN_AGREEING_INDICATORS = 2


def _frame(snapshot: MarketSnapshot, timeframe: Timeframe) -> TimeframeView | None:
    return next((view for view in snapshot.frames if view.timeframe is timeframe), None)


def _nearest_level(snapshot: MarketSnapshot, kinds: set[LevelKind], *, below: bool) -> float | None:
    """Closest level of a given kind on one side of price."""
    candidates = [
        level
        for level in snapshot.levels
        if level.kind in kinds and ((level.price < snapshot.price) == below)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda level: abs(level.price - snapshot.price)).price


def _build_intent(
    snapshot: MarketSnapshot, side: Side, confidence: float, reason: str
) -> TradeIntent | None:
    """Turn a direction into a complete plan, anchored to real structure.

    The stop goes beyond the nearest swing on the losing side, because that is
    where the idea is actually wrong. A fixed-percentage stop placed without
    reference to structure gets taken out by noise and reports it as a loss of
    edge.
    """
    atr = snapshot.atr
    price = snapshot.price

    if side is Side.LONG:
        entry = price - ENTRY_PULLBACK_ATR * atr
        anchor = _nearest_level(snapshot, {LevelKind.SWING_LOW, LevelKind.EQUAL_LOWS}, below=True)
        stop = (anchor if anchor is not None else price - 1.2 * atr) - STOP_PADDING_ATR * atr
        if stop >= entry:
            return None
        target = entry + TARGET_R * (entry - stop)
    else:
        entry = price + ENTRY_PULLBACK_ATR * atr
        anchor = _nearest_level(
            snapshot, {LevelKind.SWING_HIGH, LevelKind.EQUAL_HIGHS}, below=False
        )
        stop = (anchor if anchor is not None else price + 1.2 * atr) + STOP_PADDING_ATR * atr
        if stop <= entry:
            return None
        target = entry - TARGET_R * (stop - entry)

    intent = TradeIntent(
        side=side, entry=entry, stop=stop, target=target, confidence=confidence, reason=reason
    )
    return intent if intent.is_coherent else None


class RandomEntry:
    """A coin flip with professional risk management.

    The honest null hypothesis. If a strategy cannot beat this, whatever edge it
    appears to have belongs to the stop placement and the position sizing, not to
    its signal.
    """

    name = "random"

    def __init__(self, seed: int = 11, trade_probability: float = 0.03) -> None:
        self._rng = np.random.default_rng(seed)
        self.trade_probability = trade_probability

    def propose(self, snapshot: MarketSnapshot) -> TradeIntent | None:
        if self._rng.random() > self.trade_probability:
            return None
        side = Side.LONG if self._rng.random() < COIN else Side.SHORT
        # A fixed confidence in the middle of the scale: the point is that entry
        # direction is random, not that sizing is.
        return _build_intent(snapshot, side, confidence=75.0, reason="coin flip")


class StructureBaseline:
    """Rules only: higher-timeframe trend, a recent break, liquidity taken.

    This is the setup the model is being asked to read, reduced to conditions that
    can be checked with `if`. It is the number that matters -- beating a coin flip
    is table stakes, beating this is the actual claim.
    """

    name = "baseline"

    def __init__(self, min_confluence: int = 2) -> None:
        self.min_confluence = min_confluence

    def propose(self, snapshot: MarketSnapshot) -> TradeIntent | None:
        higher = _frame(snapshot, Timeframe.H4)
        signal = _frame(snapshot, Timeframe.H1)
        if higher is None or signal is None:
            return None

        # Direction comes from the higher frame. Taking it from the signal frame
        # means trading every pullback against the prevailing move.
        if higher.trend is Bias.BULLISH and higher.regime is RegimeKind.TREND_UP:
            side = Side.LONG
        elif higher.trend is Bias.BEARISH and higher.regime is RegimeKind.TREND_DOWN:
            side = Side.SHORT
        else:
            return None

        confluence = 0
        reasons: list[str] = [f"H4 {higher.regime.value}"]

        if signal.structure.bos:
            confluence += 1
            reasons.append("H1 break of structure")

        # A sweep against our direction is the one that helps: liquidity taken
        # below, then reclaimed, is fuel for a move up.
        liquidity = signal.liquidity
        wanted_sweep = liquidity.sweep_down if side is Side.LONG else liquidity.sweep_up
        if wanted_sweep:
            confluence += 1
            reasons.append("liquidity taken on the other side")

        agreeing = sum(
            1
            for reading in signal.indicators
            if reading.bias is (Bias.BULLISH if side is Side.LONG else Bias.BEARISH)
            and reading.strength >= MIN_AGREEING_STRENGTH
        )
        if agreeing >= MIN_AGREEING_INDICATORS:
            confluence += 1
            reasons.append(f"{agreeing} indicators agree")

        if confluence < self.min_confluence:
            return None

        # Confidence is a function of how much agreed, mapped onto the same scale
        # the model will use, so both are sized by the same rules.
        confidence = 60.0 + 10.0 * confluence
        return _build_intent(snapshot, side, confidence, ", ".join(reasons))
