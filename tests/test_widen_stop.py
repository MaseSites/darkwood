"""Widening a stop, and the ways it could quietly become a different trade.

The move is small -- push an unaffordable stop out to the cheapest distance
that passes the cost ceiling -- and that is exactly why it needs tests. Each of
the following would make the study that uses it report something other than
what it claims to measure:

* **Widening the wrong way.** A stop pushed to the *far* side of entry inverts
  the trade. Arithmetic on a sign, and the backtest would still run.
* **Touching a stop that was already fine.** The wrapper's whole claim is that
  it only rescues refusals. If it also moved affordable stops, the comparison
  against the plain pool would be measuring two changes at once.
* **Silently changing the reward-to-risk ratio.** The two modes are two
  different bets and the study reports them separately; a mode that did not do
  what its name says would merge them.
* **Reading the floor from somewhere other than the risk layer.** The wrapper
  and the layer that judges its output have to agree about where the edge is,
  or the wrapper hands over trades that are refused anyway.
"""

from __future__ import annotations

import pytest

from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.risk.sizing import costs_are_affordable, min_economic_stop_fraction
from traidingbrain.sim.plan import TradeIntent
from traidingbrain.strategies.widen_stop import Target, WidenedStop


class OnePool:
    """A pool that proposes exactly the intent a test hands it."""

    name = "one"

    def __init__(self, intent: TradeIntent | None) -> None:
        self.intent = intent

    def propose_at(self, analysis: object, index: int) -> TradeIntent | None:
        return self.intent


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


@pytest.fixture(scope="module")
def spec() -> SymbolSpec:
    return SymbolSpec(symbol="BTCUSDT", **DEFAULT_SPEC)


def wrapper(
    intent: TradeIntent | None,
    config: AppConfig,
    spec: SymbolSpec,
    mode: Target = Target.KEEP_RATIO,
) -> WidenedStop:
    return WidenedStop(inner=OnePool(intent), spec=spec, config=config, mode=mode)  # type: ignore[arg-type]


def tight_long() -> TradeIntent:
    """A stop 0.1% away -- the shape nine of twelve accounts are refused for."""
    return TradeIntent(side=Side.LONG, entry=100.0, stop=99.9, target=100.5, confidence=60.0)


def tight_short() -> TradeIntent:
    return TradeIntent(side=Side.SHORT, entry=100.0, stop=100.1, target=99.5, confidence=60.0)


# --------------------------------------------------------------------------- #
# Direction
# --------------------------------------------------------------------------- #


def test_a_long_stop_moves_down_and_stays_below_entry(config: AppConfig, spec: SymbolSpec) -> None:
    """Pushed to the far side of entry it would be a short wearing a long's
    label, and nothing downstream would notice."""
    out = wrapper(tight_long(), config, spec).propose_at(object(), 0)

    assert out is not None
    assert out.stop < out.entry
    assert out.stop < 99.9, "the stop did not move outward"
    assert out.is_coherent


def test_a_short_stop_moves_up_and_stays_above_entry(config: AppConfig, spec: SymbolSpec) -> None:
    out = wrapper(tight_short(), config, spec).propose_at(object(), 0)

    assert out is not None
    assert out.stop > out.entry
    assert out.stop > 100.1
    assert out.is_coherent


def test_the_new_distance_is_exactly_what_the_risk_layer_demands(
    config: AppConfig, spec: SymbolSpec
) -> None:
    """The wrapper and the layer that judges it must read the same number.

    Not approximately: a stop one tick inside the threshold is refused all the
    same, and the study would report the widening as useless rather than as
    mis-measured.
    """
    rule = wrapper(tight_long(), config, spec)
    out = rule.propose_at(object(), 0)

    assert out is not None
    floor = min_economic_stop_fraction(
        spec,
        config.engine.simulation.slippage_bps,
        config.risk.limits.max_cost_fraction_of_risk,
    )
    assert abs((out.entry - out.stop) / out.entry - floor) < 1e-12


def test_the_widened_trade_actually_passes_the_cost_check(
    config: AppConfig, spec: SymbolSpec
) -> None:
    """The point of the whole exercise, checked against the real rule rather
    than against the formula it was derived from."""
    out = wrapper(tight_long(), config, spec).propose_at(object(), 0)
    assert out is not None

    risk_amount = 10.0
    qty = risk_amount / (out.entry - out.stop)
    affordable, fraction = costs_are_affordable(
        qty * out.entry,
        risk_amount,
        spec,
        config.engine.simulation.slippage_bps,
        config.risk.limits.max_cost_fraction_of_risk,
    )

    assert affordable, f"still unaffordable at {fraction:.1%}"


# --------------------------------------------------------------------------- #
# What it leaves alone
# --------------------------------------------------------------------------- #


def test_an_affordable_stop_is_returned_untouched(config: AppConfig, spec: SymbolSpec) -> None:
    """Otherwise the study measures two changes and attributes both to one."""
    wide = TradeIntent(side=Side.LONG, entry=100.0, stop=95.0, target=110.0, confidence=60.0)
    rule = wrapper(wide, config, spec)

    out = rule.propose_at(object(), 0)

    assert out is wide
    assert rule.widened == 0


def test_it_proposes_nothing_when_the_pool_proposes_nothing(
    config: AppConfig, spec: SymbolSpec
) -> None:
    rule = wrapper(None, config, spec)

    assert rule.propose_at(object(), 0) is None
    assert rule.widened == 0


# --------------------------------------------------------------------------- #
# The two bets
# --------------------------------------------------------------------------- #


def test_keeping_the_ratio_moves_the_target_out_too(config: AppConfig, spec: SymbolSpec) -> None:
    """Severin asked for the ratio to be the thing that is held. Holding it
    means the target travels with the stop."""
    original = tight_long()
    out = wrapper(original, config, spec, Target.KEEP_RATIO).propose_at(object(), 0)

    assert out is not None
    assert out.target > original.target
    assert abs(out.reward_risk - original.reward_risk) < 1e-9


def test_keeping_the_target_lowers_the_ratio(config: AppConfig, spec: SymbolSpec) -> None:
    """The other bet, and the reason it is reported separately: a wider stop
    under a fixed target is a worse trade on paper, and `min_reward_risk` will
    refuse some of these anyway."""
    original = tight_long()
    out = wrapper(original, config, spec, Target.KEEP_TARGET).propose_at(object(), 0)

    assert out is not None
    assert out.target == original.target
    assert out.reward_risk < original.reward_risk


def test_the_widening_is_recorded_in_the_reason(config: AppConfig, spec: SymbolSpec) -> None:
    """A journalled trade has to say its stop is not where the setup put it.

    Without this the record would claim the setup chose a level it never
    argued for, and a later reader -- including a later version of me -- would
    draw conclusions about the setup from a number this wrapper invented.
    """
    original = TradeIntent(
        side=Side.LONG, entry=100.0, stop=99.9, target=100.5, confidence=60.0, reason="V11: Block"
    )
    out = wrapper(original, config, spec).propose_at(object(), 0)

    assert out is not None
    assert "V11: Block" in out.reason
    assert "verbreitert" in out.reason
