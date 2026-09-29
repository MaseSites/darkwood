"""Similarity search over past setups, with a time bound that is not optional.

This is the module where a leak is most tempting and most damaging, because a
leaking similarity index does not look wrong -- it looks brilliant. It reports
that similar setups won 68% of the time, confidence rises, position sizes rise,
and none of it survives contact with a market that has not happened yet.

Two bounds, and both are needed.

**Purging.** A neighbour is only admissible once its own outcome is known. A setup
that formed three hours ago has not resolved yet; including it means using an
outcome that has not happened.

**Embargo.** Stricter, and the one that gets forgotten. A setup whose outcome
window *overlaps* the present bar encodes the present bar. If trades take up to
48 hours to resolve, a neighbour from 12 hours ago had its outcome determined by
the same price action currently being judged -- so it is not evidence about this
setup, it is a partial copy of it.

Search is brute force over numpy. That is a deliberate choice, not a placeholder.
At these sizes it is fast enough, it is exact, it is deterministic, and the time
mask is a boolean array -- whereas with an approximate index the mask becomes
awkward, and awkward is where leaks live.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Growth step for the backing arrays.
_CHUNK = 4096


@dataclass(frozen=True)
class Neighbour:
    distance: float
    outcome_r: float
    ts: int
    symbol: str


@dataclass(frozen=True)
class Case:
    """One resolved setup: what it looked like, and what came of it."""

    fingerprint: np.ndarray
    entry_ts: int
    resolved_ts: int
    outcome_r: float
    symbol: str = ""


class SimilarityIndex:
    """Exact nearest-neighbour search with purging and embargo built in.

    The `as_of_ms` argument on `query` has no default on purpose. Making it
    optional would make it forgettable, and forgetting it is a silent leak rather
    than an error.
    """

    def __init__(self, dimension: int, embargo_ms: int) -> None:
        self.dimension = dimension
        self.embargo_ms = embargo_ms
        self._vectors = np.empty((_CHUNK, dimension), dtype="float64")
        self._resolved = np.empty(_CHUNK, dtype="int64")
        self._entry = np.empty(_CHUNK, dtype="int64")
        self._outcomes = np.empty(_CHUNK, dtype="float64")
        self._symbols: list[str] = []
        self._size = 0

    def __len__(self) -> int:
        return self._size

    def add(self, case: Case) -> None:
        """Record a resolved setup.

        Only resolved ones belong here. An open trade has no outcome, and storing a
        provisional one would be the leak this class exists to prevent.
        """
        if case.fingerprint.shape != (self.dimension,):
            raise ValueError(
                f"fingerprint has {case.fingerprint.shape} features, expected ({self.dimension},)"
            )
        if case.resolved_ts < case.entry_ts:
            raise ValueError("a case cannot resolve before it was entered")

        if self._size == self._vectors.shape[0]:
            self._grow()

        self._vectors[self._size] = case.fingerprint
        self._entry[self._size] = case.entry_ts
        self._resolved[self._size] = case.resolved_ts
        self._outcomes[self._size] = case.outcome_r
        self._symbols.append(case.symbol)
        self._size += 1

    def _grow(self) -> None:
        new_size = self._vectors.shape[0] * 2
        self._vectors = np.resize(self._vectors, (new_size, self.dimension))
        self._entry = np.resize(self._entry, new_size)
        self._resolved = np.resize(self._resolved, new_size)
        self._outcomes = np.resize(self._outcomes, new_size)

    def admissible(self, as_of_ms: int) -> np.ndarray:
        """Boolean mask of the cases that may legitimately be consulted.

        A case qualifies only when its outcome was fully determined before the
        embargo window that precedes the present bar.
        """
        if self._size == 0:
            return np.zeros(0, dtype=bool)
        cutoff = as_of_ms - self.embargo_ms
        return self._resolved[: self._size] <= cutoff

    def query(
        self,
        vector: np.ndarray,
        *,
        k: int,
        as_of_ms: int,
        max_distance: float | None = None,
        exclude_symbol: str | None = None,
    ) -> list[Neighbour]:
        """The k closest admissible cases.

        `exclude_symbol` supports the strictest version of the question: does a
        pattern learned on other instruments say anything about this one? Leaving
        it unset pools every symbol, which is where the statistical power is.
        """
        mask = self.admissible(as_of_ms)
        if not mask.any():
            return []

        if exclude_symbol is not None:
            symbols = np.array(self._symbols[: self._size])
            mask = mask & (symbols != exclude_symbol)
            if not mask.any():
                return []

        indices = np.nonzero(mask)[0]
        deltas = self._vectors[indices] - vector
        distances = np.sqrt(np.einsum("ij,ij->i", deltas, deltas))

        if max_distance is not None:
            keep = distances <= max_distance
            indices = indices[keep]
            distances = distances[keep]
            if indices.size == 0:
                return []

        order = np.argsort(distances, kind="stable")[:k]
        return [
            Neighbour(
                distance=float(distances[position]),
                outcome_r=float(self._outcomes[indices[position]]),
                ts=int(self._entry[indices[position]]),
                symbol=self._symbols[indices[position]],
            )
            for position in order
        ]

    def clear(self) -> None:
        self._size = 0
        self._symbols.clear()

    def snapshot_arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The stored data, for persistence or inspection."""
        return (
            self._vectors[: self._size].copy(),
            self._resolved[: self._size].copy(),
            self._outcomes[: self._size].copy(),
        )
