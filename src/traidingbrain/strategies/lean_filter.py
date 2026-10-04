"""Refuse a trade that fights the liquidity lean.

Measured on 04.10.2026 over twelve markets and 619,037 bars: when nearly all
untouched pivot weight sits above the price, the following week returns -0.195
ATR against a baseline of +0.761 -- the only condition in the whole record that
goes negative in markets that rose. Mirrored, the side with almost everything
below is the best.

So this is a filter and not a signal. It does not say when to enter; it says
when the direction a setup wants is the one the lean argues against. Every
other lever measured that day moved the number of trades without moving the
expectancy, because none of them touched what the entries know -- this one is
the first that does.

**Only the extremes are used.** The middle buckets of that measurement did not
order: -0.6 to -0.2 and -0.2 to +0.2 and +0.2 to +0.6 came out +0.937, +1.122
and +0.537, which is not a gradient. Reading a trend into them would be reading
the noise. The two ends are where the effect lives and they are all this acts
on.

**It can only subtract.** A filter that also *added* trades would be a second
strategy wearing a filter's name, and the comparison with the unfiltered pool
would stop being about the filter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from traidingbrain.analysis.liquidity_levels import balance_at, find_zones
from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.structure import StructureTimeline
from traidingbrain.config.settings import AppConfig
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.sim.plan import TradeIntent
from traidingbrain.strategies.guide import GuidePool

#: How one-sided the weight has to be before the filter acts.
#:
#: The measured edge lives at the ends. At |lean| >= 0.6 the week ahead differs
#: from the average by about an ATR; between the ends the buckets do not order
#: at all, so anything milder would be acting on noise.
EXTREME = 0.6

#: Which chart the lean is read from.
#:
#: The hourly one, because that is where it was measured. Reading it off a
#: different frame would be applying a number to a situation it was never
#: tested on -- the sort of substitution that looks like a detail and changes
#: what the measurement means.
LEAN_FRAME = Timeframe.H1


class LeanTimeline:
    """The lean at every bar of one frame, computed once.

    Once, because `balance_at` walks every live zone and a backtest asks per
    bar: doing it inside the strategy made the liquidity study the slowest
    thing in the project.
    """

    def __init__(self, frame: pd.DataFrame, config: AppConfig) -> None:
        structure = StructureTimeline(
            frame,
            lookback=config.engine.structure.swing_lookback,
            max_sequence_length=config.engine.structure.max_sequence_length,
        )
        zones = find_zones(frame, structure)
        closes = frame["close"].to_numpy(dtype="float64")
        self._ts = frame["ts"].to_numpy(dtype="int64")
        self._lean = np.full(len(frame), np.nan, dtype="float64")
        for i in range(len(frame)):
            lean = balance_at(zones, i, float(closes[i])).lean
            if lean is not None:
                self._lean[i] = lean

    def at_time(self, ts: int) -> float | None:
        """The lean on the newest bar that had closed by `ts`.

        By timestamp rather than by index, because the caller steps on a
        different frame. Asking for a bar that has not closed would be reading
        the future, which is the one mistake this whole project is built to
        avoid.
        """
        found = int(np.searchsorted(self._ts, ts, side="right")) - 1
        if found < 0 or found >= len(self._lean):
            return None
        value = self._lean[found]
        return None if not np.isfinite(value) else float(value)


@dataclass
class LeanFiltered:
    """A pool whose trades are dropped when the lean argues the other way."""

    inner: GuidePool
    timeline: LeanTimeline
    extreme: float = EXTREME
    name: str = "guide-lean"
    refused: int = field(default=0)

    def propose_at(self, analysis: MultiFrameAnalysis, index: int) -> TradeIntent | None:
        intent = self.inner.propose_at(analysis, index)
        if intent is None:
            return None
        lean = self.timeline.at_time(analysis.signal.ts_at(index))
        if lean is None:
            return intent
        # Long into a ceiling of untouched weight, or short into a floor of it.
        against = (intent.side is Side.LONG and lean >= self.extreme) or (
            intent.side is Side.SHORT and lean <= -self.extreme
        )
        if against:
            self.refused += 1
            return None
        return intent
