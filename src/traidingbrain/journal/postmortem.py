"""Why a trade ended the way it did, read off the bars it lived through.

The exit reason says which line was touched. It does not say whether the trade
was ever right, how close it came, or whether the stop was taken by a single
wick that the bar then closed back above -- and those are the three things a
person actually wants to know when looking at a loser.

Everything here is derived from the price series between entry and exit. None
of it is a judgement about whether the trade should have been taken; that is
what the entry reason is for, and keeping the two apart is what makes it
possible to ask whether good reasons and good outcomes line up.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from traidingbrain.domain.enums import ExitReason, Side
from traidingbrain.journal.record import PostMortem

#: Below this, "it never went our way" is a fairer description than a number.
#: One twentieth of the risk is inside the spread on most of these markets.
FLAT_R = 0.05


def _window(frame: pd.DataFrame, opened_ts: int, closed_ts: int) -> pd.DataFrame:
    """Only the bars that lie entirely inside the trade's life.

    Both edge bars are contaminated and the fix has to drop both. The opening
    bar contains movement from before the entry; the closing bar contains
    movement from after the exit. Including them reads the market's opinion
    about a position that did not exist yet, or no longer existed.

    How badly: measured on 07.10.2026 over the stored journal, `max_adverse_r`
    reached **147.88** on a trade that was stopped out at -0.036 R after
    `bars_held = 1`. That is the whole closing bar's low. 25.3% of stopped
    trades carried an adverse excursion above 1.6 R, which a trade closed at
    about -1 R cannot have had while it was open.

    A one-bar trade therefore has no interior bar at all, and that is the
    honest answer rather than a defect: at signal-timeframe resolution its
    excursion is **unobservable**. `examine` then bounds it by the entry and
    exit prices, which is what the data supports.
    """
    inside: pd.DataFrame = frame.loc[(frame["ts"] > opened_ts) & (frame["ts"] < closed_ts)]
    return inside


def examine(
    frame: pd.DataFrame,
    *,
    side: Side,
    entry: float,
    stop: float,
    opened_ts: int,
    closed_ts: int,
    exit_price: float,
    exit_reason: ExitReason,
    r_multiple: float,
) -> PostMortem:
    """Read the trade's life out of the bars.

    `frame` is the signal timeframe. The simulator resolves stop-or-target
    inside a bar on minute data, so a stop recorded here can be touched by a
    wick this frame does not show as a close -- which is exactly the case
    `stopped_by_wick` is for.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return PostMortem(
            bars_held=0,
            max_favourable_r=0.0,
            max_adverse_r=0.0,
            closest_to_target_r=0.0,
            stopped_by_wick=False,
            never_in_profit=True,
            verdict="kein Risikoabstand zwischen Einstieg und Stop",
        )

    # Zwei verschiedene leere Faelle, und sie bedeuten Verschiedenes.
    # Gar keine Kerze im Zeitraum heisst: keine Kursdaten. Keine INNERE Kerze
    # heisst: der Trade war kuerzer als eine Kerze, und seine Bewegung ist auf
    # dieser Zeitebene schlicht nicht beobachtbar -- was die Einstiegs- und
    # Ausstiegspreise unten ehrlich abbilden.
    spanned = int(((frame["ts"] >= opened_ts) & (frame["ts"] <= closed_ts)).sum())
    if spanned == 0:
        return PostMortem(
            bars_held=0,
            max_favourable_r=0.0,
            max_adverse_r=0.0,
            closest_to_target_r=0.0,
            stopped_by_wick=False,
            never_in_profit=True,
            verdict="keine Kursdaten zwischen Ein- und Ausstieg",
        )

    bars = _window(frame, opened_ts, closed_ts)
    long = side is Side.LONG

    # Entry and exit are observations too, and for a trade without an interior
    # bar they are the only ones. Folding them in means the excursion is always
    # bounded by something the position really saw, never by a bar it only
    # overlapped.
    highs = np.append(bars["high"].to_numpy(dtype="float64"), [entry, exit_price])
    lows = np.append(bars["low"].to_numpy(dtype="float64"), [entry, exit_price])
    closes = (
        bars["close"].to_numpy(dtype="float64")
        if not bars.empty
        else np.array([exit_price], dtype="float64")
    )

    # Favourable and adverse are the same two extremes read from opposite ends,
    # which is why the sign flips rather than the arithmetic.
    best = float(np.max(highs)) if long else float(np.min(lows))
    worst = float(np.min(lows)) if long else float(np.max(highs))
    favourable = (best - entry) / risk if long else (entry - best) / risk
    adverse = (entry - worst) / risk if long else (worst - entry) / risk

    wick = False
    if exit_reason is ExitReason.STOP:
        # The stop was reached by a low or high, and the last bar still closed
        # on the side the trade wanted. A charge people argue with, counted
        # instead of remembered.
        touched = lows <= stop if long else highs >= stop
        closed_right = closes[-1] > stop if long else closes[-1] < stop
        wick = bool(touched.any() and closed_right)

    return PostMortem(
        # Die Spanne, nicht die Zahl der benutzten Beobachtungen. `bars` enthaelt
        # nur die vollstaendig inneren Kerzen; gelebt hat der Trade auch in den
        # beiden Randkerzen, und `bars_held` ist eine Dauer.
        bars_held=spanned,
        max_favourable_r=round(favourable, 3),
        max_adverse_r=round(adverse, 3),
        closest_to_target_r=round(max(favourable, 0.0), 3),
        stopped_by_wick=wick,
        never_in_profit=favourable < FLAT_R,
        verdict=_verdict(
            exit_reason=exit_reason,
            r_multiple=r_multiple,
            favourable=favourable,
            adverse=adverse,
            bars=len(bars),
            wick=wick,
        ),
    )


def _verdict(
    *,
    exit_reason: ExitReason,
    r_multiple: float,
    favourable: float,
    adverse: float,
    bars: int,
    wick: bool,
) -> str:
    """One sentence, derived. Never a judgement, only what the bars show."""
    held = f"{bars} Kerzen"
    if exit_reason is ExitReason.STOP:
        return _stop_verdict(held=held, favourable=favourable, wick=wick)
    phrases = {
        ExitReason.TARGET: (
            f"Ziel erreicht nach {held}, zwischenzeitlich {adverse:.2f} R gegen uns."
        ),
        ExitReason.LIQUIDATION: f"Liquidiert nach {held} — der Hebel war vor dem Stop am Ende.",
        ExitReason.INVALIDATION: (
            f"Bedingung entfallen, geschlossen nach {held} bei {r_multiple:+.2f} R."
        ),
    }
    return phrases.get(
        exit_reason, f"Am Ende des Laufs geschlossen nach {held} bei {r_multiple:+.2f} R."
    )


def _stop_verdict(*, held: str, favourable: float, wick: bool) -> str:
    """The three ways a stop happens, which call for three different reactions.

    A wick is a question about where the stop sat. Never being in profit is a
    question about the entry. Giving back a gain is a question about the exit.
    One sentence for each, because "ausgestoppt" answers none of them.
    """
    if wick:
        return (
            f"Stop von einem Docht geholt ({held}); die Kerze schloss wieder "
            f"auf der richtigen Seite. Vorher {favourable:.2f} R im Plus."
        )
    if favourable < FLAT_R:
        return f"Sofort gegen uns, nie im Plus, Stop nach {held}."
    return f"Erst {favourable:.2f} R im Plus, dann gedreht und ausgestoppt ({held})."
