"""The history engine: one object that looks up the past and learns from the present.

Built walk-forward by construction. A case enters the index only when its trade
closes, and a lookup only sees cases whose outcomes resolved before the embargo
window. There is no separate "training phase" to get wrong, and no way to
accidentally load the whole history before running -- the index starts empty on
every run and fills as the backtest proceeds, which is exactly what a live system
would experience.

That also means early trades are taken with no history at all. That is correct.
The system's first hundred trades genuinely have nothing to learn from, and a
confidence cap and a risk cap are in force for precisely that period.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from traidingbrain.config.settings import HistoryConfig
from traidingbrain.domain.enums import RegimeKind
from traidingbrain.domain.snapshot import HistoryStats, MarketSnapshot
from traidingbrain.history.fingerprint import dimension, fingerprint
from traidingbrain.history.index import Case, SimilarityIndex
from traidingbrain.history.stats import NeighbourhoodQuality, summarise

HOUR_MS = 3_600_000


@dataclass
class PendingCase:
    """A setup whose outcome is not known yet.

    Held aside rather than written to the index. Writing it early -- with a
    provisional or assumed outcome -- is the leak this whole subsystem is built to
    avoid.
    """

    fingerprint: np.ndarray
    entry_ts: int
    symbol: str


class HistoryEngine:
    """Similarity lookups and outcome recording, for one run."""

    def __init__(self, config: HistoryConfig) -> None:
        self.config = config
        self.index = SimilarityIndex(
            dimension=dimension(), embargo_ms=config.embargo_hours * HOUR_MS
        )
        self.lookups = 0
        self.lookups_with_sample = 0
        self._pending: dict[str, PendingCase] = {}

    # -- reading ------------------------------------------------------------ #

    def lookup(
        self, snapshot: MarketSnapshot, *, cross_symbol_only: bool = False
    ) -> tuple[HistoryStats, NeighbourhoodQuality]:
        """What the index knows, as of this bar and no later."""
        self.lookups += 1
        vector = fingerprint(snapshot)
        decision_ts = snapshot.ts

        neighbours = self.index.query(
            vector,
            k=self.config.k_neighbours,
            as_of_ms=decision_ts,
            exclude_symbol=snapshot.symbol if cross_symbol_only else None,
        )
        stats, quality = summarise(
            neighbours,
            min_samples=self.config.min_samples_for_stats,
            regime=_regime_of(snapshot),
        )
        if stats.sample_is_sufficient:
            self.lookups_with_sample += 1
        return stats, quality

    # -- writing ------------------------------------------------------------ #

    def remember(self, key: str, snapshot: MarketSnapshot) -> None:
        """Hold a setup aside until its trade resolves."""
        self._pending[key] = PendingCase(
            fingerprint=fingerprint(snapshot), entry_ts=snapshot.ts, symbol=snapshot.symbol
        )

    def resolve(self, key: str, *, outcome_r: float, resolved_ts: int) -> bool:
        """Commit a held setup to the index now that its outcome is known."""
        pending = self._pending.pop(key, None)
        if pending is None:
            return False
        self.index.add(
            Case(
                fingerprint=pending.fingerprint,
                entry_ts=pending.entry_ts,
                resolved_ts=resolved_ts,
                outcome_r=outcome_r,
                symbol=pending.symbol,
            )
        )
        return True

    def forget(self, key: str) -> None:
        """Drop a setup that never became a trade.

        An entry that expired unfilled has no outcome. Recording it as a zero would
        put a trade that never happened into the evidence.
        """
        self._pending.pop(key, None)

    # -- reporting ---------------------------------------------------------- #

    @property
    def cases(self) -> int:
        return len(self.index)

    @property
    def unresolved(self) -> int:
        return len(self._pending)

    def summary(self) -> str:
        coverage = self.lookups_with_sample / self.lookups if self.lookups else 0.0
        return (
            f"  history         {self.cases:,} resolved cases, "
            f"{self.lookups:,} lookups, {coverage:.0%} with a usable sample"
        )


def _regime_of(snapshot: MarketSnapshot) -> RegimeKind:
    signal = next(
        (view for view in snapshot.frames if view.timeframe is snapshot.signal_timeframe), None
    )
    return signal.regime if signal else RegimeKind.UNKNOWN
