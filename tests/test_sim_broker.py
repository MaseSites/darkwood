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


def test_one_minute_that_reaches_both_resolves_at_the_stop() -> None:
    """Der Fall, den die Reihenfolge jahrelang falsch verbucht hat.

    `risk/leverage.py` setzt den Hebel so, dass die Liquidation mindestens
    2,5 Stop-Weiten *hinter* dem Stop liegt. Ein Balken, der die Liquidation
    beruehrt, hat den Stop also auf dem Weg dorthin ueberquert -- und in der
    Wirklichkeit haette der Stop zuerst ausgefuehrt.

    Der Broker prueft die Liquidation trotzdem unbedingt zuerst, und genau ein
    Trade der 2'734 Replay-Trades ist so verbucht worden: SOLUSDT, short, Stop
    10,07, Hebel 9x, abgeleitete Liquidation 10,8288 -- geschlossen bei 10,8321
    als Liquidation, mit **-3,8849 R gegen ein Budget von 1 R**. Der
    schlechteste Trade der ganzen Population war ein Artefakt der Reihenfolge,
    und jedes Randmass trug ihn mit.

    Die bestehenden Tests haben das nicht gefangen: der eine setzt den Stop
    *hinter* die Liquidation, der andere laesst den Balken die Liquidation gar
    nicht erreichen. Keiner beruehrt beide in derselben Minute.
    """
    spec = free_spec()
    broker = SimBroker(spec, config())
    broker.submit(long_entry(stop=90.0, leverage=3.0))
    minutes(broker, [(100.0, 101.0, 99.0)])

    position = broker.position
    assert position is not None
    assert position.liq_price < position.stop, "Vorbedingung: Liquidation liegt hinter dem Stop"

    # Eine Minute, die oberhalb des Stops EROEFFNET und beide Marken durchlaeuft.
    low = position.liq_price - 1.0
    fills = minutes(broker, [(95.0, 95.0, low)], start=EPOCH + 5 * MINUTE)
    fill = next(f for f in fills if f is not None)

    assert fill.reason is ExitReason.STOP, (
        "der Preis ist durch den Stop gelaufen, bevor er die Liquidation erreichte -- "
        "dann haette der Stop ausgefuehrt"
    )
    assert fill.state is not TradeState.CLOSED_LIQUIDATED


def test_a_minute_that_opens_past_liquidation_is_a_liquidation() -> None:
    """Die Ausnahme, die bleibt: ein Sprung ueber beide Marken hinweg.

    Eroeffnet die Minute schon jenseits der Liquidation, konnte auch der Stop
    nicht zu seinem Preis ausfuehren. Ohne diesen Zweig waere die Korrektur
    oben in die andere Richtung falsch -- sie wuerde eine echte Liquidation als
    Stop verbuchen und den Simulator wieder optimistisch machen.
    """
    spec = free_spec()
    broker = SimBroker(spec, config())
    broker.submit(long_entry(stop=90.0, leverage=3.0))
    minutes(broker, [(100.0, 101.0, 99.0)])

    position = broker.position
    assert position is not None

    opened_below = position.liq_price - 2.0
    fills = minutes(
        broker, [(opened_below, opened_below, opened_below - 1.0)], start=EPOCH + 5 * MINUTE
    )
    fill = next(f for f in fills if f is not None)

    assert fill.reason is ExitReason.LIQUIDATION
    assert fill.state is TradeState.CLOSED_LIQUIDATED


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

    # Both legs rest in the book here and both earn maker: the entry is a limit
    # order (100 * 0.0005) and so is the target (120 * 0.0005).
    #
    # This test asserted taker on the exit until 04.10.2026, because every exit
    # was charged as taker regardless of why it happened -- including a take
    # profit, which does not cross the spread to get out. The stop case below
    # covers the other side.
    assert fill.reason is ExitReason.TARGET
    assert fill.fees == pytest.approx(0.05 + 0.06)
    assert fill.net_pnl == pytest.approx(20.0 - 0.11)


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


