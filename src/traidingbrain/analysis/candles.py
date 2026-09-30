"""Candlestick patterns, exactly as the guide's sources define them.

Every pattern here comes from `DAYTRADING_MASTER_GUIDE.md` chapter 4 (V03) and
chapter 4.2 (V08). Nothing has been added: if a source names a pattern, it is
here; if it does not, it is not.

**Where the numbers come from, and why that matters.** The videos describe sizes
in words -- a momentum candle is "ungefähr zwei- bis dreimal so groß wie
vorherige Kerzen", a doji has a "sehr kleiner Körper". Code cannot compare
against a word. Every threshold is therefore a named constant with the source's
own phrasing beside it, set at the plain reading of that phrase, and every one
is a knob rather than a magic number buried in a condition. They are the one
place where this module is an interpretation rather than a transcription, so
they are the first place to look when a pattern fires too often or too rarely.

**No lookahead.** Each pattern is decided on the close of its own last bar and
never revised. V03's doji is the one that needs bars after it -- the video waits
for two candles in the new direction -- so the doji is reported where it forms
and its confirmation is a separate reading two bars later. Backdating the
confirmation to the doji would hand the engine two bars it did not have, inside
the signal it would be trading on.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt
import pandas as pd

from traidingbrain.domain.enums import Bias

# --------------------------------------------------------------------------- #
# The thresholds the videos state in words
# --------------------------------------------------------------------------- #

#: V03: a momentum candle is "ungefähr zwei- bis dreimal so groß wie vorherige
#: Kerzen". The lower end of the stated range, because the upper end would
#: discard the candles the video itself draws as examples.
MOMENTUM_BODY_MULTIPLE = 2.0

#: How many preceding candles the momentum comparison averages over. The video
#: says "vorherige Kerzen" without a count; five is a short memory that still
#: survives one outlier.
MOMENTUM_LOOKBACK = 5

#: V03: a doji has a "sehr kleiner Körper" with wicks on both sides. Expressed
#: as body over total range, because that is what "small body" means on a candle
#: whose range varies with volatility.
DOJI_MAX_BODY_FRACTION = 0.10

#: V03: the hammer and shooting star have "einen langen Docht". Taken as the
#: wick being at least twice the body, with little wick on the other side.
WICK_BODY_MULTIPLE = 2.0
OPPOSITE_WICK_MAX_FRACTION = 0.35

#: V03: a marubozu is "eine große Kerze ohne bzw. nahezu ohne Dochte".
MARUBOZU_MAX_WICK_FRACTION = 0.05

#: V03: tweezers need "ähnliche" wick extremes. A tolerance in ATR, so "similar"
#: scales with how much the market is moving.
TWEEZER_TOLERANCE_ATR = 0.10

#: V03: the multiple-wick pattern needs "mindestens drei Kerzen mit Dochten in
#: dieselbe Richtung".
MULTIPLE_WICK_MIN_CANDLES = 3
MULTIPLE_WICK_MIN_FRACTION = 0.40

#: V08's second accepted momentum form: "drei mittelgroße Kerzen in derselben
#: Richtung außerhalb des Niveaus".
BREAKOUT_SEQUENCE_LENGTH = 3

#: V08: a single breakout candle counts when its body lies "mehrheitlich
#: jenseits des Ausbruchsniveaus". Compared with >=, so an exact half passes:
#: a tie here is a coincidence of the last bits of a float, and making the rule
#: turn on it would be precision the source does not have.
BREAKOUT_BODY_BEYOND_FRACTION = 0.5

#: V03: after a doji the video waits for "zwei Kerzen gleicher neuer Richtung".
DOJI_CONFIRMATION_BARS = 2

#: V03 names four dojis and distinguishes them only by which side the wick is
#: on: dragonfly all below, gravestone all above, long-legged long on both. The
#: video gives no proportions, so these are the plain reading of its pictures.
DOJI_DOMINANT_WICK = 0.6
DOJI_QUIET_WICK = 0.2
DOJI_LONG_LEG = 0.3


class CandlePattern(StrEnum):
    """The patterns V03 and V08 name. No others."""

    BULLISH_ENGULFING = "bullish_engulfing"
    BEARISH_ENGULFING = "bearish_engulfing"
    MOMENTUM_UP = "momentum_up"
    MOMENTUM_DOWN = "momentum_down"
    MULTIPLE_WICK_UP = "multiple_wick_up"
    MULTIPLE_WICK_DOWN = "multiple_wick_down"
    DOJI = "doji"
    DOJI_LONG_LEGGED = "doji_long_legged"
    DOJI_DRAGONFLY = "doji_dragonfly"
    DOJI_GRAVESTONE = "doji_gravestone"
    HAMMER = "hammer"
    SHOOTING_STAR = "shooting_star"
    TWEEZER_BOTTOM = "tweezer_bottom"
    TWEEZER_TOP = "tweezer_top"
    MARUBOZU_UP = "marubozu_up"
    MARUBOZU_DOWN = "marubozu_down"
    DOJI_CONFIRMED_UP = "doji_confirmed_up"
    DOJI_CONFIRMED_DOWN = "doji_confirmed_down"


#: Which way each pattern argues, per V03. The dojis are deliberately neutral:
#: the video calls the doji "Unentschlossenheit" and only assigns a direction
#: once two candles have confirmed one, which is its own pattern above.
PATTERN_BIAS: dict[CandlePattern, Bias] = {
    CandlePattern.BULLISH_ENGULFING: Bias.BULLISH,
    CandlePattern.BEARISH_ENGULFING: Bias.BEARISH,
    CandlePattern.MOMENTUM_UP: Bias.BULLISH,
    CandlePattern.MOMENTUM_DOWN: Bias.BEARISH,
    CandlePattern.MULTIPLE_WICK_UP: Bias.BULLISH,
    CandlePattern.MULTIPLE_WICK_DOWN: Bias.BEARISH,
    CandlePattern.DOJI: Bias.NEUTRAL,
    CandlePattern.DOJI_LONG_LEGGED: Bias.NEUTRAL,
    CandlePattern.DOJI_DRAGONFLY: Bias.NEUTRAL,
    CandlePattern.DOJI_GRAVESTONE: Bias.NEUTRAL,
    CandlePattern.HAMMER: Bias.BULLISH,
    CandlePattern.SHOOTING_STAR: Bias.BEARISH,
    CandlePattern.TWEEZER_BOTTOM: Bias.BULLISH,
    CandlePattern.TWEEZER_TOP: Bias.BEARISH,
    CandlePattern.MARUBOZU_UP: Bias.BULLISH,
    CandlePattern.MARUBOZU_DOWN: Bias.BEARISH,
    CandlePattern.DOJI_CONFIRMED_UP: Bias.BULLISH,
    CandlePattern.DOJI_CONFIRMED_DOWN: Bias.BEARISH,
}

#: The source video for each pattern, so a reading can be traced back to what
#: was actually claimed rather than to this file.
PATTERN_SOURCE: dict[CandlePattern, str] = dict.fromkeys(CandlePattern, "V03")
PATTERN_SOURCE[CandlePattern.MOMENTUM_UP] = "V03/V08"
PATTERN_SOURCE[CandlePattern.MOMENTUM_DOWN] = "V03/V08"


Floats = npt.NDArray[np.float64]
Flags = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class _Bars:
    """The arrays every detector needs, derived once.

    Derived **once** is the whole point of this class, and it was not always
    true: these started as properties, and each detector reading `bars.body`
    inside the per-bar loop allocated a fresh array the length of the series.
    Forty-four thousand hourly bars took thirty-seven seconds, which across five
    timeframes and four symbols is an hour of a backtest spent finding
    candlestick patterns. As fields it is under a second.
    """

    open: Floats
    high: Floats
    low: Floats
    close: Floats
    atr: Floats
    body: Floats
    span: Floats
    upper_wick: Floats
    lower_wick: Floats
    is_up: Flags


def _bars(frame: pd.DataFrame, atr: pd.Series) -> _Bars:
    open_ = frame["open"].to_numpy(dtype="float64")
    high = frame["high"].to_numpy(dtype="float64")
    low = frame["low"].to_numpy(dtype="float64")
    close = frame["close"].to_numpy(dtype="float64")
    top = np.maximum(open_, close)
    bottom = np.minimum(open_, close)
    return _Bars(
        open=open_,
        high=high,
        low=low,
        close=close,
        atr=atr.to_numpy(dtype="float64"),
        body=np.abs(close - open_),
        span=high - low,
        upper_wick=high - top,
        lower_wick=bottom - low,
        is_up=close > open_,
    )


class CandleTimeline:
    """Which patterns closed on each bar.

    Built in one pass like the other timelines, and read the same way: what
    `at(i)` returns used only bars up to and including `i`, so it is safe inside
    a backtest loop without further guarding.
    """

    def __init__(self, frame: pd.DataFrame, atr: pd.Series) -> None:
        self.bars = _bars(frame, atr)
        count = len(frame)
        self._found: list[tuple[CandlePattern, ...]] = [() for _ in range(count)]

        for index in range(count):
            found: list[CandlePattern] = []
            found += _engulfing(self.bars, index)
            found += _momentum(self.bars, index)
            found += _doji(self.bars, index)
            found += _hammer_or_star(self.bars, index)
            found += _tweezer(self.bars, index)
            found += _marubozu(self.bars, index)
            found += _multiple_wick(self.bars, index)
            found += _doji_confirmation(self.bars, index)
            self._found[index] = tuple(found)

    def __len__(self) -> int:
        return len(self._found)

    def at(self, index: int) -> tuple[CandlePattern, ...]:
        if index < 0 or index >= len(self._found):
            return ()
        return self._found[index]

    def bias_at(self, index: int) -> Bias:
        """The net stance of the patterns on one bar.

        Disagreement resolves to neutral rather than to a count. V03's rule is
        that patterns are hints needing context, so a bar showing one bullish
        and one bearish pattern is telling you it is unclear -- and reporting
        the majority would turn that into a stance the video never takes.
        """
        stances = {PATTERN_BIAS[pattern] for pattern in self.at(index)}
        stances.discard(Bias.NEUTRAL)
        if len(stances) != 1:
            return Bias.NEUTRAL
        return stances.pop()


# --------------------------------------------------------------------------- #
# The detectors, one per pattern as the video states it
# --------------------------------------------------------------------------- #


def _usable(bars: _Bars, index: int, needs: int = 1) -> bool:
    """Enough history, and a volatility unit to measure against."""
    if index < needs:
        return False
    unit = bars.atr[index]
    return bool(np.isfinite(unit) and unit > 0)


def _engulfing(bars: _Bars, index: int) -> list[CandlePattern]:
    """V03: "Neue Kerze öffnet am/unter vorherigem Close und schließt über
    vorherigem Open; bearish spiegelverkehrt."

    Taken literally, including "am" -- open equal to the previous close counts,
    which is the common case on a continuously traded market where one bar's
    close is the next bar's open.
    """
    if not _usable(bars, index):
        return []
    previous, current = index - 1, index
    if (
        bars.open[current] <= bars.close[previous]
        and bars.close[current] > bars.open[previous]
        and bars.is_up[current]
    ):
        return [CandlePattern.BULLISH_ENGULFING]
    if (
        bars.open[current] >= bars.close[previous]
        and bars.close[current] < bars.open[previous]
        and not bars.is_up[current]
    ):
        return [CandlePattern.BEARISH_ENGULFING]
    return []


def _momentum(bars: _Bars, index: int) -> list[CandlePattern]:
    """V03: one candle roughly two to three times the size of the previous ones.

    Measured on the body rather than the range. A long-wicked bar has a large
    range and says the opposite of momentum -- it says the move was rejected --
    and V08 makes the same distinction when it refuses a breakout that is only
    a wick.
    """
    if not _usable(bars, index, needs=MOMENTUM_LOOKBACK):
        return []
    window = bars.body[index - MOMENTUM_LOOKBACK : index]
    reference = float(np.mean(window))
    if reference <= 0:
        return []
    if bars.body[index] < MOMENTUM_BODY_MULTIPLE * reference:
        return []
    return [CandlePattern.MOMENTUM_UP if bars.is_up[index] else CandlePattern.MOMENTUM_DOWN]


def _doji(bars: _Bars, index: int) -> list[CandlePattern]:
    """V03: very small body, wicks on both sides, four named variants."""
    if not _usable(bars, index, needs=0):
        return []
    span = bars.span[index]
    if span <= 0:
        return []
    if bars.body[index] / span > DOJI_MAX_BODY_FRACTION:
        return []

    upper = bars.upper_wick[index] / span
    lower = bars.lower_wick[index] / span
    variant = _doji_variant(upper, lower)
    return [CandlePattern.DOJI, variant] if variant else [CandlePattern.DOJI]


def _doji_variant(upper: float, lower: float) -> CandlePattern | None:
    """Which of V03's four dojis this is, or none of the named three."""
    if lower >= DOJI_DOMINANT_WICK and upper <= DOJI_QUIET_WICK:
        return CandlePattern.DOJI_DRAGONFLY
    if upper >= DOJI_DOMINANT_WICK and lower <= DOJI_QUIET_WICK:
        return CandlePattern.DOJI_GRAVESTONE
    if upper >= DOJI_LONG_LEG and lower >= DOJI_LONG_LEG:
        return CandlePattern.DOJI_LONG_LEGGED
    return None


