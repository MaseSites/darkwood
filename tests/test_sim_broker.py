"""The simulator, one case at a time, with the expected number worked out by hand.

A backtest is worth exactly what its broker model is worth, and a broker model is
easy to get subtly wrong in the direction that flatters. Each test here drives a
short, explicit minute series and asserts the profit and loss to the cent, so a
change in the cost model cannot slip through as a change in the strategy's
apparent edge.

The four that matter most are the ones that are usually missing: a gap through the
stop, a minute holding both stop and target, liquidation arriving before the stop,
and funding charged over a held position.
"""

from __future__ import annotations

import pytest

from tests.factories import make_symbol_spec
from tests.fakes import EPOCH
from traidingbrain.config.settings import SimulationConfig
from traidingbrain.domain.enums import ExitReason, OrderType, Side, TradeState
from traidingbrain.domain.market import FundingRate
from traidingbrain.risk.leverage import liquidation_price
from traidingbrain.sim.broker import PendingEntry, SimBroker, round_to_step

MINUTE = 60_000


def config(**overrides: object) -> SimulationConfig:
    defaults: dict[str, object] = {
        "initial_equity": 10_000.0,
        "slippage_bps": 0.0,
        "fill_on_touch": True,
        "entry_expiry_bars": 8,
        "pessimistic_intrabar": True,
    }
    return SimulationConfig.model_validate(defaults | overrides)


def free_spec(**overrides: object):
    """A venue with no fees, so a test about fills is not also a test about costs."""
    return make_symbol_spec(taker_fee=0.0, maker_fee=0.0, **overrides)


def long_entry(**overrides: object) -> PendingEntry:
    defaults: dict[str, object] = {
        "side": Side.LONG,
        "order_type": OrderType.LIMIT,
        "limit_price": 100.0,
        "stop": 90.0,
        "target": 120.0,
        "qty": 1.0,
        "leverage": 5.0,
        "created_ts": EPOCH,
        "expires_ts": EPOCH + 100 * MINUTE,
        "risk_amount": 10.0,
    }
    return PendingEntry(**(defaults | overrides))  # type: ignore[arg-type]


def minutes(broker: SimBroker, series: list[tuple[float, float, float]], start: int = EPOCH):
    """Feed (open, high, low) triples, one per minute."""
    results = []
    for i, (open_, high, low) in enumerate(series):
        results.append(broker.on_minute(start + i * MINUTE, open_, high, low))
    return results


# --------------------------------------------------------------------------- #
# Entries
# --------------------------------------------------------------------------- #


def test_a_limit_long_fills_when_price_comes_down_to_it() -> None:
    broker = SimBroker(free_spec(), config())
    assert broker.submit(long_entry())

    minutes(broker, [(105, 106, 101), (102, 103, 99)])

    assert broker.position is not None
    assert broker.position.entry_price == pytest.approx(100.0)


def test_an_entry_that_is_never_reached_expires() -> None:
    """The setup did not happen. Counting it as a trade at some other price would
    measure a strategy nobody ran."""
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry(expires_ts=EPOCH + 3 * MINUTE))

    minutes(broker, [(105, 106, 103), (106, 107, 104), (107, 108, 105), (108, 109, 106)])

    assert broker.position is None
    assert broker.pending is None
    assert broker.expired_entries == 1


def test_a_touch_is_not_a_fill_when_the_conservative_rule_is_on() -> None:
    """Price printing at our level does not mean our order was at the front of the
    queue. Requiring a trade-through keeps the fills we would plausibly have got."""
    broker = SimBroker(free_spec(), config(fill_on_touch=False))
    broker.submit(long_entry())

    minutes(broker, [(105, 106, 100.0)])
    assert broker.position is None, "a touch filled despite the conservative rule"

    minutes(broker, [(105, 106, 99.9)], start=EPOCH + 5 * MINUTE)
    assert broker.position is not None


def test_a_minute_that_opens_below_the_limit_fills_at_the_open() -> None:
    """A gap in our favour is a better fill than asked for, which is what happens."""
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry())

    minutes(broker, [(97.0, 98.0, 96.0)])

    assert broker.position is not None
    assert broker.position.entry_price == pytest.approx(97.0)


def test_a_second_entry_is_refused_while_one_is_working() -> None:
    broker = SimBroker(free_spec(), config())
    assert broker.submit(long_entry())
    assert not broker.submit(long_entry())
    assert broker.rejected_entries == 1


