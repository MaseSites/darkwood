"""The backtest loop.

One rule shapes everything here: a decision taken at the close of bar *i* can
only be acted on from bar *i+1*. The engine asks the strategy at the close of each
signal bar, queues whatever comes back, and then steps through the *next* hour
minute by minute to see what happened to it. Filling within the same bar the
decision was made on is a quiet one-hour head start, and it is enough on its own
to turn a losing strategy into a winning backtest.

The minute loop is the expensive part -- roughly a million and a half iterations
over a couple of years -- so the M1 series is unpacked into numpy arrays once and
indexed positionally, rather than queried per hour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.config.settings import AppConfig
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import ExitReason, OrderType, Side, Timeframe
from traidingbrain.domain.market import FundingRate, SymbolSpec
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.history.engine import HistoryEngine
from traidingbrain.risk.leverage import choose_leverage
from traidingbrain.risk.sizing import costs_are_affordable, position_size, risk_budget
from traidingbrain.sim.broker import Fill, PendingEntry, SimBroker
from traidingbrain.sim.metrics import BacktestMetrics, compute_metrics, format_metrics


@dataclass(frozen=True)
class TradeIntent:
    """What a strategy wants to do, in prices.

    Sizing, leverage and the liquidation check are the engine's job, not the
    strategy's -- so a strategy cannot accidentally propose a position larger than
    the risk budget allows, and every strategy is measured under the same money
    management.
    """

    side: Side
    entry: float
    stop: float
    target: float
    confidence: float
    reason: str = ""

    @property
    def reward_risk(self) -> float:
        distance = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / distance if distance > 0 else 0.0

    @property
    def is_coherent(self) -> bool:
        if self.side is Side.LONG:
            return self.stop < self.entry < self.target
        return self.target < self.entry < self.stop


class Strategy(Protocol):
    """Anything that can look at a snapshot and want something."""

    name: str

    def propose(self, snapshot: MarketSnapshot) -> TradeIntent | None: ...


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    metrics: BacktestMetrics
    fills: list[Fill]
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    snapshots_built: int = 0
    intents: int = 0
    intents_rejected_by_risk: int = 0
    first_ts: int = 0
    last_ts: int = 0

    def summary(self) -> str:
        head = (
            f"{self.symbol} / {self.strategy}\n"
            f"  snapshots       {self.snapshots_built:,}\n"
            f"  intents         {self.intents:,} "
            f"({self.intents_rejected_by_risk:,} refused by risk rules)"
        )
        return head + "\n" + format_metrics(self.metrics)


class BacktestEngine:
    """Runs one strategy over one symbol."""

    def __init__(
        self,
        symbol: str,
        analysis: MultiFrameAnalysis,
        *,
        minute_frame: pd.DataFrame,
        spec: SymbolSpec,
        config: AppConfig,
        funding: list[FundingRate] | None = None,
        history: HistoryEngine | None = None,
    ) -> None:
        self.symbol = symbol
        self.analysis = analysis
        self.spec = spec
        self.config = config
        self.funding = funding or []
        self.history = history
        self._fills_seen = 0
        self.builder = SnapshotBuilder(symbol, analysis, config.engine)

        self.minute_ts = minute_frame["ts"].to_numpy(dtype="int64")
        self.minute_open = minute_frame["open"].to_numpy(dtype="float64")
        self.minute_high = minute_frame["high"].to_numpy(dtype="float64")
        self.minute_low = minute_frame["low"].to_numpy(dtype="float64")

    def run(
        self,
        strategy: Strategy,
        *,
        max_bars: int | None = None,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> BacktestResult:
        broker = SimBroker(self.spec, self.config.engine.simulation, self.funding)
        signal = self.analysis.signal
        signal_ms = timeframe_ms(self.config.engine.timeframes.signal)
        expiry_ms = self.config.engine.simulation.entry_expiry_bars * signal_ms

        start = self.analysis.first_ready_index()
        if start is None:
            return self._empty_result(strategy, broker)

        end = len(signal) - 1
        signal_ts = signal.frame["ts"].to_numpy(dtype="int64")

        # A time window rather than a bar count, so the same period can be asked
        # for across symbols and timeframes without translating indices by hand.
        if start_ts is not None:
            start = max(start, int(np.searchsorted(signal_ts, start_ts, side="left")))
        if end_ts is not None:
            end = min(end, int(np.searchsorted(signal_ts, end_ts, side="right")) - 1)
        if max_bars is not None:
            end = min(end, start + max_bars)
        if end <= start:
            return self._empty_result(strategy, broker)

        signal_close = signal.frame["close"].to_numpy(dtype="float64")

        snapshots = 0
        intents = 0
        refused = 0
        self._fills_seen = 0

        for index in range(start, end):
            # Only build a snapshot when it can actually be acted on. Building one
            # while a position is open costs milliseconds and changes nothing --
            # over twenty thousand bars that is most of the runtime.
            snapshot = self.builder.build(index) if broker.is_flat else None
            if snapshot is not None and self.history is not None:
                # Look up from the snapshot just built and fold the answer back in,
                # rather than building a second one. Two builds per bar doubled the
                # runtime of a full backtest for no extra information.
                stats, _quality = self.history.lookup(snapshot)
                snapshot = snapshot.model_copy(update={"history": stats})
            if snapshot is not None:
                snapshots += 1
                intent = strategy.propose(snapshot)
                if intent is not None and intent.is_coherent:
                    intents += 1
                    entry = self._to_entry(
                        intent,
                        snapshot,
                        equity=broker.equity,
                        created_ts=int(signal_ts[index]) + signal_ms,
                        expires_ts=int(signal_ts[index]) + signal_ms + expiry_ms,
                    )
                    if entry is None or not broker.submit(entry):
                        refused += 1
                    elif self.history is not None:
                        # Held aside, not indexed: the outcome does not exist yet.
                        self.history.remember(entry.proposal_id, snapshot)

            # The decision is live from the start of the next bar, never this one.
            self._step_minutes(
                broker,
                from_ms=int(signal_ts[index]) + signal_ms,
                to_ms=int(signal_ts[index + 1]) + signal_ms,
            )
            self._commit_resolved(broker)
            broker.mark(int(signal_ts[index + 1]), float(signal_close[index + 1]))

        # Anything still open at the end is closed at the last price rather than
        # left out. Dropping open trades from the statistics silently discards the
        # losers a strategy was still sitting in.
        if broker.position is not None:
            broker.close_at(float(signal_close[end]), int(signal_ts[end]), ExitReason.MANUAL)

        return BacktestResult(
            symbol=self.symbol,
            strategy=strategy.name,
            metrics=compute_metrics(
                strategy.name,
                broker.fills,
                broker.equity_curve,
                self.config.engine.simulation.initial_equity,
                expired_entries=broker.expired_entries,
                rejected_entries=broker.rejected_entries,
            ),
            fills=broker.fills,
            equity_curve=broker.equity_curve,
            snapshots_built=snapshots,
            intents=intents,
            intents_rejected_by_risk=refused,
            first_ts=int(signal_ts[start]),
            last_ts=int(signal_ts[end]),
        )

    # -- history ------------------------------------------------------------ #

    def _commit_resolved(self, broker: SimBroker) -> None:
        """Move newly closed trades into the index, and drop unfilled entries.

        An entry that expired without filling has no outcome; recording it as a
        zero would put a trade that never happened into the evidence.
        """
        if self.history is None:
            return
        while self._fills_seen < len(broker.fills):
            fill = broker.fills[self._fills_seen]
            self._fills_seen += 1
            self.history.resolve(
                fill.proposal_id, outcome_r=fill.r_multiple, resolved_ts=fill.closed_ts
            )

    # -- internals ---------------------------------------------------------- #

    def _step_minutes(self, broker: SimBroker, from_ms: int, to_ms: int) -> None:
        """Replay one signal bar, minute by minute -- unless there is nothing to replay.

        With no position and no resting order, walking sixty minutes changes
        nothing except the funding cursor, and the broker can move that in one
        step. The broker is flat for most of a backtest, so this is most of the
        minute loop.
        """
        if broker.is_flat:
            broker.skip_to(to_ms)
            return

        lo = int(np.searchsorted(self.minute_ts, from_ms, side="left"))
        hi = int(np.searchsorted(self.minute_ts, to_ms, side="left"))
        for i in range(lo, hi):
            broker.on_minute(
                int(self.minute_ts[i]),
                float(self.minute_open[i]),
                float(self.minute_high[i]),
                float(self.minute_low[i]),
            )

    def _to_entry(
        self,
        intent: TradeIntent,
        snapshot: MarketSnapshot,
        *,
        equity: float,
        created_ts: int,
        expires_ts: int,
    ) -> PendingEntry | None:
        """Turn a price plan into an order, or refuse it.

        Every refusal here is a risk rule doing its job: too little confidence, a
        reward-to-risk that does not pay for the losses, a position too small to
        place, or a stop so wide that liquidation would arrive before it.
        """
        risk_config = self.config.risk
        if intent.reward_risk < risk_config.limits.min_reward_risk:
            return None

        budget = risk_budget(
            intent.confidence,
            equity,
            risk_config.sizing,
            history_samples=snapshot.history.similar_situations_found,
        )
        if budget is None:
            return None

        size = position_size(intent.side, intent.entry, intent.stop, budget.risk_amount, self.spec)
        if not size.is_viable:
            return None

        # Costs scale with the position, risk does not. A stop tight enough to
        # make the round trip cost a large share of what is at stake is a trade
        # that cannot win, whatever happens next.
        affordable, _fraction = costs_are_affordable(
            size.notional,
            size.risk_amount,
            self.spec,
            self.config.engine.simulation.slippage_bps,
            risk_config.limits.max_cost_fraction_of_risk,
        )
        if not affordable:
            return None

        leverage = choose_leverage(
            intent.side,
            intent.entry,
            intent.stop,
            qty=size.qty,
            spec=self.spec,
            config=risk_config.leverage,
        )
        if leverage is None:
            return None

        return PendingEntry(
            proposal_id=f"{self.symbol}-{created_ts}",
            side=intent.side,
            order_type=OrderType.LIMIT,
            limit_price=intent.entry,
            stop=intent.stop,
            target=intent.target,
            qty=size.qty,
            leverage=leverage.leverage,
            created_ts=created_ts,
            expires_ts=expires_ts,
            risk_amount=size.risk_amount,
            snapshot_hash=snapshot.to_brain_input().content_hash(),
        )

    def _empty_result(self, strategy: Strategy, broker: SimBroker) -> BacktestResult:
        return BacktestResult(
            symbol=self.symbol,
            strategy=strategy.name,
            metrics=compute_metrics(
                strategy.name, [], [], self.config.engine.simulation.initial_equity
            ),
            fills=[],
        )


def load_engine(
    symbol: str,
    frames: dict[Timeframe, pd.DataFrame],
    *,
    minute_frame: pd.DataFrame,
    spec: SymbolSpec,
    config: AppConfig,
    funding: list[FundingRate] | None = None,
    history: HistoryEngine | None = None,
) -> BacktestEngine:
    return BacktestEngine(
        symbol,
        MultiFrameAnalysis(frames, config.engine),
        minute_frame=minute_frame,
        spec=spec,
        config=config,
        funding=funding,
        history=history,
    )