# --------------------------------------------------------------------------- #
# Which way slippage points
#
# Found on 14.10.2026 by a test about something else. `_slipped` carried the
# EXIT geometry to the entry call site, so a long market entry filled a full
# slippage below the market -- better than the market, on the side that pays
# to get in. It had never fired, because `sim/plan.py:307` sets
# `OrderType.LIMIT` without exception; these two tests exist so that stays
# true if anyone turns market entries on.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("side", "limit", "stop", "target"),
    [(Side.LONG, 100.0, 90.0, 120.0), (Side.SHORT, 100.0, 110.0, 80.0)],
)
def test_a_market_entry_slips_against_us(
    side: Side, limit: float, stop: float, target: float
) -> None:
    """Both sides, because one formula has to serve both and it did not."""
    broker = SimBroker(free_spec(), config(slippage_bps=100.0))
    broker.submit(
        long_entry(
            side=side, order_type=OrderType.MARKET,
            limit_price=limit, stop=stop, target=target,
        )
    )

    minutes(broker, [(100.0, 100.0, 100.0)])

    assert broker.position is not None
    entry = broker.position.entry_price
    if side is Side.LONG:
        assert entry == pytest.approx(101.0), "ein Long zahlt MEHR, nicht weniger"
    else:
        assert entry == pytest.approx(99.0), "ein Short bekommt WENIGER, nicht mehr"


# --------------------------------------------------------------------------- #
# Pulling the target in (E15)
#
# `long_entry` risks 10 on one unit from 100, so one R is ten points and the
# shipped target of 120 sits at +2 R. That makes the arithmetic readable: a cap
# at 1.0 R must land on 110, and a cap at 3.0 R must change nothing.
# --------------------------------------------------------------------------- #


def test_the_cap_pulls_a_distant_target_in() -> None:
    broker = SimBroker(free_spec(), config(target_cap_r=1.0))
    broker.submit(long_entry())

    minutes(broker, [(100.0, 100.0, 100.0)])

    assert broker.position is not None
    assert broker.position.target == pytest.approx(110.0)


def test_the_cap_never_pushes_a_near_target_out() -> None:
    """The control, and the property that makes the result readable.

    A cap can only pull a target IN. Without this, a "cap" that also moved
    close targets further would be a different policy wearing the same name,
    and every difference E15 measures would have two possible sources.
    """
    broker = SimBroker(free_spec(), config(target_cap_r=3.0))
    broker.submit(long_entry())

    minutes(broker, [(100.0, 100.0, 100.0)])

    assert broker.position is not None
    assert broker.position.target == pytest.approx(120.0), (
        "der Deckel bei 3 R liegt bei 130 und das Ziel bei 120 -- es bleibt"
    )


def test_a_short_is_capped_downwards() -> None:
    """The sign flip, which is where a cap like this is usually wrong.

    A short from 100 with ten points of risk reaches +1 R at 90, not at 110.
    Taking the long formula for both would move the target to the losing side
    and the position would close instantly at a loss, every time.
    """
    broker = SimBroker(free_spec(), config(target_cap_r=1.0))
    broker.submit(long_entry(side=Side.SHORT, limit_price=100.0, stop=110.0, target=80.0))

    minutes(broker, [(100.0, 100.0, 100.0)])

    assert broker.position is not None
    assert broker.position.target == pytest.approx(90.0)


def test_the_cap_is_off_unless_it_is_configured() -> None:
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry())

    minutes(broker, [(100.0, 100.0, 100.0)])

    assert broker.position is not None
    assert broker.position.target == pytest.approx(120.0)


def test_a_capped_target_pays_out_at_the_cap() -> None:
    """Not just placed there -- actually closed there, for the capped R.

    A test that only reads `position.target` would pass even if the exit logic
    ignored the field. This one runs the trade to its end.
    """
    broker = SimBroker(free_spec(), config(target_cap_r=1.0))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0)])

    minutes(broker, [(100.0, 111.0, 100.0)], start=EPOCH + MINUTE)

    assert broker.position is None
    fill = broker.fills[-1]
    assert fill.reason is ExitReason.TARGET
    assert fill.exit_price == pytest.approx(110.0)
    assert fill.r_multiple == pytest.approx(1.0), (
        "ein Deckel bei 1.0 R muss 1.0 R auszahlen, nicht die 2.0 des "
        "Strukturziels"
    )


