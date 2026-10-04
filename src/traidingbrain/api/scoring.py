"""The score, shaped for the screen.

A separate endpoint from the chart on purpose. Building the indicator bank over
five timeframes takes about ten seconds the first time a symbol is opened, and
folding that into the chart request would mean nobody sees anything until all
of it is done -- which is exactly the complaint that got the screen rebuilt.
The chart arrives, then the reading fills in behind it.

Everything here is a view: German labels, rounded numbers, and a sentence per
family saying why it counts for what it counts for. No arithmetic that the
score itself does not already do. The one thing this layer adds is *why a
family is silent*, because "0.0" with no explanation is the single least useful
thing a screen can show.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe
from traidingbrain.score.engine import MIN_AGREEMENT, ScoredFamily
from traidingbrain.score.findings import Family
from traidingbrain.score.rating import Rating, rate
from traidingbrain.score.reading import ScoreReading, score_at

FAMILY_WORDS: dict[Family, str] = {
    Family.TREND: "Trend",
    Family.MOMENTUM: "Momentum",
    Family.VOLATILITY: "Schwankung",
    Family.VOLUME: "Volumen",
    Family.STRUCTURE: "Struktur",
    Family.LOCATION: "Lage",
    Family.LIQUIDITY: "Liquidität",
    Family.TIME_NEWS: "Zeit & Nachrichten",
    Family.POSITIONING: "Positionierung",
    Family.HISTORY: "Historie",
}

TIMEFRAME_WORDS: dict[Timeframe, str] = {
    Timeframe.W1: "Woche",
    Timeframe.D1: "Tag",
    Timeframe.H4: "4 Std",
    Timeframe.H1: "1 Std",
    Timeframe.M15: "15 Min",
    Timeframe.M1: "1 Min",
}

DIRECTION_WORDS: dict[Bias, str] = {
    Bias.BULLISH: "aufwärts",
    Bias.BEARISH: "abwärts",
    Bias.NEUTRAL: "offen",
}

REGIME_WORDS: dict[RegimeKind, str] = {
    RegimeKind.TREND_UP: "Aufwärtstrend",
    RegimeKind.TREND_DOWN: "Abwärtstrend",
    RegimeKind.RANGE: "Seitwärts",
    RegimeKind.MANIPULATION: "Manipulation",
    RegimeKind.UNKNOWN: "unklar",
}

#: What each part of the overall rating is called on screen.
#:
#: Four different questions, so that agreeing on three of them is real
#: agreement rather than one measurement restated four ways.
PART_WORDS: dict[str, str] = {
    "clarity": "Deutlichkeit",
    "agreement": "Einigkeit",
    "consensus": "Mehrheit",
    "coverage": "Abdeckung",
}

#: Above this share of the evidence arguing the other way, the headline says
#: so instead of reporting a lean. Half is the point where the reading stops
#: describing a direction and starts describing a disagreement.
LOUD_CONFLICT = 0.5

#: Indicators whose reading has a size but no side, with what they measure.
#: Shown as context rather than as evidence -- see `Spec.directional`.
CONTEXT_WORDS: dict[str, str] = {
    "adx_14": "Trendstärke",
    "atr_14": "Schwankung",
    "bb_width_20": "Bandbreite",
    "choppiness_14": "Seitwärtsneigung",
    "hist_vol_30": "Vola 30",
    "rvol_20": "rel. Volumen",
}


class PartRead(BaseModel):
    """One of the four things the overall rating is made of."""

    name: str
    label: str
    value: float
    """0 to 1."""

    weakest: bool
    """The part holding the number down. The useful half of a low rating: "41"
    says nothing a person can act on, "41, weakest part Einigkeit" says where
    to look."""


class FrameRead(BaseModel):
    """What one family said on one timeframe."""

    timeframe: str
    label: str
    lean: float
    """Signed, -1 to 1. Positive argues up."""


class FamilyRead(BaseModel):
    """One family's contribution, with the reason it is what it is."""

    family: str
    label: str
    direction: str
    strength: float
    contribution: float
    agreement: float
    timeframe_agreement: float
    members: int
    silent: bool
    reason: str
    frames: list[FrameRead] = Field(default_factory=list)


class ScoreRead(BaseModel):
    """The whole reading, as the panel shows it.

    `bullish` and `bearish` stay apart here as they do everywhere else. A panel
    that showed only the difference would hide the state a person most needs to
    see: a strong reading fighting a strong one, which looks identical to a
    quiet market once you subtract.
    """

    symbol: str
    as_of_ts: int
    rating: int
    """1 to 100: how clear the picture is, never how likely a win.

    Direction is carried separately and deliberately. 90 with "abwärts" is a
    clean short, not a forecast of a rise -- and nothing here is calibrated
    against outcomes, so it is not a probability either."""

    band: str
    parts: list[PartRead] = Field(default_factory=list)
    direction: str
    bullish: float
    bearish: float
    conflict: float
    breadth: int
    readings: int
    regime: str
    headline: str
    families: list[FamilyRead] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


def signal_index_at(analysis: MultiFrameAnalysis, ts: int) -> int | None:
    """The signal bar with this timestamp, or None.

    By timestamp rather than by position, for the same reason `setups_at` does
    it: the snapshot may be a few bars behind the newest stored one, and the
    last index would describe a different bar than the one on screen.
    """
    stamps = analysis.signal.column("ts")
    for index, stamp in enumerate(stamps):
        if int(stamp) == ts:
            return index
    return None