def test_a_position_too_small_for_the_venue_is_refused() -> None:
    broker = SimBroker(free_spec(min_qty=1.0), config())
    assert not broker.submit(long_entry(qty=0.5))
    assert broker.rejected_entries == 1


# --------------------------------------------------------------------------- #
# Exits, with the arithmetic written out
# --------------------------------------------------------------------------- #


def test_a_target_hit_pays_exactly_the_distance() -> None:
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(110, 121, 109)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    # Entered at 100, exited at 120, one unit, no fees.
    assert fill.reason is ExitReason.TARGET
    assert fill.exit_price == pytest.approx(120.0)
    assert fill.net_pnl == pytest.approx(20.0)
    assert broker.equity == pytest.approx(10_020.0)


def test_a_stop_hit_costs_exactly_the_distance() -> None:
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(95, 96, 89)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    assert fill.reason is ExitReason.STOP
    assert fill.exit_price == pytest.approx(90.0)
    assert fill.net_pnl == pytest.approx(-10.0)
    assert fill.r_multiple == pytest.approx(-1.0)


def test_a_gap_through_the_stop_costs_more_than_planned() -> None:
    """The stop is where the order rests, not where price is obliged to stop.

    A simulator that always fills at the stop price reports a loss the account
    never had the chance to take, and every gap becomes free.
    """
    broker = SimBroker(free_spec(), config())
    # Low leverage on purpose: at 5x the liquidation price sits at 80.5 and this
    # gap would trigger that first, which is the simulator being right about a
    # different thing. Liquidation gets its own test.
    broker.submit(long_entry(leverage=2.0))
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(82.0, 83.0, 80.0)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    assert fill.reason is ExitReason.STOP
    assert fill.exit_price == pytest.approx(82.0), "filled at the stop instead of the open"
    assert fill.net_pnl == pytest.approx(-18.0)
    assert fill.r_multiple == pytest.approx(-1.8), "a gap can cost more than 1R"


def test_when_one_minute_holds_both_the_stop_wins() -> None:
    """OHLC cannot say which came first. Assuming the good one is how a backtest
    lies, and it lies most on exactly the volatile bars that matter."""
    broker = SimBroker(free_spec(), config(pessimistic_intrabar=True))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(100, 125, 85)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    assert fill.reason is ExitReason.STOP
    assert fill.net_pnl < 0


def test_the_optimistic_setting_is_available_and_changes_the_answer() -> None:
    """Kept as a switch so the difference can be measured rather than argued about."""
    broker = SimBroker(free_spec(), config(pessimistic_intrabar=False))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(100, 125, 85)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    assert fill.reason is ExitReason.TARGET


def test_a_short_is_the_mirror_image() -> None:
    broker = SimBroker(free_spec(), config())
    broker.submit(
        long_entry(side=Side.SHORT, limit_price=100.0, stop=110.0, target=80.0, risk_amount=10.0)
    )
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(90, 91, 79)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    assert fill.reason is ExitReason.TARGET
    assert fill.net_pnl == pytest.approx(20.0)


# --------------------------------------------------------------------------- #
# Liquidation
# --------------------------------------------------------------------------- #


