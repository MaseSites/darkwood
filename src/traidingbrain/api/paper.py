"""What the forward paper trader has done, for the screen.

Read-only, and reading from files rather than from the running process. The
trader writes its accounts to `paper.sqlite` and its finished trades to
`journal.sqlite`; this opens both and reports what is in them. Nothing here can
start, stop or influence a trade, which is why the dashboard can show it without
the two programs having to know about each other.

**Only forward trades are counted.** The journal also holds thousands of
replayed ones, and an average over both would describe neither -- the replayed
ones were selected by somebody who knew how that stretch of history went. The
filter is not a display preference; it is the whole reason the column exists.

**Staleness is reported, not hidden.** A screen showing an account that was last
updated six hours ago looks exactly like one showing a working system, which is
the failure mode that wasted an hour of Severin's time on the score panel. So
the age of the last settled minute is part of the payload and the screen says it
out loud.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from traidingbrain.journal.record import JournalEntry, Source
from traidingbrain.journal.store import JournalStore
from traidingbrain.live.paperstate import PaperStateStore

#: How many finished trades the screen lists. Newest first.
RECENT = 12

#: Minutes after which an account is called stale.
#:
#: The trader settles every closed minute, so five is already three cycles
#: missed. Generous enough not to flicker on one slow exchange response.
STALE_AFTER_MINUTES = 5


class PaperPosition(BaseModel):
    side: str
    entry: float
    stop: float
    target: float
    qty: float
    leverage: float
    opened_ts: int
    unrealised: float
    risk_amount: float
    stop_moved: bool
    #: Positionsgroesse in der Quote-Waehrung: qty * entry.
    #:
    #: Mitgeliefert statt dem Konsumenten zum Nachrechnen ueberlassen. Wer
    #: es selbst rechnet, rechnet irgendwann mit `exit` oder mit dem
    #: aktuellen Preis -- und beantwortet damit eine andere Frage als "mit
    #: wie viel Geld wurde dieser Trade eroeffnet".
    notional: float
    #: Davon tatsaechlich gebundenes Kapital: notional / leverage.
    #: Nicht dasselbe wie `risk_amount`, siehe config/risk.yaml.
    margin: float


class PaperAccount(BaseModel):
    symbol: str
    equity: float
    last_price: float
    last_minute_ts: int
    stale: bool
    behind_minutes: int
    position: PaperPosition | None = None
    resting_at: float | None = None
    """Where an unfilled order is waiting, if one is."""

    setup: str | None = None
    setup_timeframe: str | None = None
    rating: int | None = None

    activity: str = ""
    """One German sentence on why this account is doing what it is doing.

    The panel's honest answer to "it has been flat all day". Without it the
    screen cannot tell a market that offered no setup from a risk layer that
    refused every one, and those call for opposite responses."""

    bars_seen: int = 0
    proposed: int = 0
    refused_by_risk: int = 0


class PaperTrade(BaseModel):
    closed_ts: int
    opened_ts: int
    symbol: str
    setup: str
    setup_timeframe: str
    side: str
    r_multiple: float
    net_pnl: float
    exit_reason: str
    rating: int
    bars_held: int
    verdict: str


class PaperReadout(BaseModel):
    """Everything the paper-trading panel shows."""

    accounts: list[PaperAccount]
    trades: int
    wins: int
    mean_r: float
    total_net: float
    recent: list[PaperTrade]
    running: bool
    """Is anything being settled at all? False when every account is stale,
    which is what a stopped trader looks like from here."""


def _position_view(state: object, last_price: float) -> PaperPosition | None:
    position = getattr(state, "position", None)
    if position is None:
        return None
    return PaperPosition(
        side=str(position.side),
        entry=position.entry_price,
        stop=position.stop,
        target=position.target,
        qty=position.qty,
        leverage=position.leverage,
        opened_ts=position.opened_ts,
        unrealised=round(position.unrealised(last_price), 4) if last_price else 0.0,
        risk_amount=position.risk_amount,
        stop_moved=position.stop_moved,
        notional=position.notional,
        margin=position.margin,
    )


def build_paper_readout(
    state_path: Path, journal_path: Path, *, now_ms: int, symbols: list[str] | None = None
) -> PaperReadout:
    """Read both files and say what the paper trader is doing.

    `now_ms` is passed in rather than read from the clock so a test can pin the
    staleness arithmetic, which is the only thing here with a time dependency.
    """
    states = PaperStateStore(state_path)
    journal = JournalStore(journal_path)

    wanted = symbols if symbols is not None else states.symbols()
    accounts: list[PaperAccount] = []
    for symbol in wanted:
        saved = states.load(symbol)
        if saved is None:
            continue
        behind = max(0, (now_ms - saved.last_minute_ts) // 60_000) if saved.last_minute_ts else 0
        reason = saved.reason
        accounts.append(
            PaperAccount(
                symbol=symbol,
                equity=round(saved.equity, 2),
                last_price=saved.last_price,
                last_minute_ts=saved.last_minute_ts,
                stale=behind > STALE_AFTER_MINUTES,
                behind_minutes=int(behind),
                position=_position_view(saved, saved.last_price),
                resting_at=saved.pending.limit_price if saved.pending is not None else None,
                setup=reason.setup_key if reason is not None else None,
                setup_timeframe=reason.setup_timeframe if reason is not None else None,
                rating=reason.rating if reason is not None else None,
                activity=saved.tally.sentence(),
                bars_seen=saved.tally.bars_seen,
                proposed=saved.tally.proposed,
                refused_by_risk=saved.tally.refused_by_risk,
            )
        )

    live = journal.all(source=Source.LIVE)
    rs = [entry.r_multiple for entry in live]
    return PaperReadout(
        accounts=accounts,
        trades=len(live),
        wins=sum(1 for entry in live if entry.won),
        mean_r=round(sum(rs) / len(rs), 4) if rs else 0.0,
        total_net=round(sum(entry.net_pnl for entry in live), 2),
        recent=[_trade_view(entry) for entry in reversed(live[-RECENT:])],
        running=any(not account.stale for account in accounts),
    )


def _trade_view(entry: JournalEntry) -> PaperTrade:
    return PaperTrade(
        closed_ts=entry.closed_ts,
        opened_ts=entry.opened_ts,
        symbol=entry.symbol,
        setup=entry.reason.setup_key,
        setup_timeframe=entry.reason.setup_timeframe,
        side=entry.reason.side,
        r_multiple=entry.r_multiple,
        net_pnl=entry.net_pnl,
        exit_reason=entry.exit_reason.value,
        rating=entry.reason.rating,
        bars_held=entry.post_mortem.bars_held,
        verdict=entry.post_mortem.verdict,
    )
