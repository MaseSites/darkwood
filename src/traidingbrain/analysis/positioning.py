"""Reading open interest and crowd positioning as a stance, not a number.

Open interest alone says nothing. Fifty-six thousand contracts outstanding is
neither bullish nor bearish; what carries information is the *change*, and only
when it is read against the change in price.

| price | open interest | reading                | what it argues              |
|-------|---------------|------------------------|-----------------------------|
| up    | up            | new longs              | supported, money arriving   |
| up    | down          | short covering         | a squeeze, not real demand  |
| down  | up            | new shorts             | supported, money arriving   |
| down  | down          | long liquidation       | a flush, often exhaustion   |

The two "down" cells are the valuable ones, because they are the two a chart
cannot distinguish. A rally driven by shorts being forced out ends when the last
short is out, and it looks exactly like a rally driven by buyers until it stops.

**Percentiles are rolling, never global.** A global percentile over the whole
series would rank today's open interest against a distribution that includes
tomorrow -- the same lookahead the structure module exists to prevent, arriving
through the back door of a normalisation step.

**Missing is missing.** Bybit's history starts well after the candles do, and a
gap has to stay a gap. A zero would assert positioning did not change, which is a
claim, and one that happens to be the most common reading in the table.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from traidingbrain.domain.enums import Bias

#: Bars to look back over when measuring a change. Six hours on H1: long enough
#: that a single print does not decide it, short enough to still be about now.
CHANGE_WINDOW = 6

#: Rolling window for ranking a reading against its own recent history. Thirty
#: days on H1 -- long enough to cover a regime, short enough to adapt to one.
PERCENTILE_WINDOW = 720

#: Below this many bars of history a percentile is noise dressed as a statistic.
MIN_HISTORY = 120

#: Open interest moves of less than this are not a reading. Without a floor,
#: every bar gets a confident label from rounding noise.
MIN_OI_CHANGE = 0.004

#: An evenly split book. The account ratio is a share of accounts positioned
#: long, so this is the value that means "nobody is leaning".
BALANCED = 0.5

#: Ratios beyond this are the crowd leaning hard one way. Bybit's sits near
#: BALANCED the vast majority of the time, so the tails are genuinely rare.
CROWDED = 0.62


@dataclass(frozen=True)
class PositioningView:
    """What positioning argues at one bar, or that it is unknown.

    `known` is a separate field rather than an absent object because "no data"
    has to survive all the way to the prompt. A caller that sees neutral where it
    should see unknown will weight the silence as evidence.
    """

    known: bool
    reading: str = "unknown"
    bias: Bias = Bias.NEUTRAL
    strength: float = 0.0
    oi_change_pct: float | None = None
    oi_percentile: float | None = None
    crowd_long_ratio: float | None = None
    crowd_is_stretched: bool = False

    def describe(self) -> str:
        if not self.known:
            return "positioning: no data for this period"
        parts = [f"positioning: {self.reading.replace('_', ' ')}"]
        if self.oi_change_pct is not None:
            parts.append(f"open interest {self.oi_change_pct:+.1%} over {CHANGE_WINDOW} bars")
        if self.crowd_is_stretched and self.crowd_long_ratio is not None:
            side = "long" if self.crowd_long_ratio > BALANCED else "short"
            parts.append(f"{self.crowd_long_ratio:.0%} of accounts {side}")
        return ", ".join(parts)


class PositioningTimeline:
    """Positioning readings aligned to a price frame, computed once.

    Built in one pass like the other timelines. Everything at index `i` uses only
    rows at or before `i`, which is what makes it safe to read inside a backtest
    loop without further guarding.
    """

    def __init__(
        self,
        frame: pd.DataFrame,
        open_interest: pd.DataFrame | None = None,
        account_ratio: pd.DataFrame | None = None,
        *,
        change_window: int = CHANGE_WINDOW,
        percentile_window: int = PERCENTILE_WINDOW,
    ) -> None:
        self.change_window = change_window
        self.percentile_window = percentile_window
        self.ts = frame["ts"].to_numpy(dtype="int64")
        self.close = frame["close"].to_numpy(dtype="float64")

        self.oi = _align(self.ts, open_interest, "open_interest")
        self.buy_ratio = _align(self.ts, account_ratio, "buy_ratio")

        self._oi_change = _relative_change(self.oi, change_window)
        self._oi_rank = _rolling_rank(self.oi, percentile_window, MIN_HISTORY)
        self._price_change = _relative_change(self.close, change_window)

    def __len__(self) -> int:
        return len(self.ts)

    def at(self, index: int) -> PositioningView:
        """The reading at one bar."""
        if index < 0 or index >= len(self.ts):
            return PositioningView(known=False)

        oi_change = self._oi_change[index]
        crowd = self.buy_ratio[index]
        crowd_known = bool(np.isfinite(crowd))
        # bool() rather than the numpy truth value: this field is declared bool,
        # travels into a Pydantic model and is compared with `is`, and np.bool_
        # passes none of those cleanly.
        stretched = bool(crowd_known and abs(crowd - BALANCED) >= (CROWDED - BALANCED))

        if not np.isfinite(oi_change):
            # The ratio can be present when open interest is not. A crowd reading
            # alone is thin, but it is not nothing.
            if not crowd_known:
                return PositioningView(known=False)
            return PositioningView(
                known=True,
                reading="crowded" if stretched else "unremarkable",
                bias=_fade(crowd) if stretched else Bias.NEUTRAL,
                strength=min(1.0, abs(crowd - BALANCED) * 4) if stretched else 0.0,
                crowd_long_ratio=float(crowd),
                crowd_is_stretched=stretched,
            )

        price_change = self._price_change[index]
        reading, bias = _classify(float(price_change), float(oi_change))
        rank = self._oi_rank[index]

        return PositioningView(
            known=True,
            reading=reading,
            bias=bias,
            strength=_strength(float(oi_change), float(price_change)),
            oi_change_pct=float(oi_change),
            oi_percentile=float(rank) if np.isfinite(rank) else None,
            crowd_long_ratio=float(crowd) if crowd_known else None,
            crowd_is_stretched=stretched,
        )


def _classify(price_change: float, oi_change: float) -> tuple[str, Bias]:
    """The four-quadrant read.

    A move on falling open interest is positions closing, and closing pressure
    runs out. So it argues *against* continuation even though the price is going
    that way, which is the one counter-intuitive cell in the table and the reason
    this is worth computing at all.
    """
    if abs(oi_change) < MIN_OI_CHANGE:
        return "flat_interest", Bias.NEUTRAL
    if price_change >= 0 and oi_change > 0:
        return "new_longs", Bias.BULLISH
    if price_change >= 0 and oi_change < 0:
        return "short_covering", Bias.BEARISH
    if price_change < 0 and oi_change > 0:
        return "new_shorts", Bias.BEARISH
    return "long_liquidation", Bias.BULLISH


def _fade(buy_ratio: float) -> Bias:
    """A crowded book argues against the crowd, mildly.

    Mildly is the operative word: crowds are right during trends, which is most
    of the time this reading fires. It is a caution, not a signal.
    """
    return Bias.BEARISH if buy_ratio > BALANCED else Bias.BULLISH


def _strength(oi_change: float, price_change: float) -> float:
    """How emphatic the reading is.

    Both halves have to be moving. A large open-interest change against a price
    that did nothing is an accumulation nobody has acted on yet, and calling that
    emphatic would be reading a story into a flat chart.
    """
    return float(min(1.0, abs(oi_change) / 0.05) * min(1.0, abs(price_change) / 0.02))


def _align(ts: np.ndarray, source: pd.DataFrame | None, column: str) -> np.ndarray:
    """Map a sparse series onto the price frame's bars, without inventing rows.

    Each bar takes the newest reading at or before it, and NaN where there is
    none. Forward-filling past the end of the data would turn a venue that stopped
    reporting into a positioning that stopped changing.
    """
    empty = np.full(len(ts), np.nan)
    if source is None or source.empty or column not in source.columns:
        return empty

    source_ts = source["ts"].to_numpy(dtype="int64")
    values = source[column].to_numpy(dtype="float64")
    positions = np.searchsorted(source_ts, ts, side="right") - 1

    out = empty.copy()
    valid = positions >= 0
    out[valid] = values[positions[valid]]

    # A reading far older than the bar is not a reading about it. An hourly
    # series with a day-long hole should report unknown, not yesterday's number.
    stale = np.full(len(ts), False)
    stale[valid] = (ts[valid] - source_ts[positions[valid]]) > 6 * 3_600_000
    out[stale] = np.nan
    return out


def _relative_change(values: np.ndarray, window: int) -> np.ndarray:
    """Fractional change over `window` bars, NaN where either end is missing."""
    out = np.full(len(values), np.nan)
    if len(values) <= window:
        return out
    previous = values[:-window]
    current = values[window:]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[window:] = np.where(previous > 0, (current - previous) / previous, np.nan)
    return out


def _rolling_rank(values: np.ndarray, window: int, min_history: int) -> np.ndarray:
    """Where each value sits in its own recent history, as a fraction.

    Rolling and backward-looking by construction. A global percentile would rank
    today against a distribution containing tomorrow, which is precisely the
    lookahead this codebase spends most of its tests preventing -- and it would
    arrive disguised as a normalisation step rather than as a signal.
    """
    out = np.full(len(values), np.nan)
    for index in range(len(values)):
        if not np.isfinite(values[index]):
            continue
        start = max(0, index - window + 1)
        history = values[start : index + 1]
        history = history[np.isfinite(history)]
        if len(history) < min_history:
            continue
        out[index] = float(np.mean(history <= values[index]))
    return out
