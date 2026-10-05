"""Does the labeller describe the same trade the broker would have made?

`learn/labels.py` holds a second copy of the fill and exit rules, vectorised so
that labelling tens of thousands of candidate signals takes minutes instead of
hours. A second copy of rules is exactly the duplication `sim/plan.py` exists to
prevent, and the argument for allowing it here is this file: the two
implementations are run against the same minute series and must produce the same
exit reason, the same exit price and the same R.

`test_the_labeller_agrees_with_the_broker` is the one that matters. It drives a
few hundred random price paths through both and compares. If the broker's cost
model or intrabar precedence changes and `labels.py` is not changed with it, that
test fails rather than a study quietly reporting labels from a system nobody
runs.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH
from traidingbrain.config.settings import SimulationConfig
from traidingbrain.domain.enums import ExitReason, OrderType, Side
from traidingbrain.domain.market import FundingRate
from traidingbrain.learn.labels import Barrier, Minutes, Tally, label_signal
from traidingbrain.sim.broker import PendingEntry, SimBroker

MINUTE = 60_000
HOUR = 60 * MINUTE


def config(**overrides: object) -> SimulationConfig:
    defaults: dict[str, object] = {
        "initial_equity": 10_000.0,
        "slippage_bps": 3.0,
        "fill_on_touch": False,
        "entry_expiry_bars": 32,
        "pessimistic_intrabar": True,
    }
    return SimulationConfig.model_validate(defaults | overrides)


def series(rows: list[tuple[float, float, float]], start: int = EPOCH) -> Minutes:
    """(open, high, low) triples, one per minute, as the labeller reads them."""
    return Minutes(
        ts=np.array([start + i * MINUTE for i in range(len(rows))], dtype="int64"),
        open=np.array([r[0] for r in rows], dtype="float64"),
        high=np.array([r[1] for r in rows], dtype="float64"),
        low=np.array([r[2] for r in rows], dtype="float64"),
    )


def label(
    rows: list[tuple[float, float, float]],
    *,
    side: Side = Side.LONG,
    entry: float = 100.0,
    stop: float = 90.0,
    target: float = 120.0,
    horizon_ms: int = 48 * HOUR,
    spec: object | None = None,
    cfg: SimulationConfig | None = None,
    funding: list[FundingRate] | None = None,
):
    settings = cfg or config()
    return label_signal(
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        decision_ts=EPOCH,
        minutes=series(rows),
        spec=spec or make_symbol_spec(),  # type: ignore[arg-type]
        config=settings,
        horizon_ms=horizon_ms,
        expiry_ms=settings.entry_expiry_bars * 15 * MINUTE,
        funding=funding,
    )


# --------------------------------------------------------------------------- #
# The three doors
# --------------------------------------------------------------------------- #


def test_a_signal_that_reaches_its_target() -> None:
    result = label([(105, 106, 101), (102, 103, 98), (110, 121, 109)])
    assert result.barrier is Barrier.TARGET
    assert result.entry_price == pytest.approx(100.0)
    # A target rests in the book: filled at the level, no slippage.
    assert result.exit_price == pytest.approx(120.0)
    assert result.gross_r == pytest.approx(2.0)
    assert result.resolved and result.won


def test_a_signal_that_reaches_its_stop() -> None:
    result = label([(105, 106, 101), (102, 103, 98), (95, 96, 89)])
    assert result.barrier is Barrier.STOP
    # Crossing the spread to get out: the level, made worse by slippage.
    assert result.exit_price == pytest.approx(90.0 * (1 - 3e-4))
    assert result.gross_r < -1.0
    assert not result.won


def test_the_horizon_closes_a_trade_the_broker_would_still_hold() -> None:
    """The time barrier is a labelling device, and this is what it does.

    Section 8 requires a closed label; an open case has no outcome. The broker
    has no time exit, so without this a signal that drifted sideways forever
    would never produce a label at all.
    """
    drift = [(105, 106, 101), (102, 103, 98)] + [(100, 101, 99)] * 200
    result = label(drift, horizon_ms=60 * MINUTE)
    assert result.barrier is Barrier.TIME
    assert result.resolved
    # Closed at market, so it pays taker and slippage like any crossing exit.
    assert result.exit_price < 100.0


def test_a_limit_that_is_never_reached_is_not_a_trade() -> None:
    """No fill, no outcome. A zero here would be a trade that never happened."""
    result = label([(105, 108, 104)] * 50)
    assert result.barrier is Barrier.UNFILLED
    assert not result.resolved
    assert result.gross_r == 0.0 and result.cost_r == 0.0


def test_the_entry_window_expires() -> None:
    """The limit is reached, but only after the order would have been pulled."""
    late = [(105, 108, 104)] * 600 + [(102, 103, 98)] * 10
    result = label(late, cfg=config(entry_expiry_bars=8))
    assert result.barrier is Barrier.UNFILLED


# --------------------------------------------------------------------------- #
# The rules that are easy to get wrong in the flattering direction
# --------------------------------------------------------------------------- #


def test_one_minute_holding_both_barriers_is_a_stop() -> None:
    """OHLC cannot order two events inside a minute, so the bad one wins.

    `broker._check_exits` makes the same choice, and assuming the kind one is
    the single easiest way to make a losing strategy backtest profitably.
    """
    both = [(105, 106, 101), (102, 103, 98), (100, 121, 89)]
    assert label(both).barrier is Barrier.STOP
    assert label(both, cfg=config(pessimistic_intrabar=False)).barrier is Barrier.TARGET


def test_a_gap_through_the_stop_costs_more_than_the_stop() -> None:
    """One of the few ways a trade loses more than it planned to."""
    gapped = [(105, 106, 101), (102, 103, 98), (80, 81, 79)]
    result = label(gapped)
    assert result.barrier is Barrier.STOP
    assert result.exit_price == pytest.approx(80.0 * (1 - 3e-4))
    assert result.gross_r < -1.9


def test_the_fill_minute_cannot_also_close_the_trade() -> None:
    """`broker.on_minute` returns as soon as it fills, so exits start after.

    Found by reading the broker rather than by reasoning about it. Scanning from
    the fill minute instead would stop out every signal whose entry minute also
    dipped to its stop, and tight stops would look far worse than they are.
    """
    # The minute that fills the limit at 100 also trades down to 89.
    touching = [(105, 106, 101), (102, 106, 89), (100, 101, 99), (110, 121, 109)]
    result = label(touching)
    assert result.barrier is Barrier.TARGET, "the fill minute closed the trade"


def test_a_limit_that_opens_through_the_level_fills_better() -> None:
    result = label([(95, 96, 94), (100, 121, 99)])
    assert result.entry_price == pytest.approx(95.0), "gave away a better fill"


def test_touch_versus_trade_through() -> None:
    """With `fill_on_touch` false the level has to be traded through.

    A touch means the price printed there, not that our order was at the front
    of the queue.
    """
    exactly = [(105, 106, 100.0)] * 40
    assert label(exactly).barrier is Barrier.UNFILLED
    assert label(exactly, cfg=config(fill_on_touch=True)).barrier is not Barrier.UNFILLED


def test_a_short_is_the_mirror_image() -> None:
    result = label(
        [(95, 99, 94), (98, 103, 97), (90, 91, 79)],
        side=Side.SHORT,
        entry=100.0,
        stop=110.0,
        target=80.0,
    )
    assert result.barrier is Barrier.TARGET
    assert result.gross_r == pytest.approx(2.0)


def test_a_zero_width_stop_is_refused() -> None:
    """No risk means no denominator, so there is no R to report."""
    assert label([(100, 121, 99)] * 5, entry=100.0, stop=100.0).barrier is Barrier.UNFILLED


# --------------------------------------------------------------------------- #
# Scale invariance
# --------------------------------------------------------------------------- #


def test_the_label_does_not_move_when_the_prices_do() -> None:
    """A thousand-dollar market and a ten-cent one must label alike.

    The same structural guarantee the snapshot normalisation gives the model. A
    label that moved with the price level would make BTC and XRP folds
    incomparable, and a walk-forward test across markets meaningless.
    """
    rows = [(105, 106, 101), (102, 103, 98), (110, 121, 109)]
    small = label(rows, entry=100.0, stop=90.0, target=120.0)
    scale = 1000.0
    big = label(
        [(o * scale, h * scale, lo * scale) for o, h, lo in rows],
        entry=100.0 * scale,
        stop=90.0 * scale,
        target=120.0 * scale,
    )
    assert big.gross_r == pytest.approx(small.gross_r)
    assert big.cost_r == pytest.approx(small.cost_r)
    assert big.net_r == pytest.approx(small.net_r)


def test_cost_is_reported_apart_from_the_outcome() -> None:
    """The decomposition that keeps 04.10.2026's near-miss from recurring.

    Priced after the fact, "winners had lower costs" is only "winners left at
    the target and paid maker". Keeping `cost_r` separate from `gross_r` is what
    lets a reader see that, and the asymmetry below is the reason it matters:
    the identical price path costs more to exit at a stop than at a target.
    """
    spec = make_symbol_spec(maker_fee=0.0002, taker_fee=0.00055)
    won = label([(105, 106, 101), (102, 103, 98), (110, 121, 109)], spec=spec)
    lost = label([(105, 106, 101), (102, 103, 98), (95, 96, 89)], spec=spec)
    assert won.cost_r < lost.cost_r
    assert won.cost_r > 0 and lost.cost_r > 0
    # Both legs of the winner are maker; the loser pays taker on the way out.
    assert won.cost_r == pytest.approx((100 * 0.0002 + 120 * 0.0002) / 10.0)


# --------------------------------------------------------------------------- #
# The guarantee
# --------------------------------------------------------------------------- #


def _broker_verdict(
    rows: list[tuple[float, float, float]],
    *,
    side: Side,
    entry: float,
    stop: float,
    target: float,
    spec: object,
    cfg: SimulationConfig,
    funding: list[FundingRate] | None = None,
) -> tuple[ExitReason, float, float] | None:
    """Run the authority: a real broker, stepped minute by minute.

    qty is 1 and `risk_amount` is the planned risk per unit, so the broker's
    `r_multiple` is directly comparable to the labeller's `net_r`.
    """
    broker = SimBroker(spec, cfg, funding)  # type: ignore[arg-type]
    assert broker.submit(
        PendingEntry(
            side=side,
            order_type=OrderType.LIMIT,
            limit_price=entry,
            stop=stop,
            target=target,
            qty=1.0,
            leverage=2.0,
            created_ts=EPOCH,
            expires_ts=EPOCH + cfg.entry_expiry_bars * 15 * MINUTE,
            risk_amount=abs(entry - stop),
        )
    )
    for i, (open_, high, low) in enumerate(rows):
        fill = broker.on_minute(EPOCH + i * MINUTE, open_, high, low)
        if fill is not None:
            return fill.reason, fill.exit_price, fill.r_multiple
    return None


#: Settlements inside the window the random paths cover.
#:
#: The agreement test ran without any funding at all, so it could not have
#: caught the labeller ignoring it -- which it did. Rates here make the two
#: implementations disagree unless both charge them.
RATES = [
    FundingRate(ts=EPOCH + 20 * MINUTE, rate=0.0001),
    FundingRate(ts=EPOCH + 60 * MINUTE, rate=-0.00008),
    FundingRate(ts=EPOCH + 100 * MINUTE, rate=0.00012),
]


def _random_paths(count: int, seed: int = 4) -> list[list[tuple[float, float, float]]]:
    """Random walks wide enough that all three barriers actually occur."""
    rng = np.random.default_rng(seed)
    paths = []
    for _ in range(count):
        price = 100.0
        rows: list[tuple[float, float, float]] = []
        for _ in range(120):
            price *= 1.0 + rng.normal(0.0, 0.004)
            spread = abs(rng.normal(0.0, 0.006)) * price
            open_ = price * (1.0 + rng.normal(0.0, 0.001))
            high = max(open_, price) + spread
            low = min(open_, price) - spread
            rows.append((open_, high, low))
        paths.append(rows)
    return paths


def test_the_labeller_agrees_with_the_broker() -> None:
    """The reason a second implementation of these rules is allowed to exist.

    Only the stop and target cases are compared, because those are the only
    outcomes the broker has. Where the labeller reports its time barrier the
    broker is asserted to be still holding, which is the same claim stated from
    the other side.
    """
    spec = make_symbol_spec(maker_fee=0.0002, taker_fee=0.00055)
    cfg = config()
    compared = {Barrier.TARGET: 0, Barrier.STOP: 0, Barrier.TIME: 0, Barrier.UNFILLED: 0}

    for rows in _random_paths(250):
        for side, stop, target in (
            (Side.LONG, 97.0, 106.0),
            (Side.SHORT, 103.0, 94.0),
        ):
            mine = label_signal(
                side=side,
                entry=100.0,
                stop=stop,
                target=target,
                decision_ts=EPOCH,
                minutes=series(rows),
                spec=spec,
                config=cfg,
                horizon_ms=120 * MINUTE,
                expiry_ms=cfg.entry_expiry_bars * 15 * MINUTE,
                funding=RATES,
            )
            theirs = _broker_verdict(
                rows,
                side=side,
                entry=100.0,
                stop=stop,
                target=target,
                spec=spec,
                cfg=cfg,
                funding=RATES,
            )
            compared[mine.barrier] += 1

            if mine.barrier in (Barrier.TARGET, Barrier.STOP):
                assert theirs is not None, f"broker never closed, labeller said {mine.barrier}"
                reason, price, r = theirs
                expected = ExitReason.TARGET if mine.barrier is Barrier.TARGET else ExitReason.STOP
                assert reason is expected, f"{reason} against {mine.barrier}"
                assert price == pytest.approx(mine.exit_price, rel=1e-9)
                assert r == pytest.approx(mine.net_r, rel=1e-9)
            elif mine.barrier is Barrier.TIME:
                assert theirs is None, "broker closed a trade the labeller still held"

    # A test that silently compared nothing would pass. These paths are built to
    # produce all three outcomes, so assert that they did.
    assert compared[Barrier.TARGET] > 20, compared
    assert compared[Barrier.STOP] > 20, compared


def test_the_tally_reports_how_often_the_horizon_binds() -> None:
    """A horizon that binds often means the labels describe another system."""
    tally = Tally()
    for rows, horizon in [
        ([(105, 106, 101), (102, 103, 98), (110, 121, 109)], 48 * HOUR),
        ([(105, 106, 101), (102, 103, 98), (95, 96, 89)], 48 * HOUR),
        ([(105, 106, 101), (102, 103, 98)] + [(100, 101, 99)] * 50, 60 * MINUTE),
        ([(105, 108, 104)] * 50, 48 * HOUR),
    ]:
        tally.add(label(rows, horizon_ms=horizon))

    assert (tally.target, tally.stop, tally.time, tally.unfilled) == (1, 1, 1, 1)
    assert tally.resolved == 3
    assert "33.3%" in tally.summary()
    assert "zu oft" in tally.summary()


# --------------------------------------------------------------------------- #
# Funding over the hold
# --------------------------------------------------------------------------- #


def test_a_long_pays_funding_while_the_rate_is_positive() -> None:
    """A real cost that only runs one way, and the labeller used to ignore it.

    Caught by the audit rather than by a test, because the agreement test built
    its broker without any rates and so could not have noticed.
    """
    held = [(105, 106, 101), (102, 103, 98)] + [(100, 101, 99)] * 10
    rates = [FundingRate(ts=EPOCH + 5 * MINUTE, rate=0.001)]
    without = label(held, horizon_ms=10 * MINUTE)
    with_rates = label(held, horizon_ms=10 * MINUTE, funding=rates)

    assert without.funding_r == 0.0
    # Long, filled at 100, risk 10 per unit, one settlement at 10bp.
    assert with_rates.funding_r == pytest.approx(-100.0 * 0.001 / 10.0)
    assert with_rates.net_r < without.net_r, "funding made no difference"


def test_a_short_is_paid_when_the_rate_is_positive() -> None:
    result = label(
        [(95, 99, 94), (98, 103, 97)] + [(100, 101, 99)] * 10,
        side=Side.SHORT,
        entry=100.0,
        stop=110.0,
        target=80.0,
        horizon_ms=10 * MINUTE,
        funding=[FundingRate(ts=EPOCH + 5 * MINUTE, rate=0.001)],
    )
    assert result.funding_r == pytest.approx(+100.0 * 0.001 / 10.0)


def test_funding_that_settled_before_the_fill_is_not_charged() -> None:
    """The position was not there for it."""
    result = label(
        [(105, 106, 101), (102, 103, 98)] + [(100, 101, 99)] * 10,
        horizon_ms=10 * MINUTE,
        funding=[FundingRate(ts=EPOCH, rate=0.01)],
    )
    assert result.funding_r == 0.0


def test_a_long_hold_crosses_several_settlements() -> None:
    """The reason this matters for the time barrier specifically.

    A 48-hour horizon spans up to six eight-hourly settlements, and those are
    exactly the labels the horizon keeps open longest.
    """
    held = [(105, 106, 101), (102, 103, 98)] + [(100, 101, 99)] * 30
    rates = [FundingRate(ts=EPOCH + m * MINUTE, rate=0.0005) for m in (5, 10, 15, 20)]
    result = label(held, horizon_ms=25 * MINUTE, funding=rates)
    assert result.barrier is Barrier.TIME
    assert result.funding_r == pytest.approx(-4 * 100.0 * 0.0005 / 10.0)


def test_funding_does_not_move_when_the_prices_do() -> None:
    """Scale-free like the rest of the label.

    The broker charges notional * rate and the R denominator carries the same
    quantity, so it cancels. A funding term that scaled with the price level
    would make BTC and XRP folds incomparable.
    """
    rows = [(105, 106, 101), (102, 103, 98)] + [(100, 101, 99)] * 10
    rates = [FundingRate(ts=EPOCH + 5 * MINUTE, rate=0.001)]
    small = label(rows, horizon_ms=10 * MINUTE, funding=rates)
    scale = 1000.0
    big = label(
        [(o * scale, h * scale, lo * scale) for o, h, lo in rows],
        entry=100.0 * scale,
        stop=90.0 * scale,
        target=120.0 * scale,
        horizon_ms=10 * MINUTE,
        funding=rates,
    )
    assert big.funding_r == pytest.approx(small.funding_r)
