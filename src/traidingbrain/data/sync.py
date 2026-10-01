"""Emptying the collector's landing zone forward into the archive.

The Pi collects while the laptop is off and writes into Postgres. The dashboard
and the backtest read Parquet. Between the two there was nothing, which is the
last real gap in the pipeline: the collector has been gathering into a table
nobody drains.

**Two stores, one direction.** Postgres is the landing zone -- what has been
gathered and not yet filed. Parquet is the archive, and it is what every reader
treats as true. This moves rows one way only. A sync that could also write back
would make "which one is right" a question, and the schema comment in
`0002_market_data.sql` exists precisely so that it is not one.

**It re-reads an overlapping window, like the collector does.** Not "since my
marker": a marker is a claim about a previous run, and a crash makes it false.
It asks Parquet what it actually holds, steps back from there, and lets the
Parquet writers merge. They deduplicate on the key, so overlap costs a rewrite
and a gap costs a hole that surfaces months later in a backtest.

**Deleting is opt-in and verified.** The landing zone does want emptying -- it
grows forever otherwise -- but the safe half of this job is the default. With
`prune`, rows are removed only after the write succeeded *and* the archive has
been re-read and confirms it holds them. Nothing is deleted on the strength of
having sent it.

**Open interest and the long/short ratio are not here.** Their tables exist in
the schema, and nothing writes them: `scripts/collect.py` says so in its own
docstring, because their fetcher cannot be imported on the Pi. A drain for a
table with no producer is code with no caller, and it would be the kind that
looks tested because it never runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from traidingbrain.data.frames import timeframe_ms
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import FundingRate

#: How far back to re-read beyond what the archive already holds.
#:
#: Ten bars, matching the collector's own overlap. The newest row in the archive
#: is the one most likely to have been written from a partial fetch or revised
#: by the venue afterwards, and the one before it is the one most likely to be
#: missing after a run that died mid-write.
OVERLAP_BARS = 10

#: The same idea for funding, which settles every eight hours.
OVERLAP_FUNDING_MS = 24 * 60 * 60 * 1000


class LandingZone(Protocol):
    """What the sync needs from the collector's database, and nothing more.

    A protocol rather than a direct dependency on psycopg so that the part with
    the decisions in it can be tested without a database. The decisions are the
    part that can be wrong in a way nobody notices: which window to re-read,
    what may be deleted, what counts as a failure. The SQL underneath is four
    statements.
    """

    def ohlcv_since(self, symbol: str, timeframe: Timeframe, since_ms: int) -> pd.DataFrame:
        """Every stored bar at or after `since_ms`, oldest first."""
        ...

    def funding_since(self, symbol: str, since_ms: int) -> list[FundingRate]:
        ...

    def prune_ohlcv(self, symbol: str, timeframe: Timeframe, through_ms: int) -> int:
        """Delete bars at or before `through_ms`. Returns how many went."""
        ...

    def prune_funding(self, symbol: str, through_ms: int) -> int:
        ...


@dataclass
class SeriesResult:
    """What happened to one symbol-and-timeframe."""

    series: str
    read: int = 0
    pruned: int = 0
    stored_through: int | None = None
    """The newest timestamp the archive holds afterwards. `None` means it holds
    nothing, which is a different state from holding nothing new."""

    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def describe(self) -> str:
        if self.error:
            return f"{self.series}: FEHLER {self.error}"
        pruned = f", {self.pruned} gelöscht" if self.pruned else ""
        return f"{self.series}: {self.read} Zeilen gelesen{pruned}"


@dataclass
class SyncReport:
    results: list[SeriesResult] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return sum(result.read for result in self.results)

    @property
    def pruned(self) -> int:
        return sum(result.pruned for result in self.results)

    @property
    def failures(self) -> list[SeriesResult]:
        return [result for result in self.results if not result.ok]

    def describe(self) -> str:
        broken = len(self.failures)
        tail = f", {broken} fehlgeschlagen" if broken else ""
        return f"{self.rows} Zeilen aus {len(self.results)} Serien{tail}"


def drain(
    zone: LandingZone,
    store: ParquetStore,
    funding_store: FundingStore,
    *,
    symbols: Sequence[str],
    timeframes: Sequence[Timeframe],
    prune: bool = False,
) -> SyncReport:
    """Move everything the landing zone holds into the archive.

    One series at a time, and a failure in one does not stop the others: four
    symbols across five timeframes is twenty independent jobs, and a venue that
    revised one candle badly should not leave nineteen others undrained. Every
    failure is recorded and the caller decides what to do about it.
    """
    report = SyncReport()
    for symbol in symbols:
        for timeframe in timeframes:
            report.results.append(_drain_ohlcv(zone, store, symbol, timeframe, prune=prune))
        report.results.append(_drain_funding(zone, funding_store, symbol, prune=prune))
    return report


def _drain_ohlcv(
    zone: LandingZone,
    store: ParquetStore,
    symbol: str,
    timeframe: Timeframe,
    *,
    prune: bool,
) -> SeriesResult:
    result = SeriesResult(series=f"ohlcv:{symbol}:{timeframe.value}")
    try:
        held = store.last_ts(symbol, timeframe)
        since = 0 if held is None else held - OVERLAP_BARS * timeframe_ms(timeframe)
        incoming = zone.ohlcv_since(symbol, timeframe, max(0, since))
        result.read = len(incoming)
        if not incoming.empty:
            store.write(symbol, timeframe, incoming)
        result.stored_through = store.last_ts(symbol, timeframe)
    except Exception as error:  # a bad series must not stop the other nineteen
        result.error = f"{type(error).__name__}: {error}"
        return result

    if prune and result.stored_through is not None:
        # Only what the archive has just been re-read and confirms it holds.
        # Deleting on the strength of having sent it is how a crash between the
        # two turns into a hole nobody can see.
        result.pruned = zone.prune_ohlcv(symbol, timeframe, result.stored_through)
    return result


def _drain_funding(
    zone: LandingZone, store: FundingStore, symbol: str, *, prune: bool
) -> SeriesResult:
    result = SeriesResult(series=f"funding:{symbol}")
    try:
        held = store.last_ts(symbol)
        since = 0 if held is None else held - OVERLAP_FUNDING_MS
        rates = zone.funding_since(symbol, max(0, since))
        result.read = len(rates)
        if rates:
            store.write(symbol, rates)
        result.stored_through = store.last_ts(symbol)
    except Exception as error:
        result.error = f"{type(error).__name__}: {error}"
        return result

    if prune and result.stored_through is not None:
        result.pruned = zone.prune_funding(symbol, result.stored_through)
    return result
