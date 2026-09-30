"""What the chart shows, decided here rather than in the browser.

The temptation is to send raw bars and let the front end work out what matters.
That puts judgement in JavaScript, where it cannot be tested and will drift from
the judgement the trade was actually made on. So this module answers the question
"what was this decision looking at" in Python, and the browser only draws.

Three rules shape it:

**Only bars up to the decision.** A chart that runs past the bar the decision was
made on shows the reader the answer. Even a few candles of hindsight change what
a setup looks like, and the whole point of this screen is to let someone judge the
argument on the evidence that existed when it was made.

**Levels come from the proposal, not from today's analysis.** They were captured
at the decision. Re-deriving them would draw a current reading over a past trade,
which is a different claim wearing the same chart.

**Crowded levels are thinned, not dropped silently.** Forty horizontal lines is
not more information than eight; it is less. What is removed is counted and said
so, rather than quietly disappearing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd
from pydantic import BaseModel, Field

from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import LevelKind, Side, Timeframe
from traidingbrain.domain.proposal import LevelMark, TradeProposal
from traidingbrain.domain.snapshot import Level

#: Bars of context. Enough to see the structure the decision rests on, few enough
#: that a candle is still wide enough to read on a laptop.
CONTEXT_BARS = 180

#: At most this many level lines. Past it the chart stops being readable, and an
#: unreadable chart is worse than a sparse one because it looks informative.
MAX_LEVELS = 10

#: Levels closer together than this (in ATR) are treated as one. Two lines a
#: tenth of an ATR apart are the same level drawn twice.
MERGE_WITHIN_ATR = 0.25

#: Levels further from price than this are off the useful part of the chart.
MAX_DISTANCE_ATR = 8.0

#: Drawing priority when the budget is tight. What the trade is anchored to
#: outranks context, and swept liquidity outranks an untouched swing.
_PRIORITY: dict[LevelKind, int] = {
    LevelKind.EQUAL_HIGHS: 0,
    LevelKind.EQUAL_LOWS: 0,
    LevelKind.SWING_HIGH: 1,
    LevelKind.SWING_LOW: 1,
    LevelKind.FVG_HIGH: 2,
    LevelKind.FVG_LOW: 2,
    LevelKind.PREV_DAY_HIGH: 3,
    LevelKind.PREV_DAY_LOW: 3,
    LevelKind.PREV_WEEK_HIGH: 3,
    LevelKind.PREV_WEEK_LOW: 3,
    LevelKind.RANGE_HIGH: 4,
    LevelKind.RANGE_LOW: 4,
    LevelKind.FVG_MID: 5,
    LevelKind.CURRENT: 9,
}


class Candle(BaseModel):
    """One bar, named rather than positional.

    Full names over one-letter keys: 180 candles make the difference negligible
    over the wire, and a front end that reads `candle.high` cannot transpose two
    fields the way one reading `candle[2]` can.
    """

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class LevelLine(BaseModel):
    """A horizontal line with enough about it to label."""

    id: str
    kind: str
    label: str
    price: float
    timeframe: str
    age_bars: int
    touches: int
    distance_atr: float


class PlanLine(BaseModel):
    """Entry, stop, target and liquidation -- the four that decide the money."""

    role: str
    price: float
    label: str
    detail: str


class EventLine(BaseModel):
    """A structural event placed on the time axis.

    `bar_index` is an index into this chart's own candles, resolved here rather
    than in the browser. The conversion from "eighteen H4 bars ago" to "this
    hourly candle" is arithmetic with a boundary in it, and the boundary is
    easier to get wrong than to get right.
    """

    kind: str
    label: str
    timeframe: str
    bar_index: int
    bars_ago: int


class ChartView(BaseModel):
    """Everything one screen needs, and nothing it would have to compute."""

    symbol: str
    timeframe: str
    available_timeframes: list[str] = Field(default_factory=list)
    bar_ms: int
    decision_ts: int
    price: float
    atr: float
    side: str
    candles: list[Candle]
    levels: list[LevelLine]
    plan: list[PlanLine]
    events: list[EventLine] = Field(default_factory=list)
    levels_hidden: int = 0
    note: str = ""


#: A snapshot's `Level` and a proposal's `LevelMark` carry the same seven fields,
#: for the same reason: the second is captured from the first. Spelled as a union
#: of the two rather than a protocol, because a protocol with mutable attributes
#: is invariant and would reject both -- and naming the two real types says more
#: than a structural shape would.
LevelLike = Level | LevelMark


@dataclass(frozen=True)
class _Scored:
    price: float
    priority: int
    payload: LevelLine


def _label(kind: LevelKind) -> str:
    return kind.value.replace("_", " ")


def build_chart(
    proposal: TradeProposal,
    frame: pd.DataFrame,
    *,
    context_bars: int = CONTEXT_BARS,
    timeframe: Timeframe | None = None,
    available: list[Timeframe] | None = None,
) -> ChartView:
    """Assemble the chart for one proposal on one timeframe.

    `frame` is that timeframe's bars for this symbol. It is trimmed to end at the
    decision, so passing a frame that runs to the present is safe and is in fact
    the normal case.

    The timeframe is a parameter because the decision was made across all of
    them. A setup that reads well on the hour and sits under a weekly supply
    level is a different trade from one that does not, and that is exactly what
    someone reviewing it needs to be able to check.
    """
    timeframe = timeframe or proposal.signal_timeframe or Timeframe.H1
    bar_ms = timeframe_ms(timeframe)

    visible = frame.loc[frame["ts"] <= proposal.snapshot_ts].tail(context_bars)
    # Column arrays rather than row tuples: pandas types a row as a union of every
    # dtype in the frame, so every field would need a cast that proves nothing.
    ts = visible["ts"].to_numpy(dtype="int64")
    opens = visible["open"].to_numpy(dtype="float64")
    highs = visible["high"].to_numpy(dtype="float64")
    lows = visible["low"].to_numpy(dtype="float64")
    closes = visible["close"].to_numpy(dtype="float64")
    volumes = visible["volume"].to_numpy(dtype="float64")
    candles = [
        Candle(
            ts=int(ts[i]),
            open=float(opens[i]),
            high=float(highs[i]),
            low=float(lows[i]),
            close=float(closes[i]),
            volume=float(volumes[i]),
        )
        for i in range(len(ts))
    ]

    atr = proposal.atr_at_build or abs(proposal.entry - proposal.stop)
    levels, hidden = choose_levels(proposal.levels, atr)

    return ChartView(
        symbol=proposal.symbol,
        timeframe=timeframe.value,
        available_timeframes=[tf.value for tf in (available or [timeframe])],
        bar_ms=bar_ms,
        decision_ts=proposal.snapshot_ts,
        price=proposal.price_at_build or proposal.entry,
        atr=atr,
        side=proposal.side.value,
        candles=candles,
        levels=levels,
        plan=_plan_lines(proposal),
        events=_event_lines(proposal, timeframe, bar_ms, len(candles)),
        levels_hidden=hidden,
        note=(
            "Bars stop at the decision. Anything after it would be showing you the answer."
        ),
    )


def _event_lines(
    proposal: TradeProposal, timeframe: Timeframe, bar_ms: int, candle_count: int
) -> list[EventLine]:
    """Place each recorded event on this chart's own time axis.

    An event confirmed on a higher timeframe still belongs on a lower-timeframe
    chart -- that is most of the value, since a daily break of structure is the
    reason an hourly setup is being taken at all. Its distance is converted
    through real durations rather than bar counts, because the two only agree
    when the chart happens to be on the timeframe the event came from.

    Events older than the visible window are dropped rather than clamped to the
    left edge, where they would claim to have happened at a moment they did not.
    """
    lines: list[EventLine] = []
    for event in proposal.events:
        age_ms = event.bars_ago * timeframe_ms(event.timeframe)
        bars_back = round(age_ms / bar_ms)
        index = candle_count - 1 - bars_back
        if index < 0 or index >= candle_count:
            continue
        lines.append(
            EventLine(
                kind=event.kind,
                label=f"{event.label} ({event.timeframe.value})",
                timeframe=event.timeframe.value,
                bar_index=index,
                bars_ago=event.bars_ago,
            )
        )
    # Nearest the decision last, so a later mark draws over an earlier one rather
    # than under it: recent events are the ones being argued from.
    return sorted(lines, key=lambda line: line.bar_index)


def _plan_lines(proposal: TradeProposal) -> list[PlanLine]:
    """The four prices that decide what happens, each with its consequence.

    The consequence is the point. "Stop 85,468" is a number; "stop 85,468, you
    lose 100" is a decision, and the second is what someone is actually agreeing
    to when they hold the confirm button.
    """
    risk = proposal.risk_amount
    reward = risk * proposal.reward_risk
    direction = 1.0 if proposal.side is Side.LONG else -1.0
    return [
        PlanLine(
            role="entry",
            price=proposal.entry,
            label="Entry",
            detail=f"{proposal.qty:g} at {proposal.leverage:g}x, {proposal.notional:,.0f} notional",
        ),
        PlanLine(
            role="stop",
            price=proposal.stop,
            label="Stop",
            detail=(
                f"-{risk:,.0f} "
                f"({abs(proposal.entry - proposal.stop) / proposal.entry * 100:.2f}% away)"
            ),
        ),
        PlanLine(
            role="target",
            price=proposal.target,
            label="Target",
            detail=f"+{reward:,.0f} at {proposal.reward_risk:.2f}R",
        ),
        PlanLine(
            role="liquidation",
            price=proposal.liquidation_price,
            label="Liquidation",
            detail=(
                f"{proposal.liquidation_buffer_r:.1f} stop-distances beyond the stop; "
                f"{'below' if direction > 0 else 'above'} it by design"
            ),
        ),
    ]


def choose_levels(levels: Sequence[LevelLike], atr: float) -> tuple[list[LevelLine], int]:
    """Pick the lines worth drawing, and count what was left out.

    Takes anything level-shaped rather than a proposal, because the market view
    draws the same lines from a live snapshot and there is no reason for two
    implementations of "which ten of these forty are worth the screen".

    Three passes, in this order: drop what is off-chart, merge what is
    duplicated, then keep the most informative of what remains. Merging before
    ranking matters -- otherwise a cluster of four near-identical swing highs
    consumes half the budget and the chart loses everything else.
    """
    candidates: list[_Scored] = []
    for mark in levels:
        if mark.kind is LevelKind.CURRENT:
            continue
        if abs(mark.distance_atr) > MAX_DISTANCE_ATR:
            continue
        candidates.append(
            _Scored(
                price=mark.price,
                priority=_PRIORITY.get(mark.kind, 6),
                payload=LevelLine(
                    id=mark.id,
                    kind=mark.kind.value,
                    label=_label(mark.kind),
                    price=mark.price,
                    timeframe=mark.timeframe.value,
                    age_bars=mark.age_bars,
                    touches=mark.touches,
                    distance_atr=mark.distance_atr,
                ),
            )
        )

    considered = len(candidates)
    merged = _merge_near(candidates, atr)
    merged.sort(
        key=lambda item: (
            item.priority,
            -item.payload.touches,
            abs(item.payload.distance_atr),
        )
    )
    kept = merged[:MAX_LEVELS]
    kept.sort(key=lambda item: -item.price)
    return [item.payload for item in kept], considered - len(kept)


def _merge_near(candidates: list[_Scored], atr: float) -> list[_Scored]:
    """Collapse levels that sit on top of each other, keeping the better one.

    Better means higher priority, and on a tie the one with more touches -- a
    level price has returned to five times is a level, and one it grazed once is a
    coincidence.
    """
    if atr <= 0:
        return list(candidates)
    tolerance = atr * MERGE_WITHIN_ATR
    ordered = sorted(candidates, key=lambda item: item.price)

    survivors: list[_Scored] = []
    for item in ordered:
        if survivors and abs(item.price - survivors[-1].price) <= tolerance:
            incumbent = survivors[-1]
            better = min(
                (incumbent, item),
                key=lambda candidate: (candidate.priority, -candidate.payload.touches),
            )
            survivors[-1] = better
            continue
        survivors.append(item)
    return survivors
