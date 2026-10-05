"""What a growth target demands, with the payout scheme written down.

This module exists because a number went out without its assumptions. On
05.10.2026 this project reported that turning 1,000 into 20,000 in six months
needs **56.6% weekly directional accuracy at 3% risk**. The figure was computed
as a one-off expression in a terminal and never committed, so nothing recorded
what payout it assumed.

A reader reconstructed it and found the answer: 56.6% is only correct if every
winner returns **+1.371 R** against a 1 R loser. Under a symmetric +1/-1 R
payout the same target needs **66.75%**, and 56.6% under that payout reaches
only **2.99x** -- 2,990, not 20,000. Both of those numbers are reproduced by
the tests in `tests/test_target.py`, which is the point of this file: the
arithmetic is now checkable, and the payout is an argument rather than an
assumption.

**Three different questions that all produce a percentage.** Conflating them is
what made one report carry 69.9%, 51.2% and 56.6% without saying which was
which:

* `breakeven_hit_rate` -- what directional accuracy pays the toll and nothing
  more. Answers "is this horizon tradeable at all". The 69.83% (one hour) and
  51.19% (one week) figures are this question.
* `required_hit_rate` -- what accuracy compounds a starting balance to a target
  in a given number of trades. Answers "does this reach the goal". The 56.6%
  was meant to be this one.
* `growth_at` -- the forward direction of the same model, for reading what a
  given accuracy actually reaches.

**The flaw this module keeps and labels rather than hides.** A two-point payout
is a simplification: real R outcomes are a distribution, and
`E[ln(1 + f*R)] < ln(1 + f*E[R])` whenever R varies, by Jensen's inequality. So
every required-accuracy figure here is a **lower bound** -- the real
requirement is higher, and by how much depends on the variance of R.
`required_mean_r` carries the same bias; it is what `scripts/goal.py` has
always computed. `shortfall_from_variance` measures the gap for a given
distribution instead of waving at it.

**What none of this models.** Trades here are sequential and
non-overlapping. Twelve markets held at once share one account: the capital is
not twelve independent bets, correlated losses land together, and the
compounding order stops being well defined. That belongs in a portfolio
simulation, not in a closed form, and this module's docstrings say so rather
than letting a tidy formula imply otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

#: Below this the two-point solve is meaningless: a loss that takes the whole
#: account makes log growth negative infinity, and no hit rate recovers it.
MAX_LOSS_FRACTION = 0.999


@dataclass(frozen=True, slots=True)
class Payout:
    """A two-point outcome scheme, in R.

    `win` is what a winning trade returns as a multiple of the risked amount,
    `loss` the magnitude of a losing one -- both positive. A 1.5:1 target to
    stop with no partial exits is `Payout(win=1.5, loss=1.0)`.

    Stated as its own type because the whole lesson of this module is that a
    required hit rate is meaningless without it. A function that took `win_r`
    as an optional argument defaulting to 1.0 would let the assumption go
    unstated again.
    """

    win: float
    loss: float = 1.0

    def __post_init__(self) -> None:
        if self.win <= 0 or self.loss <= 0:
            raise ValueError(f"Payout braucht positive Groessen, nicht {self}")

    @property
    def ratio(self) -> float:
        return self.win / self.loss

    def expectancy(self, hit_rate: float) -> float:
        """Mean R per trade at this hit rate. The additive, non-compounded view."""
        return hit_rate * self.win - (1.0 - hit_rate) * self.loss

    def describe(self) -> str:
        return f"+{self.win:.3f} R gewonnen / -{self.loss:.3f} R verloren (1:{self.ratio:.3f})"


#: The payout a symmetric bet implies. Named because it is the scheme under
#: which the 20x target needs 66.75%, and the one a reader will assume when a
#: report says "accuracy" without qualification.
SYMMETRIC = Payout(win=1.0, loss=1.0)


def breakeven_hit_rate(*, move: float, toll: float) -> float:
    """Directional accuracy that exactly pays the cost of trading.

    From `expectancy = (2p - 1) * move - toll`, so `p = (1 + toll/move) / 2`.
    Both arguments are fractions of entry price.

    This answers whether a horizon is tradeable at all and says nothing about
    reaching any target. It is the question behind 69.83% at one hour and
    51.19% at one week: the toll is fixed and the available move grows, so the
    requirement falls with the horizon.

    Note what it assumes: a win captures `move` and a loss gives up `move`.
    That is a symmetric payout in price terms, which is the right model for a
    directional bet held to a fixed horizon and the wrong one for a trade with
    a stop closer than its target.
    """
    if move <= 0:
        raise ValueError(f"Bewegung muss positiv sein, nicht {move}")
    return 0.5 * (1.0 + toll / move)


def required_mean_r(*, growth: float, trades: float, risk: float) -> float:
    """Mean R per trade that compounds `growth` over `trades` at `risk` each.

    This is exactly what `scripts/goal.py` computes, and it is where +0.322 R
    came from: `(20 ** (1/312) - 1) / 0.03`.

    **It assumes every trade returns the same R.** With a real distribution of
    the same mean, compounded growth is lower -- so this is a floor, not a
    requirement. `shortfall_from_variance` quantifies the difference.
    """
    if trades <= 0:
        raise ValueError(f"Trade-Zahl muss positiv sein, nicht {trades}")
    if risk <= 0:
        raise ValueError(f"Risiko muss positiv sein, nicht {risk}")
    if growth <= 0:
        raise ValueError(f"Wachstum muss positiv sein, nicht {growth}")
    # float() because `float ** float` widens to Any under --strict.
    return float(growth ** (1.0 / trades) - 1.0) / risk


def _log_steps(payout: Payout, risk: float) -> tuple[float, float]:
    """Log multiplier of a win and of a loss, checked for ruin."""
    loss_fraction = risk * payout.loss
    if loss_fraction >= MAX_LOSS_FRACTION:
        raise ValueError(
            f"Ein Verlust von {100 * loss_fraction:.1f}% des Kontos je Trade ist Ruin: "
            f"Risiko {100 * risk:.2f}% x {payout.loss:.2f} R."
        )
    return math.log1p(risk * payout.win), math.log1p(-loss_fraction)


def required_hit_rate(
    *, growth: float, trades: float, risk: float, payout: Payout = SYMMETRIC
) -> float:
    """Hit rate that compounds `growth` over `trades`, under an explicit payout.

    Solves `n * [p*ln(1 + f*w) + (1-p)*ln(1 - f*l)] = ln(G)` for p, which is
    the calculation the review asked for and the one that must be checkable.

    With `growth=20, trades=312, risk=0.03` and a symmetric payout this returns
    **0.6675** -- the figure an outside reading derived independently, and the
    reason the earlier 56.6% was wrong without its payout attached.

    Can return a value above 1.0, which is informative rather than an error: it
    means the target is unreachable at that risk and payout no matter how often
    the direction is right, and the caller should say so instead of clamping.
    """
    win_step, loss_step = _log_steps(payout, risk)
    needed = math.log(growth) / trades
    span = win_step - loss_step
    if span <= 0:
        raise ValueError("Gewinnschritt liegt nicht ueber dem Verlustschritt; kein Vorzeichen.")
    return (needed - loss_step) / span


def growth_at(
    *, hit_rate: float, trades: float, risk: float, payout: Payout = SYMMETRIC
) -> float:
    """Multiple of starting capital reached at this hit rate. The inverse view.

    With `hit_rate=0.566, trades=312, risk=0.03` and a symmetric payout this
    returns **2.99** -- so the accuracy this project reported as sufficient for
    20x reaches under 3x once the payout is stated.

    This is a point result of a deterministic model, not a forecast: it is what
    happens if the hit rate is exactly `hit_rate` and every outcome is exactly
    the payout. Real sequences scatter widely around it.
    """
    if not 0.0 <= hit_rate <= 1.0:
        raise ValueError(f"Trefferquote liegt zwischen 0 und 1, nicht {hit_rate}")
    win_step, loss_step = _log_steps(payout, risk)
    return math.exp(trades * (hit_rate * win_step + (1.0 - hit_rate) * loss_step))


def payout_implied_by(
    *, hit_rate: float, growth: float, trades: float, risk: float, loss: float = 1.0
) -> Payout:
    """The win size at which `hit_rate` would actually reach `growth`.

    The function that makes an unstated assumption visible. Given 56.6%, 20x,
    312 trades and 3% risk it returns a win of **1.371 R**, which is what the
    original claim silently required.

    Use it on any reported accuracy whose payout is missing: if the implied win
    size is not one the system has measured, the accuracy figure is not a
    result.
    """
    _, loss_step = _log_steps(Payout(win=loss, loss=loss), risk)
    needed = math.log(growth) / trades
    if hit_rate <= 0:
        raise ValueError("Trefferquote null impliziert keine Gewinngroesse.")
    win_step = (needed - (1.0 - hit_rate) * loss_step) / hit_rate
    win_fraction = math.expm1(win_step)
    if win_fraction <= 0:
        raise ValueError(
            f"Bei {100 * hit_rate:.1f}% Trefferquote reicht keine Gewinngroesse fuer {growth:.1f}x."
        )
    return Payout(win=win_fraction / risk, loss=loss)


def shortfall_from_variance(
    *, r_values: np.ndarray, risk: float, trades: float
) -> tuple[float, float]:
    """Compounded growth from a real R distribution, against the constant-R model.

    Returns `(actual, as_if_constant)` -- the multiple reached by compounding
    the given R outcomes in sequence, and the multiple the constant-R formula
    predicts from their mean.

    The second is always at least the first, by Jensen's inequality, and the
    gap is the optimism built into every closed form above. Measuring it is the
    only honest way to use them.

    Outcomes are compounded in the order given, which is deliberate: R values
    read off a journal arrive in time order, and reordering them would be a
    different claim.
    """
    if r_values.size == 0:
        raise ValueError("Keine R-Werte uebergeben.")
    # A trade at or beyond -1/risk R takes the whole account, and log1p of that
    # is nan or -inf. That is the case this function must report, so the warning
    # numpy would print is suppressed and the check below does the reporting.
    with np.errstate(invalid="ignore", divide="ignore"):
        steps = np.log1p(risk * r_values)
    if not np.all(np.isfinite(steps)):
        raise ValueError("Mindestens ein Trade loescht das Konto; kein Logarithmus moeglich.")

    scale = trades / r_values.size
    actual = float(np.exp(steps.sum() * scale))
    constant = float((1.0 + risk * float(r_values.mean())) ** trades)
    return actual, constant
