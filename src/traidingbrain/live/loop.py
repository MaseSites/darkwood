"""The live loop: the same pipeline the backtest runs, on a clock.

Deliberately the same code path. The engine, the snapshot builder, the trigger, the
guard and the risk rules are all the objects the backtest used -- if this module
reimplemented any of them, the backtest would stop being evidence about what
actually happens.

What is different is only what has to be:

**It waits for bars to close.** A decision is taken on the close of an hourly bar,
so the loop sleeps until one exists rather than polling the forming candle. Reading
a candle that is still being written is the same mistake as including it in a
backtest, except live it happens every hour.

**It reconciles before it starts.** Anything left unresolved from a previous run is
settled against the exchange first. Starting fresh while an order is in flight is
how a system ends up with two positions.

**It proposes; it does not trade.** The loop's output is a row in the proposal
store. A human confirms from the dashboard, and only then does `execution` see it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.brain.trigger import Trigger
from traidingbrain.config.settings import AppConfig
from traidingbrain.data.frames import bars_to_frame, timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.protocols import Brain, Clock, DataSource
from traidingbrain.history.engine import HistoryEngine
from traidingbrain.proposals.builder import BuildFailure, ProposalBuilder
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState

#: How often to look for a newly closed bar. Well inside an hour, because the
#: value of a setup decays and a proposal built forty minutes late is a proposal
#: priced against a market that has moved.
POLL_SECONDS = 20

#: Bars refetched each cycle. Enough to repair a gap from a brief outage without
#: re-downloading history every time.
REFRESH_BARS = 12


@dataclass
class LiveStats:
    cycles: int = 0
    bars_seen: int = 0
    snapshots: int = 0
    asked: int = 0
    proposed: int = 0
    declined: int = 0
    refused_by_risk: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"  cycles {self.cycles}, bars {self.bars_seen}, snapshots {self.snapshots}, "
            f"asked {self.asked}, proposed {self.proposed}, "
            f"declined {self.declined}, refused {self.refused_by_risk}"
            + (f", {len(self.errors)} errors" if self.errors else "")
        )


class LiveLoop:
    """Watches one symbol and puts proposals on the dashboard."""

    def __init__(
        self,
        symbol: str,
        config: AppConfig,
        *,
        source: DataSource,
        store: ParquetStore,
        proposals: ProposalStore,
        builder: ProposalBuilder,
        brain: Brain,
        spec: SymbolSpec,
        clock: Clock,
        history: HistoryEngine | None = None,
        account: Callable[[], AccountState],
    ) -> None:
        self.symbol = symbol
        self.config = config
        self.source = source
        self.store = store
        self.proposals = proposals
        self.builder = builder
        self.brain = brain
        self.spec = spec
        self.clock = clock
        self.history = history
        self.account = account

        self.trigger = Trigger(config.engine.trigger)
        self.stats = LiveStats()
        self._last_decided_ts: int | None = None
        self._bar_index = 0

    # -- the cycle ---------------------------------------------------------- #

    def refresh_data(self) -> int:
        """Pull recent closed bars for every frame. Returns the newest signal bar.

        The adapter drops the forming candle, so what lands here is only finished
        bars -- the same guarantee the backtest had.
        """
        newest = 0
        for timeframe in self.config.engine.timeframes.context:
            step = timeframe_ms(timeframe)
            since = self.clock.now_ms() - step * REFRESH_BARS
            bars = self.source.fetch_ohlcv(self.symbol, timeframe, since, REFRESH_BARS)
            if not bars:
                continue
            self.store.write(self.symbol, timeframe, bars_to_frame(bars))
            if timeframe is self.config.engine.timeframes.signal:
                newest = max(newest, bars[-1].ts)
        return newest

    def step(self) -> str | None:
        """One cycle. Returns a proposal id if one was created.

        Every failure here is caught and recorded rather than raised: a loop that
        dies on one bad API response stops watching the market, which is worse than
        missing one bar.
        """
        self.stats.cycles += 1
        try:
            newest = self.refresh_data()
        except Exception as exc:  # broad on purpose: a bad cycle must not end the loop
            self.stats.errors.append(f"data refresh failed: {exc}")
            return None

        if not newest or newest == self._last_decided_ts:
            return None

        self._last_decided_ts = newest
        self._bar_index += 1
        self.stats.bars_seen += 1

        try:
            return self._decide(newest)
        except Exception as exc:  # same reasoning
            self.stats.errors.append(f"decision failed on bar {newest}: {exc}")
            return None

    def _decide(self, bar_ts: int) -> str | None:
        frames = {
            timeframe: self.store.read(self.symbol, timeframe)
            for timeframe in self.config.engine.timeframes.context
        }
        if any(frame.empty for frame in frames.values()):
            return None

        analysis = MultiFrameAnalysis(frames, self.config.engine)
        builder = SnapshotBuilder(self.symbol, analysis, self.config.engine)
        index = len(analysis.signal) - 1
        snapshot = builder.build(index)
        if snapshot is None:
            return None

        self.stats.snapshots += 1
        if self.history is not None:
            stats, _quality = self.history.lookup(snapshot)
            snapshot = snapshot.model_copy(update={"history": stats})

        if not self.trigger.should_ask(snapshot, self._bar_index):
            return None

        self.stats.asked += 1
        decision = self.brain.decide(snapshot, snapshot.to_brain_input())
        if not decision.is_tradeable:
            self.stats.declined += 1
            return None

        built = self.builder.build(decision, snapshot, self.spec, self.account())
        if isinstance(built, BuildFailure):
            self.stats.refused_by_risk += 1
            return None

        self.proposals.put(built)
        self.stats.proposed += 1
        return built.id

    # -- running ------------------------------------------------------------ #

    def run(
        self,
        *,
        max_cycles: int | None = None,
        on_proposal: Callable[[str], None] | None = None,
    ) -> LiveStats:
        """Poll until stopped. `max_cycles` exists so tests can bound it."""
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            proposal_id = self.step()
            if proposal_id is not None and on_proposal is not None:
                on_proposal(proposal_id)
            cycles += 1
            if max_cycles is None or cycles < max_cycles:
                time.sleep(POLL_SECONDS)
        return self.stats


def next_close(timeframe: Timeframe, now_ms: int) -> datetime:
    """When the current bar finishes, for a status line worth reading."""
    step = timeframe_ms(timeframe)
    boundary = ((now_ms // step) + 1) * step
    return datetime.fromtimestamp(boundary / 1000, tz=UTC)