def _doji_confirmation(bars: _Bars, index: int) -> list[CandlePattern]:
    """V03: after a doji, wait for two candles in the same new direction.

    Reported on the second confirming bar, which is the first bar on which the
    video's condition is true. Marking it on the doji would be backdating two
    bars of knowledge into the signal being traded.
    """
    doji_index = index - DOJI_CONFIRMATION_BARS
    if doji_index < 0 or not _doji(bars, doji_index):
        return []
    following = range(doji_index + 1, index + 1)
    if all(bars.is_up[i] for i in following):
        return [CandlePattern.DOJI_CONFIRMED_UP]
    if all(not bars.is_up[i] for i in following):
        return [CandlePattern.DOJI_CONFIRMED_DOWN]
    return []


def _hammer_or_star(bars: _Bars, index: int) -> list[CandlePattern]:
    """V03: body with a long wick on one side and little on the other.

    Excludes dojis explicitly. A doji with one long wick is the dragonfly or
    gravestone the video already names, and letting it also read as a hammer
    would double-count one candle as two independent signals.
    """
    if not _usable(bars, index, needs=0) or _doji(bars, index):
        return []
    body = bars.body[index]
    span = bars.span[index]
    if body <= 0 or span <= 0:
        return []

    lower, upper = bars.lower_wick[index], bars.upper_wick[index]
    if lower >= WICK_BODY_MULTIPLE * body and upper <= OPPOSITE_WICK_MAX_FRACTION * span:
        return [CandlePattern.HAMMER]
    if upper >= WICK_BODY_MULTIPLE * body and lower <= OPPOSITE_WICK_MAX_FRACTION * span:
        return [CandlePattern.SHOOTING_STAR]
    return []


