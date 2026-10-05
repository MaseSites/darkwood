"""The goal arithmetic, checked against a reading that disagreed with it.

The tests that matter most here are the ones reproducing an outside review's
numbers. A reader worked the 20x target independently, got 66.75% for a
symmetric payout and 2.99x at 56.6%, and asked this project to show its own
derivation. If these two tests ever stop passing, this module and that review
have drifted apart and one of them is wrong.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from traidingbrain.learn.target import (
    SYMMETRIC,
    Payout,
    breakeven_hit_rate,
    growth_at,
    payout_implied_by,
    required_hit_rate,
    required_mean_r,
    shortfall_from_variance,
)

#: The scenario in dispute: 1,000 to 20,000, twelve markets over 26 weeks,
#: 3% of the account risked per trade.
GROWTH = 20.0
TRADES = 312.0
RISK = 0.03


def test_symmetric_payout_needs_sixty_six_point_seven_five() -> None:
    """The review's figure, to its stated precision.

    `312 * [p*ln(1.03) + (1-p)*ln(0.97)] = ln(20)` gives p = 0.6675. This is
    the acceptance test the order named explicitly.
    """
    rate = required_hit_rate(growth=GROWTH, trades=TRADES, risk=RISK, payout=SYMMETRIC)
    assert rate == pytest.approx(0.6675, abs=0.0001)


def test_fifty_six_point_six_reaches_three_times_not_twenty() -> None:
    """The consequence of the error: 2.99x, so 2,990 and not 20,000."""
    reached = growth_at(hit_rate=0.566, trades=TRADES, risk=RISK, payout=SYMMETRIC)
    assert reached == pytest.approx(2.99, abs=0.01)
    assert reached < 3.0


def test_the_unstated_assumption_was_a_win_of_one_point_three_seven_one_r() -> None:
    """What 56.6% silently required, recovered from the claim itself."""
    implied = payout_implied_by(hit_rate=0.566, growth=GROWTH, trades=TRADES, risk=RISK)
    assert implied.win == pytest.approx(1.371, abs=0.001)
    assert implied.loss == 1.0


def test_implied_payout_round_trips() -> None:
    """The implied win size must actually reach the target, or it is not implied."""
    for hit_rate in (0.52, 0.566, 0.60, 0.75):
        implied = payout_implied_by(
            hit_rate=hit_rate, growth=GROWTH, trades=TRADES, risk=RISK
        )
        reached = growth_at(
            hit_rate=hit_rate, trades=TRADES, risk=RISK, payout=implied
        )
        assert reached == pytest.approx(GROWTH, rel=1e-9)


def test_required_and_growth_are_inverses() -> None:
    for payout in (SYMMETRIC, Payout(win=1.5), Payout(win=2.0, loss=1.0)):
        rate = required_hit_rate(growth=GROWTH, trades=TRADES, risk=RISK, payout=payout)
        if rate > 1.0:
            continue
        assert growth_at(
            hit_rate=rate, trades=TRADES, risk=RISK, payout=payout
        ) == pytest.approx(GROWTH, rel=1e-9)


def test_required_mean_r_reproduces_the_committed_figure() -> None:
    """+0.322 R -- what scripts/goal.py has always computed, and its origin."""
    mean_r = required_mean_r(growth=GROWTH, trades=TRADES, risk=RISK)
    assert mean_r == pytest.approx(0.3215, abs=0.0001)
    # And the arithmetic it comes from, spelled out so the formula is not the
    # only witness to itself.
    assert mean_r == pytest.approx((GROWTH ** (1.0 / TRADES) - 1.0) / RISK, rel=1e-12)


def test_an_unreachable_target_says_so_instead_of_clamping() -> None:
    """A hit rate above 1.0 is the informative answer, not an error.

    At 1% risk and a symmetric payout, 20x in 312 trades is impossible: even
    winning every trade compounds to 1.01^312, which is about 22.5 -- so it is
    barely reachable there. At 0.3% risk it is not, and the function must
    report a figure above 1.0 rather than pretend 100% would do.
    """
    rate = required_hit_rate(growth=GROWTH, trades=TRADES, risk=0.003, payout=SYMMETRIC)
    assert rate > 1.0
    # Winning literally every trade falls short, which is what that means.
    assert growth_at(hit_rate=1.0, trades=TRADES, risk=0.003, payout=SYMMETRIC) < GROWTH


def test_ruinous_risk_is_rejected() -> None:
    """A loss that takes the whole account is not a small-print caveat."""
    with pytest.raises(ValueError, match="Ruin"):
        required_hit_rate(growth=GROWTH, trades=TRADES, risk=1.0, payout=SYMMETRIC)


def test_breakeven_matches_the_horizon_table() -> None:
    """The cost-coverage question, against the figures already reported.

    These come from `scripts/study_horizon.py`: a 0.1215% round trip against
    the measured median move at each horizon. They are a different question
    from the target arithmetic above, and mixing them is what put 69.9%,
    51.2% and 56.6% in one report without saying which was which.
    """
    toll = 0.001215
    assert breakeven_hit_rate(move=0.00306, toll=toll) == pytest.approx(0.6985, abs=0.0005)
    assert breakeven_hit_rate(move=0.05099, toll=toll) == pytest.approx(0.5119, abs=0.0005)

    # Binance spot's 0.2% round trip on the same one-hour move.
    assert breakeven_hit_rate(move=0.00306, toll=0.002) == pytest.approx(0.8268, abs=0.0005)


def test_breakeven_is_a_half_at_zero_cost_and_rises_with_it() -> None:
    assert breakeven_hit_rate(move=0.01, toll=0.0) == pytest.approx(0.5)
    rising = [breakeven_hit_rate(move=0.01, toll=t) for t in (0.0, 0.001, 0.002, 0.004)]
    assert rising == sorted(rising)


def test_breakeven_falls_as_the_horizon_lengthens() -> None:
    """The whole point of the horizon table, as a monotonicity property."""
    toll = 0.001215
    moves = [0.00306, 0.00614, 0.01752, 0.05099, 0.11962]
    needed = [breakeven_hit_rate(move=m, toll=toll) for m in moves]
    assert needed == sorted(needed, reverse=True)
    assert needed[-1] < 0.51


def test_variance_makes_the_closed_form_optimistic() -> None:
    """Jensen's inequality, measured rather than asserted.

    Two sequences with the same mean R: one constant, one scattered. The
    scattered one must compound to less, which is exactly the bias every
    closed form in this module carries.
    """
    rng = np.random.default_rng(20261005)
    mean = 0.3215
    constant = np.full(312, mean)
    scattered = rng.normal(loc=mean, scale=1.5, size=312)
    scattered = scattered - scattered.mean() + mean  # same mean, real spread

    flat_actual, flat_model = shortfall_from_variance(
        r_values=constant, risk=RISK, trades=TRADES
    )
    wide_actual, wide_model = shortfall_from_variance(
        r_values=scattered, risk=RISK, trades=TRADES
    )

    # With no variance the two agree.
    assert flat_actual == pytest.approx(flat_model, rel=1e-6)
    assert flat_actual == pytest.approx(GROWTH, rel=0.01)

    # The models agree with each other because the means are equal...
    assert wide_model == pytest.approx(flat_model, rel=1e-6)
    # ...but the realised compounding falls short, and that gap is the point.
    assert wide_actual < wide_model


def test_shortfall_rejects_an_account_wiping_trade() -> None:
    values = np.array([0.5, -40.0, 0.5])
    with pytest.raises(ValueError, match="loescht das Konto"):
        shortfall_from_variance(r_values=values, risk=RISK, trades=3)


def test_payout_expectancy_and_ratio() -> None:
    payout = Payout(win=1.5, loss=1.0)
    assert payout.ratio == pytest.approx(1.5)
    # A 40% hit rate at 1.5:1 is exactly break-even in additive R.
    assert payout.expectancy(0.4) == pytest.approx(0.0)
    assert payout.expectancy(0.5) == pytest.approx(0.25)
    assert "1:1.500" in payout.describe()


def test_payout_rejects_nonsense() -> None:
    for win, loss in ((0.0, 1.0), (-1.0, 1.0), (1.0, 0.0), (1.0, -1.0)):
        with pytest.raises(ValueError, match="positive"):
            Payout(win=win, loss=loss)


def test_breakeven_rejects_a_zero_move() -> None:
    with pytest.raises(ValueError, match="positiv"):
        breakeven_hit_rate(move=0.0, toll=0.001)


def test_required_mean_r_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="Trade-Zahl"):
        required_mean_r(growth=2.0, trades=0, risk=0.01)
    with pytest.raises(ValueError, match="Risiko"):
        required_mean_r(growth=2.0, trades=10, risk=0.0)
    with pytest.raises(ValueError, match="Wachstum"):
        required_mean_r(growth=0.0, trades=10, risk=0.01)


def test_hit_rate_outside_the_unit_interval_is_refused() -> None:
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError, match="zwischen 0 und 1"):
            growth_at(hit_rate=bad, trades=TRADES, risk=RISK)


def test_a_better_payout_lowers_the_requirement() -> None:
    """Monotone in the payout, which is the sanity check on the whole model."""
    rates = [
        required_hit_rate(growth=GROWTH, trades=TRADES, risk=RISK, payout=Payout(win=w))
        for w in (0.8, 1.0, 1.371, 2.0, 3.0)
    ]
    assert rates == sorted(rates, reverse=True)
    # And the middle one is the figure the original claim assumed.
    assert rates[2] == pytest.approx(0.566, abs=0.001)


def test_more_trades_lower_the_requirement_per_trade() -> None:
    rates = [
        required_hit_rate(growth=GROWTH, trades=n, risk=RISK, payout=SYMMETRIC)
        for n in (100, 200, 312, 500, 1000)
    ]
    assert rates == sorted(rates, reverse=True)


def test_log_model_agrees_with_direct_multiplication() -> None:
    """The closed form against the thing it is a closed form for."""
    hit_rate, trades = 0.6, 50
    payout = Payout(win=1.4, loss=1.0)
    wins = round(hit_rate * trades)
    direct = (1 + RISK * payout.win) ** wins * (1 - RISK * payout.loss) ** (trades - wins)
    assert growth_at(
        hit_rate=hit_rate, trades=trades, risk=RISK, payout=payout
    ) == pytest.approx(direct, rel=1e-9)


def test_breakeven_formula_against_expectancy_definition() -> None:
    """`p = (1 + toll/move)/2` must zero `(2p-1)*move - toll`, for any inputs."""
    for move, toll in ((0.003, 0.001215), (0.05, 0.002), (0.01, 0.0005)):
        p = breakeven_hit_rate(move=move, toll=toll)
        assert (2 * p - 1) * move - toll == pytest.approx(0.0, abs=1e-15)


def test_the_monthly_growth_the_target_implies() -> None:
    """64.75% a month, as the review states. A sanity anchor on the target."""
    monthly = GROWTH ** (1.0 / 6.0) - 1.0
    assert monthly == pytest.approx(0.6475, abs=0.0005)
    assert math.prod([1 + monthly] * 6) == pytest.approx(GROWTH, rel=1e-9)