def test_the_cap_measures_from_the_fill_not_the_intended_price() -> None:
    """A slipped entry must not put the cap a few points off, and silently.

    The risk per unit is `risk_amount / qty`, which does not know where the
    fill happened. Anchoring the cap on the order's limit price would therefore
    drift on every market entry, in the direction of the slippage.
    """
    broker = SimBroker(
        make_symbol_spec(taker_fee=0.0, maker_fee=0.0),
        config(target_cap_r=1.0, slippage_bps=100.0),
    )
    broker.submit(long_entry(order_type=OrderType.MARKET))

    minutes(broker, [(100.0, 100.0, 100.0)])

    assert broker.position is not None
    entry = broker.position.entry_price
    assert entry > 100.0, "ohne Slippage prueft dieser Test nichts"
    assert broker.position.target == pytest.approx(entry + 10.0)


# --------------------------------------------------------------------------- #
# Moving the stop to the entry
# --------------------------------------------------------------------------- #


def armed(at: float = 1.0) -> SimBroker:
    """A broker with the breakeven rule on and a long filled at 100.

    Risk is ten, so one R is 110 and the original stop is 90.
    """
    broker = SimBroker(free_spec(), config(breakeven_at_r=at))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0)])
    return broker


def test_the_stop_stays_put_until_the_trade_has_run_far_enough() -> None:
    broker = armed()

    minutes(broker, [(100.0, 109.0, 100.0)], start=EPOCH + MINUTE)

    assert broker.position is not None
    assert broker.position.stop == pytest.approx(90.0)


def test_reaching_the_trigger_pulls_the_stop_to_the_entry() -> None:
    broker = armed()

    minutes(broker, [(100.0, 110.0, 100.0)], start=EPOCH + MINUTE)

    assert broker.position is not None
    assert broker.position.stop == pytest.approx(100.0)


def test_a_trade_that_gave_it_back_scratches_instead_of_losing() -> None:
    """The case the rule exists for. Nineteen per cent of the journal's trades
    were a point in profit and ended as full losses."""
    broker = armed()

    minutes(broker, [(100.0, 112.0, 100.0), (100.0, 100.0, 85.0)], start=EPOCH + MINUTE)

    assert broker.position is None
    fill = broker.fills[-1]
    assert fill.reason is ExitReason.STOP
    assert fill.exit_price == pytest.approx(100.0)
    assert fill.r_multiple == pytest.approx(0.0)
    # Und der Fill sagt, dass es ein nachgezogener Stop war.
    #
    # Das ist nicht Kosmetik, sondern die Quelle einer von E14s vier VORAB
    # angemeldeten Rand-Kennzahlen: der Anteil der scharfgestellten Trades,
    # den die Regel abschneidet. `ExitReason` kann es nicht sagen -- hier
    # steht STOP wie bei einem echten Verlust, und eine Zeile wie diese ist
    # vom echten Verlust nur durch dieses Feld zu unterscheiden.
    assert fill.stop_moved


def test_a_fill_without_the_rule_reports_no_moved_stop() -> None:
    """Die Gegenprobe, ohne die das Feld nichts beweist.

    Ein Feld, das immer `True` ist, besteht den Test darueber genauso -- und
    der Anteil, den E14 daraus rechnet, waere dann 100 % und falsch. Dieses
    Projekt hat vier Messungen bezahlt, die die Apparatur beschrieben statt
    die Welt.
    """
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0), (100.0, 112.0, 85.0)])

    fill = broker.fills[-1]
    assert fill.reason is ExitReason.STOP
    assert fill.r_multiple == pytest.approx(-1.0)
    assert not fill.stop_moved


def test_the_trigger_and_the_stop_in_one_minute_resolve_as_a_stop() -> None:
    """The same reasoning as `pessimistic_intrabar`. One minute holding both
    the trigger and the original stop cannot say which came first, and taking
    the kind reading is how a backtest flatters a rule."""
    broker = armed()

    minutes(broker, [(100.0, 112.0, 89.0)], start=EPOCH + MINUTE)

    fill = broker.fills[-1]
    assert fill.reason is ExitReason.STOP
    assert fill.r_multiple == pytest.approx(-1.0)


