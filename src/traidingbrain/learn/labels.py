"""What became of a signal, under the rules that would have traded it.

The masterplan asks for this in section 8: for every signal, simulate its
outcome against three pre-declared barriers -- a stop, a target and a time limit
-- and use that as the label a filter learns from. The triple-barrier method.

**Why this cannot just read the journal.** The journal holds trades the account
actually took, and `sim/engine.py:201` only asks the strategy while the broker
is flat. A signal that fired while a position was open was never even seen. So
the journal is a record of signals that happened to find a free slot, and every
filter measured against it on 04.10.2026 ran into the same confound: removing a
trade frees its slot, another setup fills it, and the journal cannot say what
the account would have done instead. Labelling each signal on its own -- as if
it were the only thing in the world -- is what separates "is this signal good"
from "did this signal get a slot".

**Price units, not francs.** Everything here is expressed in multiples of the
planned risk, `|entry - stop|` per unit. The position size cancels out of the
R-multiple exactly, so a label does not depend on the account balance, the
venue's lot size, or which market it came from. That is not only convenient: it
is the same structural guarantee the snapshot normalisation gives the model. A
label that moved when equity moved would make every fold of a walk-forward test
incomparable with the next.

**The fee schedule is the whole game, so it is spelled out.** Entry rests as a
limit and earns maker. A target exit rests as a limit and earns maker. A stop
and a time exit cross the spread and pay taker plus slippage. That asymmetry is
real -- it is `sim/broker.py:434` -- and it is also the trap that nearly produced
a false finding on 04.10.2026: priced after the fact, "winners had lower costs"
is just "winners exited at the target". So `cost_r` is reported separately from
`gross_r`, and anything training on these labels must take its cost feature from
the plan, never from the realised fee.

**One implementation, two readers.** The barrier search here is vectorised over
numpy minute arrays, because a broker stepped minute by minute over every
candidate signal would take hours rather than minutes. That buys speed by
holding a second copy of rules whose authority is `sim/broker.py`, which is
exactly the duplication `sim/plan.py` exists to avoid. The guarantee is
`tests/test_labels.py::test_the_labeller_agrees_with_the_broker`: real signals
run through both, and the exit reason, exit price and R must match. If the
broker's rules change and this file is not changed with it, that test fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from traidingbrain.config.settings import SimulationConfig
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import FundingRate, SymbolSpec

#: Basis points, as `sim/broker.py` defines them.
BPS = 1e-4

#: Above this share of closed labels leaving by the time barrier, the labels
#: are describing a different system from the one the broker runs -- which has
#: no time exit at all -- and the horizon needs lengthening before they are
#: trained on.
TIME_BARRIER_WARN_PCT = 20.0


class Barrier(StrEnum):
    """Which of the three doors the signal left through."""

    TARGET = "ziel"
    STOP = "stop"
    TIME = "zeit"
    """The horizon ran out with the trade still open, so it is closed at market.

    The broker has no time exit -- a position there runs to its stop or its
    target and nothing else. This barrier is a labelling device, not a trading
    rule, and it exists because section 8 requires a label to be *closed*: an
    open case has no outcome and must not be trained on. How often it binds is
    reported by `Tally`, because a horizon that binds frequently would mean the
    labels describe a different system from the one that trades."""

    UNFILLED = "nicht_gefuellt"
    """The limit was never reached inside the entry window.

    Not a loss and not a win: no trade existed. Counting it as a zero would put
    a trade that never happened into the evidence, which is the mistake
    `sim/engine.py:361` already names on the history index."""


@dataclass(frozen=True)
class Label:
    """The closed outcome of one signal, in multiples of its planned risk."""

    barrier: Barrier
    filled_ts: int
    closed_ts: int
    entry_price: float
    exit_price: float
    gross_r: float
    """Before costs. Zero-ish on average for this strategy, which is the finding
    that makes the cost decomposition worth keeping separate."""

    cost_r: float
    """Fees and slippage, as a fraction of the planned risk. Always positive."""

    funding_r: float
    """Funding settled over the hold, as a fraction of the planned risk.

    Signed: negative when the position paid, positive when it was paid. Longs
    pay shorts while the rate is positive, which over a trade held for days is
    a real cost running one way -- and a label that ignored it would be
    optimistic about exactly the trades the time barrier keeps open longest. A
    48-hour horizon spans up to six settlements."""

    minutes_held: int

    @property
    def net_r(self) -> float:
        return self.gross_r - self.cost_r + self.funding_r

    @property
    def resolved(self) -> bool:
        """May this be trained on?

        An unfilled signal has no outcome. Everything else does, including a
        time-barrier exit -- that is the point of having a time barrier.
        """
        return self.barrier is not Barrier.UNFILLED

    @property
    def won(self) -> bool:
        return self.resolved and self.net_r > 0


#: A signal that never filled, with no outcome attached.
UNFILLED = Label(
    barrier=Barrier.UNFILLED,
    filled_ts=0,
    closed_ts=0,
    entry_price=0.0,
    exit_price=0.0,
    gross_r=0.0,
    cost_r=0.0,
    funding_r=0.0,
    minutes_held=0,
)


@dataclass
class Tally:
    """How the labels came out, as a check on the labelling itself."""

    target: int = 0
    stop: int = 0
    time: int = 0
    unfilled: int = 0

    def add(self, label: Label) -> None:
        match label.barrier:
            case Barrier.TARGET:
                self.target += 1
            case Barrier.STOP:
                self.stop += 1
            case Barrier.TIME:
                self.time += 1
            case Barrier.UNFILLED:
                self.unfilled += 1

    @property
    def resolved(self) -> int:
        return self.target + self.stop + self.time

    def summary(self) -> str:
        total = self.resolved + self.unfilled
        if total == 0:
            return "  keine Signale"
        share = 100 * self.time / self.resolved if self.resolved else 0.0
        return (
            f"  {total:6d} Signale: {self.target} am Ziel, {self.stop} am Stop, "
            f"{self.time} per Zeit, {self.unfilled} nie gefuellt\n"
            f"  Zeitschranke bindet in {share:.1f}% der geschlossenen Faelle"
            + (
                "  <- zu oft; die Labels beschreiben ein anderes System als der Broker"
                if share > TIME_BARRIER_WARN_PCT
                else ""
            )
        )


@dataclass(frozen=True)
class Minutes:
    """The M1 series as flat arrays, unpacked once per market.

    The engine makes the same move for the same reason: indexing numpy
    positionally rather than querying a frame per hour is most of the difference
    between a backtest that takes minutes and one that takes hours.
    """

    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray

    @classmethod
    def of(cls, frame: object) -> Minutes:
        return cls(
            ts=frame["ts"].to_numpy(dtype="int64"),  # type: ignore[index]
            open=frame["open"].to_numpy(dtype="float64"),  # type: ignore[index]
            high=frame["high"].to_numpy(dtype="float64"),  # type: ignore[index]
            low=frame["low"].to_numpy(dtype="float64"),  # type: ignore[index]
        )

    def __len__(self) -> int:
        return int(self.ts.size)


def _slipped(price: float, side: Side, slippage_bps: float, *, adverse: bool) -> float:
    """Slippage, only ever against us. Mirrors `sim/broker.py:412`."""
    amount = price * slippage_bps * BPS
    worse_is_lower = (side is Side.LONG) == adverse
    return price - amount if worse_is_lower else price + amount


def _gap_aware(
    open_: float, level: float, side: Side, slippage_bps: float, *, adverse: bool
) -> float:
    """The price actually obtainable, which may be worse. Mirrors `broker.py:400`.

    A minute that opened past the level fills at the open, not the level. That is
    one of the few ways a trade loses more than it planned to, and a labeller
    that never modelled it would be quietly optimistic about every stop.
    """
    moving_down = (side is Side.LONG) == adverse
    gapped = open_ < level if moving_down else open_ > level
    price = open_ if gapped else level
    return _slipped(price, side, slippage_bps, adverse=adverse) if adverse else price


def _funding_over(
    funding: list[FundingRate] | None,
    *,
    side: Side,
    fill_price: float,
    risk: float,
    opened_ts: int,
    closed_ts: int,
) -> float:
    """Funding settled while the position was open, in multiples of the risk.

    Mirrors `sim/broker.py:489`: charged against the open position only, and
    only for settlements strictly after it opened -- a rate that settled in the
    same minute the trade was entered is one the position was not yet there for.

    Scale-free like everything else here. The broker charges
    `-notional * rate * sign` with `notional = qty * entry_price`, and the R
    denominator is `qty * risk`, so the quantity cancels exactly and what
    remains depends only on prices.
    """
    if not funding or risk <= 0:
        return 0.0
    total = 0.0
    for rate in funding:
        if opened_ts < rate.ts <= closed_ts:
            total += -fill_price * rate.rate * side.sign
    return total / risk


def _entry_index(
    minutes: Minutes,
    *,
    side: Side,
    limit: float,
    lo: int,
    hi: int,
    fill_on_touch: bool,
) -> tuple[int, float] | None:
    """The first minute the limit would have filled, and at what price.

    Mirrors `sim/broker.py:333`. A minute that opened through the level fills at
    the open -- a better price than asked for, which is what actually happens.
    Otherwise the level has to be reached, and with `fill_on_touch` false it has
    to be traded *through*: a touch means the price printed there, not that our
    order was at the front of the queue.
    """
    if hi <= lo:
        return None
    o = minutes.open[lo:hi]
    if side is Side.LONG:
        through_open = o <= limit
        reached = (minutes.low[lo:hi] <= limit) if fill_on_touch else (minutes.low[lo:hi] < limit)
    else:
        through_open = o >= limit
        reached = (minutes.high[lo:hi] >= limit) if fill_on_touch else (minutes.high[lo:hi] > limit)

    possible = through_open | reached
    if not possible.any():
        return None
    k = int(np.argmax(possible))
    return lo + k, (float(o[k]) if bool(through_open[k]) else limit)


def label_signal(
    *,
    side: Side,
    entry: float,
    stop: float,
    target: float,
    decision_ts: int,
    minutes: Minutes,
    spec: SymbolSpec,
    config: SimulationConfig,
    horizon_ms: int,
    expiry_ms: int,
    funding: list[FundingRate] | None = None,
) -> Label:
    """Replay one signal against its three barriers.

    `decision_ts` is when the order becomes live, which is the *start of the bar
    after* the one that produced the signal. The engine computes it the same way
    (`sim/engine.py:223`) and the reason is the same: filling inside the bar the
    decision was made on is a free head start, and on its own it is enough to
    turn a losing strategy into a winning backtest.

    Liquidation is deliberately not a barrier here. `risk/leverage.py` only
    returns a leverage whose liquidation sits at least 2.5 stop-distances beyond
    the stop, so for any signal that becomes a trade the stop is always nearer
    and always fires first. Modelling it anyway would require a position size,
    and that would cost the scale invariance this module is built on.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return UNFILLED

    n = len(minutes)
    lo = int(np.searchsorted(minutes.ts, decision_ts, side="left"))
    filled = _entry_index(
        minutes,
        side=side,
        limit=entry,
        lo=lo,
        hi=min(n, int(np.searchsorted(minutes.ts, decision_ts + expiry_ms, side="left"))),
        fill_on_touch=config.fill_on_touch,
    )
    if filled is None:
        return UNFILLED

    at, fill_price = filled
    filled_ts = int(minutes.ts[at])

    # Exits are examined from the minute *after* the fill. `broker.on_minute`
    # returns as soon as it has filled a pending entry, so the minute that
    # created the position never also closes it. Starting the scan at `at`
    # instead would let a signal stop out in the same minute it entered, and
    # every very tight stop would look worse than it is.
    start = at + 1
    end = min(n, int(np.searchsorted(minutes.ts, filled_ts + horizon_ms, side="right")))

    sign = 1.0 if side is Side.LONG else -1.0
    slippage = config.slippage_bps

    if end > start:
        high = minutes.high[start:end]
        low = minutes.low[start:end]
        stop_hit = (low <= stop) if side is Side.LONG else (high >= stop)
        target_hit = (high >= target) if side is Side.LONG else (low <= target)
        event = stop_hit | target_hit
        if event.any():
            k = int(np.argmax(event))
            o = float(minutes.open[start + k])
            # The same precedence as `broker._check_exits`: when one minute holds
            # both, the stop wins. OHLC cannot order two events inside a minute,
            # and assuming the kind one is how a backtest lies.
            stopped = bool(stop_hit[k]) and (
                (bool(target_hit[k]) and config.pessimistic_intrabar) or not bool(target_hit[k])
            )
            barrier = Barrier.STOP if stopped else Barrier.TARGET
            level = stop if stopped else target
            exit_price = _gap_aware(o, level, side, slippage, adverse=stopped)
            exit_rate = spec.taker_fee if stopped else spec.maker_fee
            closed_ts = int(minutes.ts[start + k])
            return Label(
                barrier=barrier,
                filled_ts=filled_ts,
                closed_ts=closed_ts,
                entry_price=fill_price,
                exit_price=exit_price,
                gross_r=sign * (exit_price - fill_price) / risk,
                cost_r=(fill_price * spec.maker_fee + exit_price * exit_rate) / risk,
                funding_r=_funding_over(
                    funding,
                    side=side,
                    fill_price=fill_price,
                    risk=risk,
                    opened_ts=filled_ts,
                    closed_ts=closed_ts,
                ),
                minutes_held=start + k - at,
            )

    # The horizon ran out. Closed at market on the first minute past it, which
    # pays taker and slippage like any other exit that crosses the spread. Where
    # the series itself ends before the horizon, the last minute available is
    # used -- the alternative is discarding the most recent signals, which are
    # the ones a walk-forward test needs most.
    last = min(max(end, start), n) - 1
    if last < at:
        return UNFILLED
    exit_price = _slipped(float(minutes.open[last]), side, slippage, adverse=True)
    return Label(
        barrier=Barrier.TIME,
        filled_ts=filled_ts,
        closed_ts=int(minutes.ts[last]),
        entry_price=fill_price,
        exit_price=exit_price,
        gross_r=sign * (exit_price - fill_price) / risk,
        cost_r=(fill_price * spec.maker_fee + exit_price * spec.taker_fee) / risk,
        funding_r=_funding_over(
            funding,
            side=side,
            fill_price=fill_price,
            risk=risk,
            opened_ts=filled_ts,
            closed_ts=int(minutes.ts[last]),
        ),
        minutes_held=last - at,
    )
