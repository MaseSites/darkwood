"""One number from 1 to 100, and the four things it is made of.

Severin asked for a single overall rating, always visible: 100 perfect, 1
completely bad. This is it -- and the first decision was what it rates.

**It rates how clear the picture is, never how likely a win.** Direction is
shown beside it: 90 with "abwärts" is a clean short, not a forecast of a rise.
A number that meant "how probable is up" would be a claim nothing in this
system can support, and the whole project refuses it. This one is a description
of the evidence: do the families agree, do they agree emphatically, and was
there much to look at in the first place.

**It is not a probability.** Not a win rate, not an expected value, and nothing
here has been calibrated against outcomes -- the history engine that could do
that is not built. Two bars rating 80 are not two bars that win four times in
five. They are two bars where the evidence pointed the same way without much
arguing back.

**Why it is a product and not an average.** An average lets one strong part
carry a bad reading: emphatic evidence that half the families contradict would
still score respectably. A geometric mean cannot be rescued that way -- every
part has to be decent for the number to be decent, which is what "perfect"
has to mean if the word is to mean anything.

The four parts are deliberately different questions, so that agreeing on three
of them is real agreement rather than the same measurement restated:

* `clarity` -- how emphatic the lean is, in the score's own units.
* `agreement` -- how little of the *weight* argues the other way.
* `consensus` -- how many of the families that spoke agree with the lean.
* `coverage` -- how much of what the system knows how to look at spoke at all.

The last one is why a perfect score is currently unreachable, and that is
intended. Three families -- news, positioning, history -- feed nothing into the
score yet. A 100 while a third of the inventory is silent would be a lie about
how much was looked at.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from traidingbrain.domain.enums import Bias
from traidingbrain.score.engine import Score
from traidingbrain.score.findings import Family

#: The lean at which `clarity` reaches full marks.
#:
#: Measured, not chosen. Over 5,336 bars across BTC, ETH, SOL and XRP the
#: absolute lean came out:
#:
#:     median 1.09   p75 1.71   p90 2.22   p95 2.51   p99 2.94   max 3.31
#:
#: So this is the 95th percentile: full marks on clarity happen on about one
#: bar in twenty. The first draft guessed 0.80, which would have handed full
#: marks to more than half of all bars and made the part decorative -- which
#: is exactly why the number was measured before the scale was fixed.
CLEAR_LEAN = 2.5

#: How much each part counts. Clarity leads because an emphatic reading nobody
#: contradicts is the thing being asked about; coverage trails because it is
#: about the system rather than the market.
WEIGHTS: dict[str, float] = {
    "clarity": 3.0,
    "agreement": 2.0,
    "consensus": 2.0,
    "coverage": 1.0,
}

#: The floor under each part before the logarithm.
#:
#: Without it a single zero part sends the product to zero and the rating to 1
#: whatever else is true. One part at rock bottom should hurt a great deal; it
#: should not erase the other three.
PART_FLOOR = 0.02

#: What the bands are called. Read from the top down; the first band whose
#: threshold the rating clears wins.
#:
#: The thresholds are measured too, and for the same reason the scale is. Over
#: the same 5,336 bars the rating came out:
#:
#:     min 6   p10 24   p30 48   p50 64   p70 76   p90 89   max 96
#:
#: The first draft put "eindeutig" at 80, which called a quarter of all bars
#: unambiguous -- a word that describes one bar in four is not describing
#: anything. These sit near the measured deciles, so "eindeutig" is roughly the
#: top tenth and "Durcheinander" roughly the bottom eighth.
#:
#: They will need re-measuring when the three silent families start feeding the
#: score, because coverage lifts every rating at once. That is a note for
#: whoever does that work, not a reason to avoid thresholds now.
BANDS: tuple[tuple[int, str], ...] = (
    (88, "eindeutig"),
    (74, "deutlich"),
    (50, "gemischt"),
    (30, "unklar"),
    (0, "Durcheinander"),
)


@dataclass(frozen=True)
class Rating:
    """The overall number, with every part that produced it."""

    value: int
    """1 to 100. 100 would mean every family spoke, emphatically, and agreed."""

    band: str
    direction: Bias
    clarity: float
    agreement: float
    consensus: float
    coverage: float

    @property
    def parts(self) -> dict[str, float]:
        return {
            "clarity": self.clarity,
            "agreement": self.agreement,
            "consensus": self.consensus,
            "coverage": self.coverage,
        }

    @property
    def weakest(self) -> str:
        """Which part is holding the rating down.

        The useful half of a low number. "41" says nothing a person can act on;
        "41, because the timeframes disagree" says where to look.
        """
        return min(self.parts, key=lambda name: self.parts[name])


def band_for(value: int) -> str:
    return next(name for threshold, name in BANDS if value >= threshold)


def rate(score: Score) -> Rating:
    """Turn a score into one number from 1 to 100.

    Nothing measured rates 1 rather than 0: the scale Severin asked for starts
    at one, and a bar with no evidence at all is the worst case it describes.
    """
    if not score.families:
        return Rating(
            value=1,
            band=band_for(1),
            direction=Bias.NEUTRAL,
            clarity=0.0,
            agreement=0.0,
            consensus=0.0,
            coverage=0.0,
        )

    speaking = [scored for scored in score.families if not scored.split]
    leading = 1.0 if score.direction is Bias.BULLISH else -1.0
    agreeing = sum(1 for scored in speaking if scored.contribution * leading > 0)
    weighed = score.bullish + score.bearish

    clarity = min(abs(score.lean) / CLEAR_LEAN, 1.0)
    # `Score.conflict` is zero when nothing was weighed, which would read here
    # as "nothing argues the other way" -- true, and the opposite of what it
    # means. A market where every family was measured and none took a side has
    # no agreement to report, not perfect agreement.
    agreement = max(0.0, 1.0 - score.conflict) if weighed > 0 else 0.0
    consensus = agreeing / len(speaking) if speaking else 0.0
    coverage = len(score.families) / len(Family)

    parts = {
        "clarity": clarity,
        "agreement": agreement,
        "consensus": consensus,
        "coverage": coverage,
    }
    combined = _geometric(parts)
    value = max(1, min(100, round(1.0 + 99.0 * combined)))
    return Rating(
        value=value,
        band=band_for(value),
        direction=score.direction,
        clarity=round(clarity, 4),
        agreement=round(agreement, 4),
        consensus=round(consensus, 4),
        coverage=round(coverage, 4),
    )


def _geometric(parts: dict[str, float]) -> float:
    """The weighted geometric mean, floored so one zero does not erase the rest."""
    total = sum(WEIGHTS[name] for name in parts)
    logs = sum(
        WEIGHTS[name] * math.log(max(value, PART_FLOOR)) for name, value in parts.items()
    )
    return float(math.exp(logs / total))
