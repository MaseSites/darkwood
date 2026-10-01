"""Structure and liquidity, translated into evidence the score can weigh.

The detectors have existed for a while and draw on the chart. They produced no
`Finding`s, so the two families the weights rank highest -- structure at 1.00,
liquidity at 0.80 -- contributed nothing to the reading. This is the
translation, and it is mostly a matter of being careful about what the sources
actually permit.

Three sentences from `TRADING_ANALYSE_GRUNDLAGEN.md` shape everything here, and
two of them are prohibitions:

**Chapter 8.2, on pools of equal highs and lows:** "Ein Cluster aus mehreren
nahen Extrema ist sichtbarer als ein isolierter Pivot, doch *Sichtbarkeit
garantiert nicht, dass Preis dorthin läuft*." So a pool gets no direction here.
It is drawn on the chart as a level worth seeing, and it is not evidence that
price is going to it. The common reading -- liquidity is a magnet, so equal
highs above argue up -- is exactly the inference that sentence refuses.

**Chapter 8.3, on sweeps:** "Ein Sweep allein ist keine Umkehrbestätigung. In
[P10] wird erst die nachfolgende Strukturänderung als zusätzliche Information
genutzt." So a sweep on its own is weak, and only a sweep followed by a break
the other way counts for much. When it is the pair that is speaking, the sweep
declares its dependence on the break so the two are not counted as two.

**Chapter 8.1, on what a level proves:** "Das Chart zeigt das Level und die
Reaktion, nicht die Identität oder exakte Ordermenge hinter dem Level."
Nothing here is named after who is supposed to have traded.
"""

from __future__ import annotations

from traidingbrain.analysis.fvg_quality import assess_gaps, best_gap
from traidingbrain.analysis.pipeline import FrameAnalysis
from traidingbrain.analysis.structure import COMPARATIVE_LABEL_LENGTH
from traidingbrain.domain.enums import Bias
from traidingbrain.score.findings import Family, Finding

#: Labels that argue up and down, from `structure._classify`.
_BULLISH_LABELS = ("HH", "HL")
_BEARISH_LABELS = ("LH", "LL")

#: The strongest a swing-label sequence may read.
#:
#: Short of one. A run of higher highs and higher lows is the clearest thing
#: structure has to say, and it is still a description of what has happened
#: rather than a claim about what comes next.
TREND_FULL_STRENGTH = 0.85

#: How emphatic a fresh break of structure is, before its age is applied.
BREAK_STRENGTH = 0.75

#: A change of character argues against the trend it ended, which is a larger
#: claim than a break in the direction things were already going.
CHOCH_STRENGTH = 0.85

#: A sweep with nothing after it. Chapter 8.3: not a reversal confirmation.
SWEEP_ALONE_STRENGTH = 0.30

#: A sweep that a structure break then followed -- the pair chapter 8.3 does
#: accept as information.
SWEEP_CONFIRMED_STRENGTH = 0.70

#: How emphatic an unfilled gap is when price is sitting on it.
GAP_STRENGTH = 0.60

#: How far from a gap price may be before the gap stops arguing anything, in
#: ATR. Beyond this it is a level on a chart, not a thing happening now.
GAP_REACH_ATR = 3.0


def _suffix(analysis: FrameAnalysis) -> str:
    return analysis.timeframe.value.lower()


def structure_findings(analysis: FrameAnalysis, index: int) -> list[Finding]:
    """What the swing sequence and the breaks say at this bar."""
    state = analysis.structure.state_at(index)
    tf = _suffix(analysis)
    findings: list[Finding] = []

    if state.trend is not Bias.NEUTRAL:
        wanted = _BULLISH_LABELS if state.trend is Bias.BULLISH else _BEARISH_LABELS
        # The first swing of each kind is labelled `H` or `L` with nothing to
        # compare it against; only the two-letter labels carry a direction.
        comparable = [
            label for label in state.sequence if len(label) == COMPARATIVE_LABEL_LENGTH
        ]
        if comparable:
            # How much of the recent sequence actually agrees. A trend read off
            # labels that are three-for-two is a weaker statement than one read
            # off five-for-none, and the enum alone cannot tell them apart.
            share = sum(1 for label in comparable if label in wanted) / len(comparable)
            findings.append(
                Finding(
                    key=f"structure_trend_{tf}",
                    family=Family.STRUCTURE,
                    direction=state.trend,
                    strength=round(share * TREND_FULL_STRENGTH, 4),
                    timeframe=analysis.timeframe,
                    source="chapter 7",
                    label=f"Struktur {state.sequence_text()}",
                )
            )

    break_key = f"structure_break_{tf}"
    if state.bos and state.bars_since_bos is not None and state.break_direction is not Bias.NEUTRAL:
        findings.append(
            Finding(
                key=break_key,
                family=Family.STRUCTURE,
                direction=state.break_direction,
                strength=BREAK_STRENGTH,
                timeframe=analysis.timeframe,
                source="chapter 7.3",
                label=f"Strukturbruch vor {state.bars_since_bos} Kerzen",
                freshness_bars=state.bars_since_bos,
            )
        )

    if (
        state.choch
        and state.bars_since_choch is not None
        and state.break_direction is not Bias.NEUTRAL
    ):
        # A change of character *is* a break of structure -- the one that went
        # against the prior direction. When both point at the same bar they are
        # one event seen twice, and the dependence says so.
        same_event = state.bars_since_choch == state.bars_since_bos
        findings.append(
            Finding(
                key=f"structure_choch_{tf}",
                family=Family.STRUCTURE,
                direction=state.break_direction,
                strength=CHOCH_STRENGTH,
                timeframe=analysis.timeframe,
                source="chapter 7.4",
                label=f"Charakterwechsel vor {state.bars_since_choch} Kerzen",
                freshness_bars=state.bars_since_choch,
                depends_on=(break_key,) if same_event else (),
            )
        )
    return findings


