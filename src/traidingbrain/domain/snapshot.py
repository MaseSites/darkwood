"""The market snapshot -- and the normalised view of it the brain is allowed to see.

Two types live here, and the split between them is the single most important
design decision in this system.

`MarketSnapshot` is the internal, complete picture: symbol, timestamp, absolute
prices, every named level.

`BrainInput` is what actually reaches the model. It carries **no absolute price,
no timestamp, no symbol name**. Distances are in ATR units and price levels are
referenced by opaque ids. That buys four things at once:

1. The model cannot invent a price, because it never emits one -- it anchors to a
   level id and Python resolves it.
2. The model cannot recognise *when* it is. A snapshot saying "BTC, $16,540,
   extreme volatility" silently identifies November 2022, and the model knows what
   happened next. That is lookahead no unit test can detect; only this
   normalisation prevents it.
3. Identical market shapes hash identically, so the decision cache actually hits.
4. What the system learns on BTC transfers to ETH, SOL and XRP.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from traidingbrain.domain.enums import (
    Bias,
    LevelKind,
    RegimeKind,
    Timeframe,
    VolBucket,
)

#: Decimal places every normalised float is quantised to before hashing.
#: Without this, float noise in the last bits produces cache misses on snapshots
#: that are identical for every practical purpose.
NORM_PRECISION = 4


def _q(value: float) -> float:
    return round(value, NORM_PRECISION)


class Level(BaseModel):
    """A named price level, carried through to the brain by id only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^lvl_\d+$")
    kind: LevelKind
    timeframe: Timeframe
    price: float = Field(description="Absolute price -- internal only, never sent to the brain")
    distance_atr: float = Field(
        description="Signed distance from current price in ATR units; positive = above"
    )
    age_bars: int = Field(ge=0, description="Bars since this level was confirmed")
    touches: int = Field(ge=0, default=0)


class IndicatorReading(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: float
    bias: Bias
    strength: float = Field(ge=0.0, le=1.0)


class StructureView(BaseModel):
    """Market structure on one timeframe.

    Every structural object carries the index at which it was *confirmed*, not the
    index at which it formed. A swing high is only knowable some bars after the
    fact; reporting it at its formation index backdates knowledge the engine did
    not have, and does so inside the factor that carries the most weight.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: str = Field(description='e.g. "HH HL HH" -- most recent last')
    bos: bool = Field(description="Break of structure confirmed on or before this bar")
    choch: bool = Field(description="Change of character confirmed on or before this bar")
    bars_since_bos: int | None = None
    bars_since_choch: int | None = None


class LiquidityView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sweep_up: bool = Field(description="Buy-side liquidity taken and rejected")
    sweep_down: bool = Field(description="Sell-side liquidity taken and rejected")
    bars_since_sweep: int | None = None
    zone_level_ids: list[str] = Field(default_factory=list)


class TimeframeView(BaseModel):
    """Everything the engine knows about one timeframe at one instant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    regime: RegimeKind
    volatility: VolBucket
    trend: Bias
    structure: StructureView
    liquidity: LiquidityView
    indicators: list[IndicatorReading] = Field(default_factory=list)


class NewsItem(BaseModel):
    """A scheduled or published event.

    Stored bitemporally: `event_ts` is when it happens, `ingested_ts` is when the
    system could first have known about it. Only items already ingested as of the
    current bar may enter a snapshot. Stage 1 ships with this list empty and the
    news weight set to zero -- see the plan.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: str
    impact: str = Field(description="low | medium | high")
    sentiment: Bias
    minutes_until: int | None = Field(default=None, description="Negative if already passed")


class HistoryStats(BaseModel):
    """What the similarity index found among *past* setups.

    Bounded by purging and embargo: a neighbour whose outcome window overlaps the
    present is not a neighbour, it is a leak.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    similar_situations_found: int = Field(ge=0)
    historical_winrate: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_r_multiple: float | None = None
    regime: RegimeKind = RegimeKind.UNKNOWN
    sample_is_sufficient: bool = Field(
        default=False, description="False until the index holds enough non-overlapping cases"
    )


class BrainInput(BaseModel):
    """The normalised snapshot sent to the model. No price, no date, no symbol."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    signal_timeframe: Timeframe
    atr_pct: float = Field(description="ATR as a fraction of price -- scale without the price")
    frames: list[TimeframeView]
    levels: list[dict[str, Any]] = Field(
        description="Level id, kind, timeframe, distance_atr, age_bars -- never the price"
    )
    news: list[NewsItem] = Field(default_factory=list)
    history: HistoryStats

    def canonical_json(self) -> str:
        """Byte-stable serialisation. The basis of the cache key and every golden test."""
        payload = self.model_dump(mode="json")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def content_hash(self) -> str:
        """SHA-256 of the canonical JSON.

        Deliberately not Python's `hash()`: that is salted per process, so a cache
        keyed on it would silently miss on every restart.
        """
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class MarketSnapshot(BaseModel):
    """The complete internal picture at one bar. Never leaves the process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    ts: int = Field(description="Open time of the signal bar, UTC milliseconds")
    signal_timeframe: Timeframe
    price: float = Field(gt=0, description="Close of the last *closed* signal bar")
    atr: float = Field(gt=0)
    frames: list[TimeframeView]
    levels: list[Level]
    news: list[NewsItem] = Field(default_factory=list)
    history: HistoryStats

    @property
    def atr_pct(self) -> float:
        return self.atr / self.price

    def level_by_id(self, level_id: str) -> Level | None:
        return next((lvl for lvl in self.levels if lvl.id == level_id), None)

    def resolve(self, level_id: str, offset_atr: float = 0.0) -> float | None:
        """Turn a level id plus an ATR offset back into an absolute price.

        This is the only path from a model answer to a number, which is why a
        hallucinated price is structurally impossible rather than merely caught.
        """
        level = self.level_by_id(level_id)
        if level is None:
            return None
        return level.price + offset_atr * self.atr

    def to_brain_input(self) -> BrainInput:
        """Strip identity and scale. Everything the model must not know stops here."""
        return BrainInput(
            signal_timeframe=self.signal_timeframe,
            atr_pct=_q(self.atr_pct),
            frames=self.frames,
            levels=[
                {
                    "id": lvl.id,
                    "kind": lvl.kind.value,
                    "timeframe": lvl.timeframe.value,
                    "distance_atr": _q(lvl.distance_atr),
                    "age_bars": lvl.age_bars,
                    "touches": lvl.touches,
                }
                for lvl in self.levels
            ],
            news=self.news,
            history=self.history,
        )
