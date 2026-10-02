"""The current state of a paper account, so a restart is not a reset.

Forward paper trading is slow by nature: a four-hour setup puts its stop at
four-hour structure and the trade runs for days. A process that forgot its open
position on restart would be useless for exactly the trades that matter most --
and the laptop this runs on gets shut down.

So the account is written to disk after every cycle: equity, the resting order,
the open position, and -- the important one -- **the reason the trade was
taken**. The reason is persisted at the moment the order is placed, before the
outcome exists. Keeping it here rather than recomputing it at exit is what makes
the record a forward one: a reason rebuilt after the fact would be the same
numbers, but nothing on disk would prove they were not informed by the result.

**Which minute was last charged, not how many.** Resumed by timestamp, because
the process may have been off for a day and the question is which minutes have
already been settled against the account.

One row per symbol, replaced in place. This is state, not history; the history
is the journal, and it is appended forever.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from traidingbrain.domain.enums import OrderType, Side
from traidingbrain.journal.record import FamilyNote, TradeReason
from traidingbrain.sim.broker import OpenPosition, PendingEntry, SimBroker

_DDL = """
CREATE TABLE IF NOT EXISTS accounts (
    symbol          TEXT PRIMARY KEY,
    equity          REAL    NOT NULL,
    last_minute_ts  INTEGER NOT NULL,
    last_decided_ts INTEGER NOT NULL,
    last_price      REAL    NOT NULL,
    opened_ts       INTEGER NOT NULL,
    pending         TEXT,
    position        TEXT,
    reason          TEXT
);
"""


@dataclass
class PaperState:
    """Everything needed to carry a paper account across a restart."""

    symbol: str
    equity: float
    last_minute_ts: int = 0
    last_decided_ts: int = 0
    last_price: float = 0.0
    opened_ts: int = 0
    pending: PendingEntry | None = None
    position: OpenPosition | None = None
    reason: TradeReason | None = None

    def capture_from(self, broker: SimBroker, *, reason: TradeReason | None) -> None:
        self.equity = broker.equity
        self.pending = broker.pending
        self.position = broker.position
        self.reason = reason

    def restore_into(self, broker: SimBroker) -> None:
        """Put a saved account back into a fresh broker.

        The funding cursor is advanced to the last settled minute, so a trade
        resumed after a gap is not charged twice for settlements it already
        paid. That advance has to happen while the broker is still flat, which
        is why it comes before the position is attached.
        """
        broker.ledger.equity = self.equity
        broker.ledger.peak_equity = max(self.equity, broker.ledger.peak_equity)
        if self.last_minute_ts:
            broker.skip_to(self.last_minute_ts)
        broker.pending = self.pending
        broker.position = self.position


class PaperStateStore:
    """Where paper accounts are kept between cycles."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def save(self, state: PaperState) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO accounts (symbol, equity, last_minute_ts, last_decided_ts, "
                "last_price, opened_ts, pending, position, reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET equity=excluded.equity, "
                "last_minute_ts=excluded.last_minute_ts, "
                "last_decided_ts=excluded.last_decided_ts, "
                "last_price=excluded.last_price, opened_ts=excluded.opened_ts, "
                "pending=excluded.pending, position=excluded.position, "
                "reason=excluded.reason",
                (
                    state.symbol,
                    state.equity,
                    state.last_minute_ts,
                    state.last_decided_ts,
                    state.last_price,
                    state.opened_ts,
                    _dump(state.pending),
                    _dump(state.position),
                    _dump_reason(state.reason),
                ),
            )
            conn.commit()

    def load(self, symbol: str) -> PaperState | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT equity, last_minute_ts, last_decided_ts, last_price, opened_ts, "
                "pending, position, reason FROM accounts WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        return PaperState(
            symbol=symbol,
            equity=float(row[0]),
            last_minute_ts=int(row[1]),
            last_decided_ts=int(row[2]),
            last_price=float(row[3]),
            opened_ts=int(row[4]),
            pending=_load_pending(row[5]),
            position=_load_position(row[6]),
            reason=_load_reason(row[7]),
        )

    def symbols(self) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT symbol FROM accounts ORDER BY symbol").fetchall()
        return [str(row[0]) for row in rows]

    def forget(self, symbol: str) -> None:
        """Start this symbol's account over. For deliberate resets only."""
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM accounts WHERE symbol = ?", (symbol,))
            conn.commit()


def _dump(value: PendingEntry | OpenPosition | None) -> str | None:
    """Serialise, with enums written as their values.

    `StrEnum` members compare equal to their strings, so leaving them as text
    on the way back would work until the first `is` comparison -- which is the
    kind of bug that passes every test and fails once, in a position that is
    holding fake money and whose exits are decided by `side is Side.LONG`.
    """
    if value is None:
        return None
    data = asdict(value)
    data["side"] = str(data["side"])
    if "order_type" in data:
        data["order_type"] = str(data["order_type"])
    return json.dumps(data)


def _load_pending(raw: str | None) -> PendingEntry | None:
    if not raw:
        return None
    data: dict[str, Any] = json.loads(raw)
    data["side"] = Side(data["side"])
    data["order_type"] = OrderType(data["order_type"])
    return PendingEntry(**data)


def _load_position(raw: str | None) -> OpenPosition | None:
    if not raw:
        return None
    data: dict[str, Any] = json.loads(raw)
    data["side"] = Side(data["side"])
    return OpenPosition(**data)


def _dump_reason(reason: TradeReason | None) -> str | None:
    return None if reason is None else json.dumps(asdict(reason), ensure_ascii=False)


def _load_reason(raw: str | None) -> TradeReason | None:
    if not raw:
        return None
    data: dict[str, Any] = json.loads(raw)
    families = [FamilyNote(**note) for note in data.pop("families", [])]
    return TradeReason(**data, families=families)
