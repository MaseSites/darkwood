"""The only module that can place an order.

Everything upstream analyses, proposes and waits. This sends. It is therefore the
one place where being careful matters more than being clever, and it is written to
be dull.

Five things it refuses to do:

**Start on mainnet by accident.** Testnet is the default and live requires an
explicit flag *and* a matching credential, so a stale config alone cannot arm it.

**Send without a stop.** The stop goes on the entry order in the same call. Bybit
accepts it there; a venue that does not would need the watchdog to close the gap,
and the gap is the dangerous part -- a position that exists for even a few seconds
without a stop is an unbounded loss waiting for a dropped connection.

**Send twice.** The `clientOrderId` is derived from the proposal, so a retry after
a timeout carries the same one and the exchange rejects the duplicate. That turns
"did that go through?" into a question with an answer.

**Change leverage under an open position.** `set_leverage` is symbol-wide, not
per-order. Changing it while something is open silently moves that position's
liquidation price, which is the kind of thing nobody finds out about until it
matters.

**Trust its own clock.** Bybit rejects requests whose timestamp drifts outside
`recvWindow`, and the resulting signature errors are sporadic and confusing. The
drift is measured once at startup and reported plainly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import ccxt

from traidingbrain.data.exchange import BybitDataSource
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import SymbolSpec
from traidingbrain.domain.proposal import ExecutionIntent, Position, TradeProposal
from traidingbrain.execution.intent import IntentLog, IntentState
from traidingbrain.risk.limits import KillSwitch

#: Clock drift beyond this makes signed requests fail unpredictably.
MAX_CLOCK_DRIFT_MS = 1500


class ExecutionRefusedError(RuntimeError):
    """A refusal by this system, not by the exchange."""


class UnsafeConfigurationError(ExecutionRefusedError):
    """The account is not in a state where sending would be safe."""


@dataclass(frozen=True)
class Preflight:
    """What the account looked like before anything was sent."""

    position_mode: str
    margin_mode: str
    clock_drift_ms: int
    open_positions: int
    testnet: bool

    def describe(self) -> str:
        return (
            f"{'testnet' if self.testnet else 'LIVE'} | {self.position_mode} mode, "
            f"{self.margin_mode} margin, clock off by {self.clock_drift_ms}ms, "
            f"{self.open_positions} position(s) open"
        )


class BybitExecutor:
    """Places orders on Bybit. Testnet unless told otherwise, twice."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        intents: IntentLog,
        kill_switch: KillSwitch,
        *,
        testnet: bool = True,
        allow_live: bool = False,
        exchange: Any | None = None,
    ) -> None:
        if not testnet and not allow_live:
            # Two independent signals are required to trade real money. A single
            # config value flipped by accident -- or carried over from a copied
            # file -- must not be enough.
            raise UnsafeConfigurationError(
                "live trading needs both testnet=False and allow_live=True; one alone "
                "is treated as a mistake"
            )

        self.testnet = testnet
        self.intents = intents
        self.kill_switch = kill_switch
        self._leverage_set: dict[str, float] = {}

        if exchange is not None:
            self.exchange = exchange
        else:
            self.exchange = ccxt.bybit(
                {
                    "apiKey": api_key,
                    "secret": api_secret,
                    "enableRateLimit": True,
                    "options": {"defaultType": "swap", "defaultSubType": "linear"},
                }
            )
            if testnet:
                self.exchange.set_sandbox_mode(True)

    # -- before anything is sent -------------------------------------------- #

    def preflight(self) -> Preflight:
        """Check the account is in a state where an order would behave as expected.

        Run once at startup and worth failing loudly on. Every item here is
        something that changes what an order does without changing the order.
        """
        server_ms = int(self.exchange.fetch_time())
        drift = abs(server_ms - int(time.time() * 1000))
        if drift > MAX_CLOCK_DRIFT_MS:
            raise UnsafeConfigurationError(
                f"this machine's clock is {drift}ms away from the exchange's; signed "
                f"requests will fail unpredictably until it is corrected"
            )

        positions = [p for p in self.exchange.fetch_positions() if float(p.get("contracts") or 0)]
        info = self.exchange.fetch_balance().get("info", {})

        return Preflight(
            position_mode=str(info.get("positionMode", "unknown")),
            margin_mode=str(info.get("marginMode", "unknown")),
            clock_drift_ms=drift,
            open_positions=len(positions),
            testnet=self.testnet,
        )

    def ensure_leverage(self, symbol: str, leverage: float) -> None:
        """Set leverage, refusing while a position in that symbol is open.

        `set_leverage` is symbol-wide rather than per-order. Changing it under an
        open position moves that position's liquidation price, and nobody finds out
        until the market goes there.
        """
        if self._leverage_set.get(symbol) == leverage:
            return

        held = [
            p
            for p in self.exchange.fetch_positions([_ccxt_symbol(symbol)])
            if float(p.get("contracts") or 0)
        ]
        if held:
            raise UnsafeConfigurationError(
                f"refusing to change {symbol} leverage to {leverage:g}x while a position "
                f"is open: it is a symbol-wide setting and would move that position's "
                f"liquidation price"
            )

        self.exchange.set_leverage(leverage, _ccxt_symbol(symbol))
        self._leverage_set[symbol] = leverage

    # -- sending ------------------------------------------------------------ #

    def send(self, proposal: TradeProposal) -> str:
        """Place the entry with its stop and target attached.

        The write-ahead record goes down first, so that a crash anywhere after this
        line leaves something for reconciliation to ask about.
        """
        if self.kill_switch.is_engaged():
            raise ExecutionRefusedError(f"kill switch engaged: {self.kill_switch.reason()}")

        existing = self.intents.for_proposal(proposal.id)
        if existing is not None:
            raise ExecutionRefusedError(
                f"this proposal already has an order intent in state "
                f"{existing.state.value}; resolve it through reconciliation rather "
                f"than sending again"
            )

        self.ensure_leverage(proposal.symbol, proposal.leverage)
        intent = self.intents.write_ahead(proposal, testnet=self.testnet)

        try:
            order = self._place(intent)
        except ccxt.BaseError as exc:
            # The order may or may not exist. Marked as sent rather than failed,
            # because the exchange is now the only authority on which -- and
            # marking it failed here would tell reconciliation not to look.
            self.intents.mark(intent.client_order_id, IntentState.SENT, note=f"send raised: {exc}")
            raise ExecutionRefusedError(f"the exchange refused or timed out: {exc}") from exc

        reference = str(order.get("id") or intent.client_order_id)
        self.intents.mark(intent.client_order_id, IntentState.CONFIRMED, exchange_ref=reference)
        return reference

    def _place(self, intent: ExecutionIntent) -> dict[str, Any]:
        """One call carrying entry, stop and target together.

        Not three calls. Between a filled entry and a separately-placed stop there
        is a window with an unprotected position in it, and that window is exactly
        where a dropped connection turns a one percent risk into an open-ended one.
        """
        side = "buy" if intent.side is Side.LONG else "sell"
        order: dict[str, Any] = self.exchange.create_order(
            _ccxt_symbol(intent.symbol),
            "limit",
            side,
            intent.qty,
            intent.entry,
            {
                "clientOrderId": intent.client_order_id,
                "stopLoss": intent.stop,
                "takeProfit": intent.target,
                "slTriggerBy": "MarkPrice",
                "tpTriggerBy": "MarkPrice",
                "timeInForce": "GTC",
                "reduceOnly": False,
            },
        )
        return order

    # -- reading ------------------------------------------------------------ #

    def open_positions(self) -> list[Position]:
        found: list[Position] = []
        for raw in self.exchange.fetch_positions():
            contracts = float(raw.get("contracts") or 0)
            if not contracts:
                continue
            found.append(
                Position(
                    symbol=_plain_symbol(str(raw.get("symbol", ""))),
                    side=Side.LONG if str(raw.get("side")) == "long" else Side.SHORT,
                    qty=contracts,
                    entry_price=float(raw.get("entryPrice") or 0) or 1e-9,
                    leverage=float(raw.get("leverage") or 1),
                    liquidation_price=float(raw.get("liquidationPrice") or 0) or 1e-9,
                    opened_ts=int(raw.get("timestamp") or 0),
                )
            )
        return found

    def stops_for(self, symbol: str) -> list[dict[str, Any]]:
        """Conditional orders resting on a symbol, for the watchdog to count."""
        return [
            order
            for order in self.exchange.fetch_open_orders(_ccxt_symbol(symbol))
            if order.get("stopPrice") or (order.get("info") or {}).get("stopLoss")
        ]

    def cancel_all(self, symbol: str) -> None:
        self.exchange.cancel_all_orders(_ccxt_symbol(symbol))

    def close_position(self, symbol: str) -> str | None:
        """Flatten a symbol at market. Used by the watchdog and the kill switch."""
        held = [
            p
            for p in self.exchange.fetch_positions([_ccxt_symbol(symbol)])
            if float(p.get("contracts") or 0)
        ]
        if not held:
            return None
        position = held[0]
        closing_side = "sell" if str(position.get("side")) == "long" else "buy"
        order = self.exchange.create_order(
            _ccxt_symbol(symbol),
            "market",
            closing_side,
            float(position["contracts"]),
            None,
            {"reduceOnly": True},
        )
        return str(order.get("id"))

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        return BybitDataSource(testnet=self.testnet, exchange=self.exchange).fetch_symbol_spec(
            symbol
        )


def _ccxt_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol
    return f"{symbol[:-4]}/USDT:USDT"


def _plain_symbol(ccxt_name: str) -> str:
    return ccxt_name.split(":", maxsplit=1)[0].replace("/", "")
