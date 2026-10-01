"""From the analysed frames to one score, across every timeframe at once.

This is the join. `analysis` produces the numbers, `registry` says what each
indicator reading is worth, `observations` turns the structural detectors into
evidence, `engine` reconciles them -- and this walks the aligned timeframes,
collects the findings, and asks for the score.

Two decisions live here, and both are about the multi-timeframe part.

**Every timeframe contributes, and the timeframe is in the key.** The hourly
RSI and the daily RSI are two findings in one family, not one finding read
twice, because they are measurements of different things. The family machinery
then does what it always does: five RSIs agreeing across five frames is still
one momentum verdict, with high agreement.

**The regime comes from the signal timeframe.** Chapter 12.2's rule -- a
momentum extreme means something different inside a trend -- has to be answered
somewhere, and the frame the decision is taken on is the honest place. Taking it
from the weekly would tell the hourly oscillators they are inside a trend that
has not been visible for days.

What this deliberately does **not** do is decide anything. It describes a
situation: two numbers, which families spoke, how much they disagree. The gate,
the sizing and the confirm button are untouched and stay where they are.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from traidingbrain.analysis.pipeline import FrameAnalysis, MultiFrameAnalysis
from traidingbrain.domain.enums import RegimeKind, Timeframe
from traidingbrain.score.engine import Score, compute
from traidingbrain.score.findings import Evidence, Finding
from traidingbrain.score.observations import observations_for
from traidingbrain.score.registry import context_at, read_all


def findings_for(analysis: FrameAnalysis, index: int) -> list[Finding]:
    """What the indicators say on one frame at one bar."""
    return read_all(analysis.bank(), index, analysis.timeframe)


def context_for(analysis: FrameAnalysis, index: int) -> dict[str, float]:
    """The readings with a size but no side: how violent, wide, choppy, busy."""
    return context_at(analysis.bank(), index)


@dataclass
class ScoreReading:
    """One score, with enough beside it to argue about."""

    score: Score
    regime: RegimeKind
    evidence: Evidence
    context: dict[Timeframe, dict[str, float]] = field(default_factory=dict)
    indices: dict[Timeframe, int] = field(default_factory=dict)

    @property
    def indicator_count(self) -> int:
        """How many readings went in. Not how many opinions came out.

        Worth reporting next to `score.breadth`, because the gap between them
        is the whole argument of chapter 12.6: forty readings can still be
        three pieces of information.
        """
        return len(self.evidence.findings)


def evidence_at(
    multi: MultiFrameAnalysis, indices: dict[Timeframe, int]
) -> tuple[Evidence, dict[Timeframe, dict[str, float]]]:
    """Collect every timeframe's findings into one body of evidence.

    Timeframes are walked in a fixed order so that the result does not depend
    on dictionary insertion -- a score that changed when the config listed its
    frames differently would be very hard to believe later.
    """
    evidence = Evidence()
    context: dict[Timeframe, dict[str, float]] = {}
    for timeframe in Timeframe:
        index = indices.get(timeframe)
        analysis = multi.analyses.get(timeframe)
        if index is None or analysis is None:
            continue
        for finding in findings_for(analysis, index):
            evidence.add(finding)
        for finding in observations_for(analysis, index):
            evidence.add(finding)
        context[timeframe] = context_for(analysis, index)
    return evidence, context


def score_at(multi: MultiFrameAnalysis, signal_index: int) -> ScoreReading | None:
    """The score at one signal bar, or None while any frame is still warming.

    None rather than a partial reading, for the reason `aligned_indices` gives:
    a snapshot missing its weekly frame looks complete and quietly reports the
    weekly as neutral when the truth is that it is unknown.
    """
    indices = multi.aligned_indices(signal_index)
    if indices is None:
        return None

    regime = multi.signal.regime.state_at(signal_index).kind
    evidence, context = evidence_at(multi, indices)
    return ScoreReading(
        score=compute(evidence, regime=regime),
        regime=regime,
        evidence=evidence,
        context=context,
        indices=indices,
    )
