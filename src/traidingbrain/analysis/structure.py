"""Market structure: swings, the HH/HL sequence, break of structure, change of character.

This is the module where lookahead is easiest to introduce and hardest to notice,
and it carries the heaviest weight of the five factors. The trap is specific:

A swing high at bar *i* is only a swing high once *lookback* further bars have
printed without exceeding it. At bar *i* nobody knows. Reporting the swing at *i*
-- which is what every naive implementation does, because that is where the price
is -- hands the engine several bars of foresight in its most influential input.
The backtest looks excellent and nothing about the code looks wrong.

So every structural object here carries two indices: `index`, where the price is,
and `confirmed_index`, the earliest bar at which it could have been known. The
timeline below is built in a single forward pass and will only ever expose objects
whose `confirmed_index` has already passed. `StructureTimeline.state_at(i)` is the
only supported way to read it, so using an unconfirmed swing is not something a
caller can do by accident.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from traidingbrain.domain.enums import Bias

#: How many of the last four swing labels must agree before the structure is
#: called directional. Three out of four with nothing against it is a clear
#: read; anything looser flips on a single swing and makes the regime label
#: noise.
CLEAR_TREND_LABELS = 3

#: Labels considered when reading direction -- two highs and two lows.
TREND_WINDOW_LABELS = 4

#: Length of a comparative label (HH, HL, LH, LL). The seed labels H and L are
#: one character because there was nothing to compare them against.
COMPARATIVE_LABEL_LENGTH = 2

#: Comparable labels required before any direction is claimed. Below this the
#: honest answer is neutral: a trend read off two swings is not a trend.
MIN_LABELS_FOR_DIRECTION = 3

#: How recently a break of structure must have happened for `bos` to be true.
#:
#: Without a window this flag is useless: over thousands of bars a break has
#: always happened at some point, so the field is true everywhere and tells the
#: model nothing while looking like a signal. What matters is whether structure
#: broke recently enough to still be driving price. `bars_since_bos` carries the
#: precise answer for anyone who needs it.
BREAK_RECENCY_BARS = 20


class SwingKind(StrEnum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class Swing:
    """A local extreme, with the bar it formed on and the bar it became knowable on."""

    index: int
    ts: int
    price: float
    kind: SwingKind
    confirmed_index: int

    @property
    def confirmation_lag(self) -> int:
        return self.confirmed_index - self.index


@dataclass(frozen=True)
class StructureState:
    """What was knowable about structure at one bar."""

    index: int
    sequence: tuple[str, ...]
    trend: Bias
    bos: bool
    """A break of structure happened within the recency window -- not ever."""

    choch: bool
    """A change of character happened within the recency window -- not ever."""

    bars_since_bos: int | None
    bars_since_choch: int | None
    last_swing_high: Swing | None
    last_swing_low: Swing | None

    def sequence_text(self) -> str:
        return " ".join(self.sequence)


def find_swings(frame: pd.DataFrame, lookback: int = 3) -> list[Swing]:
    """Locate local extremes, each tagged with when it became knowable.

    A bar is a swing high when its high is the strict maximum of the window
    reaching `lookback` bars either side. The right-hand half of that window is
    the whole point: it is what turns "the highest bar so far" into "a high the
    market turned away from", and it is why confirmation arrives `lookback` bars
    late.

    Ties are not swings. A flat top is two bars at the same price and a level that
    has not yet been rejected.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")

    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    ts = frame["ts"].to_numpy(dtype="int64")
    n = len(frame)

    swings: list[Swing] = []
    for i in range(lookback, n - lookback):
        window = slice(i - lookback, i + lookback + 1)
        if highs[i] == np.max(highs[window]) and np.sum(highs[window] == highs[i]) == 1:
            swings.append(
                Swing(
                    index=i,
                    ts=int(ts[i]),
                    price=float(highs[i]),
                    kind=SwingKind.HIGH,
                    confirmed_index=i + lookback,
                )
            )
        if lows[i] == np.min(lows[window]) and np.sum(lows[window] == lows[i]) == 1:
            swings.append(
                Swing(
                    index=i,
                    ts=int(ts[i]),
                    price=float(lows[i]),
                    kind=SwingKind.LOW,
                    confirmed_index=i + lookback,
                )
            )
    return sorted(swings, key=lambda s: (s.confirmed_index, s.index))


def _classify(previous: Swing | None, current: Swing) -> str:
    """Label a swing against the one before it of the same kind."""
    if previous is None:
        return "H" if current.kind is SwingKind.HIGH else "L"
    if current.kind is SwingKind.HIGH:
        return "HH" if current.price > previous.price else "LH"
    return "HL" if current.price > previous.price else "LL"


def _trend_from(sequence: list[str]) -> Bias:
    """Read direction off the last few labels.

    Higher highs with higher lows is an uptrend; lower highs with lower lows is a
    downtrend; anything mixed is neutral, and saying so is more useful than
    forcing a direction onto a range.

    The first swing of each kind is labelled `H` or `L` because there is nothing
    to compare it against. Those carry no direction and are excluded -- otherwise
    a market with exactly two comparable swings gets called trending, which is a
    direction read off two data points.
    """
    recent = [
        label for label in sequence[-TREND_WINDOW_LABELS:] if len(label) == COMPARATIVE_LABEL_LENGTH
    ]
    if len(recent) < MIN_LABELS_FOR_DIRECTION:
        return Bias.NEUTRAL
    bullish = sum(1 for label in recent if label in ("HH", "HL"))
    bearish = sum(1 for label in recent if label in ("LH", "LL"))
    if bullish >= CLEAR_TREND_LABELS and bearish == 0:
        return Bias.BULLISH
    if bearish >= CLEAR_TREND_LABELS and bullish == 0:
        return Bias.BEARISH
    if bullish > bearish + 1:
        return Bias.BULLISH
    if bearish > bullish + 1:
        return Bias.BEARISH
    return Bias.NEUTRAL


