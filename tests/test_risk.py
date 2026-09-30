"""Position sizing and leverage.

Two properties carry the whole safety argument, and both are asserted directly
rather than inferred from a passing backtest:

1. **The loss, if the stop is hit, is the risk budget.** Not approximately, not
   before fees -- the quantity is derived from the stop distance so the arithmetic
   is exact, and rounding only ever makes it smaller.

2. **Liquidation sits beyond the stop.** The stop is where the plan says the trade
   is wrong; liquidation is where the exchange says the trade is over. If the
   second arrives first, the stop is decoration and the real risk is the entire
   margin. That is the failure that makes leveraged trading dangerous, and it
   happens silently to anyone who picks a leverage number that sounded reasonable.
"""

from __future__ import annotations

import pytest

from tests.factories import make_symbol_spec
from traidingbrain.config.settings import LeverageConfig, SizingConfig, load_config
from traidingbrain.domain.enums import Side
from traidingbrain.risk.leverage import choose_leverage, liquidation_price, validate_user_leverage
from traidingbrain.risk.sizing import (
    costs_are_affordable,
    min_economic_stop_fraction,
    position_size,
    risk_budget,
)

EQUITY = 10_000.0


@pytest.fixture
def sizing() -> SizingConfig:
    return load_config().risk.sizing


@pytest.fixture
def leverage_config() -> LeverageConfig:
    return load_config().risk.leverage


# --------------------------------------------------------------------------- #
# The risk budget
# --------------------------------------------------------------------------- #


def test_below_the_minimum_confidence_there_is_no_trade(sizing: SizingConfig) -> None:
    """A refusal, not a smaller position.

    A setup the system does not believe in is not a scaled-down version of a good
    one.
    """
    assert risk_budget(55.0, EQUITY, sizing) is None


def test_the_budget_rises_with_confidence(sizing: SizingConfig) -> None:
    generous = SizingConfig.model_validate(sizing.model_dump() | {"min_samples_for_uncap": 0})
    low = risk_budget(65.0, EQUITY, generous, history_samples=1000)
    high = risk_budget(92.0, EQUITY, generous, history_samples=1000)

    assert low is not None and high is not None
    assert high.risk_pct > low.risk_pct
    assert high.risk_amount > low.risk_amount


def test_the_upper_tiers_stay_locked_until_history_earns_them(sizing: SizingConfig) -> None:
    """A stated confidence is not a calibrated probability on day one.

    Letting an uncalibrated number size a position is how "the model was very sure"
    becomes a 3% loss on a setup that was never better than average.
    """
    budget = risk_budget(95.0, EQUITY, sizing, history_samples=0)

    assert budget is not None
    assert budget.capped_by_calibration is True
    assert budget.risk_pct == pytest.approx(sizing.uncalibrated_cap_risk_pct)
    assert "until" in budget.reason


def test_the_cap_lifts_once_there_are_enough_cases(sizing: SizingConfig) -> None:
    budget = risk_budget(95.0, EQUITY, sizing, history_samples=sizing.min_samples_for_uncap)

    assert budget is not None
    assert budget.capped_by_calibration is False
    assert budget.risk_pct > sizing.uncalibrated_cap_risk_pct


def test_nothing_exceeds_the_absolute_ceiling(sizing: SizingConfig) -> None:
    for confidence in (60.0, 75.0, 88.0, 99.0, 100.0):
        budget = risk_budget(confidence, EQUITY, sizing, history_samples=10_000)
        if budget is not None:
            assert budget.risk_pct <= sizing.absolute_max_risk_pct


# --------------------------------------------------------------------------- #
# Position size
# --------------------------------------------------------------------------- #