def test_the_stop_does_not_walk_back_down_after_it_has_moved() -> None:
    """Once moved, moved. Re-arming on a later dip would drag the stop back to
    an entry it had already left, which is not a rule anybody described."""
    broker = armed()

    minutes(
        broker,
        [(100.0, 111.0, 100.0), (100.0, 101.0, 100.5), (100.0, 115.0, 100.5)],
        start=EPOCH + MINUTE,
    )

    assert broker.position is not None
    assert broker.position.stop == pytest.approx(100.0)
    assert broker.position.stop_moved


def test_a_short_arms_on_the_low_not_the_high() -> None:
    """The sign flip. Reading the high for a short would arm the rule when the
    trade went against it, which is the exact opposite of the rule."""
    broker = SimBroker(free_spec(), config(breakeven_at_r=1.0))
    broker.submit(long_entry(side=Side.SHORT, limit_price=100.0, stop=110.0, target=80.0))
    minutes(broker, [(100.0, 100.0, 100.0)])

    minutes(broker, [(100.0, 100.0, 90.0)], start=EPOCH + MINUTE)

    assert broker.position is not None
    assert broker.position.stop == pytest.approx(100.0)


def test_the_rule_is_off_unless_it_is_configured() -> None:
    """It changes what gets traded, not how a trade is simulated, so it cannot
    be a default that quietly rewrites every historical result."""
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0), (100.0, 115.0, 100.0)])

    assert broker.position is not None
    assert broker.position.stop == pytest.approx(90.0)


def test_a_target_exit_pays_the_maker_fee_and_a_stop_pays_taker() -> None:
    """A take profit rests in the book; a stop crosses the spread to get out.

    Entries already made this distinction and exits did not, so every winner
    was charged as though it had paid to leave. Worth 0.0092 R a trade over the
    journalled record -- a seventh of all fees, in a system whose entire net
    loss is fees.

    The test pins both sides, because charging *everything* as maker would be
    the same mistake in the flattering direction.
    """
    spec = make_symbol_spec(maker_fee=0.0002, taker_fee=0.0006)
    settings = config(slippage_bps=0.0)

    def run(hit_target: bool) -> object:
        broker = SimBroker(spec, settings)
        broker.submit(
            PendingEntry(
                side=Side.LONG,
                order_type=OrderType.LIMIT,
                limit_price=100.0,
                stop=90.0,
                target=120.0,
                qty=1.0,
                leverage=1.0,
                created_ts=0,
                expires_ts=10_000_000,
                risk_amount=10.0,
            )
        )
        broker.on_minute(1_000, 100.0, 100.0, 100.0)
        assert broker.position is not None
        reach = 120.0 if hit_target else 90.0
        fill = broker.on_minute(2_000, 100.0, max(100.0, reach), min(100.0, reach))
        assert fill is not None
        return fill

    won = run(hit_target=True)
    lost = run(hit_target=False)

    entry_fee = 100.0 * spec.maker_fee
    assert won.reason is ExitReason.TARGET
    assert won.fees == pytest.approx(entry_fee + 120.0 * spec.maker_fee)
    assert lost.reason is ExitReason.STOP
    assert lost.fees == pytest.approx(entry_fee + 90.0 * spec.taker_fee)


# --------------------------------------------------------------------------- #
# Funding that arrives after the broker was built
# --------------------------------------------------------------------------- #


def test_a_settlement_the_broker_was_never_given_costs_nothing() -> None:
    """The defect, stated as a test before the fix is shown to cure it.

    This is the forward paper trader's situation: it hands each broker a
    funding schedule once, in the constructor, and keeps running for days. Rates
    that settle later are simply absent, and absent costs nothing.
    """
    broker = SimBroker(free_spec(), config(), funding=[])
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])

    fills = minutes(
        broker, [(105, 106, 104), (105, 106, 104), (110, 121, 109)], start=EPOCH + MINUTE
    )
    fill = next(f for f in fills if f is not None)
    assert fill.funding == pytest.approx(0.0)


