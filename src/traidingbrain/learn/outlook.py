"""How good would it be to buy or sell *right now* -- asked at every bar.

Severin asked for this after an ADA reading misled him: the dashboard showed
"85/100, deutlich, Richtung aufwaerts" while ADA ran +10.84% and the system
took nothing. The 85 was not wrong, it was answering a different question.
`score/rating.py` blends clarity, agreement, consensus and coverage -- how much
the evidence agrees with itself. Nothing in it was ever trained against what
happened next, so it describes the present and is silent about the future, and
a number that looks like a buy signal and is not one is worse than no number.

So this module predicts the thing the question is actually about: **the price
move over the next 5-10 hours, net of the round trip.** Two properties follow
from the identity measured on 05.10.2026 --

    net_r = (move_fraction - fee_fraction - funding) / stop_fraction

-- where every term in the numerator is a fraction of the entry price and the
stop appears only in the denominator. So the sign of a trade's outcome does not
depend on the stop, the size or the leverage at all, and the only question worth
a model is whether the coming move beats the toll. That makes the target scalar
and direction-free: predict the signed move, and

* the direction is its sign -- a short earns `-move` and pays the same fee,
* worth trading at all only when `abs(move) > fee`.

**Why it is asked at every bar, not when a setup fires.** The signal ledger
cannot answer this. It only holds bars where the broker was flat: while a
position or even a resting entry occupies the single slot, the strategy is
never consulted and no row is written (`Action.OCCUPIED` exists in the enum and
has zero rows in the database). For BTC about 22,900 of 34,165 hours lie in the
shadow of a taken signal -- two thirds of four years the ledger is silent
about. A per-bar score needs no slot, no position and no capital, so it is the
first instrument here that can see that time.

**What this module deliberately does not do.** It does not map anything to
1-100. That mapping belongs with the measurement that earns it, in
`scripts/study_outlook.py`, and only if the thing survives a permutation null.
Shipping the number first is how the 85 happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from traidingbrain.analysis.pipeline import MultiFrameAnalysis, decision_time_ms
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe

if TYPE_CHECKING:
    import pandas as pd

HOUR_MS = 3_600_000

#: The horizon Severin asked for, in hours: "in 5-10h plus machen".
#:
#: Both ends are kept. The near end is the question as asked; the far end says
#: whether the answer is a property of the market or of one horizon choice. A
#: predictor that works at 5h and not at 10h has found something about 5h.
HORIZONS_H: tuple[int, ...] = (5, 10)

#: Round trip as a fraction of price: taker in, maker out, from DEFAULT_SPEC.
#: Subtracted from the target so the model predicts profit rather than motion.
ROUND_TRIP = 0.00055 + 0.0002

#: Bias as a number, so a one-hot is not needed for an ordered thing.
_LEAN = {Bias.BULLISH: 1.0, Bias.NEUTRAL: 0.0, Bias.BEARISH: -1.0}

#: Regimes are not ordered, so these stay one-hot.
#:
#: UNKNOWN is deliberately absent: it is the all-zeros case, which says "none
#: of these" rather than inventing a fifth state. The two trend directions are
#: kept apart because the target is signed -- collapsing them to one "trending"
#: flag would throw away exactly the half of the information that decides
#: whether to buy or to sell.
_REGIMES = (
    RegimeKind.TREND_UP,
    RegimeKind.TREND_DOWN,
    RegimeKind.RANGE,
    RegimeKind.MANIPULATION,
)

#: Stand-in for "no break recorded yet". A bar count of None cannot go into a
#: matrix, and zero would mean "a break just happened", which is its opposite.
NEVER = 999.0


def horizon_bars(hours: int, timeframe: Timeframe) -> int:
    """How many bars of `timeframe` cover `hours`. M15: 5h -> 20, 10h -> 40."""
    return max(1, round(hours * HOUR_MS / timeframe_ms(timeframe)))


@dataclass(frozen=True)
class OutlookCase:
    """One bar, its features, and what the next 5-10 hours actually did.

    Shaped to satisfy `learn.evaluate.Scorable` so the walk-forward, purging,
    embargo and permutation machinery applies unchanged.
    """

    opened_ts: int
    closed_ts: int
    target: float
    features: tuple[float, ...]
    move: float
    symbol: str = ""

    @property
    def taken(self) -> bool:
        """No baseline group exists here, and inventing one would mislead.

        `Scorable` has this because a signal filter must be compared against
        what the rules already take. Every bar is a case here, and the system
        trades on roughly none of them, so there is nothing to compare to; the
        comparison that matters is against the permutation null instead.
        """
        return False


NAMES: tuple[str, ...] = (
    "rsi",
    "percent_b",
    "macd_hist_atr",
    "ema_spread_atr",
    "close_vs_ema_fast_atr",
    "atr_pct",
    "vol_percentile",
    "trend_strength",
    "regime_trend_up",
    "regime_trend_down",
    "regime_range",
    "regime_manipulation",
    "structure_lean",
    "bars_since_bos",
    "bars_since_choch",
    "candle_lean",
    "body_share",
    "upper_wick_share",
    "lower_wick_share",
    "bars_since_sweep",
    "swept_up",
    "swept_down",
    "h1_lean",
    "h4_lean",
    "d1_lean",
    "w1_lean",
    "hour_sin",
    "hour_cos",
)


def features_at(
    analysis: MultiFrameAnalysis, index: int, indices: dict[Timeframe, int]
) -> tuple[float, ...] | None:
    """The state of the market at one bar, using only O(1) reads.

    Every value here is a cached array lookup or a scalar method. The readable
    things this deliberately avoids are the ones that copy a list per call --
    `swings_known_at`, `ZoneTimeline.known_at`, `unmitigated_at` and the whole
    `TrendlineTimeline` -- because each is O(number found so far) and so
    quadratic over a full pass of 175,535 bars.

    Three traps from the same reading, each avoided here rather than noted:

    * `StructureState.bos` and `.choch` are windowed at 20 bars, so they throw
      away how long ago a break was. The unbounded counters are used instead.
    * `LiquidityState.sweep_up` is the latched *direction* of the most recent
      sweep, gated by `sweep_lookback_bars`, not "a sweep happened on this
      bar". Both the gated flags and the ungated age are included, since they
      say different things.
    * `CandleTimeline.bias_at` collapses disagreement to NEUTRAL, which makes
      "no pattern" and "two opposite patterns" the same number. The wick and
      body shares below carry what that discards.
    """
    signal = analysis.signal
    if not signal.is_ready(index):
        return None

    atr = signal.atr_at(index)
    close = signal.close_at(index)
    if not (np.isfinite(atr) and atr > 0 and np.isfinite(close) and close > 0):
        return None

    ind = signal.indicators
    regime = signal.regime.state_at(index)
    structure = signal.structure.state_at(index)
    liquidity = signal.liquidity.state_at(index)
    bars = signal.candles.bars

    span = float(bars.span[index])
    body = float(bars.body[index])
    upper = float(bars.upper_wick[index])
    lower = float(bars.lower_wick[index])
    # A doji has span 0 and no shares at all; dividing would give inf.
    shares = (body / span, upper / span, lower / span) if span > 0 else (0.0, 0.0, 0.0)

    ema_fast = ind.at("ema_fast", index)
    ema_slow = ind.at("ema_slow", index)

    # Computed from the bands rather than through Bollinger.percent_b_at: that
    # method lives on the Bollinger object, not on IndicatorSet, and the bands
    # are already named series here. A flat band would divide by zero, and the
    # honest value then is the middle.
    upper_band = ind.at("bb_upper", index)
    lower_band = ind.at("bb_lower", index)
    width = upper_band - lower_band
    percent_b = (close - lower_band) / width if width > 0 else 0.5

    since_bos = NEVER if structure.bars_since_bos is None else min(structure.bars_since_bos, NEVER)
    since_choch = (
        NEVER if structure.bars_since_choch is None else min(structure.bars_since_choch, NEVER)
    )
    since_sweep = (
        NEVER if liquidity.bars_since_sweep is None else min(liquidity.bars_since_sweep, NEVER)
    )
    higher = (Timeframe.H1, Timeframe.H4, Timeframe.D1, Timeframe.W1)

    # Hour of the decision, not of the bar open, and from the timestamp rather
    # than any local clock: everything stored here is UTC.
    hour = (decision_time_ms(signal.ts_at(index), analysis.signal_timeframe) // HOUR_MS) % 24
    angle = 2.0 * np.pi * hour / 24.0

    row = (
        ind.at("rsi", index) / 100.0,
        percent_b,
        ind.at("macd_histogram", index) / atr,
        (ema_fast - ema_slow) / atr,
        (close - ema_fast) / atr,
        100.0 * atr / close,
        regime.volatility_percentile,
        regime.trend_strength,
        *(1.0 if regime.kind is kind else 0.0 for kind in _REGIMES),
        _LEAN.get(structure.trend, 0.0),
        float(since_bos),
        float(since_choch),
        _LEAN.get(signal.candles.bias_at(index), 0.0),
        *shares,
        float(since_sweep),
        1.0 if liquidity.sweep_up else 0.0,
        1.0 if liquidity.sweep_down else 0.0,
        *(_frame_lean(analysis, indices, tf) for tf in higher),
        float(np.sin(angle)),
        float(np.cos(angle)),
    )
    return row if all(np.isfinite(value) for value in row) else None


def _frame_lean(
    analysis: MultiFrameAnalysis, indices: dict[Timeframe, int], timeframe: Timeframe
) -> float:
    """Where a higher timeframe stands, in its own ATR units.

    Zero when that timeframe is not loaded, which is honest rather than
    neutral-looking: `aligned_indices` already refuses to return a partial map,
    so an absent frame here means it is not in the context list at all.
    """
    frame = analysis.analyses.get(timeframe)
    index = indices.get(timeframe)
    if frame is None or index is None:
        return 0.0
    atr = frame.atr_at(index)
    if not (np.isfinite(atr) and atr > 0):
        return 0.0
    fast = frame.indicators.at("ema_fast", index)
    slow = frame.indicators.at("ema_slow", index)
    lean = (fast - slow) / atr
    return float(lean) if np.isfinite(lean) else 0.0


@dataclass
class Tally:
    """Why bars were dropped, so a thin result is explainable."""

    seen: int = 0
    not_ready: int = 0
    unaligned: int = 0
    no_features: int = 0
    no_future: int = 0
    kept: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"{self.seen} Kerzen: {self.kept} verwendbar, "
            f"{self.not_ready} nicht aufgewaermt, {self.unaligned} nicht ausgerichtet, "
            f"{self.no_features} ohne Merkmale, {self.no_future} ohne Zukunft"
        )


def build_cases(
    analysis: MultiFrameAnalysis,
    *,
    hours: int,
    symbol: str = "",
    step: int = 1,
    cost: float = ROUND_TRIP,
) -> tuple[list[OutlookCase], Tally]:
    """Every bar that has both a complete picture and a known future.

    `step` thins the pass. The target at neighbouring bars overlaps almost
    entirely at a 5-10 hour horizon, so consecutive cases are near-duplicates:
    they cost time and add no information. Thinning is not a substitute for the
    embargo and the block bootstrap -- those are still required, because
    thinning by anything less than the horizon leaves overlap behind.

    `closed_ts` is the end of the horizon, which is what `Fold.training` purges
    and embargoes against. Setting it to the bar's own time would quietly let a
    training case whose future runs into the validation window stay in.
    """
    signal = analysis.signal
    timeframe = analysis.signal_timeframe
    ahead = horizon_bars(hours, timeframe)
    closes = signal.column("close")
    total = len(signal)

    cases: list[OutlookCase] = []
    tally = Tally()
    for index in range(0, total, step):
        tally.seen += 1
        if index + ahead >= total:
            tally.no_future += 1
            continue
        if not signal.is_ready(index):
            tally.not_ready += 1
            continue
        indices = analysis.aligned_indices(index)
        if indices is None:
            tally.unaligned += 1
            continue
        row = features_at(analysis, index, indices)
        if row is None:
            tally.no_features += 1
            continue

        here = float(closes[index])
        later = float(closes[index + ahead])
        if not (np.isfinite(here) and here > 0 and np.isfinite(later)):
            tally.no_features += 1
            continue

        move = (later - here) / here
        opened = decision_time_ms(signal.ts_at(index), timeframe)
        cases.append(
            OutlookCase(
                opened_ts=opened,
                closed_ts=opened + hours * HOUR_MS,
                # Signed, and the fee taken off the *magnitude*: a short earns
                # the negative of the move and pays the same toll, so what the
                # model has to beat is the toll either way.
                target=float(np.sign(move) * max(0.0, abs(move) - cost)),
                features=row,
                move=move,
                symbol=symbol,
            )
        )
        tally.kept += 1
    return cases, tally


def frame_of(analysis: MultiFrameAnalysis) -> pd.DataFrame:
    """The signal frame, for callers that want the bars behind the cases."""
    return analysis.signal.frame