def liquidity_findings(analysis: FrameAnalysis, index: int) -> list[Finding]:
    """What was swept and what imbalance is still open at this bar.

    Pools of equal highs and lows are deliberately absent. They are levels the
    chart should show -- and chapter 8.2 says plainly that being visible does
    not make price go there, so they are not evidence of a direction.
    """
    state = analysis.liquidity.state_at(index)
    structure = analysis.structure.state_at(index)
    tf = _suffix(analysis)
    findings: list[Finding] = []

    if (state.sweep_up or state.sweep_down) and state.bars_since_sweep is not None:
        # Buy-side liquidity taken above the highs argues down, and sell-side
        # taken below argues up: the level was reached and given back, which is
        # the "Stop-Auslösung plus Ablehnung" reading of chapter 8.3.
        direction = Bias.BEARISH if state.sweep_up else Bias.BULLISH
        confirmed = (
            structure.bars_since_bos is not None
            and structure.bars_since_bos <= state.bars_since_sweep
            and structure.break_direction is direction
        )
        findings.append(
            Finding(
                key=f"liquidity_sweep_{tf}",
                family=Family.LIQUIDITY,
                direction=direction,
                strength=SWEEP_CONFIRMED_STRENGTH if confirmed else SWEEP_ALONE_STRENGTH,
                timeframe=analysis.timeframe,
                source="chapter 8.3",
                label=(
                    "Liquidität geholt und Struktur gebrochen"
                    if confirmed
                    else "Liquidität geholt, noch ohne Strukturbruch"
                ),
                freshness_bars=state.bars_since_sweep,
                # When the break is what makes this count, it is the same
                # information the structure family already reported.
                depends_on=(f"structure_break_{tf}",) if confirmed else (),
            )
        )

    findings.extend(_gap_findings(analysis, index))
    return findings


def _gap_findings(analysis: FrameAnalysis, index: int) -> list[Finding]:
    """The one unfilled gap each way that passes every factor, if any.

    Only gaps that `best_gap` accepts, which is usually none. Returning the
    least bad gap would be the mistake V13's whole list of factors exists to
    prevent, and a score built on near-misses is a score that always has
    something to say.
    """
    assessments = assess_gaps(
        analysis.frame,
        analysis.indicators.atr,
        analysis.structure,
        index,
        gaps=analysis.fair_value_gaps,
    )
    if not assessments:
        return []

    close = analysis.close_at(index)
    unit = analysis.atr_at(index)
    tf = _suffix(analysis)
    findings: list[Finding] = []

    for bullish in (True, False):
        chosen = best_gap(assessments, bullish=bullish)
        if chosen is None:
            continue
        distance = abs(close - chosen.gap.mid) / unit
        if distance > GAP_REACH_ATR:
            continue
        # Nearer is louder, linearly to nothing at the reach. A gap three ATR
        # away is a level; a gap price is standing in is a thing happening.
        fade = 1.0 - distance / GAP_REACH_ATR
        findings.append(
            Finding(
                key=f"fvg_{'bullish' if bullish else 'bearish'}_{tf}",
                family=Family.LIQUIDITY,
                direction=Bias.BULLISH if bullish else Bias.BEARISH,
                strength=round(GAP_STRENGTH * fade, 4),
                timeframe=analysis.timeframe,
                source="V13",
                label=f"Fair Value Gap {'unter' if bullish else 'über'} dem Preis",
                freshness_bars=index - chosen.gap.created_index,
                distance_atr=round(distance, 2),
            )
        )
    return findings


def observations_for(analysis: FrameAnalysis, index: int) -> list[Finding]:
    """Everything the structural detectors have to say at one bar."""
    return [*structure_findings(analysis, index), *liquidity_findings(analysis, index)]