@dataclass
class _Cursor:
    """Mutable state carried through the forward pass."""

    highs: list[Swing] = field(default_factory=list)
    lows: list[Swing] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    trend: Bias = Bias.NEUTRAL
    reference_high: Swing | None = None
    reference_low: Swing | None = None
    last_bos_index: int | None = None
    last_bos_direction: Bias = Bias.NEUTRAL
    last_choch_index: int | None = None


class StructureTimeline:
    """Structure state for every bar, built once, read by index.

    Construction is a single forward pass, so by design nothing can consult a bar
    that has not happened. Reading is `state_at(i)`; there is deliberately no
    accessor that hands out raw swings without their confirmation index.
    """

    def __init__(
        self,
        frame: pd.DataFrame,
        lookback: int = 3,
        max_sequence_length: int = 6,
        break_recency_bars: int = BREAK_RECENCY_BARS,
    ) -> None:
        self.lookback = lookback
        self.max_sequence_length = max_sequence_length
        self.break_recency_bars = break_recency_bars
        self._swings = find_swings(frame, lookback)
        self._confirmed_indices = [s.confirmed_index for s in self._swings]
        self._states = self._build(frame)

    def _build(self, frame: pd.DataFrame) -> list[StructureState]:
        closes = frame["close"].to_numpy(dtype="float64")
        n = len(frame)

        arriving: dict[int, list[Swing]] = {}
        for swing in self._swings:
            arriving.setdefault(swing.confirmed_index, []).append(swing)

        cursor = _Cursor()
        states: list[StructureState] = []

        for i in range(n):
            for swing in arriving.get(i, []):
                if swing.kind is SwingKind.HIGH:
                    cursor.labels.append(_classify(_last(cursor.highs), swing))
                    cursor.highs.append(swing)
                    cursor.reference_high = swing
                else:
                    cursor.labels.append(_classify(_last(cursor.lows), swing))
                    cursor.lows.append(swing)
                    cursor.reference_low = swing
                cursor.trend = _trend_from(cursor.labels)

            bos_here = False
            choch_here = False
            close = closes[i]

            if cursor.reference_high is not None and close > cursor.reference_high.price:
                bos_here = True
                choch_here = cursor.last_bos_direction is Bias.BEARISH
                cursor.last_bos_direction = Bias.BULLISH
                # The level has been taken; the next confirmed swing high becomes
                # the reference, rather than this one firing on every later bar.
                cursor.reference_high = None
            elif cursor.reference_low is not None and close < cursor.reference_low.price:
                bos_here = True
                choch_here = cursor.last_bos_direction is Bias.BULLISH
                cursor.last_bos_direction = Bias.BEARISH
                cursor.reference_low = None

            if bos_here:
                cursor.last_bos_index = i
            if choch_here:
                cursor.last_choch_index = i

            states.append(
                StructureState(
                    index=i,
                    sequence=tuple(cursor.labels[-self.max_sequence_length :]),
                    trend=cursor.trend,
                    bos=_within(cursor.last_bos_index, i, self.break_recency_bars),
                    choch=_within(cursor.last_choch_index, i, self.break_recency_bars),
                    bars_since_bos=(
                        None if cursor.last_bos_index is None else i - cursor.last_bos_index
                    ),
                    bars_since_choch=(
                        None if cursor.last_choch_index is None else i - cursor.last_choch_index
                    ),
                    last_swing_high=_last(cursor.highs),
                    last_swing_low=_last(cursor.lows),
                )
            )
        return states

    def state_at(self, index: int) -> StructureState:
        return self._states[index]

    def all_swings(self) -> list[Swing]:
        """Every swing with its confirmation index, ordered by when it became known.

        For callers that walk the timeline forward and fold swings in as they are
        confirmed. Anyone asking "what was known at bar i" should use
        `swings_known_at`, which cannot accidentally include one that had not been
        confirmed yet.
        """
        return list(self._swings)

    def swings_known_at(self, index: int) -> list[Swing]:
        """Swings the engine could legitimately have seen by this bar.

        `self._swings` is sorted by confirmation index, so this is a binary search
        rather than a scan -- it is called per bar in places, and a linear filter
        there makes the whole analysis quadratic.
        """
        cut = bisect_right(self._confirmed_indices, index)
        return self._swings[:cut]

    def recent_swings(
        self, index: int, kind: SwingKind | None = None, limit: int = 5
    ) -> list[Swing]:
        known = self.swings_known_at(index)
        if kind is not None:
            known = [s for s in known if s.kind is kind]
        return known[-limit:]

    def __len__(self) -> int:
        return len(self._states)


def _last(items: list[Swing]) -> Swing | None:
    return items[-1] if items else None


def _within(event_index: int | None, now_index: int, window: int) -> bool:
    return event_index is not None and (now_index - event_index) <= window