def _tweezer(bars: _Bars, index: int) -> list[CandlePattern]:
    """V03: "Bottom: rote, dann grüne Kerze mit ähnlichen Tiefdochten." """
    if not _usable(bars, index):
        return []
    tolerance = TWEEZER_TOLERANCE_ATR * bars.atr[index]
    first, second = index - 1, index

    if (
        not bars.is_up[first]
        and bars.is_up[second]
        and abs(bars.low[first] - bars.low[second]) <= tolerance
    ):
        return [CandlePattern.TWEEZER_BOTTOM]
    if (
        bars.is_up[first]
        and not bars.is_up[second]
        and abs(bars.high[first] - bars.high[second]) <= tolerance
    ):
        return [CandlePattern.TWEEZER_TOP]
    return []


def _marubozu(bars: _Bars, index: int) -> list[CandlePattern]:
    """V03: "Große Kerze ohne bzw. nahezu ohne Dochte."

    The "große" half is carried by the momentum test: a candle with no wicks but
    a tiny body is a pause, not the continuation signal the video describes.
    """
    if not _usable(bars, index, needs=MOMENTUM_LOOKBACK):
        return []
    span = bars.span[index]
    if span <= 0:
        return []
    wicks = bars.upper_wick[index] + bars.lower_wick[index]
    if wicks / span > MARUBOZU_MAX_WICK_FRACTION:
        return []
    if not _momentum(bars, index):
        return []
    return [CandlePattern.MARUBOZU_UP if bars.is_up[index] else CandlePattern.MARUBOZU_DOWN]


