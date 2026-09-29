"""Turning neighbours into the `history` block of a snapshot.

The output of this module is what unlocks the upper risk tiers, so it is written
to be reluctant. `sample_is_sufficient` is false by default and stays false until
there are genuinely enough non-overlapping cases -- and while it is false, the
confidence is capped and no trade may risk more than the base tier.

Two forms of dishonesty are specifically guarded against.

**Quoting a rate from a handful of cases.** Four similar setups at a 75% win rate
is not a 75% win rate; it is three wins. The threshold is a count, not a
suggestion.

**Counting near-duplicates as independent evidence.** Consecutive bars in the same
market produce nearly identical fingerprints, so twenty "similar cases" can be one
episode seen twenty times. They are de-duplicated by time before anything is
counted.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from traidingbrain.domain.enums import RegimeKind
from traidingbrain.domain.snapshot import HistoryStats
from traidingbrain.history.index import Neighbour

#: Two cases closer together than this are treated as the same episode.
#: Consecutive hourly bars in one move look almost identical, and counting each
#: as separate evidence inflates the sample by an order of magnitude.
MIN_SEPARATION_MS = 12 * 60 * 60 * 1000

#: Neighbours further than this are not neighbours. Without a ceiling, a query in
#: a market state that has genuinely never occurred returns the k least-unlike
#: cases and reports them as similar.
#:
#: Set from measurement rather than intuition, because intuition about distance in
#: 41 dimensions is unreliable. Over 171 well-separated BTCUSDT snapshots the
#: pairwise distances ran: p1 = 2.62, p5 = 3.10, p25 = 3.84, median 4.33. So 3.2
#: means roughly "in the closest 5% of all market states", which is a defensible
#: reading of similar. The first value tried here was 2.5 -- the 0.6th percentile
#: -- and it admitted about two neighbours per query, which is why this is a
#: measured number and not a guess.
#:
#: Note the consequence: at this cutoff a query finds around 4% of the index, so
#: `min_samples_for_stats` of 30 needs roughly 750 resolved cases before any
#: lookup can quote a rate. One symbol over two and a half years produces a few
#: hundred. That is a real limitation and the reason the confidence cap is where
#: it is -- not a reason to lower the threshold until the output looks better.
MAX_DISTANCE = 3.2


@dataclass(frozen=True)
class NeighbourhoodQuality:
    """How much the neighbourhood is actually worth.

    Reported alongside the statistics so that a thin or scattered match can be
    recognised as such rather than read as a weak signal.
    """

    raw: int
    independent: int
    mean_distance: float
    spans_days: float

    @property
    def is_tight(self) -> bool:
        return self.mean_distance <= MAX_DISTANCE / 2


def deduplicate(neighbours: list[Neighbour]) -> list[Neighbour]:
    """Keep one case per episode, preferring the closest match.

    Sorted by distance first so that when two cases collapse into one, the one
    kept is the better match rather than whichever happened to come first.
    """
    kept: list[Neighbour] = []
    for candidate in sorted(neighbours, key=lambda n: n.distance):
        clash = any(
            existing.symbol == candidate.symbol
            and abs(existing.ts - candidate.ts) < MIN_SEPARATION_MS
            for existing in kept
        )
        if not clash:
            kept.append(candidate)
    return kept


def summarise(
    neighbours: list[Neighbour],
    *,
    min_samples: int,
    regime: RegimeKind = RegimeKind.UNKNOWN,
) -> tuple[HistoryStats, NeighbourhoodQuality]:
    """Build the history block, refusing to quote numbers that are not supported."""
    usable = deduplicate([n for n in neighbours if n.distance <= MAX_DISTANCE])
    quality = _quality(neighbours, usable)

    if not usable:
        return (
            HistoryStats(similar_situations_found=0, regime=regime, sample_is_sufficient=False),
            quality,
        )

    outcomes = np.array([n.outcome_r for n in usable], dtype="float64")
    sufficient = len(usable) >= min_samples

    return (
        HistoryStats(
            similar_situations_found=len(usable),
            # A win rate from six cases is three wins. Below the threshold the
            # honest answer is that there is no rate, not a noisy one.
            historical_winrate=float((outcomes > 0).mean()) if sufficient else None,
            mean_r_multiple=float(outcomes.mean()) if sufficient else None,
            regime=regime,
            sample_is_sufficient=sufficient,
        ),
        quality,
    )


def _quality(raw: list[Neighbour], usable: list[Neighbour]) -> NeighbourhoodQuality:
    if not usable:
        return NeighbourhoodQuality(len(raw), 0, float("inf"), 0.0)
    stamps = [n.ts for n in usable]
    return NeighbourhoodQuality(
        raw=len(raw),
        independent=len(usable),
        mean_distance=float(np.mean([n.distance for n in usable])),
        spans_days=(max(stamps) - min(stamps)) / 86_400_000,
    )


def describe(stats: HistoryStats, quality: NeighbourhoodQuality) -> str:
    if stats.similar_situations_found == 0:
        return "no comparable setup in the index yet"
    if not stats.sample_is_sufficient:
        return (
            f"{stats.similar_situations_found} comparable setups -- too few to quote a rate "
            f"(collapsed from {quality.raw} raw matches)"
        )
    return (
        f"{stats.similar_situations_found} comparable setups at "
        f"{stats.historical_winrate:.0%}, mean {stats.mean_r_multiple:+.2f}R, "
        f"spread over {quality.spans_days:.0f} days, mean distance {quality.mean_distance:.2f}"
    )
