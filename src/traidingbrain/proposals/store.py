"""Where proposals live, and the one transition that has to be atomic.

Everything in this file exists for a single line:

    UPDATE proposals SET status='executing' WHERE id=? AND status='pending'

That compare-and-swap, not the confirmation token, is what makes it impossible to
execute a proposal twice. A token can be validated by two requests at the same
instant -- both read it, both find it valid, both proceed. Only one `UPDATE` can
report a changed row.

The token still matters, for a different reason: it binds the confirmation to the
exact numbers the user looked at. Change the leverage and the old token stops
matching, so it is never possible to confirm one trade and send another.

SQLite in WAL mode, and one writer. A long-running proposal generator writing
while a dashboard reads is the normal case here, not an edge one.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from traidingbrain.domain.enums import ProposalStatus
from traidingbrain.domain.proposal import ConfirmationToken, TradeProposal
from traidingbrain.proposals.rules import fingerprint, token_objection, utc_now_ms

_DDL = """
CREATE TABLE IF NOT EXISTS proposals (
    id            TEXT PRIMARY KEY,
    symbol        TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_ts    INTEGER NOT NULL,
    expires_ts    INTEGER NOT NULL,
    payload       TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    finished_ts   INTEGER
);
CREATE INDEX IF NOT EXISTS proposals_by_status ON proposals (status, expires_ts);

CREATE TABLE IF NOT EXISTS tokens (
    token        TEXT PRIMARY KEY,
    proposal_id  TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    issued_ts    INTEGER NOT NULL,
    expires_ts   INTEGER NOT NULL,
    used_ts      INTEGER
);
CREATE INDEX IF NOT EXISTS tokens_by_proposal ON tokens (proposal_id);
"""


def _hydrate(row: tuple[str, str]) -> TradeProposal:
    """Rebuild a proposal, taking the status from the column and not the payload.

    The status lives in two places: inside the serialised proposal, and in its own
    column. Only the column is authoritative, because the column is what the
    compare-and-swap updates -- rewriting the whole payload inside that statement
    would make it a read-modify-write and destroy the atomicity it exists for.

    So the column wins on the way out. Without this, a proposal that has already
    been claimed still reads as pending, which is the one thing the status is for.
    """
    payload, status = row
    return TradeProposal.model_validate_json(payload).model_copy(
        update={"status": ProposalStatus(status)}
    )


class ProposalStore:
    """Persistence for proposals and their confirmation tokens."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # -- proposals ---------------------------------------------------------- #

    def put(self, proposal: TradeProposal) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO proposals "
                "(id, symbol, status, created_ts, expires_ts, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    proposal.id,
                    proposal.symbol,
                    proposal.status.value,
                    proposal.created_ts,
                    proposal.expires_ts,
                    proposal.model_dump_json(),
                ),
            )

    def get(self, proposal_id: str) -> TradeProposal | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload, status FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        return _hydrate(row) if row else None

    def list_pending(self, now_ms: int | None = None) -> list[TradeProposal]:
        """Live proposals only. Expired ones are marked, not returned.

        A stale proposal on a dashboard is an invitation to confirm a trade at
        yesterday's prices.
        """
        now = now_ms if now_ms is not None else utc_now_ms()
        self.expire_stale(now)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload, status FROM proposals WHERE status = ? ORDER BY created_ts DESC",
                (ProposalStatus.PENDING.value,),
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def expire_stale(self, now_ms: int | None = None) -> int:
        now = now_ms if now_ms is not None else utc_now_ms()
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE proposals SET status = ?, finished_ts = ?, note = 'expired unseen' "
                "WHERE status = ? AND expires_ts <= ?",
                (ProposalStatus.EXPIRED.value, now, ProposalStatus.PENDING.value, now),
            )
            return int(cursor.rowcount)

    # -- the transition that matters ---------------------------------------- #

    def claim_for_execution(self, proposal_id: str) -> bool:
        """PENDING -> EXECUTING, atomically. True for exactly one caller.

        This, not the token check, is what makes concurrent confirmations safe.
        Two requests can both read a token and both find it valid; only one
        `UPDATE ... WHERE status = 'pending'` can report a changed row.
        """
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE proposals SET status = ? WHERE id = ? AND status = ?",
                (
                    ProposalStatus.EXECUTING.value,
                    proposal_id,
                    ProposalStatus.PENDING.value,
                ),
            )
            return cursor.rowcount == 1

    def finish(self, proposal_id: str, *, ok: bool, note: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE proposals SET status = ?, note = ?, finished_ts = ? WHERE id = ?",
                (
                    (ProposalStatus.EXECUTED if ok else ProposalStatus.FAILED).value,
                    note,
                    utc_now_ms(),
                    proposal_id,
                ),
            )

    def reject(self, proposal_id: str, note: str = "declined") -> bool:
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE proposals SET status = ?, note = ?, finished_ts = ? "
                "WHERE id = ? AND status = ?",
                (
                    ProposalStatus.REJECTED.value,
                    note,
                    utc_now_ms(),
                    proposal_id,
                    ProposalStatus.PENDING.value,
                ),
            )
            return cursor.rowcount == 1

    # -- tokens ------------------------------------------------------------- #

    def issue_token(self, proposal: TradeProposal, ttl_seconds: int) -> ConfirmationToken:
        now = utc_now_ms()
        token = ConfirmationToken(
            proposal_id=proposal.id,
            issued_ts=now,
            expires_ts=now + ttl_seconds * 1000,
            proposal_fingerprint=fingerprint(proposal),
        )
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO tokens (token, proposal_id, fingerprint, issued_ts, expires_ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    token.token,
                    token.proposal_id,
                    token.proposal_fingerprint,
                    token.issued_ts,
                    token.expires_ts,
                ),
            )
        return token

    def consume_token(self, token: str, proposal: TradeProposal) -> str | None:
        """Spend a token. Returns None on success, or why it was refused.

        Single use, enforced by `used_ts IS NULL` in the same statement that marks
        it used -- so two simultaneous attempts cannot both succeed here either.
        """
        now = utc_now_ms()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT proposal_id, fingerprint, expires_ts, used_ts FROM tokens WHERE token = ?",
                (token,),
            ).fetchone()
            if row is None:
                return "no such confirmation token"

            objection = token_objection(row, proposal, now)
            if objection is not None:
                return objection

            cursor = conn.execute(
                "UPDATE tokens SET used_ts = ? WHERE token = ? AND used_ts IS NULL",
                (now, token),
            )
            if cursor.rowcount != 1:
                return "that confirmation was used by another request"
        return None

    # -- reporting ---------------------------------------------------------- #

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT status, count(*) FROM proposals GROUP BY status").fetchall()
        return {status: int(count) for status, count in rows}

    def history(self, limit: int = 50) -> list[TradeProposal]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload, status FROM proposals ORDER BY created_ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_hydrate(row) for row in rows]
