"""The proposal store, on Postgres.

A translation of the SQLite one, not an improvement on it. Both exist while the
switch is being made, and the only way that is safe is if they behave
identically -- so the same test suite runs against both, and any difference in
this file is a difference someone would have to hold in their head at every call
site.

What Postgres buys is not a better table. It is that two processes on two
machines can hold this at once. A collector writing while a dashboard reads is
the normal case for the architecture this is heading towards, and SQLite over a
network share is how databases get corrupted.

Two details carry the safety argument, and both are single statements on
purpose:

**The claim.** `UPDATE ... WHERE status = 'pending'` returning one row is what
makes a hundred simultaneous confirmations send one order. Not the token check --
two requests can both read a token and both find it valid.

**The token.** `WHERE used_ts IS NULL` in the same statement that sets it. Read
first and write second, and two requests both read NULL.

And one that is not about concurrency: the status column is authoritative, never
the copy inside the JSON payload. They disagree after a transition, and a reader
trusting the payload sees a proposal that has already been claimed as still
pending. That was a real bug in the SQLite store, found by a concurrency test.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

import psycopg

from traidingbrain.domain.enums import ProposalStatus
from traidingbrain.domain.proposal import ConfirmationToken, TradeProposal
from traidingbrain.proposals.rules import fingerprint, token_objection, utc_now_ms
from traidingbrain.storage.postgres import migrate, pool_for


def _hydrate(payload: dict[str, Any], status: str) -> TradeProposal:
    """Rebuild a proposal, with the column's status winning over the payload's.

    The payload is a snapshot from when the row was written; the column is
    updated in place by every transition. Trusting the payload means reading a
    claimed proposal as still pending, which is exactly the window a second
    confirmation would slip through.
    """
    return TradeProposal.model_validate({**payload, "status": status})


class PostgresProposalStore:
    """Persistence for proposals and their confirmation tokens, on Postgres."""

    def __init__(self, url: str, *, migrate_on_start: bool = True) -> None:
        self.url = url
        if migrate_on_start:
            # Every start-up. A deployment that has to remember whether it
            # migrated is a deployment that will forget.
            migrate(url)

    def _connect(self) -> AbstractContextManager[psycopg.Connection[Any]]:
        """A connection from the shared pool, returned when the block ends.

        Not a fresh connection per call, which is what this used to be. The
        dashboard polls this store every four seconds, the live loop uses it,
        and the confirmation path deliberately runs a hundred callers at once --
        against a server allowing twenty connections in total.
        """
        return pool_for(self.url).connection()

    # -- proposals ---------------------------------------------------------- #

    def put(self, proposal: TradeProposal) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO proposals "
                "(id, symbol, status, created_ts, expires_ts, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET "
                "  symbol = EXCLUDED.symbol,"
                "  status = EXCLUDED.status,"
                "  created_ts = EXCLUDED.created_ts,"
                "  expires_ts = EXCLUDED.expires_ts,"
                "  payload = EXCLUDED.payload",
                (
                    proposal.id,
                    proposal.symbol,
                    proposal.status.value,
                    proposal.created_ts,
                    proposal.expires_ts,
                    proposal.model_dump_json(),
                ),
            )
            conn.commit()

    def get(self, proposal_id: str) -> TradeProposal | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload, status FROM proposals WHERE id = %s", (proposal_id,)
            )
            row = cur.fetchone()
        return _hydrate(row[0], row[1]) if row else None

    def list_pending(self, now_ms: int | None = None) -> list[TradeProposal]:
        """Live proposals only. Expired ones are marked, not returned.

        A stale proposal on a dashboard is an invitation to confirm a trade at
        yesterday's prices.
        """
        now = now_ms if now_ms is not None else utc_now_ms()
        self.expire_stale(now)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload, status FROM proposals WHERE status = %s "
                "ORDER BY created_ts DESC",
                (ProposalStatus.PENDING.value,),
            )
            rows = cur.fetchall()
        return [_hydrate(payload, status) for payload, status in rows]

    def expire_stale(self, now_ms: int | None = None) -> int:
        now = now_ms if now_ms is not None else utc_now_ms()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE proposals SET status = %s, finished_ts = %s, note = 'expired unseen' "
                "WHERE status = %s AND expires_ts <= %s",
                (ProposalStatus.EXPIRED.value, now, ProposalStatus.PENDING.value, now),
            )
            count = cur.rowcount
            conn.commit()
        return int(count)

    # -- the transition that matters ---------------------------------------- #

    def claim_for_execution(self, proposal_id: str) -> bool:
        """PENDING -> EXECUTING, atomically. True for exactly one caller.

        One statement, so the row lock is held for its whole duration and a
        second caller sees the new status rather than the old one. Reading the
        status and then writing it would leave a window between the two, and a
        hundred simultaneous confirmations is exactly what finds that window.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE proposals SET status = %s WHERE id = %s AND status = %s",
                (
                    ProposalStatus.EXECUTING.value,
                    proposal_id,
                    ProposalStatus.PENDING.value,
                ),
            )
            claimed = cur.rowcount == 1
            conn.commit()
        return claimed

    def finish(self, proposal_id: str, *, ok: bool, note: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE proposals SET status = %s, note = %s, finished_ts = %s WHERE id = %s",
                (
                    (ProposalStatus.EXECUTED if ok else ProposalStatus.FAILED).value,
                    note,
                    utc_now_ms(),
                    proposal_id,
                ),
            )
            conn.commit()

    def reject(self, proposal_id: str, note: str = "declined") -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE proposals SET status = %s, note = %s, finished_ts = %s "
                "WHERE id = %s AND status = %s",
                (
                    ProposalStatus.REJECTED.value,
                    note,
                    utc_now_ms(),
                    proposal_id,
                    ProposalStatus.PENDING.value,
                ),
            )
            rejected = cur.rowcount == 1
            conn.commit()
        return rejected

    # -- tokens ------------------------------------------------------------- #

    def issue_token(self, proposal: TradeProposal, ttl_seconds: int) -> ConfirmationToken:
        now = utc_now_ms()
        token = ConfirmationToken(
            proposal_id=proposal.id,
            issued_ts=now,
            expires_ts=now + ttl_seconds * 1000,
            proposal_fingerprint=fingerprint(proposal),
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tokens (token, proposal_id, fingerprint, issued_ts, expires_ts) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    token.token,
                    token.proposal_id,
                    token.proposal_fingerprint,
                    token.issued_ts,
                    token.expires_ts,
                ),
            )
            conn.commit()
        return token

    def consume_token(self, token: str, proposal: TradeProposal) -> str | None:
        """Spend a token. Returns None on success, or why it was refused.

        Single use, enforced by `used_ts IS NULL` in the same statement that
        marks it used -- so two simultaneous attempts cannot both succeed.
        """
        now = utc_now_ms()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT proposal_id, fingerprint, expires_ts, used_ts "
                "FROM tokens WHERE token = %s",
                (token,),
            )
            row = cur.fetchone()
            if row is None:
                return "no such confirmation token"

            objection = token_objection(row, proposal, now)
            if objection is not None:
                return objection

            cur.execute(
                "UPDATE tokens SET used_ts = %s WHERE token = %s AND used_ts IS NULL",
                (now, token),
            )
            spent = cur.rowcount == 1
            conn.commit()
            if not spent:
                return "that confirmation was used by another request"
        return None

    # -- reporting ---------------------------------------------------------- #

    def counts(self) -> dict[str, int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT status, count(*) FROM proposals GROUP BY status")
            rows = cur.fetchall()
        return {status: int(count) for status, count in rows}

    def history(self, limit: int = 50) -> list[TradeProposal]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload, status FROM proposals ORDER BY created_ts DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
        return [_hydrate(payload, status) for payload, status in rows]

    # -- testing support ---------------------------------------------------- #

    def truncate(self) -> None:
        """Empty every table. For tests, which need a clean database each time.

        CASCADE because tokens reference proposals; without it this fails on a
        foreign key and the next test starts with yesterday's rows.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE proposals, tokens CASCADE")
            conn.commit()
