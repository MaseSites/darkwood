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
from traidingbrain.domain.enums import STATE_OF_EXIT, ExitReason, OrderType, Side, TradeState
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


#: Milliseconds in an hour. `max_hold_hours` is the only setting here
#: expressed in wall-clock time, because the broker knows no timeframe.
HOUR_MS = 3_600_000


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
    #: Which rule proposed this, by name.
    #:
    #: Carried through to the Fill so that "which setup wins" is answerable per
    #: trade. Without it the only way to ask was to re-run the whole backtest
    #: with one setup switched off -- which answers a different question,
    #: because removing a setup frees its slots for the others.
    setup: str = ""
    #: Which chart the signal was read off, by the same reasoning as `setup`.
    #:
    #: A setup can fire on more than one timeframe, so the setup name does not
    #: say which one. The entry minute does not say it either: an H1 signal
    #: enters on :00 and an M15 signal on any quarter, so grouping trades by
    #: their minute mark without this field measures the timeframe and calls
    #: it the clock.
    timeframe: str = ""

    @property
    def planned_notional(self) -> float:
        """Positionsgroesse, wenn diese Order zum Limit fuellt.

        `planned_`, und das Praefix ist nicht Hoeflichkeit: eine Order fuellt
        nicht zwingend zum Limit, und sie fuellt vielleicht nie. Was
        tatsaechlich im Trade steckt, steht erst in `OpenPosition.notional`,
        gerechnet auf dem echten Fill-Preis. Die beiden gleich zu benennen
        waere die Einladung, die Absicht als Tatsache zu berichten.
        """
        return self.qty * self.limit_price

    @property
    def planned_margin(self) -> float:
        """Gebundenes Kapital, wenn diese Order zum Limit fuellt.

        Dieselbe Rechnung, die `fill()` macht: Notional durch Hebel. Hier
        als property statt als Kopie, damit Anzeige und Konto nicht
        auseinanderdriften koennen.
        """
        return self.planned_notional / self.leverage if self.leverage else 0.0


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
    setup: str = ""
    timeframe: str = ""
    stop_moved: bool = False
    """True once the breakeven rule has pulled the stop up. Checked so the
    move happens once; without it a later dip would re-arm it and the stop
    would walk back down to the entry it had already left."""

    @property
    def risk_price(self) -> float:
        """What one unit was risked, in price. Survives moving the stop.

        Taken from the sizing rather than from `entry_price - stop`, because
        after the first move that difference is zero and every R measured from
        it would be infinite."""
        return self.risk_amount / self.qty if self.qty else 0.0

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
    setup: str = ""
    timeframe: str = ""

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
        ledger: _Ledger | None = None,
    ) -> None:
        self.spec = spec
        self.config = config
        self.funding = sorted(funding or [], key=lambda f: f.ts)
        self._funding_cursor = 0
        #: The settlement time of the last funding rate the cursor consumed.
        #:
        #: Tracked separately from the cursor so `refresh_funding` can place a
        #: new schedule without trusting an index into the old one -- and
        #: deliberately not the clock, because a rate is published at its own
        #: settlement time and fetched minutes later, so "in the past" and
        #: "already settled" are different questions.
        self._funding_settled_ts = 0

        #: Die Kasse. Eigene oder geteilte.
        #:
        #: **Warum sie teilbar ist.** Der Papierhandel faehrt zwoelf Broker,
        #: einen je Symbol, jeder mit eigener Kasse von 1.000 USDT. Dadurch
        #: bemisst sich jede Position an einem Zwoelftel des Kapitals: 1 %
        #: Risiko je Trade sind 0,083 % des Ganzen. Das ist nicht als
        #: Risikoentscheidung gewaehlt, es faellt aus der Struktur.
        #:
        #: Die Groesse einfach zu verzwoelffachen genuegt nicht, und das ist
        #: gemessen: bei 1 % des Gesamtkapitals braucht die Position im
        #: schlimmsten Fall 1.733 USDT Margin, und ein Einzelkonto hat 1.006.
        #: Sechs von 26 Vorwaertstrades wuerden an `submit` scheitern -- und
        #: zwar die mit den ENGSTEN Stops, also die Population mit den
        #: besseren Bruttozahlen. Eine Auswahl aus einer Verrohrungsgrenze.
        #:
        #: Mit geteilter Kasse scheitert keiner von 26. Darum teilbar statt
        #: groesser.
        self.ledger = ledger if ledger is not None else _Ledger(
            equity=config.initial_equity, peak_equity=config.initial_equity
        )
        #: Ob diese Kasse diesem Broker allein gehoert.
        #:
        #: `paperstate.restore_into` setzt die Kontostaende beim Neustart
        #: zurueck. Bei geteilter Kasse wuerden das zwoelf Broker
        #: hintereinander mit zwoelf Zahlen tun, und der letzte gewinnt --
        #: still. Darum fragt der Wiederherstellungspfad hier nach.
        self.owns_ledger = ledger is None
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

    @property
    def funding_settled_ts(self) -> int:
        """The settlement time of the last rate the cursor consumed.

        Exposed because it is the one piece of funding state a restart cannot
        recompute. `funding_paid` is a sum, and a sum cannot say *which* rates
        are in it -- so without this number a restored broker cannot tell
        "already booked" from "still owed", and no ordering of the restore
        steps can be correct.
        """
        return self._funding_settled_ts

    def resume_funding(self, settled_ts: int) -> None:
        """Place the cursor from a settlement time restored from disk.

        The same placement `refresh_funding` makes, handed to the restore path
        so the position can be attached *before* anything is charged. That
        order matters: `_charge_funding` only credits a position that was
        already open when the rate settled, so charging while the position is
        still detached consumes the rate and books nothing -- which is exactly
        the defect this method exists to fix.
        """
        self._funding_settled_ts = settled_ts
        self._funding_cursor = sum(1 for rate in self.funding if rate.ts <= settled_ts)

    def settle_funding(self, ts: int) -> None:
        """Charge what is owed up to `ts`, with a position attached.

        Unlike `skip_to` this does not demand a flat broker, which is the
        whole point on the restore path. Everything else is identical: the
        cursor only moves forward, and `_charge_funding` still skips any rate
        that settled before the position opened.
        """
        self._charge_funding(ts)

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
            exit_fill = self._check_exits(ts, open_, high, low)
            if exit_fill is not None:
                return exit_fill
            # Only after the exits, so a minute that held both the stop and the
            # breakeven trigger is resolved as a stop. The same reasoning as
            # `pessimistic_intrabar`: OHLC cannot order two events inside one
            # minute, and assuming the kind one is how a backtest lies.
            self._maybe_move_to_breakeven(high, low)
            return None

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
            setup=pending.setup,
            timeframe=pending.timeframe,
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

        stop_hit = _touched(position.side, high, low, position.stop, adverse=True)
        target_hit = _touched(position.side, high, low, position.target, adverse=False)

        # Liquidation zuerst zu pruefen war falsch, und zwar auf eine Art, die
        # nur im Rand auffaellt. `risk/leverage.py` setzt den Hebel so, dass die
        # Liquidation mindestens 2,5 Stop-Weiten HINTER dem Stop liegt -- ein
        # Balken, der sie beruehrt, hat den Stop also auf dem Weg dorthin
        # ueberquert, und in der Wirklichkeit haette der Stop zuerst ausgefuehrt.
        #
        # Gemessen: genau ein Trade der 2'734 Replay-Trades wurde so verbucht
        # (SOLUSDT-1672552800000, short, Stop 10,07, Hebel 9x, abgeleitete
        # Liquidation 10,8288, verbucht bei 10,8321 als `liquidation`) und kam
        # mit **-3,8849 R** gegen ein Budget von 1 R heraus. Der schlechteste
        # Trade der ganzen Population war damit ein Artefakt der Reihenfolge,
        # und jedes Randmass -- schlechtester Trade, 5-%-Quantil -- trug ihn mit.
        #
        # Die Ausnahme, die bleibt: ein Sprung ueber beide Marken hinweg. Wenn
        # die Minute schon jenseits der Liquidation EROEFFNET, konnte auch der
        # Stop nicht zu seinem Preis ausfuehren, und dann ist die Liquidation
        # die richtige Antwort.
        liq_hit = _touched(position.side, high, low, position.liq_price, adverse=True)
        if liq_hit:
            moving_down = position.side is Side.LONG
            gapped_past_liq = (
                open_ <= position.liq_price if moving_down else open_ >= position.liq_price
            )
            if gapped_past_liq or not stop_hit:
                price = self._gap_aware(
                    open_, position.liq_price, position.side, adverse=True
                )
                return self._close(position, price, ts, ExitReason.LIQUIDATION)

        if stop_hit and ((target_hit and self.config.pessimistic_intrabar) or not target_hit):
            price = self._gap_aware(open_, position.stop, position.side, adverse=True)
            return self._close(position, price, ts, ExitReason.STOP)

        if target_hit:
            price = self._gap_aware(open_, position.target, position.side, adverse=False)
            return self._close(position, price, ts, ExitReason.TARGET)

        # Last, and the order is the whole correctness argument. Stop and target
        # must win the minute the clock runs out, because that is what the
        # labeller does: `learn/labels.py` resolves both barriers across the
        # entire horizon first and only falls through to TIME at the end. A time
        # branch above these two would close trades that had already hit their
        # stop and quietly disagree with every label ever computed.
        #
        # Off unless configured, so the champion is untouched and this is a
        # challenger arm rather than a change nobody measured.
        hold = self.config.max_hold_hours
        if hold is not None and ts - position.opened_ts >= hold * HOUR_MS:
            # `_slipped`, not `_gap_aware`: there is no level to gap through.
            # A time exit is a market order at whatever is there, and `on_minute`
            # is given no close, so the open of this minute is the only price
            # that exists -- which is also the price the labeller uses.
            price = self._slipped(open_, position.side, adverse=True)
            return self._close(position, price, ts, ExitReason.TIME)

        return None

    def _maybe_move_to_breakeven(self, high: float, low: float) -> None:
        """Pull the stop to the entry once the trade has run far enough.

        Measured from the favourable extreme of the minute, not its close: the
        trade really was that far ahead, and a rule that only counted closes
        would arm later than the one a person would actually have used.
        """
        trigger = self.config.breakeven_at_r
        position = self.position
        if trigger is None or position is None or position.stop_moved:
            return
        risk = position.risk_price
        if risk <= 0:
            return
        best = high - position.entry_price
        if position.side is Side.SHORT:
            best = position.entry_price - low
        if best < trigger * risk:
            return
        position.stop = position.entry_price
        position.stop_moved = True

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
        # A target is a limit order resting in the book and earns the maker fee;
        # everything else leaves at market and pays taker. Entries already made
        # this distinction and exits did not, so every take profit was charged
        # as though it had crossed the spread to get out.
        #
        # Worth 0.0092 R a trade, measured over 1,862 journalled trades: 37% of
        # them end at the target and each saves the 0.04% difference. That is a
        # seventh of all fees in a system whose entire net loss is fees.
        #
        # **It is also a constraint on the live side, not only a model change.**
        # It is only true if the executor places a resting limit at the target.
        # A take-profit-market order, which is the easier thing to send and what
        # most venues offer by default, crosses the spread and pays taker -- and
        # then this line would be quietly optimistic about every winner.
        maker_exit = reason is ExitReason.TARGET
        rate = self.spec.maker_fee if maker_exit else self.spec.taker_fee
        exit_fee = price * position.qty * rate
        fees = position.fees_paid + exit_fee

        state = STATE_OF_EXIT[reason]

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
            setup=position.setup,
            timeframe=position.timeframe,
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

    def refresh_funding(self, rates: list[FundingRate]) -> int:
        """Replace the funding schedule with a longer one, mid-run.

        The forward paper trader runs for days against a schedule it was handed
        once, at construction. Funding settles every eight hours, so every
        settlement falling due after the process started was charged against an
        empty tail of that list -- which is to say charged as zero. A long held
        two days in a positive-funding market pays for it, and the account did
        not. `scripts/papertrade.py` was already fetching the new rates every
        twenty cycles and writing them to disk, where nothing read them.

        The cursor is rebuilt from the last settlement actually *consumed*, not
        from how far the clock has run, and the difference is the whole fix. A
        rate for 08:00 is published at 08:00 and fetched by the next top-up a
        few minutes later, by which time the clock is already past it. Placing
        the cursor by the clock would discard it as "in the past" -- which is
        the behaviour this method exists to correct, reproduced one level down.
        Placing it by what was consumed charges it on the next minute step,
        where `_charge_funding` still checks that the position was open before
        the settlement.

        An index into the old list cannot be carried over, because the new list
        may start earlier or hold rates the old one lacked, and the same index
        would then point at a different settlement.

        The conservative edge: a rate arriving *older* than the last consumed
        one is skipped. That loses a late backfilled settlement rather than
        risking a second charge for one already paid, and double-charging is
        the error that would quietly make every held trade look worse.

        Returns how many settlements are now pending, so a caller can say
        whether the top-up actually brought anything.
        """
        self.funding = sorted(rates, key=lambda f: f.ts)
        self.resume_funding(self._funding_settled_ts)
        return len(self.funding) - self._funding_cursor

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
            # What has been consumed, which is what a later `refresh_funding`
            # must not offer again.
            self._funding_settled_ts = max(self._funding_settled_ts, rate.ts)

    def skip_to(self, ts: int) -> None:
        """Advance the clock without walking every minute.

        Only valid while nothing is working -- with no position and no resting
        order, the minute loop's sole effect is moving the funding cursor, and it
        does that identically in one step.

        Worth having because of the scale: a two-year backtest steps roughly one
        and a half million minutes, and the broker is flat for most of them. The
        caller is responsible for checking `is_flat`; this asserts it rather than
        trusting it, because a silent skip while a position was open would drop
        every fill in that hour.
        """
        if not self.is_flat:
            raise RuntimeError(
                "skip_to called while an order or position was live; that would "
                "discard fills rather than fast-forward past nothing"
            )
        self._charge_funding(ts)
