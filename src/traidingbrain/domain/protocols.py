"""The seams between layers.

Each protocol has at least two implementations -- a real one and a test double --
and one pair matters more than the rest: `Broker` is implemented by both the
simulator and the live exchange adapter. They drive the same `TradeState` machine
through the same interface, so the backtest exercises the code that runs live
instead of a parallel universe that merely resembles it.

Nothing in this module imports pandas, ccxt or anthropic. That is enforced by a
test, not by good intentions.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import Bar, FundingRate, SymbolSpec
from traidingbrain.domain.proposal import (
    ClosedTrade,
    ExecutionIntent,
    Position,
    TradeProposal,
)
from traidingbrain.domain.snapshot import BrainInput, MarketSnapshot
from traidingbrain.domain.verdict import BrainDecision, PostTradeReview


@runtime_checkable
class Clock(Protocol):
    """Current time, injected rather than read.

    A backtest steps a simulated clock; live code reads the wall clock. Code that
    calls `datetime.now()` directly cannot be replayed, and silently invalidates
    the prompt cache when the value lands in a prompt.
    """

    def now_ms(self) -> int: ...


@runtime_checkable
class DataSource(Protocol):
    """Read-only access to market history and instrument rules."""

    def fetch_ohlcv(
        self, symbol: str, timeframe: Timeframe, since_ms: int, limit: int
    ) -> list[Bar]:
        """Closed candles only, oldest first.

        Implementations must drop the forming candle before returning. A forming
        candle's high, low and close change under the reader, and treating them as
        final is the most common way a backtest ends up knowing the future.
        """
        ...

    def fetch_funding(self, symbol: str, since_ms: int, limit: int) -> list[FundingRate]: ...

    def fetch_symbol_spec(self, symbol: str) -> SymbolSpec: ...


@runtime_checkable
class Brain(Protocol):
    """The interpretation layer.

    Takes a normalised snapshot, returns a decision. The live implementation calls
    Anthropic; the replay implementation serves recorded answers from the cache;
    the fake returns canned answers so the test suite can run with the network
    switched off.
    """

    def decide(self, snapshot: MarketSnapshot, brain_input: BrainInput) -> BrainDecision: ...

    def review(self, trade: ClosedTrade, snapshot_at_entry: MarketSnapshot) -> PostTradeReview: ...


@runtime_checkable
class DecisionCache(Protocol):
    """Content-addressed store of past model answers.

    Because sampling parameters no longer exist on the current models, this cache
    is not merely a cost optimisation -- it is the only thing that makes a backtest
    reproducible. Re-running over the same data must return the same decisions.
    """

    def get(self, key: str) -> BrainDecision | None: ...

    def put(self, key: str, decision: BrainDecision) -> None: ...


@runtime_checkable
class SimilarityIndex(Protocol):
    """Neighbour search over past setups, with a time bound.

    `as_of_ms` is not optional and not a convenience: without it the index happily
    returns setups from the future. `embargo_ms` additionally excludes the recent
    past, whose outcomes overlap the present bar and therefore encode it.
    """

    def add(self, fingerprint: list[float], ts_ms: int, outcome_r: float) -> None: ...

    def query(
        self,
        fingerprint: list[float],
        k: int,
        as_of_ms: int,
        embargo_ms: int,
    ) -> list[tuple[float, float]]:
        """Return (distance, outcome_r) for up to k admissible neighbours."""
        ...


@runtime_checkable
class Broker(Protocol):
    """Order placement. Implemented by the simulator and by the live adapter.

    Every method is written so that the simulator can be honest about the things
    that cost money in reality: fees, funding, gaps through the stop, and
    liquidation.
    """

    def symbol_spec(self, symbol: str) -> SymbolSpec: ...

    def equity(self) -> float: ...

    def open_positions(self) -> list[Position]: ...

    def set_leverage(self, symbol: str, leverage: float) -> None:
        """Set leverage for a symbol.

        Exchange-wide per symbol, not per order. Changing it while a position in
        that symbol is open moves that position's liquidation price too, which is
        why callers must check for open positions first.
        """
        ...

    def submit(self, intent: ExecutionIntent) -> Position:
        """Send entry, stop and target, and return the resulting position.

        Implementations must attach the stop as part of this call. A position that
        exists for even a few seconds without a stop on the exchange is an
        unbounded loss waiting for a connection drop.
        """
        ...

    def cancel_all(self, symbol: str) -> None: ...

    def close_position(self, symbol: str) -> ClosedTrade | None: ...


@runtime_checkable
class ProposalStore(Protocol):
    """Persistence for proposals, with the one transition that must be atomic."""

    def put(self, proposal: TradeProposal) -> None: ...

    def get(self, proposal_id: str) -> TradeProposal | None: ...

    def list_pending(self) -> list[TradeProposal]: ...

    def claim_for_execution(self, proposal_id: str) -> bool:
        """Compare-and-swap PENDING -> EXECUTING. True for exactly one caller.

        This, not the token check, is what makes concurrent confirmations safe: a
        token can be validated by two requests at the same instant, but only one
        `UPDATE ... WHERE status = 'pending'` can report a changed row.
        """
        ...

    def finish(self, proposal_id: str, ok: bool, note: str) -> None: ...


@runtime_checkable
class KillSwitch(Protocol):
    """Checked before every send, and reachable from outside this process.

    A kill switch that only the running process can set is not a kill switch.
    """

    def is_engaged(self) -> bool: ...

    def engage(self, reason: str) -> None: ...
