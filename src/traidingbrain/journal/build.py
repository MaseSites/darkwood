"""Joining what happened to why it was done.

The simulator produces fills; it knows nothing about the score. Recomputing the
reasoning afterwards, for the hundred bars that actually produced a trade, is
what keeps the two apart -- scoring all twenty thousand bars inside the
execution loop would make every backtest ten times slower for a number only a
journal reads.

That is only safe because the score is a pure function of the bars up to its
own index. `test_bank.py` proves it does not read ahead, so asking it after the
fact gives the same answer it would have given at the time. If that stopped
being true this module would silently start writing hindsight into the record,
which is why the property has its own test rather than being a comment.
"""

from __future__ import annotations

import numpy as np

from traidingbrain.analysis.pipeline import MultiFrameAnalysis, decision_time_ms
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.journal.postmortem import examine
from traidingbrain.journal.record import (
    FamilyNote,
    JournalEntry,
    Source,
    TradeReason,
)
from traidingbrain.score.rating import rate
from traidingbrain.score.reading import score_at
from traidingbrain.sim.broker import Fill
from traidingbrain.strategies.guide import SEARCH_ORDER, _just_closed
from traidingbrain.strategy.setups import SetupSignal, evaluate_all

#: What the setup fields say when no setup can be matched to a fill.
#:
#: Possible rather than hypothetical: a pooled strategy submits one order and
#: several setups may have fired, and the brain path produces trades with no
#: setup at all. Saying so is better than attributing the trade to whichever
#: one happened to be first in the list.
UNKNOWN_SETUP = "—"


def decision_index(multi: MultiFrameAnalysis, proposal_id: str, signal: Timeframe) -> int | None:
    """Which signal bar a proposal was decided on.

    The id is `{symbol}-{created_ts}` and `created_ts` is the decision bar's
    close, so the bar is recoverable without the engine recording anything. A
    test pins that relationship: if the id format changes, this returns None
    for every trade and the journal silently loses its reasoning.
    """
    _, _, tail = proposal_id.rpartition("-")
    if not tail.isdigit():
        return None
    # The tail is the decision bar's CLOSE. On time bars the open follows by
    # subtraction; on takt bars (E24) the close is a stored column and the
    # bar is found by it directly.
    frame = getattr(multi.signal, "frame", None)
    if frame is not None and "close_ts" in frame.columns:
        found = np.nonzero(multi.signal.close_times() == int(tail))[0]
        return int(found[0]) if found.size else None
    opened = int(tail) - timeframe_ms(signal)
    stamps = multi.signal.column("ts")
    found = np.nonzero(stamps == opened)[0]
    return int(found[0]) if found.size else None


def _setup_for(analysis: MultiFrameAnalysis, index: int, side: Side) -> SetupSignal | None:
    """The setup that fired for this trade, on whichever chart it came from.

    Searched across the frames in the pool's own order, because a trade may
    have been found on any of them. Looking only at the signal frame left 40%
    of the journal with no setup attributed once the search went
    multi-timeframe -- the trades were fine, the record of why was not.

    **Nur freigegebene Setups, und das war bis zum 14.10.2026 falsch.**
    `evaluate_all` laeuft ueber `TRADEABLE`, also auch ueber die Setups, die
    die Konfiguration abgeschaltet hat; `GuidePool.propose_at` laeuft nur ueber
    die freigegebenen. C steht an Stelle 2 von sechs, vor E, F und G -- ein
    Trade, den E, F oder G erzeugt hat, bekam deshalb das Etikett "C",
    sobald C auf demselben Balken mitfeuerte.

    Gemessen in `data/replay_fills/` (7.335 Trades, zwoelf Maerkte, gerechnet
    unter `enabled: [A, B, E, F, G]`): **204 Trades tragen `setup_key = "C"`**,
    also 2.8 % der Population, und C war zur Laufzeit aus. Jede Zahl je Setup
    fuer E, F und G ist damit zu klein und in ihrer Zusammensetzung falsch --
    E hat 168 Zeilen, F hat 25.

    Der Absatz unten sagte selbst, anders zu raten „would attribute the trade
    to a setup the engine did not act on". Genau das geschah, nur nicht durch
    Raten, sondern durch eine Liste, die eine Ebene zu breit war.
    """
    aligned = analysis.aligned_indices(index)
    if aligned is None:
        return None
    allowed = set(analysis.config.setups.enabled)
    decision = decision_time_ms(analysis.signal.ts_at(index), analysis.signal_timeframe)
    for timeframe in SEARCH_ORDER:
        frame = analysis.analyses.get(timeframe)
        at = aligned.get(timeframe)
        if frame is None or at is None or not _just_closed(analysis, timeframe, decision):
            continue
        matching = [
            s for s in evaluate_all(frame, at)
            if s.side is side and s.setup in allowed
        ]
        if matching:
            # More than one may have fired. The pool takes the first in
            # TRADEABLE order and so does this -- `evaluate_all` preserves that
            # order, and picking differently would name a setup the engine
            # passed over.
            return matching[0]
    return None


