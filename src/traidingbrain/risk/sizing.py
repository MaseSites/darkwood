"""Position sizing: risk budget first, size second, leverage last.

This ordering is the whole safety argument of the system, and it is what makes
"invest more when the read is strong" a reasonable thing to want rather than a
way to lose an account.

Two things get conflated when people talk about trade size:

* the **position** -- how much capital is in the trade;
* the **risk** -- how much is lost if the stop is hit, which is
  `position size x distance to stop`.

A 5,000 CHF position with a 3% stop risks 150 CHF, not 5,000. So the position can
be large while the loss stays small, which is exactly the shape people mean when
they say they want to commit more to a setup they believe in.

The risk budget scales with confidence, but with a hard cap that stays in force
until the history engine has shown that high-confidence setups actually do better.
A model's stated confidence is not a calibrated probability on day one, and an
uncalibrated number must not be allowed to size a position.
"""

from __future__ import annotations

from dataclasses import dataclass

from traidingbrain.config.settings import SizingConfig
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import SymbolSpec


@dataclass(frozen=True)
class RiskBudget:
    """How much may be lost on this trade, and why that number."""

    risk_pct: float
    risk_amount: float
    tier_confidence: float
    capped_by_calibration: bool
    reason: str


@dataclass(frozen=True)
class PositionSize:
    """The trade as the exchange will see it."""

    qty: float
    notional: float
    risk_amount: float
    stop_distance: float

    @property
    def is_viable(self) -> bool:
        return self.qty > 0


def risk_budget(
    confidence: float,
    equity: float,
    config: SizingConfig,
    *,
    history_samples: int = 0,
) -> RiskBudget | None:
    """Pick the risk budget for a given confidence.

    Returns None below the minimum confidence, which is a refusal rather than a
    tiny position: a setup the system does not believe in is not a smaller version
    of a good trade.
    """
    if confidence < config.min_confidence:
        return None

    eligible = [tier for tier in config.tiers if confidence >= tier.min_confidence]
    if not eligible:
        return None
    tier = eligible[-1]

    risk_pct = tier.risk_pct
    capped = False
    reason = f"confidence {confidence:.0f} -> {risk_pct:.1%} of equity"

    # The upper tiers stay locked until there is evidence that confidence means
    # anything. Until then the system is allowed to be confident, not to bet on it.
    uncalibrated = history_samples < config.min_samples_for_uncap
    if uncalibrated and risk_pct > config.uncalibrated_cap_risk_pct:
        risk_pct = config.uncalibrated_cap_risk_pct
        capped = True
        reason = (
            f"confidence {confidence:.0f} would allow {tier.risk_pct:.1%}, capped to "
            f"{risk_pct:.1%} until {config.min_samples_for_uncap} historical cases "
            f"show the upper bands earn it (have {history_samples})"
        )

    risk_pct = min(risk_pct, config.absolute_max_risk_pct)
    return RiskBudget(
        risk_pct=risk_pct,
        risk_amount=equity * risk_pct,
        tier_confidence=tier.min_confidence,
        capped_by_calibration=capped,
        reason=reason,
    )


def position_size(
    side: Side,
    entry: float,
    stop: float,
    risk_amount: float,
    spec: SymbolSpec,
) -> PositionSize:
    """Turn a risk budget and a stop distance into a quantity.

    `qty = risk / stop distance` -- so a tight stop buys a large position and a
    wide one a small position, and the loss if wrong is the same either way. That
    invariance is the point: it means the sizing does not need to have an opinion
    about volatility, because the stop already does.

    Rounding is down. Rounding a quantity up can push the notional past what the
    margin supports, and the rejection then happens at the exchange.
    """
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return PositionSize(qty=0.0, notional=0.0, risk_amount=0.0, stop_distance=0.0)
    if (side is Side.LONG and stop >= entry) or (side is Side.SHORT and stop <= entry):
        return PositionSize(qty=0.0, notional=0.0, risk_amount=0.0, stop_distance=stop_distance)

    raw_qty = risk_amount / stop_distance
    steps = int(raw_qty / spec.qty_step)
    qty = steps * spec.qty_step

    if qty < spec.min_qty or qty * entry < spec.min_notional:
        return PositionSize(qty=0.0, notional=0.0, risk_amount=0.0, stop_distance=stop_distance)

    return PositionSize(
        qty=qty,
        notional=qty * entry,
        # The realised risk after rounding, not the budget that was asked for.
        # Reporting the budget would overstate exposure on a small account where
        # rounding bites.
        risk_amount=qty * stop_distance,
        stop_distance=stop_distance,
    )
