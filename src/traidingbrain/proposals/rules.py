"""The confirmation rules, shared by every store that holds proposals.

These moved out of `store.py` when a second implementation appeared. The reason
is not tidiness: this is the logic that decides whether a token may send an
order, and two copies of it would be two answers to that question. One of them
would drift, and the drift would be invisible until a token that should have been
refused was not.

So the rules live once, and a store is only the part that knows about rows.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from traidingbrain.domain.proposal import TradeProposal


def utc_now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def fingerprint(proposal: TradeProposal) -> str:
    """A hash of the numbers a confirmation is agreeing to.

    Only the numbers that change what gets sent. If any of them moves, the token
    stops matching -- so it is never possible to look at one trade, adjust it, and
    confirm the version you were shown first.
    """
    material = json.dumps(
        {
            "id": proposal.id,
            "side": proposal.side.value,
            "entry": round(proposal.entry, 8),
            "stop": round(proposal.stop, 8),
            "target": round(proposal.target, 8),
            "qty": round(proposal.qty, 8),
            "leverage": round(proposal.leverage, 4),
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def token_objection(
    row: tuple[str, str, int, int | None], proposal: TradeProposal, now: int
) -> str | None:
    """Why this token cannot be spent, or None.

    Separated from the spending so the reasons read as a list rather than as
    control flow, and so each one can be tested on its own.
    """
    proposal_id, stored_fingerprint, expires_ts, used_ts = row
    if used_ts is not None:
        return "that confirmation has already been used"
    if proposal_id != proposal.id:
        return "the confirmation belongs to a different proposal"
    if now >= expires_ts:
        return "the confirmation expired; the market has moved on since"
    if stored_fingerprint != fingerprint(proposal):
        return "the proposal changed after this confirmation was issued"
    return None
