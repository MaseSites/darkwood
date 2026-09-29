"""The write-ahead log for orders.

The failure this exists for is narrow and expensive: the process sends an order and
dies before recording that it did. On restart the system believes it is flat, the
exchange believes otherwise, and the next proposal opens a second position on top
of the first.

The sequence is therefore fixed and cannot be reordered:

1. Write the intent, including the `clientOrderId` that will be used.
2. Send.
3. Write the result.

A crash between 1 and 2 leaves an intent with no order -- reconciliation asks the
exchange about that id, finds nothing, and marks it abandoned. A crash between 2
and 3 leaves an intent whose order exists -- reconciliation finds it and adopts it.
Either way there is a key to ask about, which is the entire point. Without the
write-ahead, the second case is unrecoverable: there is nothing to ask.

The `clientOrderId` is derived from the proposal id rather than generated, so a
retry after a timeout carries the same one. Exchanges reject a duplicate, which
turns "did that go through?" from a guess into an answer.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from traidingbrain.domain.proposal import ExecutionIntent, TradeProposal

#: Bybit accepts up to 36 characters for an order link id.
MAX_CLIENT_ID = 36


class IntentState(StrEnum):
    WRITTEN = "written"
    """Recorded, not yet sent. A crash here means nothing reached the exchange."""

    SENT = "sent"
    """Handed to the exchange. A crash here needs reconciliation to resolve."""

    CONFIRMED = "confirmed"
    """The exchange acknowledged it and the acknowledgement was recorded."""

    FAILED = "failed"
    """The exchange refused it, and said why."""

    ABANDONED = "abandoned"
    """Reconciliation asked and the exchange had never heard of it."""


_DDL = """
CREATE TABLE IF NOT EXISTS intents (
    client_order_id TEXT PRIMARY KEY,
    proposal_id     TEXT NOT NULL UNIQUE,
    state           TEXT NOT NULL,
    payload         TEXT NOT NULL,
    exchange_ref    TEXT,
    note            TEXT NOT NULL DEFAULT '',
    written_ts      INTEGER NOT NULL,
    settled_ts      INTEGER
);
CREATE INDEX IF NOT EXISTS intents_by_state ON intents (state);
"""


def client_order_id(proposal_id: str) -> str:
    """Deterministic from the proposal, so a retry cannot become a second position.

    Hashed rather than used raw: a proposal id is a UUID, which is longer than the
    36 characters Bybit allows, and truncating one would risk a collision that
    silently merges two different trades.
    """
    digest = hashlib.sha256(proposal_id.encode("utf-8")).hexdigest()
    return f"tb-{digest[: MAX_CLIENT_ID - 3]}"


def _now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


@dataclass(frozen=True)
class IntentRecord:
    client_order_id: str
    proposal_id: str
    state: IntentState
    intent: ExecutionIntent
    exchange_ref: str | None
    note: str
    written_ts: int


class IntentLog:
    """Durable record of every order this system has tried to place."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def write_ahead(self, proposal: TradeProposal, *, testnet: bool) -> ExecutionIntent:
        """Record what is about to be sent, before sending it.

        Refuses if this proposal already has an intent. That refusal is the
        idempotency guarantee: whatever happened to the first attempt, a second one
        must be resolved by asking the exchange rather than by sending again.
        """
        intent = ExecutionIntent(
            proposal_id=proposal.id,
            client_order_id=client_order_id(proposal.id),
            symbol=proposal.symbol,
            side=proposal.side,
            qty=proposal.qty,
            entry=proposal.entry,
            stop=proposal.stop,
            target=proposal.target,
            leverage=proposal.leverage,
            testnet=testnet,
        )
        with closing(self._connect()) as conn:
            try:
                conn.execute(
                    "INSERT INTO intents "
                    "(client_order_id, proposal_id, state, payload, written_ts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        intent.client_order_id,
                        intent.proposal_id,
                        IntentState.WRITTEN.value,
                        intent.model_dump_json(),
                        _now_ms(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AlreadyAttemptedError(
                    f"proposal {proposal.id} already has an order intent; resolve it by "
                    f"asking the exchange about {intent.client_order_id}, not by sending again"
                ) from exc
        return intent

    def mark(
        self,
        client_id: str,
        state: IntentState,
        *,
        exchange_ref: str | None = None,
        note: str = "",
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE intents SET state = ?, exchange_ref = ?, note = ?, settled_ts = ? "
                "WHERE client_order_id = ?",
                (state.value, exchange_ref, note, _now_ms(), client_id),
            )

    def get(self, client_id: str) -> IntentRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT client_order_id, proposal_id, state, payload, exchange_ref, note, "
                "written_ts FROM intents WHERE client_order_id = ?",
                (client_id,),
            ).fetchone()
        return _hydrate(row) if row else None

    def for_proposal(self, proposal_id: str) -> IntentRecord | None:
        return self.get(client_order_id(proposal_id))

    def unresolved(self) -> list[IntentRecord]:
        """Intents that were written or sent and never settled.

        What reconciliation works through on startup. An empty list is the only
        acceptable steady state: anything here is an order whose fate is unknown.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT client_order_id, proposal_id, state, payload, exchange_ref, note, "
                "written_ts FROM intents WHERE state IN (?, ?) ORDER BY written_ts",
                (IntentState.WRITTEN.value, IntentState.SENT.value),
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT state, count(*) FROM intents GROUP BY state").fetchall()
        return {state: int(count) for state, count in rows}


class AlreadyAttemptedError(RuntimeError):
    """Raised when a proposal already has an intent.

    Not an error to work around. It means an order may already exist, and the
    correct response is to ask the exchange rather than to send another.
    """


def _hydrate(row: tuple[str, str, str, str, str | None, str, int]) -> IntentRecord:
    client_id, proposal_id, state, payload, ref, note, written = row
    return IntentRecord(
        client_order_id=client_id,
        proposal_id=proposal_id,
        state=IntentState(state),
        intent=ExecutionIntent.model_validate(json.loads(payload)),
        exchange_ref=ref,
        note=note,
        written_ts=written,
    )