def test_the_loss_at_the_stop_equals_the_risk_budget() -> None:
    """The invariant the whole design rests on.

    It also means the sizing needs no opinion about volatility: the stop already
    has one, and a wider stop automatically buys a smaller position.
    """
    spec = make_symbol_spec(qty_step=0.00001, min_qty=0.00001)

    for entry, stop in ((42_000.0, 41_000.0), (42_000.0, 41_800.0), (100.0, 80.0)):
        size = position_size(Side.LONG, entry, stop, risk_amount=100.0, spec=spec)
        assert size.is_viable
        loss_at_stop = size.qty * (entry - stop)
        assert loss_at_stop == pytest.approx(100.0, rel=1e-3)


def test_a_tighter_stop_buys_a_bigger_position_for_the_same_risk() -> None:
    spec = make_symbol_spec(qty_step=0.00001, min_qty=0.00001)

    tight = position_size(Side.LONG, 42_000.0, 41_900.0, 100.0, spec)
    wide = position_size(Side.LONG, 42_000.0, 41_000.0, 100.0, spec)

    assert tight.qty > wide.qty * 5
    assert tight.risk_amount == pytest.approx(wide.risk_amount, rel=1e-2)


def test_rounding_never_increases_the_risk() -> None:
    """Rounding up could push the notional past the margin, and the rejection then
    happens at the exchange rather than here."""
    spec = make_symbol_spec(qty_step=0.01, min_qty=0.01)
    size = position_size(Side.LONG, 100.0, 90.0, risk_amount=100.0, spec=spec)

    assert size.qty == pytest.approx(10.0)
    assert size.risk_amount <= 100.0 + 1e-9


def test_a_stop_on_the_wrong_side_produces_nothing() -> None:
    spec = make_symbol_spec()
    assert not position_size(Side.LONG, 100.0, 110.0, 100.0, spec).is_viable
    assert not position_size(Side.SHORT, 100.0, 90.0, 100.0, spec).is_viable
    assert not position_size(Side.LONG, 100.0, 100.0, 100.0, spec).is_viable


def test_a_position_below_the_venue_minimum_is_refused() -> None:
    spec = make_symbol_spec(min_qty=1.0, min_notional=1000.0)
    assert not position_size(Side.LONG, 100.0, 99.0, risk_amount=0.5, spec=spec).is_viable


# --------------------------------------------------------------------------- #
# Leverage
# --------------------------------------------------------------------------- #


def test_liquidation_always_lands_beyond_the_stop(leverage_config: LeverageConfig) -> None:
    spec = make_symbol_spec()

    for entry, stop in ((42_000.0, 41_000.0), (42_000.0, 41_580.0), (100.0, 97.0)):
        choice = choose_leverage(Side.LONG, entry, stop, qty=1.0, spec=spec, config=leverage_config)
        assert choice is not None, f"no safe leverage for a stop at {stop}"
        assert choice.liquidation_price < stop
        assert choice.buffer_r >= leverage_config.min_liquidation_buffer_r * 0.99


def test_the_same_holds_for_shorts(leverage_config: LeverageConfig) -> None:
    spec = make_symbol_spec()
    choice = choose_leverage(
        Side.SHORT, 42_000.0, 43_000.0, qty=1.0, spec=spec, config=leverage_config
    )
    assert choice is not None
    assert choice.liquidation_price > 43_000.0


def test_a_tighter_stop_allows_more_leverage(leverage_config: LeverageConfig) -> None:
    """Leverage is a consequence of the stop, not a preference."""
    spec = make_symbol_spec()
    tight = choose_leverage(
        Side.LONG, 42_000.0, 41_900.0, qty=1.0, spec=spec, config=leverage_config
    )
    wide = choose_leverage(
        Side.LONG, 42_000.0, 38_000.0, qty=1.0, spec=spec, config=leverage_config
    )

    assert tight is not None and wide is not None
    assert tight.leverage > wide.leverage


def test_a_stop_too_wide_for_any_leverage_is_refused(leverage_config: LeverageConfig) -> None:
    """At some width the position would be liquidated before reaching the stop.

    That is a refusal rather than a number to round down to: the trade as specified
    cannot be taken safely at any leverage.
    """
    spec = make_symbol_spec()
    assert (
        choose_leverage(Side.LONG, 100.0, 10.0, qty=1.0, spec=spec, config=leverage_config) is None
    )


