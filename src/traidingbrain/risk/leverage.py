"""Leverage: derived from the stop, never chosen.

Once the risk budget and the stop distance are fixed, the position size is fixed
too -- `risk / stop distance`. Leverage does not change how much is at stake. All
it changes is how much margin is tied up, and how far away the exchange's own exit
sits.

That second part is the only thing that matters, and it is why leverage is
computed here rather than asked for. The stop is where the plan says the trade is
wrong. Liquidation is where the exchange says the trade is over. If liquidation
arrives first, the stop is decoration and the real risk is the entire margin --
which is precisely the failure that makes leveraged trading dangerous, and it
happens silently to anyone who picks a leverage number because it sounded
reasonable.

So: pick the highest leverage that still leaves the liquidation price a
comfortable multiple of the stop distance beyond the stop. The user may lower it
in the dashboard, which only widens that gap and is therefore always safe.
"""

from __future__ import annotations

from dataclasses import dataclass

from traidingbrain.config.settings import LeverageConfig
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import SymbolSpec


def liquidation_price(
    side: Side, entry: float, leverage: float, maintenance_margin_rate: float
) -> float:
    """Where isolated margin runs out.

    The position is closed when the loss has eaten the margin down to the
    maintenance requirement, which for isolated margin is `1/leverage - mmr` away
    from entry as a fraction. Approximate -- venues add fee buffers and tiered
    maintenance rates -- and deliberately approximate on the conservative side, so
    the simulator liquidates slightly earlier than the real venue rather than
    later.
    """
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    distance = 1.0 / leverage - maintenance_margin_rate
    if side is Side.LONG:
        return entry * (1.0 - distance)
    return entry * (1.0 + distance)


#: Leverage is offered in whole steps. A venue accepts 3.7x, but nobody reasons in
#: 3.7x, and the extra precision buys nothing that 3x does not already give.
LEVERAGE_STEP = 1.0

#: Below this there is no meaningful position.
MIN_LEVERAGE = 1.0


@dataclass(frozen=True)
class LeverageChoice:
    """The leverage, and what it implies for where the trade dies."""

    leverage: float
    liquidation_price: float
    buffer_r: float
    margin: float
    reason: str

    @property
    def is_safe(self) -> bool:
        return self.buffer_r > 0


def choose_leverage(
    side: Side,
    entry: float,
    stop: float,
    *,
    qty: float,
    spec: SymbolSpec,
    config: LeverageConfig,
) -> LeverageChoice | None:
    """Highest leverage that keeps liquidation well beyond the stop.

    Returns None when even 1x cannot satisfy the requirement, which happens when
    the stop is so wide that the position would be liquidated before reaching it.
    That is a refusal, not a number to round down to -- the trade as specified
    cannot be taken safely at any leverage.
    """
    stop_distance = abs(entry - stop)
    if stop_distance <= 0 or entry <= 0 or qty <= 0:
        return None

    # Required distance from entry to liquidation, as a fraction of price.
    required = stop_distance * (1.0 + config.min_liquidation_buffer_r) / entry
    denominator = required + spec.maintenance_margin_rate
    if denominator <= 0:
        return None

    ceiling = min(1.0 / denominator, config.max, spec.max_leverage)
    leverage = float(int(ceiling / LEVERAGE_STEP) * LEVERAGE_STEP)

    if leverage < MIN_LEVERAGE:
        return None

    liquidation = liquidation_price(side, entry, leverage, spec.maintenance_margin_rate)
    buffer_r = abs(liquidation - stop) / stop_distance
    on_correct_side = liquidation < stop if side is Side.LONG else liquidation > stop
    if not on_correct_side:
        return None

    return LeverageChoice(
        leverage=leverage,
        liquidation_price=liquidation,
        buffer_r=buffer_r,
        margin=qty * entry / leverage,
        reason=(
            f"{leverage:.0f}x puts liquidation at {liquidation:,.2f}, "
            f"{buffer_r:.1f} stop-distances beyond the stop"
        ),
    )


def validate_user_leverage(
    requested: float,
    derived: LeverageChoice,
    *,
    side: Side,
    entry: float,
    stop: float,
    qty: float,
    spec: SymbolSpec,
    config: LeverageConfig,
) -> LeverageChoice | None:
    """Check a leverage the user typed in the dashboard.

    Lowering is always allowed: it only moves liquidation further away. Raising is
    refused unless the config explicitly permits it, because the number the system
    derived is the highest one that still satisfies the buffer requirement.
    """
    if requested <= 0:
        return None
    if requested > derived.leverage and not config.allow_user_increase:
        return None
    if requested > min(config.max, spec.max_leverage):
        return None

    liquidation = liquidation_price(side, entry, requested, spec.maintenance_margin_rate)
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return None

    on_correct_side = liquidation < stop if side is Side.LONG else liquidation > stop
    if not on_correct_side:
        return None

    return LeverageChoice(
        leverage=requested,
        liquidation_price=liquidation,
        buffer_r=abs(liquidation - stop) / stop_distance,
        margin=qty * entry / requested,
        reason=f"{requested:.0f}x chosen manually; liquidation at {liquidation:,.2f}",
    )
