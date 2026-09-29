"""Trade proposals, confirmation tokens, and the write-ahead record of an intent.

This is where the system's hardest rule lives. Everything upstream analyses; this
module is the last thing before money. A proposal is a complete, ready-to-send
trade -- entry, stop, target, leverage, size, the cash at risk and the price at
which the position would be liquidated -- that sits and waits for a human.

Nothing here sends an order. `execution` does, and only against a
`ConfirmationToken` this module issued.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from traidingbrain.domain.enums import (
    Bias,
    Factor,
    LevelKind,
    ProposalStatus,
    RiskLevel,
    Side,
    Timeframe,
    TradeState,
)

#: How long a confirmation token stays valid. A proposal priced minutes ago is a
#: proposal priced at a stale market; past this the user must look again.
TOKEN_TTL_SECONDS = 60

#: How long a proposal stays on the dashboard before it expires unseen.
PROPOSAL_TTL_SECONDS = 15 * 60


def _now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


class FactorView(BaseModel):
    """One weighted input, with its arithmetic shown.

    The confidence number is the first thing anyone questions, and "74" on its own
    invites either blind trust or blind dismissal. Carrying the factor, the
    model's read, its own certainty, the configured weight and the resulting
    points makes the number checkable by hand -- which is the only kind of
    trustworthy there is for a figure that decides position size.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    factor: Factor
    score: float = Field(ge=-1.0, le=1.0, description="Directional read: + favours bullish")
    certainty: float = Field(ge=0.0, le=1.0, description="How sure the model is of this read")
    weight: float = Field(ge=0.0, le=1.0, description="Share after renormalising for gaps")
    contribution: float = Field(description="Confidence points this factor added or removed")
    reasoning: str = ""


