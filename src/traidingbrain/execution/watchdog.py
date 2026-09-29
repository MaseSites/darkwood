"""The thing that notices an unprotected position.

The stop is sent with the entry, in one call, so in the ordinary case there is no
gap. This exists for the cases that are not ordinary: the exchange accepted the
entry and silently dropped the conditional part, a stop was cancelled by hand and
forgotten, or a partial fill left a position whose protection does not cover it.

None of those announce themselves. A position with no stop behaves exactly like a
position with a stop right up until the market moves, and then it does not stop.

The response is deliberately blunt. The watchdog tries once to re-attach the stop,
and if that does not work it closes the position at market. Closing a good trade
costs a small, known amount. Holding an unprotected leveraged position costs an
amount nobody has bounded, and the whole risk framework upstream is built on the
assumption that a stop exists.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from traidingbrain.domain.enums import Side
from traidingbrain.domain.proposal import Position


class Venue(Protocol):
    def open_positions(self) -> list[Position]: ...
    def stops_for(self, symbol: str) -> list[dict[str, Any]]: ...
    def close_position(self, symbol: str) -> str | None: ...


@dataclass
class WatchdogEvent:
    symbol: str
    action: str
    detail: str
    ts: float = field(default_factory=time.time)

    def __str__(self) -> str:
        return f"{self.symbol}: {self.action} -- {self.detail}"


class StopWatchdog:
    """Checks that every open position has a stop behind it, and acts if not."""

    def __init__(
        self,
        venue: Venue,
        *,
        deadline_seconds: float = 2.0,
        reattach: Callable[[Position], bool] | None = None,
    ) -> None:
        self.venue = venue
        self.deadline_seconds = deadline_seconds
        self.reattach = reattach
        self.events: list[WatchdogEvent] = []
        self._unprotected_since: dict[str, float] = {}

    def sweep(self, *, now: float | None = None) -> list[WatchdogEvent]:
        """One pass. Call it on a timer and after every fill.

        A grace period before acting, because a stop placed microseconds ago may not
        be visible on the next read. Closing a properly protected position because
        of a race would be its own kind of failure.
        """
        moment = now if now is not None else time.time()
        fired: list[WatchdogEvent] = []
        positions = self.venue.open_positions()
        live = {p.symbol for p in positions}

        for symbol in list(self._unprotected_since):
            if symbol not in live:
                del self._unprotected_since[symbol]

        for position in positions:
            if self._is_protected(position):
                self._unprotected_since.pop(position.symbol, None)
                continue

            first_seen = self._unprotected_since.setdefault(position.symbol, moment)
            waited = moment - first_seen
            if waited < self.deadline_seconds:
                continue

            fired.append(self._intervene(position, waited))

        self.events.extend(fired)
        return fired

    def _is_protected(self, position: Position) -> bool:
        """Is there a resting stop on the correct side, covering the whole position?

        Side and size both matter. A stop on the wrong side is not protection, and
        one covering half the position leaves the other half naked -- which is the
        case a simple "is there a stop order?" check misses entirely.
        """
        stops = self.venue.stops_for(position.symbol)
        if not stops:
            return False

        covered = 0.0
        for order in stops:
            price = _stop_price(order)
            if price is None:
                continue
            on_correct_side = (
                price < position.entry_price
                if position.side is Side.LONG
                else price > position.entry_price
            )
            if on_correct_side:
                covered += float(order.get("amount") or 0) or position.qty

        return covered >= position.qty * 0.999

    def _intervene(self, position: Position, waited: float) -> WatchdogEvent:
        if self.reattach is not None and self.reattach(position):
            return WatchdogEvent(
                position.symbol,
                "stop re-attached",
                f"position was unprotected for {waited:.1f}s; a stop has been placed",
            )

        reference = self.venue.close_position(position.symbol)
        return WatchdogEvent(
            position.symbol,
            "position closed",
            (
                f"unprotected for {waited:.1f}s and the stop could not be re-attached, "
                f"so it was closed at market ({reference}). A small known loss is the "
                f"correct trade against an unbounded unknown one."
            ),
        )

    def summary(self) -> str:
        if not self.events:
            return "  watchdog        nothing to report"
        lines = [f"  watchdog        {len(self.events)} intervention(s)"]
        lines.extend(f"    {event}" for event in self.events[-5:])
        return "\n".join(lines)


def _stop_price(order: dict[str, Any]) -> float | None:
    for key in ("stopPrice", "triggerPrice"):
        value = order.get(key)
        if value:
            return float(value)
    info = order.get("info")
    if isinstance(info, dict):
        value = info.get("stopLoss") or info.get("triggerPrice")
        if value:
            return float(value)
    return None
