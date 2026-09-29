"""The live loop.

The property worth testing is that it runs the same pipeline the backtest ran. If
this module reimplemented the snapshot builder, the gate or the risk rules, the
backtest would stop being evidence about what actually happens -- and that is a
failure nobody would notice until the live results diverged.

The rest is robustness: a loop that dies on one bad API response stops watching the
market, which is worse than missing a bar.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH, fast_engine_config, multi_frame_fixture
from traidingbrain.brain.fake import FakeBrain
from traidingbrain.clock import FixedClock
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.frames import frame_to_bars, timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import Bar, FundingRate, SymbolSpec
from traidingbrain.live.loop import LiveLoop, next_close
from traidingbrain.proposals.builder import ProposalBuilder
from traidingbrain.proposals.store import ProposalStore
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits


class ReplaySource:
    """Serves a fixed history, and can be told to fail."""

    def __init__(self, frames: dict[Timeframe, pd.DataFrame]) -> None:
        self.bars = {tf: frame_to_bars(frame) for tf, frame in frames.items()}
        self.fail_next = False
        self.calls = 0

    def fetch_ohlcv(
        self, symbol: str, timeframe: Timeframe, since_ms: int, limit: int
    ) -> list[Bar]:
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("exchange unreachable")
        window = [b for b in self.bars.get(timeframe, []) if b.ts >= since_ms]
        return window[-limit:] if window else []

    def fetch_funding(self, symbol: str, since_ms: int, limit: int) -> list[FundingRate]:
        return []

    def fetch_symbol_spec(self, symbol: str) -> SymbolSpec:
        return make_symbol_spec()


@pytest.fixture(scope="module")
def config() -> AppConfig:
    base = load_config()
    return base.model_copy(update={"engine": fast_engine_config()})


@pytest.fixture(scope="module")
def frames() -> dict[Timeframe, pd.DataFrame]:
    return multi_frame_fixture(6000)


def build_loop(
    tmp_path: Path,
    config: AppConfig,
    frames: dict[Timeframe, pd.DataFrame],
    *,
    now_ms: int,
) -> tuple[LiveLoop, ProposalStore, ReplaySource]:
    store = ParquetStore(tmp_path / "ohlcv")
    for timeframe, frame in frames.items():
        store.write("TESTUSDT", timeframe, frame)

    proposals = ProposalStore(tmp_path / "proposals.sqlite")
    switch = KillSwitch(tmp_path / "KILL")
    limits = RiskLimits(config.risk.limits, switch)
    source = ReplaySource(frames)

    loop = LiveLoop(
        "TESTUSDT",
        config,
        source=source,
        store=store,
        proposals=proposals,
        builder=ProposalBuilder(config, limits),
        brain=FakeBrain(config),
        spec=make_symbol_spec(),
        clock=FixedClock(now_ms),
        account=lambda: AccountState(
            equity=10_000.0,
            starting_equity_today=10_000.0,
            starting_equity_this_week=10_000.0,
            open_positions=[],
            recent_trades=[],
            now_ms=now_ms,
        ),
    )
    return loop, proposals, source


@pytest.fixture
def wired(tmp_path: Path, config: AppConfig, frames: dict[Timeframe, pd.DataFrame]):
    latest = int(frames[Timeframe.H1]["ts"].iloc[-1])
    return build_loop(tmp_path, config, frames, now_ms=latest + timeframe_ms(Timeframe.H1))


# --------------------------------------------------------------------------- #
# The cycle
# --------------------------------------------------------------------------- #


def test_a_cycle_runs_the_whole_pipeline(wired) -> None:
    loop, _proposals, _source = wired

    loop.step()

    assert loop.stats.cycles == 1
    assert loop.stats.bars_seen == 1
    assert loop.stats.snapshots == 1, "no snapshot was built from a complete history"


def test_the_same_bar_is_not_decided_twice(wired) -> None:
    """Polling every twenty seconds means most cycles see nothing new.

    Re-deciding the same bar would produce a duplicate proposal each poll, and the
    dashboard would fill with the same trade.
    """
    loop, _proposals, _source = wired

    loop.step()
    loop.step()
    loop.step()

    assert loop.stats.cycles == 3
    assert loop.stats.bars_seen == 1


def test_a_failed_fetch_does_not_end_the_loop(wired) -> None:
    """A loop that dies on one bad response stops watching the market."""
    loop, _proposals, source = wired
    source.fail_next = True

    assert loop.step() is None
    assert loop.stats.errors, "the failure was swallowed without a record"

    loop.step()
    assert loop.stats.bars_seen == 1, "the loop did not recover"


def test_the_gate_runs_before_the_brain(wired) -> None:
    """The expensive call happens only on bars that passed a cheap filter."""
    loop, _proposals, _source = wired

    loop.step()

    assert loop.trigger.stats.seen == loop.stats.snapshots
    assert loop.stats.asked <= loop.stats.snapshots


def test_a_proposal_reaches_the_store_and_nothing_else(wired) -> None:
    """The loop proposes. Confirming is somebody else's job, in another process."""
    loop, proposals, _source = wired

    for _ in range(3):
        loop.step()

    stored = proposals.list_pending()
    assert len(stored) == loop.stats.proposed
    for proposal in stored:
        assert proposal.status.value == "pending"


def test_no_data_means_no_decision(
    tmp_path: Path, config: AppConfig, frames: dict[Timeframe, pd.DataFrame]
) -> None:
    loop, _proposals, _source = build_loop(tmp_path, config, {}, now_ms=EPOCH)

    assert loop.step() is None
    assert loop.stats.snapshots == 0


# --------------------------------------------------------------------------- #
# Timing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("timeframe", "minutes"),
    [(Timeframe.H1, 60), (Timeframe.M15, 15), (Timeframe.H4, 240)],
)
def test_the_next_close_lands_on_the_grid(timeframe: Timeframe, minutes: int) -> None:
    """A status line that says the wrong time is worse than none."""
    step = minutes * 60_000
    mid_bar = EPOCH + step // 3

    closes = next_close(timeframe, mid_bar)

    assert int(closes.timestamp() * 1000) == EPOCH + step
