"""Enumerations shared across every layer.

These are the vocabulary of the system. They live in `domain` so that no layer has
to import another layer just to name a concept.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class Timeframe(StrEnum):
    """Candle durations the engine works with.

    H1 is the heartbeat: the backtest loop and the live loop both step bar by bar
    on H1. The higher frames provide context, M15 refines entry timing, and M1
    exists only so the simulator can tell whether stop or target was hit first
    inside an H1 candle.
    """

    M1 = "M1"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"

    @property
    def minutes(self) -> int:
        return _TF_MINUTES[self]

    @property
    def bybit_interval(self) -> str:
        """Bybit v5 `interval` parameter value."""
        return _TF_BYBIT[self]

    @property
    def ccxt_timeframe(self) -> str:
        return _TF_CCXT[self]


_TF_MINUTES: Final[dict[Timeframe, int]] = {
    Timeframe.M1: 1,
    Timeframe.M15: 15,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
    Timeframe.W1: 10080,
}

_TF_BYBIT: Final[dict[Timeframe, str]] = {
    Timeframe.M1: "1",
    Timeframe.M15: "15",
    Timeframe.H1: "60",
    Timeframe.H4: "240",
    Timeframe.D1: "D",
    Timeframe.W1: "W",
}

_TF_CCXT: Final[dict[Timeframe, str]] = {
    Timeframe.M1: "1m",
    Timeframe.M15: "15m",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1d",
    Timeframe.W1: "1w",
}

#: Frames that feed the multi-timeframe snapshot, high to low.
CONTEXT_FRAMES: Final[tuple[Timeframe, ...]] = (
    Timeframe.W1,
    Timeframe.D1,
    Timeframe.H4,
    Timeframe.H1,
    Timeframe.M15,
)

#: The frame the decision loop steps on.
SIGNAL_FRAME: Final[Timeframe] = Timeframe.H1

#: The frame the simulator uses to resolve intrabar ordering of stop vs target.
EXECUTION_FRAME: Final[Timeframe] = Timeframe.M1


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        """+1 for long, -1 for short — for direction-agnostic arithmetic."""
        return 1 if self is Side.LONG else -1

    @property
    def opposite(self) -> Side:
        return Side.SHORT if self is Side.LONG else Side.LONG


class Bias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Decision(StrEnum):
    """The brain's verdict on whether a trade exists here at all."""

    VALID_TRADE = "VALID TRADE"
    INVALID_TRADE = "INVALID TRADE"
    WAIT = "WAIT"


class RegimeKind(StrEnum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    MANIPULATION = "manipulation"
    UNKNOWN = "unknown"


class VolBucket(StrEnum):
    """Volatility relative to the symbol's own recent history — rolling, never global."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


class Factor(StrEnum):
    """The five inputs whose weighted sum produces confidence.

    The brain scores each one in [-1, +1]; Python does the weighting. See
    `config/weights.yaml`.
    """

    STRUCTURE = "structure"
    INDICATORS = "indicators"
    LIQUIDITY = "liquidity"
    NEWS = "news"
    HISTORY = "history"


class LevelKind(StrEnum):
    """What a named price level represents.

    The brain never sees prices — it anchors entries and stops to these levels by
    id, and Python resolves them back to numbers.
    """

    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    FVG_HIGH = "fvg_high"
    FVG_MID = "fvg_mid"
    FVG_LOW = "fvg_low"
    RANGE_HIGH = "range_high"
    RANGE_LOW = "range_low"
    PREV_DAY_HIGH = "prev_day_high"
    PREV_DAY_LOW = "prev_day_low"
    PREV_WEEK_HIGH = "prev_week_high"
    PREV_WEEK_LOW = "prev_week_low"
    CURRENT = "current"


class ProposalStatus(StrEnum):
    """Lifecycle of a trade proposal.

    The transition PENDING -> EXECUTING is the compare-and-swap that guarantees a
    proposal can be executed at most once, even under concurrent confirmations.
    """

    PENDING = "pending"
    EXECUTING = "executing"
    EXECUTED = "executed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class TradeState(StrEnum):
    """Shared lifecycle for simulated and live trades.

    `sim` and `execution` are twins: both drive this same state machine, so the
    backtest exercises the logic that runs live.
    """

    PENDING_ENTRY = "pending_entry"
    OPEN = "open"
    CLOSED_TARGET = "closed_target"
    CLOSED_STOP = "closed_stop"
    CLOSED_MANUAL = "closed_manual"
    CLOSED_LIQUIDATED = "closed_liquidated"
    CLOSED_TIME = "closed_time"
    """Held longer than allowed and closed on that ground alone.

    Terminal without being asked: `is_terminal` is "not PENDING_ENTRY and not
    OPEN", so a new closed state is terminal by construction."""
    EXPIRED_UNFILLED = "expired_unfilled"

    @property
    def is_terminal(self) -> bool:
        return self not in (TradeState.PENDING_ENTRY, TradeState.OPEN)


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"


class ExitReason(StrEnum):
    TARGET = "target"
    STOP = "stop"
    LIQUIDATION = "liquidation"
    MANUAL = "manual"
    INVALIDATION = "invalidation"
    TIME = "time"
    """Closed because it had been held long enough, nothing else.

    The value is permanent once a row is written: `JournalEntry.from_json`
    calls `ExitReason(...)` on the stored string and raises on anything it
    does not know, so a later rename would make old journals unreadable.
    English like its siblings -- `learn.labels.Barrier` uses German values
    ("zeit") and the two enums are deliberately not the same thing: a
    barrier is a labelling device, this is a trading rule.

    Pays taker on the way out, like every exit except TARGET. A time exit
    is a market order at whatever is there."""


class Rule(StrEnum):
    """Which risk rule refused a signal.

    Five members because `sim/plan.py` has five refusal branches, and the whole
    point of naming them is that "refused" is not one population. A signal
    turned down for a reward-to-risk of 1.4 and one turned down because the
    venue will not place a position that small are different claims about
    different trades, and lumping them cost the project the ability to ask
    whether either rule earns its place.

    Here rather than next to the rules themselves so the signal ledger can name
    them without `journal/` having to import `sim/`.
    """

    REWARD_RISK = "chance_risiko"
    CONFIDENCE = "zuversicht"
    SIZE = "groesse"
    COSTS = "kosten"
    LIQUIDATION = "liquidation"
