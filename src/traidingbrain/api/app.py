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

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from traidingbrain.api.chart import ChartView, build_chart
from traidingbrain.api.market import (
    MarketAnalysisCache,
    MarketView,
    build_market_view,
    setups_at,
)
from traidingbrain.api.paper import PaperReadout, build_paper_readout
from traidingbrain.api.portfolio import (
    CHART_CANDLES,
    Curve,
    Ledger,
    OpenTrade,
    Portfolio,
    PositionChart,
    SettingsView,
    TopUpRequest,
    build_curve,
    build_ledger,
    build_open,
    build_portfolio,
    build_position_chart,
    build_settings,
    reset_account,
    top_up,
)
from traidingbrain.api.scoring import ScoreRead, build_score_view
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.proposal import FactorView, ProposalAdjustment, TradeProposal
from traidingbrain.journal.record import Source
from traidingbrain.proposals.builder import BuildFailure, ProposalBuilder, describe
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits
from traidingbrain.risk.sizing import min_economic_stop_fraction

BPS = 1e-4


class NoCacheStatic(StaticFiles):
    """The dashboard's own files, never cached.

    Chrome happily serves a stale `app.js` after it changes, and the page then
    runs yesterday's code against today's markup -- which looks like a bug in
    whatever was just built rather than like a cache. It has cost real time here
    more than once, and the handover note carries a warning about it that this
    class is meant to make unnecessary.

    Nothing is given up. These files are served from this machine to this
    machine, they are tens of kilobytes, and the dashboard is the one surface
    where seeing the current version matters more than any load time.
    """

    def is_not_modified(self, *args: Any, **kwargs: Any) -> bool:
        return False

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


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
        """Instrument rules, or a 404 -- for the paths that cannot work without them.

        Sizing and order placement genuinely need tick size and fees, and a
        guess there would produce a rejected order or a wrong position. This
        raises for those.
        """
        spec = self.specs.get(symbol)
        if spec is None:
            raise HTTPException(404, f"no instrument rules loaded for {symbol}")
        return spec

    def optional_spec(self, symbol: str) -> SymbolSpec | None:
        """The same rules, for a caller that can live without them.

        The market view is one: it uses fees only to annotate whether a setup's
        stop is wide enough to be affordable, which is useful and not essential.
        Asking for the strict version there took the whole chart down with a
        404 whenever no exchange was connected -- which is the ordinary state of
        this build. An optional annotation must never be able to fail the page
        it decorates.
        """
        return self.specs.get(symbol)

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
        app.mount("/static", NoCacheStatic(directory=dashboard / "static"), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            # Same reasoning as NoCacheStatic: the page is served from this
            # machine to this machine, and a cached shell loading fresh scripts
            # is the worst of both.
            return FileResponse(
                dashboard / "templates" / "index.html",
                headers={"Cache-Control": "no-store"},
            )

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

    @app.get("/api/paper", response_model=PaperReadout)
    def paper() -> PaperReadout:
        """What the forward paper trader is holding and what it has closed.

        Read straight from the trader's two files rather than from the process,
        so the dashboard works whether or not it is running -- and says which,
        because an account last settled six hours ago looks exactly like a
        working one otherwise.
        """
        return build_paper_readout(
            services.config.engine.paths.data_dir / "paper.sqlite",
            services.config.engine.paths.data_dir / "journal.sqlite",
            config=services.config,
            now_ms=int(time.time() * 1000),
            symbols=_followed_symbols(services),
        )

    @app.get("/api/portfolio", response_model=Portfolio)
    def portfolio() -> Portfolio:
        """Das EINE Papierkonto, und was die Maerkte darauf beigetragen haben.

        Hier stand bis zum 14.10.2026 "every paper account side by side".
        Beides war ueberholt: es gibt ein Konto, und die Nutzlast traegt
        `markets` statt `accounts`. Ein Leser, der dem alten Satz glaubte,
        suchte Kontostaende je Markt -- und wer sie fand, summierte sie.
        """
        return build_portfolio(
            _state_path(services),
            _journal_path(services),
            services.config,
            now_ms=int(time.time() * 1000),
        )

    @app.get("/api/portfolio/open", response_model=list[OpenTrade])
    def open_trades() -> list[OpenTrade]:
        """Every position still running, with where it stands right now."""
        return build_open(_state_path(services), services.config, now_ms=int(time.time() * 1000))

    @app.get("/api/portfolio/open/{symbol}/chart", response_model=PositionChart)
    def open_chart(
        symbol: str, tf: str | None = None, candles: int = CHART_CANDLES
    ) -> PositionChart:
        """The candles behind one running trade, with its stop and target.

        `tf` switches the timeframe, `candles` how many bars come back. Both
        default to what the page showed before the interactive chart existed,
        so an old caller gets the old answer.

        Eine unbekannte Ebene ist 404 und nicht stillschweigend die
        Vorgabeebene: wer M5 anfragt und M15 bekaeme, wuerde die falschen
        Kerzen fuer die richtigen halten.
        """
        _known(services, symbol)
        chart = build_position_chart(
            _state_path(services), services.config, symbol, timeframe=tf, candles=candles
        )
        if chart is None:
            raise HTTPException(
                404, f"{symbol} has no open position, or no candles on {tf or 'its frame'}"
            )
        return chart

    @app.get("/api/portfolio/ledger", response_model=Ledger)
    def ledger(source: str = "live", symbol: str | None = None) -> Ledger:
        """Every trade of one kind, newest first.

        One kind, never both. A list that mixed replayed with forward trades
        would invite exactly the average this project refuses to compute.
        """
        return build_ledger(_journal_path(services), source=_source(source), symbol=symbol)

    @app.get("/api/portfolio/curve", response_model=Curve)
    def curve(source: str = "live") -> Curve:
        """The running total in R, with how far it fell below its own peak."""
        return build_curve(_journal_path(services), source=_source(source))

    @app.get("/api/portfolio/settings", response_model=SettingsView)
    def settings() -> SettingsView:
        """What the engine is configured to do. Read-only on purpose."""
        return build_settings(services.config)

    @app.post("/api/portfolio/topup")
    def topup(request: TopUpRequest) -> dict[str, Any]:
        """Papiergeld auf DAS Konto legen.

        Ohne Symbol, und das ist der Punkt: es gibt ein Konto. Bis zum
        14.10.2026 lautete der Pfad `/api/portfolio/{symbol}/topup` und legte
        Geld auf einen Markt -- eine Handlung, die es unter einer geteilten
        Kasse nicht gibt.

        Papier. Es gibt von hier keinen Pfad zu einer Boerse, und der Betrag
        wird addiert statt gesetzt.
        """
        return {"equity": top_up(_state_path(services), services.config, request.amount)}

    @app.post("/api/portfolio/reset")
    def reset_all() -> dict[str, Any]:
        """Das ganze Konto von vorn: alle Maerkte vergessen, Kasse auf den Einsatz.

        Das Journal bleibt unberuehrt -- was passiert ist, ist passiert.
        """
        return {"equity": reset_account(_state_path(services), services.config)}

    @app.post("/api/portfolio/{symbol}/reset")
    def reset(symbol: str) -> dict[str, Any]:
        """Den ARBEITSSTAND eines Marktes vergessen, nicht seinen Kontostand.

        Unter einer Kasse hat ein Markt keinen Kontostand. Was hier faellt,
        sind Zaehler, offene Position und letzter Kurs dieses Marktes.
        """
        _known(services, symbol)
        cleared = reset_account(_state_path(services), services.config, symbol)
        return {"symbol": symbol, "equity": cleared}

    @app.get("/api/market/{symbol}/score", response_model=ScoreRead)
    def score(symbol: str) -> ScoreRead:
        """Every indicator, reconciled by family, across every timeframe.

        Its own request rather than part of the chart. Building the indicator
        bank over five frames takes about ten seconds the first time a symbol
        is opened, and putting that in front of the chart would mean an empty
        screen for all of it -- which is the thing this dashboard was rebuilt
        to stop doing.
        """
        return _score_for(services, symbol)


def _state_path(services: Services) -> Path:
    return services.config.engine.paths.data_dir / "paper.sqlite"


def _journal_path(services: Services) -> Path:
    return services.config.engine.paths.data_dir / "journal.sqlite"


def _source(value: str) -> Source:
    """The journal kind named in a query string, or a 400.

    Not a default: asking for a kind that does not exist is a caller bug, and
    quietly serving the other one is how a screen ends up showing replayed
    trades under a heading that says forward.
    """
    try:
        return Source(value)
    except ValueError:
        raise HTTPException(400, f"unknown source {value!r}; use live or replay") from None


def _known(services: Services, symbol: str) -> None:
    """Refuse a symbol nobody follows, so a typo cannot create an account."""
    if symbol not in services.config.engine.symbols.active:
        raise HTTPException(404, f"{symbol} is not one of the followed markets")


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


def _cost_floor(services: Services, symbol: str) -> float:
    """The stop distance below which a trade cannot be afforded, or zero.

    Zero means "unknown", and the panel then shows no affordability note at
    all -- which is honest. Substituting typical fees would put a number on the
    screen that looks measured and is not.
    """
    spec = services.optional_spec(symbol)
    if spec is None:
        return 0.0
    return min_economic_stop_fraction(
        spec,
        services.config.engine.simulation.slippage_bps,
        services.config.risk.limits.max_cost_fraction_of_risk,
    )


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
            f"no analysable data for {symbol}; run scripts/backfill.py {symbol} --since 2023-01-01",
        )
    snapshot, analysis = built
    frame = services.bars.read(symbol, timeframe, until_ms=snapshot.ts)
    if frame.empty:
        raise HTTPException(404, f"no stored {timeframe.value} bars for {symbol}")
    return build_market_view(
        snapshot,
        frame,
        timeframe=timeframe,
        available=offered,
        trigger=services.config.engine.trigger,
        setups=setups_at(analysis, snapshot.ts),
        min_stop=_cost_floor(services, symbol),
        analysis=analysis,
    )


def _score_for(services: Services, symbol: str) -> ScoreRead:
    """The reading for the bar the chart is drawn for."""
    if services.market is None:
        raise HTTPException(503, "no bar source is wired, so nothing can be scored")
    if symbol not in services.config.engine.symbols.active:
        raise HTTPException(404, f"{symbol} is not a symbol this build follows")

    built = services.market.latest_snapshot(symbol)
    if built is None:
        raise HTTPException(
            404,
            f"no analysable data for {symbol}; run scripts/backfill.py {symbol} --since 2023-01-01",
        )
    snapshot, analysis = built
    view = build_score_view(symbol, analysis, snapshot.ts)
    if view is None:
        raise HTTPException(409, "the timeframes are still warming up on this bar")
    return view


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
