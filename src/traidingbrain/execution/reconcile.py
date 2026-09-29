"""Working out what actually happened, after the fact.

Run at startup and after any interruption. Its job is to answer one question for
every intent whose fate is unknown: does that order exist on the exchange?

The write-ahead log makes the question answerable. Without it, a crash between
sending and recording leaves a position the system has no name for -- it cannot
even ask, because it does not know what to ask about. With it, there is always a
`clientOrderId` to look up, and the exchange is the authority on the answer.

What this refuses to do is guess. An intent it cannot resolve stays unresolved and
is reported, rather than being quietly marked abandoned so the list looks clean. A
tidy log with a real orphaned position behind it is worse than an untidy one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from traidingbrain.domain.proposal import Position
from traidingbrain.execution.intent import IntentLog, IntentRecord, IntentState


class Venue(Protocol):
    def open_positions(self) -> list[Position]: ...

    def fetch_order_by_client_id(self, client_id: str, symbol: str) -> dict[str, Any] | None: ...


@dataclass
class Reconciliation:
    """What the pass found, in enough detail to act on."""

    adopted: list[str] = field(default_factory=list)
    abandoned: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    orphan_positions: list[Position] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.unresolved and not self.orphan_positions

    def summary(self) -> str:
        if self.is_clean and not self.adopted and not self.abandoned:
            return "  reconcile       nothing outstanding"

        lines = ["  reconcile"]
        if self.adopted:
            lines.append(f"    adopted   {len(self.adopted)} order(s) that had been sent")
        if self.abandoned:
            lines.append(
                f"    abandoned {len(self.abandoned)} intent(s) that never reached the venue"
            )
        if self.unresolved:
            lines.append(
                f"    UNRESOLVED {len(self.unresolved)} intent(s) -- the exchange could not be "
                f"asked; do not trade until this is settled"
            )
        if self.orphan_positions:
            lines.append(
                f"    ORPHANS   {len(self.orphan_positions)} position(s) with no matching "
                f"intent; something opened these outside this system"
            )
            lines.extend(
                f"      {p.symbol} {p.side.value} {p.qty:g} @ {p.entry_price:,.2f}"
                for p in self.orphan_positions
            )
        return "\n".join(lines)


def reconcile(log: IntentLog, venue: Venue) -> Reconciliation:
    """Resolve every unsettled intent against the exchange."""
    result = Reconciliation()
    outstanding = log.unresolved()
    positions = venue.open_positions()
    claimed: set[str] = set()

    for record in outstanding:
        resolved = _resolve(record, log, venue)
        if resolved is None:
            result.unresolved.append(record.client_order_id)
        elif resolved:
            result.adopted.append(record.client_order_id)
            claimed.add(record.intent.symbol)
        else:
            result.abandoned.append(record.client_order_id)

    # A position with no intent behind it was opened by something other than this
    # system -- by hand, by another process, or by an earlier build. Reported
    # rather than adopted: the risk layer has no record of what it was sized
    # against and cannot manage it.
    known = {r.intent.symbol for r in outstanding} | claimed
    result.orphan_positions = [p for p in positions if p.symbol not in known]

    return result


def _resolve(record: IntentRecord, log: IntentLog, venue: Venue) -> bool | None:
    """True if the order exists, False if it never did, None if unanswerable.

    The three-way return matters. Collapsing "could not ask" into "does not exist"
    would mark a live order abandoned, and the next proposal would open a second
    position on top of it.
    """
    try:
        order = venue.fetch_order_by_client_id(record.client_order_id, record.intent.symbol)
    except Exception as exc:  # broad on purpose: any failure to ask is 'unknown'
        log.mark(record.client_order_id, record.state, note=f"could not be checked: {exc}")
        return None

    if order is None:
        log.mark(
            record.client_order_id,
            IntentState.ABANDONED,
            note="the exchange has no record of this order",
        )
        return False

    log.mark(
        record.client_order_id,
        IntentState.CONFIRMED,
        exchange_ref=str(order.get("id") or record.client_order_id),
        note=f"adopted during reconciliation, status {order.get('status')}",
    )
    return True
