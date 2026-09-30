"""The HTTP surface the dashboard talks to.

Deliberately, there is no endpoint here that sends an order. Confirming a proposal
claims it and hands back exactly what would be sent; the thing that talks to an
exchange arrives separately and is injected. Until then this whole service can be
run against a real account's data with no possibility of it placing a trade, which
is the right default for the stage where the interface is still being shaped.

The confirmation flow is three steps, and the split matters:

1. **Ask for a token.** The server re-prices the proposal against the current
   market first. If price has drifted past the tolerance, there is no token -- the
   trade you were looking at is not the trade that would be sent.
2. **Confirm with it.** The token is single-use and bound to the proposal's exact
   numbers, so adjusting anything invalidates it.
3. **Claim.** A compare-and-swap decides who actually proceeds. Two tabs, a
   double-click and a retried request all end here, and exactly one wins.

Adjusting a proposal returns a new one rather than editing in place. Changing the
leverage moves the liquidation price; changing the risk moves the size, which moves
the cost ratio. A patched field would leave the rest describing a trade that no
longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from traidingbrain.api.chart import ChartView, build_chart
from traidingbrain.api.market import MarketAnalysisCache, MarketView, build_market_view
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.proposal import FactorView, ProposalAdjustment, TradeProposal
from traidingbrain.proposals.builder import BuildFailure, ProposalBuilder, describe
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits

BPS = 1e-4


class PriceSource(Protocol):
    """Whatever can say what something costs right now."""

    def last_price(self, symbol: str) -> float | None: ...


class BarSource(Protocol):
    """Whatever can supply closed candles for a symbol.

    A protocol rather than the concrete store, so the chart endpoint can be tested
    against a handful of hand-built bars instead of a parquet directory.
    """

    def read(
        self,
        symbol: str,
        timeframe: Timeframe,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> pd.DataFrame: ...


class Executor(Protocol):
    """Whatever can actually place the order.

    A protocol with no implementation in this stage, on purpose. The service runs
    fully without one, and a confirmation then reports what would have been sent.
    """

    def send(self, proposal: TradeProposal) -> str: ...


@dataclass
class Services:
    """Everything the endpoints need, gathered so it can be swapped in tests."""

    config: AppConfig
    store: ProposalStore
    builder: ProposalBuilder
    limits: RiskLimits
    kill_switch: KillSwitch
    specs: dict[str, SymbolSpec] = field(default_factory=dict)
    prices: PriceSource | None = None
    bars: BarSource | None = None
    # Built lazily on the first market request: constructing it eagerly would
    # make every start-up pay for a page nobody may open.
    market: MarketAnalysisCache | None = None
    executor: Executor | None = None
    account: AccountState | None = None

    def spec_for(self, symbol: str) -> SymbolSpec:
        spec = self.specs.get(symbol)
        if spec is None:
            raise HTTPException(404, f"no instrument rules loaded for {symbol}")
        return spec

    def account_state(self) -> AccountState:
        if self.account is None:
            raise HTTPException(503, "no account state available yet")
        return self.account


# --------------------------------------------------------------------------- #
# Wire types
# --------------------------------------------------------------------------- #


class ProposalView(BaseModel):
    """A proposal as the dashboard shows it.

    Everything pre-computed. The interface should never be doing arithmetic that
    the risk layer has already done, because then there are two versions of the
    number and one of them is wrong.
    """

    id: str
    symbol: str
    side: str
    entry: float
    stop: float
    target: float
    qty: float
    leverage: float
    notional: float
    margin: float
    liquidation_price: float
    risk_amount: float
    risk_pct: float
    equity: float
    confidence: float
    bias: str
    risk_level: str
    reward_risk: float
    stop_distance_pct: float
    liquidation_buffer_r: float
    reasoning: list[str]
    invalidation_note: str
    expires_ts: int
    status: str
    # The arithmetic behind the confidence number. Sent with the proposal rather
    # than fetched separately: it is the answer to the first question anyone asks
    # about a confidence figure, and a second request would make it feel optional.
    factors: list[FactorView] = Field(default_factory=list)
    chartable: bool = False
    confidence_raw: float = 0.0
    confidence_cap_reason: str = ""

    @classmethod
    def of(cls, proposal: TradeProposal) -> ProposalView:
        return cls(
            id=proposal.id,
            symbol=proposal.symbol,
            side=proposal.side.value,
            entry=proposal.entry,
            stop=proposal.stop,
            target=proposal.target,
            qty=proposal.qty,
            leverage=proposal.leverage,
            notional=proposal.notional,
            margin=proposal.margin,
            liquidation_price=proposal.liquidation_price,
            risk_amount=proposal.risk_amount,
            risk_pct=proposal.risk_pct,
            equity=proposal.equity_at_build,
            confidence=proposal.confidence,
            bias=proposal.bias.value,
            risk_level=proposal.risk_level.value,
            reward_risk=proposal.reward_risk,
            stop_distance_pct=abs(proposal.entry - proposal.stop) / proposal.entry,
            liquidation_buffer_r=proposal.liquidation_buffer_r,
            reasoning=proposal.reasoning,
            invalidation_note=proposal.invalidation_note,
            factors=list(proposal.factors),
            chartable=proposal.is_chartable,
            confidence_raw=proposal.confidence_raw or proposal.confidence,
            confidence_cap_reason=proposal.confidence_cap_reason,
            expires_ts=proposal.expires_ts,
            status=proposal.status.value,
        )


class AdjustRequest(BaseModel):
    leverage: float | None = Field(default=None, gt=0)
    risk_pct: float | None = Field(default=None, gt=0, le=0.05)


class ConfirmRequest(BaseModel):
    token: str


class KillRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class SystemState(BaseModel):
    equity: float
    open_positions: int
    pending_proposals: int
    kill_switch_engaged: bool
    kill_switch_reason: str
    limits_allow_trading: bool
    limit_blockers: list[str]
    execution_connected: bool
    testnet: bool


# --------------------------------------------------------------------------- #
# The app
# --------------------------------------------------------------------------- #


def create_app(services: Services) -> FastAPI:
    app = FastAPI(
        title="traidingBrain",
        summary="Trade proposals awaiting a human decision",
        version="0.1.0",
    )

    dashboard = Path(__file__).resolve().parent.parent / "dashboard"
    if dashboard.exists():
        app.mount("/static", StaticFiles(directory=dashboard / "static"), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(dashboard / "templates" / "index.html")

    @app.get("/api/state", response_model=SystemState)
    def state() -> SystemState:
        account = services.account
        verdict = services.limits.check(account, symbol="") if account is not None else None
        return SystemState(
            equity=account.equity if account else 0.0,
            open_positions=len(account.open_positions) if account else 0,
            pending_proposals=len(services.store.list_pending()),
            kill_switch_engaged=services.kill_switch.is_engaged(),
            kill_switch_reason=services.kill_switch.reason(),
            limits_allow_trading=verdict.allowed if verdict else False,
            limit_blockers=verdict.blockers if verdict else ["no account state"],
            execution_connected=services.executor is not None,
            testnet=services.config.engine.exchange.testnet,
        )

    @app.get("/api/proposals", response_model=list[ProposalView])
    def pending() -> list[ProposalView]:
        return [ProposalView.of(p) for p in services.store.list_pending()]

    @app.get("/api/proposals/{proposal_id}", response_model=ProposalView)
    def one(proposal_id: str) -> ProposalView:
        return ProposalView.of(_require(services, proposal_id))

    _register_market_routes(app, services)

    @app.get("/api/proposals/{proposal_id}/chart", response_model=ChartView)
    def chart(proposal_id: str, timeframe: str | None = None) -> ChartView:
        """The bars and lines this decision was made on.

        Served from stored history rather than fetched live, and trimmed to end at
        the decision bar. A chart that runs to the present would be showing the
        reader what happened next, which is the one thing that makes it impossible
        to judge the argument on its own terms.
        """
        return _chart_for(services, proposal_id, timeframe)

    @app.post("/api/proposals/{proposal_id}/adjust", response_model=ProposalView)
    def adjust(proposal_id: str, change: AdjustRequest) -> ProposalView:
        """Re-price after the user lowers leverage or risk.

        Returns a fresh proposal with a new fingerprint, so any token issued for
        the previous version stops working. That is the mechanism that makes it
        impossible to look at one trade, adjust it, and confirm the first.
        """
        proposal = _require(services, proposal_id)
        rebuilt = services.builder.adjust(
            proposal,
            ProposalAdjustment(leverage=change.leverage, risk_pct=change.risk_pct),
            services.spec_for(proposal.symbol),
            services.account_state(),
        )
        if isinstance(rebuilt, BuildFailure):
            raise HTTPException(422, str(rebuilt))

        # The id and the clock carry over: this is the same opportunity, re-priced.
        # A new id would leave the original sitting on the dashboard alongside it,
        # and a reset expiry would let an adjustment quietly extend a stale offer.
        replacement = rebuilt.model_copy(
            update={
                "id": proposal.id,
                "created_ts": proposal.created_ts,
                "expires_ts": proposal.expires_ts,
            }
        )
        services.store.put(replacement)
        return ProposalView.of(replacement)

    @app.post("/api/proposals/{proposal_id}/token")
    def token(proposal_id: str) -> dict[str, Any]:
        """Issue a short-lived confirmation, after checking the price still holds.

        The drift check is the point. A proposal built minutes ago was priced
        against a market that has since moved; sending it would be executing a
        trade nobody agreed to.
        """
        proposal = _require(services, proposal_id)
        drift = _assert_priced_against_now(services, proposal)

        issued = services.store.issue_token(
            proposal, services.config.risk.execution.confirmation_token_ttl_seconds
        )
        return {
            "token": issued.token,
            "expires_ts": issued.expires_ts,
            "price_drift_bps": drift,
        }

    @app.post("/api/proposals/{proposal_id}/confirm")
    def confirm(proposal_id: str, request: ConfirmRequest) -> dict[str, Any]:
        """Spend the token, claim the proposal, and send -- if anything can send."""
        proposal = _require(services, proposal_id)

        if services.kill_switch.is_engaged():
            raise HTTPException(423, f"kill switch engaged: {services.kill_switch.reason()}")

        objection = services.store.consume_token(request.token, proposal)
        if objection is not None:
            raise HTTPException(409, objection)

        # The token was valid; this is what decides who actually proceeds.
        if not services.store.claim_for_execution(proposal.id):
            raise HTTPException(409, "this proposal is no longer pending")

        if services.executor is None:
            services.store.finish(
                proposal.id, ok=False, note="no execution connected; nothing was sent"
            )
            return {
                "sent": False,
                "reason": "execution is not connected in this build",
                "would_have_sent": describe(proposal),
            }

        try:
            reference = services.executor.send(proposal)
        except Exception as exc:
            services.store.finish(proposal.id, ok=False, note=f"send failed: {exc}")
            raise HTTPException(502, f"the exchange rejected the order: {exc}") from exc

        services.store.finish(proposal.id, ok=True, note=f"sent as {reference}")
        return {"sent": True, "reference": reference}

    @app.post("/api/proposals/{proposal_id}/reject")
    def reject(proposal_id: str) -> dict[str, bool]:
        return {"rejected": services.store.reject(proposal_id, "declined by the user")}

    @app.post("/api/kill")
    def kill(request: KillRequest) -> dict[str, str]:
        """Stop everything. Cleared only by hand."""
        services.kill_switch.engage(request.reason)
        return {"status": "engaged", "reason": request.reason}

    @app.delete("/api/kill")
    def release() -> dict[str, str]:
        services.kill_switch.release()
        return {"status": "released"}

    return app


def _register_market_routes(app: FastAPI, services: Services) -> None:
    """The browsing half of the surface, kept out of the confirmation half.

    Grouped rather than inlined because create_app is a route table, and a route
    table stops being readable once it is also a collection of handlers.
    """

    @app.get("/api/market", response_model=list[str])
    def symbols() -> list[str]:
        return _followed_symbols(services)

    @app.get("/api/market/{symbol}/chart", response_model=MarketView)
    def market(symbol: str, timeframe: str | None = None) -> MarketView:
        """The market right now, drawn the way the analysis reads it.

        No trade attached. Most hours have no setup, and a screen only worth
        opening when one appears is a screen nobody learns the market on.
        """
        return _market_for(services, symbol, timeframe)


def _followed_symbols(services: Services) -> list[str]:
    return list(services.config.engine.symbols.active)


def _offered_timeframes(services: Services) -> list[Timeframe]:
    """The frames worth charting: every context frame except the execution one.

    Minutes exist to resolve intrabar order, not to read a setup from, and a wall
    of them is not a timeframe anyone browses.
    """
    return [
        tf
        for tf in services.config.engine.timeframes.context
        if tf is not services.config.engine.timeframes.execution
    ]


def _market_for(services: Services, symbol: str, requested: str | None) -> MarketView:
    """Build the market view, saying which piece is missing when one is."""
    if services.bars is None or services.market is None:
        raise HTTPException(503, "no bar source is wired, so nothing can be charted")
    if symbol not in services.config.engine.symbols.active:
        raise HTTPException(
            404,
            f"{symbol} is not a symbol this build follows; "
            f"it watches {', '.join(services.config.engine.symbols.active)}",
        )

    offered = _offered_timeframes(services)
    timeframe = services.config.engine.timeframes.signal
    if requested is not None:
        match = next((tf for tf in offered if tf.value.lower() == requested.lower()), None)
        if match is None:
            raise HTTPException(
                404,
                f"{requested!r} is not a timeframe this analysis covers; "
                f"it reads {', '.join(tf.value for tf in offered)}",
            )
        timeframe = match

    built = services.market.latest_snapshot(symbol)
    if built is None:
        raise HTTPException(
            404,
            f"no analysable data for {symbol}; "
            f"run scripts/backfill.py {symbol} --since 2023-01-01",
        )
    snapshot, _analysis = built
    frame = services.bars.read(symbol, timeframe, until_ms=snapshot.ts)
    if frame.empty:
        raise HTTPException(404, f"no stored {timeframe.value} bars for {symbol}")
    return build_market_view(
        snapshot,
        frame,
        timeframe=timeframe,
        available=offered,
        trigger=services.config.engine.trigger,
    )


def _chart_for(services: Services, proposal_id: str, requested: str | None = None) -> ChartView:
    """Gather the bars and lines behind one proposal, on one timeframe.

    Each refusal is a different missing piece and says which: no bar source wired,
    a proposal from before charts existed, an unknown timeframe, or a symbol with
    nothing backfilled. Collapsing them into one error would send someone to check
    the wrong thing.
    """
    proposal = _require(services, proposal_id)
    if services.bars is None:
        raise HTTPException(503, "no bar source is wired, so nothing can be charted")
    if not proposal.is_chartable:
        raise HTTPException(
            409,
            "this proposal predates chart support and did not record which bar it was "
            "made on; a newly built proposal will chart normally",
        )

    # The execution frame is minutes and exists only to resolve intrabar order;
    # offering it here would be a wall of candles nobody reads a setup from.
    offered = [
        tf
        for tf in services.config.engine.timeframes.context
        if tf is not services.config.engine.timeframes.execution
    ]
    timeframe = proposal.signal_timeframe or services.config.engine.timeframes.signal
    if requested is not None:
        match = next((tf for tf in offered if tf.value.lower() == requested.lower()), None)
        if match is None:
            raise HTTPException(
                404,
                f"{requested!r} is not a timeframe this decision was made across; "
                f"it looked at {', '.join(tf.value for tf in offered)}",
            )
        timeframe = match

    frame = services.bars.read(proposal.symbol, timeframe, until_ms=proposal.snapshot_ts)
    if frame.empty:
        raise HTTPException(
            404,
            f"no stored {timeframe.value} bars for {proposal.symbol}; "
            f"run scripts/backfill.py {proposal.symbol}",
        )
    return build_chart(proposal, frame, timeframe=timeframe, available=offered)


def _require(services: Services, proposal_id: str) -> TradeProposal:
    proposal = services.store.get(proposal_id)
    if proposal is None:
        raise HTTPException(404, "no such proposal")
    return proposal


def _assert_priced_against_now(services: Services, proposal: TradeProposal) -> float | None:
    """Refuse a proposal the market has moved away from, and one it cannot check.

    Unknown is not the same as unchanged. While no executor is wired a missing
    price is merely a blank field on a screen; once one is armed, treating unknown
    as zero drift would send a proposal priced twenty minutes ago without ever
    testing it against the market.
    """
    drift = _price_drift(services, proposal)
    tolerance = services.config.risk.execution.max_price_drift_bps

    if drift is None:
        if services.executor is not None:
            raise HTTPException(
                409,
                "the current price could not be read, so this proposal cannot be "
                "checked against the market; refusing to issue a confirmation",
            )
        return None

    if abs(drift) > tolerance:
        raise HTTPException(
            409,
            f"price has moved {drift:+.1f} bps since this was priced "
            f"(tolerance {tolerance:.0f}); the proposal needs rebuilding rather "
            f"than confirming",
        )
    return drift


def _price_drift(services: Services, proposal: TradeProposal) -> float | None:
    """How far the market has moved from the proposed entry, in basis points."""
    if services.prices is None:
        return None
    current = services.prices.last_price(proposal.symbol)
    if current is None or proposal.entry <= 0:
        return None
    return (current - proposal.entry) / proposal.entry / BPS


def build_default_services(config: AppConfig | None = None) -> Services:
    """Wire the service together from configuration, with nothing that can trade."""
    settings = config or load_config()
    store = ParquetStore(settings.engine.paths.parquet_dir)
    kill_switch = KillSwitch(settings.engine.paths.data_dir / "KILL_SWITCH")
    limits = RiskLimits(settings.risk.limits, kill_switch)
    return Services(
        config=settings,
        store=ProposalStore(settings.engine.paths.db_path),
        bars=store,
        market=MarketAnalysisCache(store, settings.engine),
        builder=ProposalBuilder(settings, limits),
        limits=limits,
        kill_switch=kill_switch,
    )