def reason_at(multi: MultiFrameAnalysis, index: int, side: Side) -> TradeReason | None:
    """The whole case for a trade, as it stood on its decision bar."""
    reading = score_at(multi, index)
    if reading is None:
        return None
    rating = rate(reading.score)
    setup = _setup_for(multi, index, side)
    close = multi.signal.close_at(index)

    entry = setup.entry if setup else close
    stop = setup.stop if setup else close
    target = setup.target if setup else close
    risk = abs(entry - stop)
    return TradeReason(
        setup_key=setup.setup if setup else UNKNOWN_SETUP,
        setup_name=setup.name if setup else UNKNOWN_SETUP,
        setup_source=setup.source if setup else UNKNOWN_SETUP,
        setup_timeframe=setup.timeframe.value if setup else UNKNOWN_SETUP,
        signal_timeframe=multi.signal_timeframe.value,
        side=str(side),
        entry=entry,
        stop=stop,
        target=target,
        reward_risk=round(abs(target - entry) / risk, 3) if risk else 0.0,
        stop_distance_pct=round(100.0 * risk / entry, 4) if entry else 0.0,
        rating=rating.value,
        rating_band=rating.band,
        clarity=rating.clarity,
        agreement=rating.agreement,
        consensus=rating.consensus,
        coverage=rating.coverage,
        score_bullish=reading.score.bullish,
        score_bearish=reading.score.bearish,
        score_direction=_direction_word(reading.score.direction.value),
        conflict=reading.score.conflict,
        breadth=reading.score.breadth,
        readings=reading.indicator_count,
        regime=reading.regime.value,
        families=[
            FamilyNote(
                family=scored.verdict.family.value,
                direction=scored.verdict.direction.value,
                contribution=round(scored.contribution, 4),
                agreement=scored.verdict.agreement,
                timeframe_agreement=scored.verdict.timeframe_agreement,
                silent=scored.split,
            )
            for scored in reading.score.families
        ],
    )


def _direction_word(value: str) -> str:
    return {"bullish": "aufwärts", "bearish": "abwärts"}.get(value, "offen")


def entries_from(
    multi: MultiFrameAnalysis,
    fills: list[Fill],
    *,
    symbol: str,
    strategy: str,
    source: Source,
    signal: Timeframe,
) -> list[JournalEntry]:
    """Build the journal for one run.

    A fill whose decision bar cannot be found, or whose score will not build,
    is skipped rather than written without its reasoning. A journal row that
    says only "lost 1 R" is the thing this whole module exists to avoid.
    """
    frame = multi.signal.frame
    out: list[JournalEntry] = []
    for fill in fills:
        index = decision_index(multi, fill.proposal_id, signal)
        if index is None:
            continue
        reason = reason_at(multi, index, fill.side)
        if reason is None:
            continue
        out.append(
            JournalEntry(
                trade_id=fill.proposal_id,
                source=source,
                symbol=symbol,
                strategy=strategy,
                opened_ts=fill.opened_ts,
                closed_ts=fill.closed_ts,
                exit_reason=fill.reason,
                entry_price=fill.entry_price,
                exit_price=fill.exit_price,
                qty=fill.qty,
                leverage=fill.leverage,
                risk_amount=fill.risk_amount,
                gross_pnl=round(fill.gross_pnl, 4),
                fees=round(fill.fees, 4),
                funding=round(fill.funding, 4),
                net_pnl=round(fill.net_pnl, 4),
                r_multiple=round(fill.r_multiple, 4),
                reason=reason,
                post_mortem=examine(
                    frame,
                    side=fill.side,
                    entry=fill.entry_price,
                    stop=reason.stop,
                    opened_ts=fill.opened_ts,
                    closed_ts=fill.closed_ts,
                    exit_price=fill.exit_price,
                    exit_reason=fill.reason,
                    r_multiple=fill.r_multiple,
                ),
            )
        )
    return out