class LevelMark(BaseModel):
    """A named level as it stood at the decision, kept for drawing.

    Re-deriving these when the chart is opened would show today's analysis over
    yesterday's trade. A proposal is an argument made at one instant, and the
    evidence has to be preserved with it or the chart quietly becomes a different
    claim.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: LevelKind
    timeframe: Timeframe
    price: float = Field(gt=0)
    distance_atr: float
    age_bars: int = Field(ge=0)
    touches: int = Field(ge=0, default=0)


class TradeProposal(BaseModel):
    """A fully specified trade, waiting for confirmation.

    Every number here is computed by Python: the model chose the levels, the risk
    module chose the size, and the leverage was derived from the requirement that
    liquidation sit well beyond the stop. The user may lower leverage or risk in
    the dashboard; any change re-runs sizing and the guard before it is offered
    again.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_ts: int = Field(default_factory=_now_ms)
    expires_ts: int = Field(default_factory=lambda: _now_ms() + PROPOSAL_TTL_SECONDS * 1000)

    symbol: str
    side: Side

    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)

    qty: float = Field(gt=0, description="Contracts/base units, rounded to the exchange step")
    leverage: float = Field(gt=0)
    notional: float = Field(gt=0, description="qty * entry -- the size of the position")
    margin: float = Field(gt=0, description="notional / leverage -- the capital tied up")
    liquidation_price: float = Field(gt=0)

    risk_amount: float = Field(gt=0, description="Loss in quote currency if the stop is hit")
    risk_pct: float = Field(gt=0, le=0.05, description="risk_amount as a fraction of equity")
    equity_at_build: float = Field(gt=0)

    bias: Bias
    confidence: float = Field(ge=0.0, le=100.0)
    risk_level: RiskLevel
    reasoning: list[str] = Field(default_factory=list)
    invalidation_note: str = ""

    snapshot_hash: str
    decision_id: str | None = None
    status: ProposalStatus = ProposalStatus.PENDING

    # -- what the analysis was looking at -------------------------------------- #
    # Defaulted so rows written before this existed still load. A proposal without
    # them is displayable; it simply cannot be charted, which is the honest
    # degradation rather than a crash on old data.

    snapshot_ts: int = Field(default=0, description="Open time of the bar the decision was made on")
    signal_timeframe: Timeframe | None = None
    price_at_build: float = Field(default=0.0, ge=0.0, description="Close of that bar")
    atr_at_build: float = Field(default=0.0, ge=0.0)
    factors: list[FactorView] = Field(default_factory=list)
    levels: list[LevelMark] = Field(default_factory=list)
    confidence_raw: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Before any cap. Equal to confidence unless something limited it.",
    )
    confidence_cap_reason: str = Field(
        default="",
        description="Why the raw number was not used. Empty when nothing was capped.",
    )

    @property
    def is_chartable(self) -> bool:
        return self.snapshot_ts > 0 and self.signal_timeframe is not None

    @model_validator(mode="after")
    def _directions_are_coherent(self) -> TradeProposal:
        """Stop below entry below target for a long, and the mirror for a short.

        Cheap to check, and it makes an inverted plan impossible to represent
        rather than merely unlikely.
        """
        if self.side is Side.LONG:
            if not (self.stop < self.entry < self.target):
                raise ValueError(
                    f"long requires stop < entry < target, got "
                    f"{self.stop} / {self.entry} / {self.target}"
                )
            if self.liquidation_price >= self.stop:
                raise ValueError(
                    f"long liquidation {self.liquidation_price} must sit below the stop "
                    f"{self.stop}; otherwise the position dies before the plan says it should"
                )
        else:
            if not (self.target < self.entry < self.stop):
                raise ValueError(
                    f"short requires target < entry < stop, got "
                    f"{self.target} / {self.entry} / {self.stop}"
                )
            if self.liquidation_price <= self.stop:
                raise ValueError(
                    f"short liquidation {self.liquidation_price} must sit above the stop "
                    f"{self.stop}; otherwise the position dies before the plan says it should"
                )
        return self

    @property
    def stop_distance(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_risk(self) -> float:
        if self.stop_distance == 0:
            return 0.0
        return abs(self.target - self.entry) / self.stop_distance

    @property
    def liquidation_buffer_r(self) -> float:
        """How far past the stop liquidation sits, measured in stop distances."""
        if self.stop_distance == 0:
            return 0.0
        return abs(self.liquidation_price - self.stop) / self.stop_distance

    def is_expired(self, now_ms: int | None = None) -> bool:
        return (now_ms if now_ms is not None else _now_ms()) >= self.expires_ts


class ProposalAdjustment(BaseModel):
    """What the user is allowed to change before confirming.

    Leverage and risk may only be lowered. Lowering is always safe; raising is a
    different trade and has to be proposed as one, because the sizing, the
    liquidation price and the guard all depend on it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    leverage: float | None = Field(default=None, gt=0)
    risk_pct: float | None = Field(default=None, gt=0, le=0.05)
    entry: float | None = Field(default=None, gt=0)
    stop: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)


class ConfirmationToken(BaseModel):
    """Single-use, short-lived permission to send exactly one proposal.

    Possession is not sufficient on its own: `execution.confirm` still performs a
    compare-and-swap on the proposal row, so two holders of the same token race
    and exactly one wins.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str = Field(default_factory=lambda: uuid.uuid4().hex)
    proposal_id: str
    issued_ts: int = Field(default_factory=_now_ms)
    expires_ts: int = Field(default_factory=lambda: _now_ms() + TOKEN_TTL_SECONDS * 1000)
    proposal_fingerprint: str = Field(
        description="Hash of the proposal's numbers; a token does not survive an edit"
    )

    def is_expired(self, now_ms: int | None = None) -> bool:
        return (now_ms if now_ms is not None else _now_ms()) >= self.expires_ts


class ExecutionIntent(BaseModel):
    """The write-ahead record, persisted *before* anything is sent.

    Without it, a crash between "sent" and "recorded" leaves a position nobody
    knows about. With it, reconciliation has a key -- `client_order_id` -- to ask
    the exchange what actually happened.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str
    client_order_id: str = Field(
        description="Deterministic from the proposal id, so a retry cannot open a second position"
    )
    symbol: str
    side: Side
    qty: float = Field(gt=0)
    entry: float = Field(gt=0)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)
    leverage: float = Field(gt=0)
    testnet: bool
    created_ts: int = Field(default_factory=_now_ms)


class Position(BaseModel):
    """An open position, as the system understands it.

    Reconciliation compares this against the exchange. Any divergence is a bug
    worth stopping for, not a rounding difference to shrug at.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    side: Side
    qty: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    leverage: float = Field(gt=0)
    liquidation_price: float = Field(gt=0)
    stop_order_id: str | None = Field(
        default=None, description="None means the position is unprotected -- the watchdog acts"
    )
    target_order_id: str | None = None
    opened_ts: int


class ClosedTrade(BaseModel):
    """A finished trade. The unit the history engine and the metrics both work on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str
    symbol: str
    side: Side
    state: TradeState
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    qty: float = Field(gt=0)
    opened_ts: int
    closed_ts: int
    gross_pnl: float
    fees: float = Field(ge=0)
    funding: float = Field(description="Signed; negative means the position paid")
    net_pnl: float
    r_multiple: float = Field(description="net_pnl divided by the cash that was at risk")
    snapshot_hash: str
