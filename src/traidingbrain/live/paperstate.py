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
from dataclasses import asdict, dataclass, field
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
    reason          TEXT,
    tally           TEXT
);
"""

#: Columns added after the table first shipped.
#:
#: SQLite has no `ADD COLUMN IF NOT EXISTS`, and `CREATE TABLE IF NOT EXISTS`
#: leaves an existing table exactly as it was -- so a file written by an earlier
#: version keeps its old shape and every read of a new column fails. Three
#: accounts had already been running when `tally` was added.
_ADDED_COLUMNS = {"tally": "TEXT"}


@dataclass
class Tally:
    """What the loop has done since the account was opened.

    Persisted rather than held in memory, because the interesting case is a
    trader that has run for three days and traded nothing. "Still flat" cannot
    say whether no setup fired, whether the risk layer refused every one, or
    whether the score was never ready -- and those are three different problems
    with three different answers. Printed only at shutdown, the counters were
    invisible for exactly as long as they mattered.
    """

    cycles: int = 0
    bars_seen: int = 0
    proposed: int = 0
    refused_by_risk: int = 0
    not_ready: int = 0
    opened: int = 0
    closed: int = 0
    expired: int = 0
    failures: int = 0
    """Cycles that threw. A loop failing every pass reads on the screen exactly
    like a quiet market, so the sentence below has to be able to say it."""

    @property
    def mostly_failing(self) -> bool:
        """Is this a broken loop rather than a flaky exchange response?

        Half the cycles, not one. A handful of failures over a long run is a
        request that timed out; half of them is a loop that cannot work and is
        wearing the costume of a quiet market.
        """
        return bool(self.failures) and self.failures >= max(1, self.cycles // 2)

    def sentence(self) -> str:
        """One German line saying why nothing is happening, if nothing is.

        A table rather than a chain of returns, and ordered: the first true row
        wins. "Everything is throwing" comes before every explanation of a
        quiet market, because a broken loop that explains itself as patience is
        the one answer here that actively misleads.
        """
        reasons = (
            (
                self.mostly_failing,
                f"{self.failures} von {self.cycles} Zyklen scheitern -- Fehlerliste prüfen",
            ),
            (
                bool(self.opened),
                f"{self.opened} eröffnet, {self.closed} geschlossen "
                f"({self.proposed} Vorschläge auf {self.bars_seen} Kerzen)",
            ),
            (not self.bars_seen, "noch keine Kerze ausgewertet"),
            (
                not self.proposed,
                f"{self.bars_seen} Kerzen ausgewertet, kein Setup hat ausgelöst",
            ),
            (
                bool(self.not_ready),
                f"{self.proposed} Setups ausgelöst, {self.not_ready} ohne Bewertung",
            ),
            (
                bool(self.refused_by_risk),
                f"{self.proposed} Setups ausgelöst, alle von der Risikoschicht "
                f"abgelehnt -- meist zu enger Stop für die Gebühren",
            ),
        )
        for applies, text in reasons:
            if applies:
                return text
        return f"{self.proposed} Vorschläge auf {self.bars_seen} Kerzen"


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
    tally: Tally = field(default_factory=Tally)

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
            have = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
            for column, kind in _ADDED_COLUMNS.items():
                if column not in have:
                    conn.execute(f"ALTER TABLE accounts ADD COLUMN {column} {kind}")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def save(self, state: PaperState) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO accounts (symbol, equity, last_minute_ts, last_decided_ts, "
                "last_price, opened_ts, pending, position, reason, tally) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET equity=excluded.equity, "
                "last_minute_ts=excluded.last_minute_ts, "
                "last_decided_ts=excluded.last_decided_ts, "
                "last_price=excluded.last_price, opened_ts=excluded.opened_ts, "
                "pending=excluded.pending, position=excluded.position, "
                "reason=excluded.reason, tally=excluded.tally",
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
                    json.dumps(asdict(state.tally)),
                ),
            )
            conn.commit()

    def load(self, symbol: str) -> PaperState | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT equity, last_minute_ts, last_decided_ts, last_price, opened_ts, "
                "pending, position, reason, tally FROM accounts WHERE symbol = ?",
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
            tally=_load_tally(row[8]),
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


def _load_tally(raw: str | None) -> Tally:
    """The counters, or fresh ones.

    Unknown keys are dropped rather than raising: a file written by a later
    version with one more counter in it should still open, because the thing it
    is protecting is an account with an open position.
    """
    if not raw:
        return Tally()
    data: dict[str, Any] = json.loads(raw)
    fields = set(Tally().__dict__)
    return Tally(**{k: int(v) for k, v in data.items() if k in fields})


def _dump_reason(reason: TradeReason | None) -> str | None:
    return None if reason is None else json.dumps(asdict(reason), ensure_ascii=False)


def _load_reason(raw: str | None) -> TradeReason | None:
    if not raw:
        return None
    data: dict[str, Any] = json.loads(raw)
    families = [FamilyNote(**note) for note in data.pop("families", [])]
    return TradeReason(**data, families=families)