def _multiple_wick(bars: _Bars, index: int) -> list[CandlePattern]:
    """V03: at least three candles with wicks in the same direction.

    The video claims more candles strengthen the signal. That claim is not
    encoded as a strength score here, because the video offers no scale for it
    and a number invented to represent "stronger" would read as a measurement.
    """
    needed = MULTIPLE_WICK_MIN_CANDLES
    if not _usable(bars, index, needs=needed - 1):
        return []
    window = range(index - needed + 1, index + 1)

    def dominant(side: Floats, i: int) -> bool:
        span = bars.span[i]
        return bool(span > 0 and side[i] / span >= MULTIPLE_WICK_MIN_FRACTION)

    if all(dominant(bars.lower_wick, i) for i in window):
        return [CandlePattern.MULTIPLE_WICK_UP]
    if all(dominant(bars.upper_wick, i) for i in window):
        return [CandlePattern.MULTIPLE_WICK_DOWN]
    return []


# --------------------------------------------------------------------------- #
# V08's breakout confirmation, which is about a level rather than a bar
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BreakoutConfirmation:
    """Whether a break of one level is confirmed in V08's terms."""

    confirmed: bool
    form: str
    detail: str


def confirm_breakout(
    frame: pd.DataFrame,
    atr: pd.Series,
    index: int,
    level: float,
    *,
    upward: bool,
) -> BreakoutConfirmation:
    """V08's two accepted momentum forms, and nothing else.

    Either a single large candle whose body lies mostly beyond the level, or
    three medium candles in the same direction beyond it, entered at the close
    of the third. A wick through the level, or a small body poking past it, is
    explicitly refused -- that refusal is the whole point of the video, so it is
    reported as its own answer rather than as a silent False.
    """
    bars = _bars(frame, atr)
    if index < BREAKOUT_SEQUENCE_LENGTH or not _usable(bars, index, needs=MOMENTUM_LOOKBACK):
        return BreakoutConfirmation(False, "none", "not enough bars to judge the break")

    beyond = _body_fraction_beyond(bars, index, level, upward=upward)
    if beyond <= 0:
        return BreakoutConfirmation(False, "none", "the body has not crossed the level")

    directional = bars.is_up[index] if upward else not bars.is_up[index]
    if not directional:
        return BreakoutConfirmation(False, "none", "the bar closed against the break")

    if _momentum(bars, index) and beyond >= BREAKOUT_BODY_BEYOND_FRACTION:
        return BreakoutConfirmation(
            True, "momentum_candle", f"body {beyond:.0%} beyond the level"
        )

    window = range(index - BREAKOUT_SEQUENCE_LENGTH + 1, index + 1)
    same_way = all((bars.is_up[i] if upward else not bars.is_up[i]) for i in window)
    all_beyond = all(
        _body_fraction_beyond(bars, i, level, upward=upward) >= BREAKOUT_BODY_BEYOND_FRACTION
        for i in window
    )
    if same_way and all_beyond:
        return BreakoutConfirmation(
            True, "three_candles", f"{BREAKOUT_SEQUENCE_LENGTH} candles closed beyond the level"
        )

    return BreakoutConfirmation(
        False, "none", "no momentum candle and no three-candle sequence beyond the level"
    )


def _body_fraction_beyond(bars: _Bars, index: int, level: float, *, upward: bool) -> float:
    """How much of the candle's body lies past the level, as a fraction of it.

    Body, not range: V08 refuses a break that is "nur ein Docht oder eine kleine
    Körperspitze", and measuring the range would accept exactly that.
    """
    top = max(bars.open[index], bars.close[index])
    bottom = min(bars.open[index], bars.close[index])
    body = top - bottom
    if body <= 0:
        # A body of zero either sits beyond the level or does not; there is no
        # fraction to take, and calling it fully beyond would let a doji confirm
        # a breakout.
        return 0.0
    past = (top - level) if upward else (level - bottom)
    return float(np.clip(past / body, 0.0, 1.0))
