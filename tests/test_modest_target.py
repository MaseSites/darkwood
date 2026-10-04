"""Capping an over-ambitious target, and the four ways it could cheat.

The measurement behind it: bucketed by planned reward-to-risk over 2,734
journalled trades, the group at or below 1.75 came out at -0.026 R with 41 %
hits, against -0.193 R and 18 % for the group above 2.50. A nearer target is
reached more often, and the hit rate gained outweighs the payoff given up.

The rule is two lines, which is exactly why it needs tests -- each of these
would leave the study measuring something other than the rule:

* **Moving the stop.** Only the target is capped. The stop is where the setup
  says the idea is wrong, and widening it was the most harmful thing measured
  that day.
* **Capping the wrong way for a short.** A short's target sits *below* its
  entry, so the arithmetic has a sign in it and a backtest would still run.
* **Touching a proposal that was already modest.** The claim is that it acts
  only on the ambitious ones; if it rewrote every target, the comparison would
  be measuring two changes.
* **Adding trades.** Like every wrapper here, it can only subtract or rewrite,
  never propose.
"""

from __future__ import annotations

import pytest

from traidingbrain.domain.enums import Side
from traidingbrain.sim.plan import TradeIntent
from traidingbrain.strategies.modest_target import CAP, Action, ModestTarget


class OnePool:
    name = "one"

    def __init__(self, intent: TradeIntent | None) -> None:
        self.intent = intent

    def propose_at(self, analysis: object, index: int) -> TradeIntent | None:
        return self.intent


def ambitious(side: Side = Side.LONG) -> TradeIntent:
    """A 3:1 proposal: 2 wide, reaching 6."""
    if side is Side.LONG:
        return TradeIntent(
            side=side, entry=100.0, stop=98.0, target=112.0, confidence=60.0, reason="A: Zone"
        )
    return TradeIntent(
        side=side, entry=100.0, stop=102.0, target=88.0, confidence=60.0, reason="A: Zone"
    )


def rule(intent: TradeIntent | None, action: Action = Action.REFUSE) -> ModestTarget:
    return ModestTarget(inner=OnePool(intent), action=action)  # type: ignore[arg-type]


def test_an_ambitious_target_is_refused() -> None:
    r = rule(ambitious())
    assert r.propose_at(object(), 0) is None
    assert r.touched == 1


def test_truncating_keeps_the_trade_and_pulls_the_target_in() -> None:
    """The variant that matters for the trade count Severin asked for."""
    out = rule(ambitious(), Action.TRUNCATE).propose_at(object(), 0)

    assert out is not None
    assert out.reward_risk == pytest.approx(CAP)
    assert out.target < 112.0
    assert out.is_coherent


def test_the_stop_is_never_moved() -> None:
    """Only the target is capped.

    The stop marks where the setup says the idea is wrong. Moving it out was
    measured the same day as the single harmful change in the record, with the
    only interval that excluded zero on the bad side.
    """
    original = ambitious()
    out = rule(original, Action.TRUNCATE).propose_at(object(), 0)

    assert out is not None
    assert out.stop == original.stop
    assert out.entry == original.entry


def test_a_short_target_is_capped_downward() -> None:
    """The sign. Capped the wrong way it would sit above the entry, and the
    trade would be incoherent while the backtest still ran."""
    out = rule(ambitious(Side.SHORT), Action.TRUNCATE).propose_at(object(), 0)

    assert out is not None
    assert out.target < out.entry
    assert out.reward_risk == pytest.approx(CAP)
    assert out.is_coherent


@pytest.mark.parametrize("action", list(Action))
def test_a_modest_proposal_passes_through_untouched(action: Action) -> None:
    """Otherwise the study measures a rewrite of every target at once."""
    modest = TradeIntent(
        side=Side.LONG, entry=100.0, stop=98.0, target=103.0, confidence=60.0, reason="A: Zone"
    )
    r = rule(modest, action)

    assert r.propose_at(object(), 0) is modest
    assert r.touched == 0


@pytest.mark.parametrize("action", list(Action))
def test_it_proposes_nothing_of_its_own(action: Action) -> None:
    r = rule(None, action)
    assert r.propose_at(object(), 0) is None
    assert r.touched == 0


def test_the_cap_is_named_rather_than_written_into_the_rule() -> None:
    """1.75 is the upper edge of the best of five buckets whose boundaries were
    fixed before looking -- not a fitted optimum. The buckets between the ends
    do not order, so the number carries the end of a scale and nothing more,
    and the forward journal is where it has to prove itself."""
    assert 1.0 < CAP < 3.0