def _why_silent(scored: ScoredFamily) -> str:
    """The sentence that turns a zero into information.

    Three different reasons produce the same contribution of nothing, and they
    call for three different responses: look closer, wait for the frames to
    line up, or accept that this family has no opinion today.
    """
    verdict = scored.verdict
    if verdict.direction is Bias.NEUTRAL:
        return "nimmt keine Seite ein"
    if verdict.timeframe_agreement < MIN_AGREEMENT:
        return "die Zeitebenen widersprechen sich"
    if verdict.agreement < MIN_AGREEMENT:
        return "die Indikatoren widersprechen sich"
    return ""


def _family_read(scored: ScoredFamily) -> FamilyRead:
    verdict = scored.verdict
    return FamilyRead(
        family=verdict.family.value,
        label=FAMILY_WORDS.get(verdict.family, verdict.family.value),
        direction=DIRECTION_WORDS[verdict.direction],
        strength=round(verdict.strength, 3),
        contribution=round(scored.contribution, 3),
        agreement=round(verdict.agreement, 2),
        timeframe_agreement=round(verdict.timeframe_agreement, 2),
        members=len(verdict.members),
        silent=scored.split,
        reason=_why_silent(scored),
        frames=[
            FrameRead(
                timeframe=frame.timeframe.value,
                label=TIMEFRAME_WORDS.get(frame.timeframe, frame.timeframe.value),
                lean=round(frame.signed_strength, 3),
            )
            for frame in verdict.by_timeframe
        ],
    )


def _part_reads(rating: Rating) -> list[PartRead]:
    weakest = rating.weakest
    return [
        PartRead(
            name=name,
            label=PART_WORDS.get(name, name),
            value=round(value, 3),
            weakest=name == weakest,
        )
        for name, value in rating.parts.items()
    ]


def _headline(reading: ScoreReading) -> str:
    """One sentence a person can read without the table underneath.

    Deliberately says what argues, never what will happen. Nothing here is a
    forecast, and a headline that sounded like one would undo every careful
    thing below it.

    It counts the families that agree with the lean, not the families that
    spoke. Those are different numbers and the first draft printed the second:
    four families arguing down and one arguing up came out as "five families
    argue down", which is the opposite of what the table underneath showed.
    """
    score = reading.score
    speaking = [scored for scored in score.families if not scored.split]
    if not speaking:
        return "Keine Familie nimmt eine Seite ein — nichts, worauf man handeln könnte."

    side = DIRECTION_WORDS[score.direction]
    leading = 1.0 if score.direction is Bias.BULLISH else -1.0
    agreeing = sum(1 for scored in speaking if scored.contribution * leading > 0)
    against = len(speaking) - agreeing
    sentence = (
        f"{agreeing} von {len(speaking)} Familien mit Meinung zeigen {side}"
        + (f", {against} dagegen" if against else "")
        + f" ({score.bullish:.2f} dafür / {score.bearish:.2f} dagegen)."
    )
    if score.conflict >= LOUD_CONFLICT:
        # The share of the evidence on the losing side, not `conflict` itself.
        # Conflict is twice that by construction -- a scale that reaches one
        # when the two sides are equal -- and printing it as a share said "76 %
        # of the evidence is against" about a market where 38 % was.
        total = score.bullish + score.bearish
        losing = min(score.bullish, score.bearish) / total if total else 0.0
        return f"{sentence} Stark umstritten — {losing:.0%} der Belege stehen dagegen."
    return sentence


def _context_lines(reading: ScoreReading) -> list[str]:
    """The readings with a size but no side, from the signal timeframe.

    Kept on the screen even though they get no vote. How violent and how choppy
    change what a side is worth, and dropping them at the point where they stop
    being evidence would hide the thing that explains a quiet score.
    """
    for timeframe in (Timeframe.H1, Timeframe.H4, Timeframe.D1):
        values = reading.context.get(timeframe)
        if not values:
            continue
        return [
            f"{CONTEXT_WORDS.get(name, name)} {value:.4g}"
            for name, value in sorted(values.items())
            if name in CONTEXT_WORDS
        ]
    return []


def build_score_view(symbol: str, analysis: MultiFrameAnalysis, ts: int) -> ScoreRead | None:
    """The score at the bar the chart is drawn for, or None if it is not ready."""
    index = signal_index_at(analysis, ts)
    if index is None:
        return None
    reading = score_at(analysis, index)
    if reading is None:
        return None

    score = reading.score
    rating = rate(score)
    return ScoreRead(
        symbol=symbol,
        as_of_ts=ts,
        rating=rating.value,
        band=rating.band,
        parts=_part_reads(rating),
        direction=DIRECTION_WORDS[score.direction],
        bullish=round(score.bullish, 3),
        bearish=round(score.bearish, 3),
        conflict=round(score.conflict, 3),
        breadth=score.breadth,
        readings=reading.indicator_count,
        regime=REGIME_WORDS.get(reading.regime, reading.regime.value),
        headline=_headline(reading),
        families=[
            _family_read(scored)
            for scored in sorted(score.families, key=lambda s: -abs(s.contribution))
        ],
        context=_context_lines(reading),
        missing=[FAMILY_WORDS.get(family, family.value) for family in score.missing_families],
    )
