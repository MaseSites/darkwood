"""The account, the ledger and the curve — what the paper money has done.

Three questions a person actually asks, and the screen answers each on its own
page: *how much have I got*, *what did I trade*, *is it going up or down*.

**The curve is in R, not in francs.** A trade's result in money depends on the
account it was taken on, and that account has changed size: the first forward
trades were taken on ten thousand and the rest on one thousand, because Severin
asked for the number he will actually have. A franc curve across that boundary
would show a cliff that no trade caused. R -- the result as a multiple of what
was risked -- is the same measurement whatever the account, which is why every
other report in this project is already in it. Francs are shown beside it as
the current balance, where they mean something.

**Replay and forward are never added together.** The journal holds thousands of
replayed trades and a handful of forward ones. The replayed decisions are
honest, but the *period* was chosen by somebody who knew how it went, and
mixing them produces a number that describes neither. Every figure here is one
or the other, and the page says which.

Writing is deliberately narrow: top up an account, or start one over. Both are
paper money and neither can touch an exchange. Everything else -- risk per
trade, the cost ceiling, which setups are on -- is shown read-only, because
those are the settings every measurement in this project was taken under, and a
knob that silently invalidates the evidence is worse than no knob.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, Field

from traidingbrain.api.chart import Candle
from traidingbrain.config.settings import AppConfig
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Side
from traidingbrain.journal.record import JournalEntry, Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.paperstate import PaperState, PaperStateStore
from traidingbrain.strategy.setups import TRADEABLE

#: Most trades the ledger hands over at once.
#:
#: The replay journal holds thousands and the browser has to draw them. Forward
#: trades are far fewer and are never truncated, because those are the ones the
#: whole exercise is about.
MAX_LEDGER = 400

#: Candles shown behind an open trade.
#:
#: Enough to see the approach, not so many that the plan lines are a smudge at
#: the right-hand edge. A trade can run for days -- Severin said so explicitly --
#: so this is a window on the recent past rather than the whole holding period.
CHART_CANDLES = 90


#: Minutes behind before an account is called stale.
#:
#: The trader settles every closed minute, so five is three cycles missed --
#: generous enough not to flicker on one slow exchange response, tight enough
#: that a stopped trader is obvious within the time it takes to notice.
STALE_AFTER_MINUTES = 5


class AccountRow(BaseModel):
    symbol: str
    equity: float
    start_equity: float
    change: float
    change_pct: float
    open_risk: float
    """What is at stake in an open position right now, in francs. Zero when
    flat. This is the number a person means by "how much can I lose", and it is
    not the position size."""

    unrealised: float
    has_position: bool
    stale: bool
    behind_minutes: int
    activity: str


class Portfolio(BaseModel):
    """Every paper account, side by side.

    `total_equity` is a sum and not a portfolio. Each market keeps its own
    account at the configured starting balance, so that a loss on one cannot
    change the position size on another -- if they shared, every row would be
    conditioned on every other row and none of them would be comparable. Twelve
    accounts of a thousand are twelve experiments on a realistic account, not
    one account of twelve thousand, and the screen says so beneath the figure.
    """

    accounts: list[AccountRow]
    total_equity: float
    total_start: float
    total_change: float
    total_change_pct: float
    open_risk: float
    trades: int
    wins: int
    mean_r: float
    total_r: float
    running: bool


class LedgerRow(BaseModel):
    trade_id: str
    source: str
    closed_ts: int
    opened_ts: int
    symbol: str
    setup: str
    setup_name: str
    setup_timeframe: str
    side: str
    entry: float
    exit: float
    stop: float
    target: float
    r_multiple: float
    net_pnl: float
    fees: float
    exit_reason: str
    rating: int
    rating_band: str
    score_direction: str
    agreed_with_score: bool
    bars_held: int
    max_favourable_r: float
    max_adverse_r: float
    stopped_by_wick: bool
    verdict: str


class Ledger(BaseModel):
    rows: list[LedgerRow]
    total: int
    truncated: bool


class CurvePoint(BaseModel):
    ts: int
    cumulative_r: float
    trade: int
    """How many trades had closed by this point. The x-axis a person reads is
    time, but the one that makes the slope meaningful is the trade count."""


class Curve(BaseModel):
    points: list[CurvePoint]
    source: str
    best_r: float
    worst_r: float
    peak_r: float
    drawdown_r: float
    """Furthest the curve has fallen below its own peak, in R. The number that
    says what holding this would have felt like, which the final total never
    does."""

    by_symbol: dict[str, float]
    by_setup: dict[str, float]


class SettingsView(BaseModel):
    """What the engine is configured to do. Read-only on purpose."""

    initial_equity: float
    risk_pct_floor: float
    max_leverage: float
    min_reward_risk: float
    max_cost_fraction_of_risk: float
    slippage_bps: float
    setups_on: list[str]
    signal_timeframe: str
    searched_timeframes: list[str]
    note: str


@dataclass(frozen=True)
class TopUp:
    """A deposit of paper money, or a fresh start."""

    symbol: str
    amount: float


class TopUpRequest(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)


class OpenTrade(BaseModel):
    """A position that is still running.

    Its own shape rather than a `LedgerRow` with blanks: a trade that has not
    finished has no exit, no result and no verdict, and a row carrying three
    empty columns invites them to be read as zeroes. What it has instead is
    where it stands right now, which a closed trade does not.
    """

    symbol: str
    side: str
    entry: float
    stop: float
    target: float
    qty: float
    leverage: float
    notional: float
    margin: float
    opened_ts: int
    held_minutes: int
    last_price: float
    unrealised: float
    risk_amount: float
    r_now: float
    """Where it stands in units of the risk. +1.0 means it is a full risk ahead;
    the target sits at the reward-to-risk ratio and the stop at -1.0."""

    progress: float
    """How far along the path from stop to target, 0 to 1, with the entry
    wherever it falls between them. The one number that says "nearly there" or
    "nearly wrong" without needing the prices read off."""

    reward_risk: float
    setup: str
    setup_name: str
    setup_timeframe: str
    signal_timeframe: str
    rating: int
    rating_band: str
    agreed_with_score: bool
    stop_moved: bool


class PositionChart(BaseModel):
    """Candles behind an open trade, with the three lines that decide it."""

    symbol: str
    timeframe: str
    bar_ms: int
    side: str
    entry: float
    stop: float
    target: float
    opened_ts: int
    candles: list[Candle]
    note: str = ""


def _candles(frame: pd.DataFrame) -> list[Candle]:
    """Bars as a list, read off numpy rather than row by row.

    `itertuples` hands back loosely typed rows that the type checker cannot see
    the columns of, and the arrays are what every other reader in this project
    uses anyway.
    """
    ts = frame["ts"].to_numpy(dtype="int64")
    opens = frame["open"].to_numpy(dtype="float64")
    highs = frame["high"].to_numpy(dtype="float64")
    lows = frame["low"].to_numpy(dtype="float64")
    closes = frame["close"].to_numpy(dtype="float64")
    volumes = frame["volume"].to_numpy(dtype="float64")
    return [
        Candle(
            ts=int(ts[i]),
            open=float(opens[i]),
            high=float(highs[i]),
            low=float(lows[i]),
            close=float(closes[i]),
            volume=float(volumes[i]),
        )
        for i in range(len(ts))
    ]


def build_open(state_path: Path, config: AppConfig, *, now_ms: int) -> list[OpenTrade]:
    """Every position still running, newest first.

    Read from the trader's state file rather than from the journal, because the
    journal only learns about a trade when it ends. These are the ones that have
    not.
    """
    states = PaperStateStore(state_path)
    out: list[OpenTrade] = []
    for symbol in config.engine.symbols.active:
        saved = states.load(symbol)
        if saved is None or saved.position is None:
            continue
        position = saved.position
        reason = saved.reason
        risk = position.risk_price
        price = saved.last_price or position.entry_price
        sign = 1.0 if position.side is Side.LONG else -1.0
        r_now = ((price - position.entry_price) * sign / risk) if risk else 0.0

        low, high = sorted((position.stop, position.target))
        span = high - low
        progress = (price - low) / span if span > 0 else 0.0
        if position.side is Side.SHORT:
            progress = 1.0 - progress

        out.append(
            OpenTrade(
                symbol=symbol,
                side=str(position.side),
                entry=position.entry_price,
                stop=position.stop,
                target=position.target,
                qty=position.qty,
                leverage=position.leverage,
                notional=round(position.notional, 2),
                margin=round(position.margin, 2),
                opened_ts=position.opened_ts,
                held_minutes=int(max(0, (now_ms - position.opened_ts) // 60_000)),
                last_price=price,
                unrealised=round(position.unrealised(price), 2),
                risk_amount=round(position.risk_amount, 2),
                r_now=round(r_now, 3),
                progress=round(min(1.0, max(0.0, progress)), 4),
                reward_risk=round(abs(position.target - position.entry_price) / risk, 2)
                if risk
                else 0.0,
                setup=reason.setup_key if reason else "—",
                setup_name=reason.setup_name if reason else "—",
                setup_timeframe=reason.setup_timeframe if reason else "—",
                signal_timeframe=reason.signal_timeframe if reason else "",
                rating=reason.rating if reason else 0,
                rating_band=reason.rating_band if reason else "",
                agreed_with_score=reason.rating_agreed_with_setup if reason else False,
                stop_moved=position.stop_moved,
            )
        )
    out.sort(key=lambda t: t.opened_ts, reverse=True)
    return out


def build_position_chart(state_path: Path, config: AppConfig, symbol: str) -> PositionChart | None:
    """The recent candles behind one open trade, on the chart it was found on.

    On the setup's own timeframe rather than the decision cadence: a four-hour
    setup read off fifteen-minute candles is ninety candles of noise around a
    plan drawn from something else. Falls back to the signal frame when the
    setup is unknown.
    """
    saved = PaperStateStore(state_path).load(symbol)
    if saved is None or saved.position is None:
        return None
    position = saved.position

    wanted = config.engine.timeframes.signal
    if saved.reason is not None:
        for candidate in config.engine.timeframes.context:
            if candidate.value == saved.reason.setup_timeframe:
                wanted = candidate
                break

    frame = ParquetStore(config.engine.paths.parquet_dir).read(symbol, wanted)
    if frame.empty:
        return None
    tail = frame.tail(CHART_CANDLES)
    return PositionChart(
        symbol=symbol,
        timeframe=wanted.value,
        bar_ms=wanted.minutes * 60_000,
        side=str(position.side),
        entry=position.entry_price,
        stop=position.stop,
        target=position.target,
        opened_ts=position.opened_ts,
        candles=_candles(tail),
    )


def _account_row(state: PaperState, *, start: float, now_ms: int) -> AccountRow:
    behind = max(0, (now_ms - state.last_minute_ts) // 60_000) if state.last_minute_ts else 0
    position = state.position
    change = state.equity - start
    return AccountRow(
        symbol=state.symbol,
        equity=round(state.equity, 2),
        start_equity=round(start, 2),
        change=round(change, 2),
        change_pct=round(100.0 * change / start, 3) if start else 0.0,
        open_risk=round(position.risk_amount, 2) if position is not None else 0.0,
        unrealised=(
            round(position.unrealised(state.last_price), 2)
            if position is not None and state.last_price
            else 0.0
        ),
        has_position=position is not None,
        stale=behind > STALE_AFTER_MINUTES,
        behind_minutes=int(behind),
        activity=state.tally.sentence(),
    )


def build_portfolio(
    state_path: Path, journal_path: Path, config: AppConfig, *, now_ms: int
) -> Portfolio:
    """Every account side by side, plus what the forward trades add up to."""
    states = PaperStateStore(state_path)
    journal = JournalStore(journal_path)
    start = config.engine.simulation.initial_equity

    rows: list[AccountRow] = []
    for symbol in config.engine.symbols.active:
        saved = states.load(symbol)
        if saved is None:
            # Not yet started is a state worth showing: the account exists in
            # configuration and simply has no file behind it until the trader
            # has run once. An empty screen would look like a failure.
            saved = PaperState(symbol=symbol, equity=start)
        rows.append(_account_row(saved, start=start, now_ms=now_ms))

    live = journal.all(source=Source.LIVE)
    rs = [entry.r_multiple for entry in live]
    total_equity = sum(row.equity for row in rows)
    total_start = sum(row.start_equity for row in rows)
    return Portfolio(
        accounts=rows,
        total_equity=round(total_equity, 2),
        total_start=round(total_start, 2),
        total_change=round(total_equity - total_start, 2),
        total_change_pct=(
            round(100.0 * (total_equity - total_start) / total_start, 3) if total_start else 0.0
        ),
        open_risk=round(sum(row.open_risk for row in rows), 2),
        trades=len(live),
        wins=sum(1 for entry in live if entry.won),
        mean_r=round(sum(rs) / len(rs), 4) if rs else 0.0,
        total_r=round(sum(rs), 3),
        running=any(not row.stale for row in rows),
    )


def _ledger_row(entry: JournalEntry) -> LedgerRow:
    reason = entry.reason
    post = entry.post_mortem
    return LedgerRow(
        trade_id=entry.trade_id,
        source=str(entry.source),
        closed_ts=entry.closed_ts,
        opened_ts=entry.opened_ts,
        symbol=entry.symbol,
        setup=reason.setup_key,
        setup_name=reason.setup_name,
        setup_timeframe=reason.setup_timeframe,
        side=reason.side,
        entry=entry.entry_price,
        exit=entry.exit_price,
        stop=reason.stop,
        target=reason.target,
        r_multiple=entry.r_multiple,
        net_pnl=entry.net_pnl,
        fees=entry.fees,
        exit_reason=entry.exit_reason.value,
        rating=reason.rating,
        rating_band=reason.rating_band,
        score_direction=reason.score_direction,
        agreed_with_score=reason.rating_agreed_with_setup,
        bars_held=post.bars_held,
        max_favourable_r=post.max_favourable_r,
        max_adverse_r=post.max_adverse_r,
        stopped_by_wick=post.stopped_by_wick,
        verdict=post.verdict,
    )


def build_ledger(journal_path: Path, *, source: Source, symbol: str | None = None) -> Ledger:
    """Every trade of one kind, newest first.

    One kind, never both: a list that mixed replayed and forward trades would
    invite exactly the average this project refuses to compute.
    """
    journal = JournalStore(journal_path)
    entries = journal.all(source=source, symbol=symbol)
    entries.sort(key=lambda e: e.closed_ts, reverse=True)
    shown = entries[:MAX_LEDGER]
    return Ledger(
        rows=[_ledger_row(entry) for entry in shown],
        total=len(entries),
        truncated=len(entries) > len(shown),
    )


def build_curve(journal_path: Path, *, source: Source) -> Curve:
    """The running total in R, oldest first, with how far it fell on the way.

    In R rather than francs because the account changed size: a franc curve
    across that boundary shows a cliff no trade caused.
    """
    journal = JournalStore(journal_path)
    entries = sorted(journal.all(source=source), key=lambda e: e.closed_ts)

    points: list[CurvePoint] = []
    running = 0.0
    peak = 0.0
    drawdown = 0.0
    for index, entry in enumerate(entries, start=1):
        running += entry.r_multiple
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
        points.append(CurvePoint(ts=entry.closed_ts, cumulative_r=round(running, 4), trade=index))

    by_symbol: dict[str, float] = {}
    by_setup: dict[str, float] = {}
    for entry in entries:
        by_symbol[entry.symbol] = round(by_symbol.get(entry.symbol, 0.0) + entry.r_multiple, 3)
        key = entry.reason.setup_key
        by_setup[key] = round(by_setup.get(key, 0.0) + entry.r_multiple, 3)

    rs = [entry.r_multiple for entry in entries]
    return Curve(
        points=points,
        source=str(source),
        best_r=round(max(rs), 3) if rs else 0.0,
        worst_r=round(min(rs), 3) if rs else 0.0,
        peak_r=round(peak, 3),
        drawdown_r=round(drawdown, 3),
        by_symbol=by_symbol,
        by_setup=by_setup,
    )


def build_settings(config: AppConfig) -> SettingsView:
    """What every measurement in this project was taken under.

    Read-only, and the note says why. These are not preferences; they are the
    conditions the recorded results hold under, and a screen that let them be
    changed with a slider would quietly make the journal describe a system that
    no longer exists.
    """
    tiers = config.risk.sizing.tiers
    floor = min((tier.risk_pct for tier in tiers), default=0.0)
    return SettingsView(
        initial_equity=config.engine.simulation.initial_equity,
        risk_pct_floor=floor,
        max_leverage=config.risk.leverage.max,
        min_reward_risk=config.risk.limits.min_reward_risk,
        max_cost_fraction_of_risk=config.risk.limits.max_cost_fraction_of_risk,
        slippage_bps=config.engine.simulation.slippage_bps,
        setups_on=[setup.key for setup in TRADEABLE],
        signal_timeframe=config.engine.timeframes.signal.value,
        searched_timeframes=[tf.value for tf in config.engine.timeframes.context],
        note=(
            "Diese Werte sind die Bedingungen, unter denen jede Messung in diesem "
            "Projekt entstanden ist. Sie hier per Schieberegler zu ändern würde das "
            "Journal still zu einem Bericht über ein System machen, das es nicht "
            "mehr gibt. Wenn einer davon geändert werden soll, sag welcher — dann "
            "wird er geändert und neu gemessen."
        ),
    )


def top_up(state_path: Path, config: AppConfig, request: TopUp) -> AccountRow:
    """Add paper money to one account, or create it at that balance.

    Paper only. There is no path from here to an exchange, and the amount is
    added to the balance rather than replacing it, so a deposit reads like a
    deposit and the account's history is not rewritten.
    """
    states = PaperStateStore(state_path)
    saved = states.load(request.symbol) or PaperState(
        symbol=request.symbol, equity=config.engine.simulation.initial_equity
    )
    saved.equity += request.amount
    states.save(saved)
    return _account_row(saved, start=config.engine.simulation.initial_equity, now_ms=0)


def reset_account(state_path: Path, symbol: str) -> None:
    """Forget one account so it starts again at the configured balance.

    The journal is untouched: what happened happened, and a reset is about the
    account rather than about the record.
    """
    PaperStateStore(state_path).forget(symbol)
