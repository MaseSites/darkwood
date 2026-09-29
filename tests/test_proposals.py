"""Proposals, limits, and the confirmation mechanics.

The most important test in this file fires a hundred simultaneous confirmations at
one proposal and demands that exactly one wins. That is the failure the whole
design is arranged around: a double-click, a retried request, two browser tabs --
any of them can produce two confirmations of the same trade within microseconds of
each other, and the result must never be two positions.

The token is not what prevents it. Two requests can both read a token and both
find it valid. What prevents it is the compare-and-swap: only one
`UPDATE ... WHERE status = 'pending'` can report a changed row.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.factories import make_snapshot, make_symbol_spec
from traidingbrain.brain.fake import FakeBrain
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Decision, ProposalStatus, Side, TradeState
from traidingbrain.domain.proposal import ClosedTrade, Position, ProposalAdjustment
from traidingbrain.proposals.builder import BuildFailure, ProposalBuilder, describe
from traidingbrain.proposals.store import ProposalStore, fingerprint
from traidingbrain.risk.limits import AccountState, KillSwitch, RiskLimits

NOW = 1_700_000_000_000
HOUR = 3_600_000
DAY = 24 * HOUR


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


@pytest.fixture
def account() -> AccountState:
    return AccountState(
        equity=10_000.0,
        starting_equity_today=10_000.0,
        starting_equity_this_week=10_000.0,
        open_positions=[],
        recent_trades=[],
        now_ms=NOW,
    )


@pytest.fixture
def store(tmp_path: Path) -> ProposalStore:
    return ProposalStore(tmp_path / "proposals.sqlite")


def closed(pnl: float, hours_ago: float) -> ClosedTrade:
    """A closed trade with a chosen net result.

    Prices are kept plausible independently of the size of the result: a 550-unit
    loss on a 100-unit instrument is a large position, not a negative price.
    """
    return ClosedTrade(
        proposal_id="p",
        symbol="BTCUSDT",
        side=Side.LONG,
        state=TradeState.CLOSED_TARGET if pnl > 0 else TradeState.CLOSED_STOP,
        entry_price=100.0,
        exit_price=100.0 + (1.0 if pnl > 0 else -1.0),
        qty=1.0,
        opened_ts=NOW - int(hours_ago * HOUR) - HOUR,
        closed_ts=NOW - int(hours_ago * HOUR),
        gross_pnl=pnl,
        fees=0.0,
        funding=0.0,
        net_pnl=pnl,
        r_multiple=pnl / 100.0,
        snapshot_hash="h",
    )


def position(symbol: str = "BTCUSDT") -> Position:
    return Position(
        symbol=symbol,
        side=Side.LONG,
        qty=1.0,
        entry_price=100.0,
        leverage=5.0,
        liquidation_price=82.0,
        opened_ts=NOW,
    )


def build_one(config: AppConfig, account: AccountState):
    builder = ProposalBuilder(config, RiskLimits(config.risk.limits))
    decision = FakeBrain(config).decide(make_snapshot())
    return builder.build(decision, make_snapshot(), make_symbol_spec(), account), decision


# --------------------------------------------------------------------------- #
# Building a proposal
# --------------------------------------------------------------------------- #


def test_a_proposal_is_internally_coherent(config: AppConfig, account: AccountState) -> None:
    """Every number checked against every other, because the model typed none of them."""
    proposal, _ = build_one(config, account)
    if isinstance(proposal, BuildFailure):
        pytest.skip(f"the fake brain declined here: {proposal}")

    assert proposal.notional == pytest.approx(proposal.qty * proposal.entry)
    assert proposal.margin == pytest.approx(proposal.notional / proposal.leverage, rel=1e-6)
    assert proposal.risk_amount == pytest.approx(
        proposal.qty * abs(proposal.entry - proposal.stop), rel=1e-6
    )
    assert proposal.risk_amount == pytest.approx(
        proposal.equity_at_build * proposal.risk_pct, rel=0.05
    )


def test_liquidation_always_sits_beyond_the_stop(config: AppConfig, account: AccountState) -> None:
    """The invariant that makes leverage safe, checked at the type level too.

    `TradeProposal` refuses to construct otherwise, so this is belt and braces --
    which is appropriate for the one thing that turns a 1% loss into a 100% loss.
    """
    proposal, _ = build_one(config, account)
    if isinstance(proposal, BuildFailure):
        pytest.skip(str(proposal))

    if proposal.side is Side.LONG:
        assert proposal.liquidation_price < proposal.stop
    else:
        assert proposal.liquidation_price > proposal.stop
    assert proposal.liquidation_buffer_r >= config.risk.leverage.min_liquidation_buffer_r * 0.9


def test_a_declined_analysis_produces_a_reason_not_a_trade(
    config: AppConfig, account: AccountState
) -> None:
    builder = ProposalBuilder(config, RiskLimits(config.risk.limits))
    decision = FakeBrain(config).decide(make_snapshot())
    waiting = decision.model_copy(
        update={"verdict": decision.verdict.model_copy(update={"decision": Decision.WAIT})}
    )

    result = builder.build(waiting, make_snapshot(), make_symbol_spec(), account)

    assert isinstance(result, BuildFailure)
    assert "did not produce a trade" in result.reason


def test_a_stop_too_tight_for_its_costs_is_refused(
    config: AppConfig, account: AccountState
) -> None:
    """The rule that turned both strategies from losing to positive.

    Position size is risk over stop distance, so fees scale with the position while
    the risk stays fixed. The refusal has to say that, not just "no".
    """
    builder = ProposalBuilder(config, RiskLimits(config.risk.limits))
    decision = FakeBrain(config).decide(make_snapshot())
    if decision.plan is None:
        pytest.skip("the fake brain declined here")

    hair_trigger = decision.plan.model_copy(
        update={"stop": decision.plan.entry - decision.plan.entry * 0.0002}
    )
    result = builder.build(
        decision.model_copy(update={"plan": hair_trigger}),
        make_snapshot(),
        make_symbol_spec(),
        account,
    )

    assert isinstance(result, BuildFailure)
    assert "costs" in result.reason


def test_the_description_names_every_number_that_matters(
    config: AppConfig, account: AccountState
) -> None:
    proposal, _ = build_one(config, account)
    if isinstance(proposal, BuildFailure):
        pytest.skip(str(proposal))

    text = describe(proposal)
    for label in ("entry", "stop", "target", "size", "margin", "at risk", "liquidation"):
        assert label in text


# --------------------------------------------------------------------------- #
# Adjusting
# --------------------------------------------------------------------------- #


def test_lowering_leverage_widens_the_liquidation_buffer(
    config: AppConfig, account: AccountState
) -> None:
    """The change the user actually asked for: 5x to 4x.

    Lowering is always safe, and this says why -- the exchange's exit moves
    further away.
    """
    builder = ProposalBuilder(config, RiskLimits(config.risk.limits))
    proposal, _ = build_one(config, account)
    if isinstance(proposal, BuildFailure) or proposal.leverage < 2:
        pytest.skip("no headroom to lower leverage in this setup")

    lowered = builder.adjust(
        proposal,
        ProposalAdjustment(leverage=proposal.leverage - 1),
        make_symbol_spec(),
        account,
    )

    assert not isinstance(lowered, BuildFailure), str(lowered)
    assert lowered.leverage == proposal.leverage - 1
    assert lowered.liquidation_buffer_r > proposal.liquidation_buffer_r
    assert lowered.qty == pytest.approx(proposal.qty), "leverage must not change the size"
    assert lowered.risk_amount == pytest.approx(proposal.risk_amount), (
        "leverage must not change what is at risk"
    )


def test_raising_leverage_is_refused(config: AppConfig, account: AccountState) -> None:
    builder = ProposalBuilder(config, RiskLimits(config.risk.limits))
    proposal, _ = build_one(config, account)
    if isinstance(proposal, BuildFailure):
        pytest.skip(str(proposal))

    result = builder.adjust(
        proposal, ProposalAdjustment(leverage=proposal.leverage + 5), make_symbol_spec(), account
    )

    assert isinstance(result, BuildFailure)
    assert "not allowed" in result.reason


def test_raising_the_risk_is_refused(config: AppConfig, account: AccountState) -> None:
    builder = ProposalBuilder(config, RiskLimits(config.risk.limits))
    proposal, _ = build_one(config, account)
    if isinstance(proposal, BuildFailure):
        pytest.skip(str(proposal))

    result = builder.adjust(
        proposal, ProposalAdjustment(risk_pct=0.05), make_symbol_spec(), account
    )

    assert isinstance(result, BuildFailure)
    assert "lowered" in result.reason


def test_lowering_the_risk_shrinks_the_position(config: AppConfig, account: AccountState) -> None:
    builder = ProposalBuilder(config, RiskLimits(config.risk.limits))
    proposal, _ = build_one(config, account)
    if isinstance(proposal, BuildFailure):
        pytest.skip(str(proposal))

    halved = builder.adjust(
        proposal, ProposalAdjustment(risk_pct=proposal.risk_pct / 2), make_symbol_spec(), account
    )

    assert not isinstance(halved, BuildFailure), str(halved)
    assert halved.qty < proposal.qty
    assert halved.risk_amount == pytest.approx(proposal.risk_amount / 2, rel=0.05)


# --------------------------------------------------------------------------- #
# Limits
# --------------------------------------------------------------------------- #


def test_an_open_position_blocks_another_in_the_same_symbol(
    config: AppConfig, account: AccountState
) -> None:
    limits = RiskLimits(config.risk.limits)
    account.open_positions = [position("BTCUSDT")]

    verdict = limits.check(account, symbol="BTCUSDT")

    assert not verdict.allowed
    assert "BTCUSDT" in verdict.reason


def test_the_daily_loss_limit_stops_trading(config: AppConfig, account: AccountState) -> None:
    """Measured against equity at the start of the day, not current equity.

    Otherwise the allowance shrinks as losses accumulate and the limit is never
    quite reached.
    """
    limits = RiskLimits(config.risk.limits)
    allowance = 10_000.0 * config.risk.limits.max_daily_loss_pct
    account.recent_trades = [closed(-allowance * 1.1, hours_ago=2)]

    verdict = limits.check(account, symbol="BTCUSDT")

    assert not verdict.allowed
    assert "daily limit" in verdict.reason


def test_a_losing_streak_triggers_a_cooldown(config: AppConfig, account: AccountState) -> None:
    """The moment after three losses is when judgement is worst and conviction
    highest. That is what this is for."""
    limits = RiskLimits(config.risk.limits)
    streak = config.risk.limits.cooldown_after_consecutive_losses
    account.recent_trades = [closed(-10.0, hours_ago=i + 1) for i in range(streak)]

    verdict = limits.check(account, symbol="BTCUSDT")

    assert not verdict.allowed
    assert "in a row" in verdict.reason
    assert limits.cooldown_ends_at(account) is not None


def test_a_win_breaks_the_streak(config: AppConfig, account: AccountState) -> None:
    limits = RiskLimits(config.risk.limits)
    streak = config.risk.limits.cooldown_after_consecutive_losses
    account.recent_trades = [closed(-10.0, hours_ago=i + 2) for i in range(streak)]
    account.recent_trades.append(closed(+5.0, hours_ago=1))

    assert account.consecutive_losses() == 0
    assert limits.check(account, symbol="BTCUSDT").allowed


def test_the_kill_switch_overrides_everything(
    config: AppConfig, account: AccountState, tmp_path: Path
) -> None:
    """A file, so it can be set from anywhere -- including by someone who cannot
    reach the running system any other way."""
    switch = KillSwitch(tmp_path / "KILL")
    limits = RiskLimits(config.risk.limits, switch)

    assert limits.check(account, symbol="BTCUSDT").allowed

    switch.engage("stopping for the day")
    verdict = limits.check(account, symbol="BTCUSDT")

    assert not verdict.allowed
    assert "kill switch" in verdict.reason
    assert "stopping for the day" in verdict.reason


def test_the_kill_switch_only_clears_by_hand(tmp_path: Path) -> None:
    """A switch that resets on a timer or on restart turns itself back on at the
    worst possible moment."""
    switch = KillSwitch(tmp_path / "KILL")
    switch.engage("because")
    assert KillSwitch(tmp_path / "KILL").is_engaged()

    switch.release()
    assert not switch.is_engaged()


# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #


def stored_proposal(config: AppConfig, account: AccountState, store: ProposalStore):
    proposal, _ = build_one(config, account)
    if isinstance(proposal, BuildFailure):
        pytest.skip(str(proposal))
    store.put(proposal)
    return proposal


def test_only_one_of_a_hundred_simultaneous_confirmations_wins(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    """The failure this whole design is arranged around.

    A double-click, a retried request, two open tabs -- any of them can confirm the
    same trade twice within microseconds. The token does not prevent it: two
    requests can both read it and both find it valid. The compare-and-swap does.
    """
    proposal = stored_proposal(config, account, store)

    with ThreadPoolExecutor(max_workers=16) as pool:
        wins = list(pool.map(lambda _: store.claim_for_execution(proposal.id), range(100)))

    assert sum(wins) == 1, f"{sum(wins)} callers were told to send the same order"
    assert store.get(proposal.id).status is ProposalStatus.EXECUTING  # type: ignore[union-attr]


def test_a_token_is_single_use(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    proposal = stored_proposal(config, account, store)
    token = store.issue_token(proposal, ttl_seconds=60)

    assert store.consume_token(token.token, proposal) is None
    assert store.consume_token(token.token, proposal) == "that confirmation has already been used"


def test_an_expired_token_is_refused(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    """A proposal priced minutes ago is a proposal priced at a stale market."""
    proposal = stored_proposal(config, account, store)
    token = store.issue_token(proposal, ttl_seconds=-1)

    assert "expired" in (store.consume_token(token.token, proposal) or "")


def test_a_token_stops_matching_once_the_proposal_changes(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    """So it is never possible to look at one trade, adjust it, and confirm the
    version you were shown first."""
    proposal = stored_proposal(config, account, store)
    token = store.issue_token(proposal, ttl_seconds=60)

    edited = proposal.model_copy(update={"leverage": proposal.leverage - 1})
    assert fingerprint(edited) != fingerprint(proposal)

    store.put(edited)
    assert "changed" in (store.consume_token(token.token, edited) or "")


def test_an_unknown_token_is_refused(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    proposal = stored_proposal(config, account, store)
    assert store.consume_token("not-a-token", proposal) == "no such confirmation token"


def test_a_token_from_another_proposal_is_refused(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    first = stored_proposal(config, account, store)
    second = first.model_copy(update={"id": "another-id"})
    store.put(second)
    token = store.issue_token(first, ttl_seconds=60)

    assert "different proposal" in (store.consume_token(token.token, second) or "")


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


def test_a_stale_proposal_never_reaches_the_dashboard(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    """Showing one is an invitation to confirm a trade at yesterday's prices."""
    proposal = stored_proposal(config, account, store)

    assert len(store.list_pending(now_ms=proposal.created_ts)) == 1
    assert store.list_pending(now_ms=proposal.expires_ts + 1) == []
    assert store.get(proposal.id).status is ProposalStatus.EXPIRED  # type: ignore[union-attr]


def test_a_rejected_proposal_cannot_then_be_executed(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    proposal = stored_proposal(config, account, store)

    assert store.reject(proposal.id, "not this one") is True
    assert store.claim_for_execution(proposal.id) is False
    assert store.get(proposal.id).status is ProposalStatus.REJECTED  # type: ignore[union-attr]


def test_finishing_records_the_outcome(
    config: AppConfig, account: AccountState, store: ProposalStore
) -> None:
    proposal = stored_proposal(config, account, store)
    store.claim_for_execution(proposal.id)
    store.finish(proposal.id, ok=True, note="filled at 42010")

    assert store.get(proposal.id).status is ProposalStatus.EXECUTED  # type: ignore[union-attr]
    assert store.counts()[ProposalStatus.EXECUTED.value] == 1