def test_refresh_charges_a_settlement_that_has_already_gone_past() -> None:
    """The fix, and the reason it cannot be keyed on the clock.

    A rate is published at its own settlement time and fetched by the next
    top-up minutes afterwards, so by the time it arrives the broker's clock is
    already past it. A cursor placed by the clock would discard it as history --
    the same silence, one level down. It is placed by what was actually
    consumed instead, so the settlement is charged on the next minute step.
    """
    broker = SimBroker(free_spec(), config(), funding=[])
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])
    # Two minutes pass with the schedule still empty.
    minutes(broker, [(105, 106, 104), (105, 106, 104)], start=EPOCH + MINUTE)

    pending = broker.refresh_funding([FundingRate(ts=EPOCH + 2 * MINUTE, rate=0.0001)])
    assert pending == 1, "the settlement was dropped as already past"

    fills = minutes(broker, [(110, 121, 109)], start=EPOCH + 3 * MINUTE)
    fill = next(f for f in fills if f is not None)
    assert fill.funding == pytest.approx(-0.01)


def test_refresh_does_not_charge_a_settlement_twice() -> None:
    """A top-up re-reads the whole series, so it re-offers what was paid."""
    rate = FundingRate(ts=EPOCH + 2 * MINUTE, rate=0.0001)
    broker = SimBroker(free_spec(), config(), funding=[rate])
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])
    minutes(broker, [(105, 106, 104), (105, 106, 104)], start=EPOCH + MINUTE)

    # The same rate comes back, plus one that has not settled yet.
    pending = broker.refresh_funding([rate, FundingRate(ts=EPOCH + 9 * MINUTE, rate=0.0001)])
    assert pending == 1, "the already-settled rate was offered again"

    fills = minutes(broker, [(110, 121, 109)], start=EPOCH + 3 * MINUTE)
    fill = next(f for f in fills if f is not None)
    assert fill.funding == pytest.approx(-0.01), "charged twice for one settlement"


def test_refresh_keeps_the_cursor_when_the_new_series_starts_earlier() -> None:
    """A longer history must not shift the cursor onto a different settlement.

    The reason the index is rebuilt rather than carried: a backfill that reaches
    further back changes what position 3 means.
    """
    settled = FundingRate(ts=EPOCH + 2 * MINUTE, rate=0.0001)
    broker = SimBroker(free_spec(), config(), funding=[settled])
    broker.submit(long_entry())
    minutes(broker, [(100.0, 101.0, 99.0)])
    minutes(broker, [(105, 106, 104), (105, 106, 104)], start=EPOCH + MINUTE)

    older = [FundingRate(ts=EPOCH - 10 * MINUTE, rate=0.05)] * 3
    assert broker.refresh_funding([*older, settled]) == 0

    fills = minutes(broker, [(110, 121, 109)], start=EPOCH + 3 * MINUTE)
    fill = next(f for f in fills if f is not None)
    assert fill.funding == pytest.approx(-0.01), "an older rate leaked in"


# --------------------------------------------------------------------------- #
# The time exit
# --------------------------------------------------------------------------- #


def test_without_a_limit_a_position_is_held_forever() -> None:
    """The shipped behaviour, and why the occupancy shadow exists.

    The broker holds exactly one position and had no time exit at all, so a
    trade that neither stops nor targets keeps the only slot indefinitely.
    Measured on the ledger, about two thirds of BTC's four years lies behind a
    taken signal where the strategy is never even asked.
    """
    broker = SimBroker(free_spec(), config())
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0)])

    # A full week of bars that touch neither barrier.
    fills = minutes(
        broker,
        [(100.0, 101.0, 99.0)] * (7 * 24 * 60),
        start=EPOCH + MINUTE,
    )

    assert not any(fills), "something closed the trade without being asked to"
    assert not broker.is_flat


def test_a_held_position_closes_once_the_clock_runs_out() -> None:
    broker = SimBroker(free_spec(), config(max_hold_hours=5.0))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0)])

    fills = minutes(
        broker,
        [(100.0, 101.0, 99.0)] * (6 * 60),
        start=EPOCH + MINUTE,
    )

    closed = [f for f in fills if f is not None]
    assert len(closed) == 1
    assert closed[0].reason is ExitReason.TIME
    assert closed[0].state is TradeState.CLOSED_TIME
    assert broker.is_flat