def test_leverage_never_exceeds_the_configured_ceiling(leverage_config: LeverageConfig) -> None:
    spec = make_symbol_spec(max_leverage=100.0)
    choice = choose_leverage(
        Side.LONG, 42_000.0, 41_995.0, qty=1.0, spec=spec, config=leverage_config
    )
    assert choice is not None
    assert choice.leverage <= leverage_config.max


def test_the_user_may_lower_leverage_but_not_raise_it(leverage_config: LeverageConfig) -> None:
    """Lowering only moves liquidation further away, so it is always safe.

    Raising is refused because the derived number is already the highest that
    satisfies the buffer.
    """
    spec = make_symbol_spec()
    derived = choose_leverage(
        Side.LONG, 42_000.0, 41_000.0, qty=1.0, spec=spec, config=leverage_config
    )
    assert derived is not None

    lower = validate_user_leverage(
        derived.leverage - 1,
        derived,
        side=Side.LONG,
        entry=42_000.0,
        stop=41_000.0,
        qty=1.0,
        spec=spec,
        config=leverage_config,
    )
    assert lower is not None
    assert lower.buffer_r > derived.buffer_r, "lowering should widen the safety margin"

    higher = validate_user_leverage(
        derived.leverage + 5,
        derived,
        side=Side.LONG,
        entry=42_000.0,
        stop=41_000.0,
        qty=1.0,
        spec=spec,
        config=leverage_config,
    )
    assert higher is None


@pytest.mark.parametrize("leverage", [1.0, 2.0, 5.0, 10.0, 25.0])
def test_the_liquidation_formula_is_symmetric(leverage: float) -> None:
    entry = 100.0
    mmr = 0.005
    long_liq = liquidation_price(Side.LONG, entry, leverage, mmr)
    short_liq = liquidation_price(Side.SHORT, entry, leverage, mmr)

    assert long_liq < entry < short_liq
    assert entry - long_liq == pytest.approx(short_liq - entry)
    assert (entry - long_liq) / entry == pytest.approx(1.0 / leverage - mmr)


# --------------------------------------------------------------------------- #
# The stop distance below which nothing can be afforded
# --------------------------------------------------------------------------- #


def test_the_minimum_economic_stop_is_the_cost_rule_solved_backwards() -> None:
    """The same rule as `costs_are_affordable`, read the other way round.

    Worth its own function because it depends on nothing about the strategy: at
    a given fee schedule and cap there is a stop distance below which no trade
    is affordable, whatever the idea behind it. It is what most of a rule set
    gets refused for, and it is invisible until someone writes it down.
    """
    spec = make_symbol_spec()
    slippage = 3.0
    cap = 0.15

    minimum = min_economic_stop_fraction(spec, slippage, cap)

    # A stop a hair wider than the minimum is affordable; a hair tighter is not.
    risk = 100.0
    for distance, expected in ((minimum * 1.001, True), (minimum * 0.999, False)):
        notional = risk / distance
        affordable, _fraction = costs_are_affordable(notional, risk, spec, slippage, cap)

        assert affordable is expected, f"a stop {distance:.4%} away should be {expected}"


def test_a_cap_of_zero_makes_every_stop_too_tight() -> None:
    """Not a division by zero, and not silently permissive. A cap of zero says
    no cost at all is acceptable, and the honest answer is that no finite stop
    distance satisfies it."""
    assert min_economic_stop_fraction(make_symbol_spec(), 3.0, 0.0) == float("inf")


def test_looser_caps_permit_tighter_stops() -> None:
    """The direction of the relationship, pinned so a sign error cannot hide.

    Inverted, the rule would refuse wide stops and wave tight ones through --
    which is exactly backwards, and would look like a working filter.
    """
    spec = make_symbol_spec()

    strict = min_economic_stop_fraction(spec, 3.0, 0.10)
    loose = min_economic_stop_fraction(spec, 3.0, 0.50)

    assert strict > loose