def test_liquidation_costs_the_margin_and_nothing_more() -> None:
    """With leverage the exchange has its own opinion about when the trade is over.

    A simulator without this reports a small loss where the account actually lost
    its whole margin -- which is the entire reason leverage is dangerous.
    """
    spec = free_spec(maintenance_margin_rate=0.005)
    broker = SimBroker(spec, config())
    # A stop far below the liquidation price: the venue gets there first.
    broker.submit(long_entry(stop=50.0, leverage=5.0, risk_amount=50.0))
    minutes(broker, [(100.0, 101.0, 99.0)])

    expected_liq = liquidation_price(Side.LONG, 100.0, 5.0, 0.005)
    assert 50.0 < expected_liq < 100.0

    fills = minutes(broker, [(85, 86, 79)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    assert fill.reason is ExitReason.LIQUIDATION
    assert fill.state is TradeState.CLOSED_LIQUIDATED
    # Margin was 100 * 1 / 5 = 20.
    assert fill.net_pnl == pytest.approx(-20.0)
    assert broker.equity == pytest.approx(9_980.0)


def test_a_properly_levered_trade_reaches_its_stop_first() -> None:
    """The point of deriving leverage from the stop: liquidation never arrives first."""
    spec = free_spec()
    broker = SimBroker(spec, config())
    broker.submit(long_entry(stop=90.0, leverage=3.0))
    minutes(broker, [(100.0, 101.0, 99.0)])

    position = broker.position
    assert position is not None
    assert position.liq_price < position.stop

    fills = minutes(broker, [(92, 93, 89)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)
    assert fill.reason is ExitReason.STOP


# --------------------------------------------------------------------------- #
# Costs
# --------------------------------------------------------------------------- #


def test_fees_are_charged_on_both_sides() -> None:
    spec = make_symbol_spec(taker_fee=0.001, maker_fee=0.0005)
    broker = SimBroker(spec, config())
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(110, 121, 109)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    # A resting limit entry earns maker (100 * 0.0005 = 0.05); the exit crosses
    # the spread and pays taker (120 * 0.001 = 0.12).
    assert fill.fees == pytest.approx(0.05 + 0.12)
    assert fill.net_pnl == pytest.approx(20.0 - 0.17)


def test_slippage_only_ever_runs_against_us() -> None:
    broker = SimBroker(free_spec(), config(slippage_bps=10.0))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(95, 96, 89)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    # 10bps below the stop: 90 * (1 - 0.001) = 89.91.
    assert fill.exit_price == pytest.approx(89.91)
    assert fill.exit_price < 90.0


def test_funding_is_charged_for_every_settlement_while_held() -> None:
    """Small per settlement, one-directional, and the cost people leave out."""
    rates = [
        FundingRate(ts=EPOCH + 2 * MINUTE, rate=0.0001),
        FundingRate(ts=EPOCH + 4 * MINUTE, rate=0.0001),
    ]
    broker = SimBroker(free_spec(), config(), funding=rates)
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(
        broker,
        [(105, 106, 104), (105, 106, 104), (105, 106, 104), (110, 121, 109)],
        start=EPOCH + MINUTE,
    )
    fill = next(f for f in fills if f is not None)

    # Long, notional 100, two settlements at 1bp each, paid by longs.
    assert fill.funding == pytest.approx(-0.02)
    assert fill.net_pnl == pytest.approx(20.0 - 0.02)


def test_a_short_receives_funding_when_the_rate_is_positive() -> None:
    rates = [FundingRate(ts=EPOCH + 2 * MINUTE, rate=0.0001)]
    broker = SimBroker(free_spec(), config(), funding=rates)
    broker.submit(long_entry(side=Side.SHORT, limit_price=100.0, stop=110.0, target=80.0))
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(broker, [(99, 100, 98), (90, 91, 79)], start=EPOCH + MINUTE)
    fill = next(f for f in fills if f is not None)

    assert fill.funding == pytest.approx(+0.01)


def test_funding_before_the_position_opened_is_not_charged() -> None:
    rates = [FundingRate(ts=EPOCH - MINUTE, rate=0.01)]
    broker = SimBroker(free_spec(), config(), funding=rates)
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0), (110, 121, 109)])

    fill = broker.fills[0]
    assert fill.funding == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Bookkeeping
# --------------------------------------------------------------------------- #


def test_equity_curve_includes_open_profit() -> None:
    """Drawdown on closed trades alone understates it.

    An account that went underwater and recovered did experience that, and a
    number that hides it is not a risk measure.
    """
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    broker.mark(EPOCH + 10 * MINUTE, 95.0)

    assert broker.equity_curve[-1][1] == pytest.approx(10_000.0 - 5.0)
    assert broker.equity == pytest.approx(10_000.0), "unrealised profit is not banked"


def test_r_multiple_is_relative_to_what_was_risked() -> None:
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry(risk_amount=10.0))
    minutes(broker, [(100.0, 101.0, 99.0), (110, 121, 109)])

    assert broker.fills[0].r_multiple == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("value", "step", "expected"),
    [(1.2345, 0.001, 1.234), (0.9999, 0.001, 0.999), (5.0, 1.0, 5.0), (0.0005, 0.001, 0.0)],
)
def test_quantities_round_down_to_the_venue_step(
    value: float, step: float, expected: float
) -> None:
    """Down, never nearest: rounding up can push the notional past the margin, and
    the rejection then happens at the exchange."""
    assert round_to_step(value, step) == pytest.approx(expected)