def test_the_clock_is_measured_from_the_fill_not_from_the_order() -> None:
    """A resting entry can wait for bars before it fills.

    Counting from `created_ts` would cut a trade short by however long its
    limit order sat unfilled, which has nothing to do with how long the trade
    was held.
    """
    broker = SimBroker(free_spec(), config(max_hold_hours=3.0))
    # The default entry expires after 100 minutes, which would retire the
    # order before it ever fills and make this test about expiry instead.
    broker.submit(long_entry(expires_ts=EPOCH + 1000 * MINUTE))

    # Two hours of bars that never reach the limit, so nothing fills.
    minutes(broker, [(105.0, 106.0, 101.0)] * 120)
    assert broker.position is None, "the entry filled when it should not have"

    # Now it fills, and the clock starts here.
    minutes(broker, [(100.0, 100.0, 100.0)], start=EPOCH + 120 * MINUTE)
    assert broker.position is not None
    opened = broker.position.opened_ts

    fills = minutes(broker, [(100.0, 101.0, 99.0)] * 181, start=EPOCH + 121 * MINUTE)
    closed = [f for f in fills if f is not None]

    assert len(closed) == 1
    assert closed[0].reason is ExitReason.TIME
    assert closed[0].closed_ts - opened >= 3 * 3_600_000
    assert closed[0].opened_ts == opened, "the fill records a different open time"


def test_the_stop_still_wins_the_minute_the_clock_runs_out() -> None:
    """The ordering that is the whole correctness argument.

    `learn/labels.py` resolves stop and target across the entire horizon first
    and only falls through to its TIME barrier at the end. A time branch placed
    above the stop would close trades that had already been stopped out, and
    every R multiple ever computed from a label would disagree with the
    simulator that produced it.
    """
    broker = SimBroker(free_spec(), config(max_hold_hours=1.0))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0)])

    # The minute the hour expires also trades through the stop at 90.
    fills = minutes(broker, [(100.0, 101.0, 99.0)] * 59, start=EPOCH + MINUTE)
    assert not any(fills)
    [fill] = [f for f in minutes(broker, [(100.0, 100.5, 89.0)], start=EPOCH + 60 * MINUTE) if f]

    assert fill.reason is ExitReason.STOP, "the time exit jumped the queue"
    assert fill.state is TradeState.CLOSED_STOP


def test_the_target_also_wins_that_minute() -> None:
    broker = SimBroker(free_spec(), config(max_hold_hours=1.0))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0)])

    minutes(broker, [(100.0, 101.0, 99.0)] * 59, start=EPOCH + MINUTE)
    [fill] = [f for f in minutes(broker, [(100.0, 121.0, 99.5)], start=EPOCH + 60 * MINUTE) if f]

    assert fill.reason is ExitReason.TARGET


def test_a_time_exit_pays_taker_like_every_exit_but_the_target() -> None:
    """It is a market order at whatever is there, not a resting limit."""
    spec = make_symbol_spec(taker_fee=0.001, maker_fee=0.0)
    broker = SimBroker(spec, config(max_hold_hours=1.0))
    broker.submit(long_entry(order_type=OrderType.LIMIT))
    minutes(broker, [(100.0, 100.0, 100.0)])

    fills = minutes(broker, [(100.0, 101.0, 99.0)] * 61, start=EPOCH + MINUTE)
    [fill] = [f for f in fills if f is not None]

    assert fill.reason is ExitReason.TIME
    # Entry was a resting limit at zero maker fee; the whole fee is the exit.
    assert fill.fees == pytest.approx(fill.exit_price * 1.0 * 0.001)


def test_the_time_exit_prices_off_the_open_of_that_minute() -> None:
    """There is no level to gap through, and `on_minute` is given no close.

    So the open is the only price that exists -- and it is the price
    `learn/labels.py` uses for its own time barrier, which is what keeps the
    two agreeing.
    """
    broker = SimBroker(free_spec(), config(max_hold_hours=1.0, slippage_bps=0.0))
    broker.submit(long_entry())
    minutes(broker, [(100.0, 100.0, 100.0)])

    fills = minutes(broker, [(100.0, 101.0, 99.0)] * 59, start=EPOCH + MINUTE)
    assert not any(fills), "closed before the hour was up"
    fills += minutes(broker, [(97.5, 103.0, 95.0)], start=EPOCH + 60 * MINUTE)
    [fill] = [f for f in fills if f is not None]

    assert fill.reason is ExitReason.TIME
    assert fill.exit_price == pytest.approx(97.5), "priced off something other than the open"
