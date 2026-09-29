"""The simulated exchange.

A backtest is only worth what its broker model is worth. Four things separate a
useful simulator from a flattering one, and all four are handled here.

**Intrabar ordering.** When an hourly candle contains both the stop and the
target, OHLC alone cannot say which came first. Guessing in our favour is the
single most common way a strategy looks profitable on paper and is not. This
simulator resolves the hour minute by minute against the M1 series, and where even
a minute is ambiguous the stop wins.

**Gaps.** Price does not stop at the stop. If a minute opens beyond it, the fill is
at the open and the loss is larger than planned. A simulator that always fills at
the stop price reports a loss the account never had the chance to take.

**Funding.** Charged from the venue's realised rates at its own settlement times,
not estimated. A guessed rate quietly changes the outcome of every trade held
overnight, in one direction.

**Liquidation.** With leverage the exchange has an opinion about when the trade is
over, and it does not consult the plan. A simulator without it reports a 2% loss
where the account actually lost its whole margin.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from traidingbrain.config.settings import SimulationConfig
from traidingbrain.domain.enums import ExitReason, OrderType, Side, TradeState
from traidingbrain.domain.market import FundingRate, SymbolSpec
from traidingbrain.risk.leverage import liquidation_price

#: Basis points to fraction.
BPS = 1e-4


def round_to_step(value: float, step: float) -> float:
    """Round down to the venue's increment.

    Down, not nearest: rounding a quantity up can push the notional past what the
    margin supports, and the rejection then happens at the exchange rather than
    here.
    """
    if step <= 0:
        return value
    return int(value / step) * step


def _touched(side: Side, high: float, low: float, level: float, *, adverse: bool) -> bool:
    """Did this minute reach a level, in the direction that matters?"""
    moving_down = (side is Side.LONG) == adverse
    return low <= level if moving_down else high >= level


@dataclass
class PendingEntry:
    """An order waiting to be filled."""

    side: Side
    order_type: OrderType
    limit_price: float
    stop: float
    target: float
    qty: float
    leverage: float
    created_ts: int
    expires_ts: int
    risk_amount: float
    snapshot_hash: str = ""
    proposal_id: str = ""


@dataclass
class OpenPosition:
    """A live position and everything charged against it so far."""

    side: Side
    entry_price: float
    qty: float
    leverage: float
    stop: float
    target: float
    liq_price: float
    opened_ts: int
    margin: float
    risk_amount: float
    fees_paid: float = 0.0
    funding_paid: float = 0.0
    snapshot_hash: str = ""
    proposal_id: str = ""

    @property
    def notional(self) -> float:
        return self.qty * self.entry_price

    def unrealised(self, price: float) -> float:
        return (price - self.entry_price) * self.qty * self.side.sign


@dataclass(frozen=True)
class Fill:
    """A completed trade, with every cost accounted for."""

    proposal_id: str
    snapshot_hash: str
    side: Side
    state: TradeState
    reason: ExitReason
    entry_price: float
    exit_price: float
    qty: float
    leverage: float
    opened_ts: int
    closed_ts: int
    gross_pnl: float
    fees: float
    funding: float
    risk_amount: float

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.fees + self.funding

    @property
    def r_multiple(self) -> float:
        """Result as a multiple of what was risked.

        The unit that makes trades comparable across position sizes, and the one
        expectancy is measured in.
        """
        if self.risk_amount <= 0:
            return 0.0
        return self.net_pnl / self.risk_amount


@dataclass
class _Ledger:
    equity: float
    peak_equity: float
    fills: list[Fill] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)


class SimBroker:
    """A single-symbol, single-position simulated venue.

    Deliberately narrow. The live adapter in `execution` drives the same lifecycle
    through the same protocol, and holding both to one position per symbol means
    the backtest exercises what runs live rather than a more permissive cousin of
    it.
    """

    def __init__(
        self,
        spec: SymbolSpec,
        config: SimulationConfig,
        funding: list[FundingRate] | None = None,
    ) -> None:
        self.spec = spec
        self.config = config
        self.funding = sorted(funding or [], key=lambda f: f.ts)
        self._funding_cursor = 0

        self.ledger = _Ledger(equity=config.initial_equity, peak_equity=config.initial_equity)
        self.pending: PendingEntry | None = None
        self.position: OpenPosition | None = None
        self.rejected_entries = 0
        self.expired_entries = 0

    # -- state -------------------------------------------------------------- #

    @property
    def equity(self) -> float:
        return self.ledger.equity

    @property
    def fills(self) -> list[Fill]:
        return self.ledger.fills

    @property
    def equity_curve(self) -> list[tuple[int, float]]:
        return self.ledger.equity_curve

    @property
    def is_flat(self) -> bool:
        return self.position is None and self.pending is None

    def mark(self, ts: int, price: float) -> None:
        """Record equity including open profit, for the drawdown curve.

        Drawdown measured on closed trades only understates it: an account that
        went 40% underwater before recovering did experience that, and a number
        that hides it is not a risk measure.
        """
        floating = self.position.unrealised(price) if self.position else 0.0
        value = self.ledger.equity + floating
        self.ledger.equity_curve.append((ts, value))
        self.ledger.peak_equity = max(self.ledger.peak_equity, value)

    # -- orders ------------------------------------------------------------- #

    def submit(self, entry: PendingEntry) -> bool:
        """Queue an entry. Refused if something is already working.

        Returns False rather than raising: a strategy proposing a trade while one
        is open is ordinary, and the count of refusals is itself worth reporting --
        a strategy that is constantly blocked is not the one that was measured.
        """
        if self.position is not None or self.pending is not None:
            self.rejected_entries += 1
            return False

        qty = round_to_step(entry.qty, self.spec.qty_step)
        if qty < self.spec.min_qty or qty * entry.limit_price < self.spec.min_notional:
            self.rejected_entries += 1
            return False

        if qty * entry.limit_price / entry.leverage > self.ledger.equity:
            self.rejected_entries += 1
            return False

        entry.qty = qty
        self.pending = entry
        return True

    def cancel_pending(self) -> None:
        self.pending = None

    # -- the clock ---------------------------------------------------------- #

    def on_minute(self, ts: int, open_: float, high: float, low: float) -> Fill | None:
        """Advance one minute. At most one thing happens per minute.

        Order within the minute is fixed and pessimistic: funding first, then
        liquidation, then the stop, then the target. Liquidation before the stop
        because the exchange does not wait; the stop before the target because when
        one minute holds both, OHLC cannot say which came first and assuming the
        good one is how a backtest lies.

        Takes loose floats rather than a `Bar`. This runs well over a million times
        per backtest, and validating a model per minute costs more than the rest of
        the simulation put together. `close` is absent because nothing here needs
        it: fills are decided by open, high and low.
        """
        self._charge_funding(ts)

        if self.position is not None:
            return self._check_exits(ts, open_, high, low)

        if self.pending is not None:
            if ts >= self.pending.expires_ts:
                self.pending = None
                self.expired_entries += 1
                return None
            self._try_fill(ts, open_, high, low)
        return None

    # -- entry -------------------------------------------------------------- #

    def _try_fill(self, ts: int, open_: float, high: float, low: float) -> None:
        pending = self.pending
        if pending is None:
            return

        price = self._entry_fill_price(pending, open_, high, low)
        if price is None:
            return

        notional = pending.qty * price
        margin = notional / pending.leverage
        if margin > self.ledger.equity:
            self.pending = None
            self.rejected_entries += 1
            return

        # A limit order that was already resting earns the maker fee; a market
        # entry crosses the spread and pays taker.
        fee_rate = (
            self.spec.maker_fee if pending.order_type is OrderType.LIMIT else self.spec.taker_fee
        )

        self.position = OpenPosition(
            side=pending.side,
            entry_price=price,
            qty=pending.qty,
            leverage=pending.leverage,
            stop=pending.stop,
            target=pending.target,
            liq_price=liquidation_price(
                pending.side, price, pending.leverage, self.spec.maintenance_margin_rate
            ),
            opened_ts=ts,
            margin=margin,
            risk_amount=pending.risk_amount,
            fees_paid=notional * fee_rate,
            snapshot_hash=pending.snapshot_hash,
            proposal_id=pending.proposal_id,
        )
        self.pending = None

    def _entry_fill_price(
        self, pending: PendingEntry, open_: float, high: float, low: float
    ) -> float | None:
        """Where a limit order would have filled in this minute, if at all."""
        if pending.order_type is OrderType.MARKET:
            return self._slipped(open_, pending.side, adverse=True)

        limit = pending.limit_price
        if pending.side is Side.LONG:
            if open_ <= limit:
                # Already through the level when the minute opened: a better fill
                # than asked for, which is what actually happens.
                return open_
            reached = low <= limit if self.config.fill_on_touch else low < limit
            return limit if reached else None

        if open_ >= limit:
            return open_
        reached = high >= limit if self.config.fill_on_touch else high > limit
        return limit if reached else None

    # -- exits -------------------------------------------------------------- #

    def _check_exits(self, ts: int, open_: float, high: float, low: float) -> Fill | None:
        position = self.position
        if position is None:
            return None

        if _touched(position.side, high, low, position.liq_price, adverse=True):
            price = self._gap_aware(open_, position.liq_price, position.side, adverse=True)
            return self._close(position, price, ts, ExitReason.LIQUIDATION)

        stop_hit = _touched(position.side, high, low, position.stop, adverse=True)
        target_hit = _touched(position.side, high, low, position.target, adverse=False)

        if stop_hit and ((target_hit and self.config.pessimistic_intrabar) or not target_hit):
            price = self._gap_aware(open_, position.stop, position.side, adverse=True)
            return self._close(position, price, ts, ExitReason.STOP)

        if target_hit:
            price = self._gap_aware(open_, position.target, position.side, adverse=False)
            return self._close(position, price, ts, ExitReason.TARGET)

        return None

    def _gap_aware(self, open_: float, level: float, side: Side, *, adverse: bool) -> float:
        """The price actually obtainable, which may be worse than the level.

        If the minute opened past the level, the order fills at the open. A gap
        through a stop is one of the few ways a trade loses more than planned, and
        a simulator that never models it is quietly optimistic about every one.
        """
        moving_down = (side is Side.LONG) == adverse
        gapped = open_ < level if moving_down else open_ > level
        price = open_ if gapped else level
        return self._slipped(price, side, adverse=adverse) if adverse else price

    def _slipped(self, price: float, side: Side, *, adverse: bool) -> float:
        """Apply slippage against us. Only ever against us."""
        amount = price * self.config.slippage_bps * BPS
        worse_is_lower = (side is Side.LONG) == adverse
        return price - amount if worse_is_lower else price + amount

    def _close(self, position: OpenPosition, price: float, ts: int, reason: ExitReason) -> Fill:
        gross = (price - position.entry_price) * position.qty * position.side.sign
        exit_fee = price * position.qty * self.spec.taker_fee
        fees = position.fees_paid + exit_fee

        state = {
            ExitReason.STOP: TradeState.CLOSED_STOP,
            ExitReason.TARGET: TradeState.CLOSED_TARGET,
            ExitReason.LIQUIDATION: TradeState.CLOSED_LIQUIDATED,
            ExitReason.MANUAL: TradeState.CLOSED_MANUAL,
            ExitReason.INVALIDATION: TradeState.CLOSED_MANUAL,
        }[reason]

        if reason is ExitReason.LIQUIDATION:
            # Isolated margin: what is lost is the margin, no more and no less.
            # Deriving it from the fill price instead would make the loss depend on
            # how far past the liquidation level that minute happened to trade,
            # which is not how the venue settles it.
            net = -position.margin
            gross = net + fees - position.funding_paid
        else:
            net = gross - fees + position.funding_paid

        self.ledger.equity += net
        fill = Fill(
            proposal_id=position.proposal_id,
            snapshot_hash=position.snapshot_hash,
            side=position.side,
            state=state,
            reason=reason,
            entry_price=position.entry_price,
            exit_price=price,
            qty=position.qty,
            leverage=position.leverage,
            opened_ts=position.opened_ts,
            closed_ts=ts,
            gross_pnl=gross,
            fees=fees,
            funding=position.funding_paid,
            risk_amount=position.risk_amount,
        )
        self.ledger.fills.append(fill)
        self.position = None
        return fill

    def close_at(
        self, price: float, ts: int, reason: ExitReason = ExitReason.MANUAL
    ) -> Fill | None:
        if self.position is None:
            return None
        return self._close(self.position, price, ts, reason)

    # -- funding ------------------------------------------------------------ #

    def _charge_funding(self, ts: int) -> None:
        """Settle any funding whose settlement time has passed.

        Charged against the open position only. Longs pay shorts when the rate is
        positive, which over a trend-following trade held for days is a real cost
        that only ever runs one way.
        """
        while self._funding_cursor < len(self.funding):
            rate = self.funding[self._funding_cursor]
            if rate.ts > ts:
                break
            if self.position is not None and self.position.opened_ts < rate.ts:
                self.position.funding_paid += (
                    -self.position.notional * rate.rate * self.position.side.sign
                )
            self._funding_cursor += 1
