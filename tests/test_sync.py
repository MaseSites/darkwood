"""Draining the landing zone, with no database in sight.

The sync's SQL is four statements. Everything that can be wrong in a way nobody
notices is in the decisions around them -- which window to re-read, what may be
deleted, what counts as a failure -- so those are what a fake landing zone makes
testable here. The Postgres implementation is covered by the integration test at
the bottom, which skips when no database answers.

The test that matters most is the one about deletion. A sync that removes a row
it believes it filed, after a write that did not land, produces a hole in the
history that is indistinguishable from a quiet market and surfaces months later
in a backtest. Nothing may be deleted on the strength of having been sent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from traidingbrain.data.funding import FundingStore
from traidingbrain.data.grid import collected_timeframes, timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.data.sync import (
    OVERLAP_BARS,
    OVERLAP_FUNDING_MS,
    LandingZone,
    SyncReport,
    drain,
)
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import FundingRate
from traidingbrain.storage.landing import PostgresLandingZone
from traidingbrain.storage.postgres import migrate, pool_for

H1 = Timeframe.H1
H1_MS = timeframe_ms(H1)
SYMBOL = "TESTUSDT"


def bars(first_ts: int, count: int, *, step: int = H1_MS) -> pd.DataFrame:
    close = 100.0 + np.arange(count, dtype="float64") * 0.5
    return pd.DataFrame(
        {
            "ts": first_ts + np.arange(count, dtype="int64") * step,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(count, 10.0),
        }
    )


class FakeZone:
    """A landing zone in memory, which also records what it was asked for."""

    def __init__(
        self, frame: pd.DataFrame | None = None, rates: list[FundingRate] | None = None
    ) -> None:
        self.frame = frame if frame is not None else bars(0, 0)
        self.rates = rates or []
        self.asked: list[tuple[str, int]] = []
        self.pruned: list[tuple[str, int]] = []

    def ohlcv_since(self, symbol: str, timeframe: Timeframe, since_ms: int) -> pd.DataFrame:
        self.asked.append((f"ohlcv:{symbol}:{timeframe.value}", since_ms))
        return self.frame.loc[self.frame["ts"] >= since_ms].reset_index(drop=True)

    def funding_since(self, symbol: str, since_ms: int) -> list[FundingRate]:
        self.asked.append((f"funding:{symbol}", since_ms))
        return [rate for rate in self.rates if rate.ts >= since_ms]

    def prune_ohlcv(self, symbol: str, timeframe: Timeframe, through_ms: int) -> int:
        self.pruned.append((f"ohlcv:{symbol}:{timeframe.value}", through_ms))
        gone = int((self.frame["ts"] <= through_ms).sum())
        self.frame = self.frame.loc[self.frame["ts"] > through_ms].reset_index(drop=True)
        return gone

    def prune_funding(self, symbol: str, through_ms: int) -> int:
        self.pruned.append((f"funding:{symbol}", through_ms))
        gone = sum(1 for rate in self.rates if rate.ts <= through_ms)
        self.rates = [rate for rate in self.rates if rate.ts > through_ms]
        return gone


class BrokenStore(ParquetStore):
    """An archive whose writes fail. Stands in for a full disk or bad data."""

    def write(self, *args: object, **kwargs: object) -> object:
        raise OSError("no space left on device")


@pytest.fixture
def stores(tmp_path: Path) -> tuple[ParquetStore, FundingStore]:
    return ParquetStore(tmp_path / "ohlcv"), FundingStore(tmp_path / "funding")


def run(
    zone: LandingZone,
    stores: tuple[ParquetStore, FundingStore],
    *,
    prune: bool = False,
) -> SyncReport:
    return drain(
        zone,
        stores[0],
        stores[1],
        symbols=[SYMBOL],
        timeframes=[H1],
        prune=prune,
    )


# --------------------------------------------------------------------------- #
# Moving rows forward
# --------------------------------------------------------------------------- #


def test_an_empty_archive_takes_everything(stores: tuple[ParquetStore, FundingStore]) -> None:
    zone = FakeZone(bars(0, 50))

    report = run(zone, stores)

    assert report.rows == 50
    assert len(stores[0].read(SYMBOL, H1)) == 50


def test_it_re_reads_an_overlapping_window_rather_than_trusting_a_marker(
    stores: tuple[ParquetStore, FundingStore],
) -> None:
    """The collector's own rule, applied in the other direction.

    The newest row in the archive is the one most likely to have come from a
    partial fetch, and the one before it the one most likely to be missing
    after a run that died mid-write. Asking from exactly where the archive ends
    would file both mistakes permanently.
    """
    store, _ = stores
    store.write(SYMBOL, H1, bars(0, 30))
    zone = FakeZone(bars(0, 50))

    run(zone, stores)

    asked = dict(zone.asked)
    last_held = int(bars(0, 30)["ts"].iloc[-1])
    assert asked[f"ohlcv:{SYMBOL}:H1"] == last_held - OVERLAP_BARS * H1_MS


def test_re_reading_the_overlap_does_not_duplicate_anything(
    stores: tuple[ParquetStore, FundingStore],
) -> None:
    """The archive's writers deduplicate on the key, which is what makes the
    overlap free. If they did not, every sync would widen the history."""
    store, _ = stores
    store.write(SYMBOL, H1, bars(0, 30))
    zone = FakeZone(bars(0, 50))

    run(zone, stores)
    run(zone, stores)

    stored = store.read(SYMBOL, H1)
    assert len(stored) == 50
    assert stored["ts"].is_unique


def test_a_landing_zone_with_nothing_new_writes_nothing(
    stores: tuple[ParquetStore, FundingStore],
) -> None:
    store, _ = stores
    store.write(SYMBOL, H1, bars(0, 50))
    before = store.partition_path(SYMBOL, H1, 1970).read_bytes()

    run(FakeZone(bars(0, 0)), stores)

    assert store.partition_path(SYMBOL, H1, 1970).read_bytes() == before


def test_funding_is_drained_too(stores: tuple[ParquetStore, FundingStore]) -> None:
    rates = [FundingRate(ts=i * 8 * 3_600_000, rate=0.0001) for i in range(1, 12)]
    zone = FakeZone(rates=rates)

    run(zone, stores)

    assert len(stores[1].read(SYMBOL)) == len(rates)


def test_funding_re_reads_a_day_rather_than_ten_bars(
    stores: tuple[ParquetStore, FundingStore],
) -> None:
    """Settlements are eight-hourly, so a bar count would mean something
    different here than it does for candles."""
    rates = [FundingRate(ts=i * 8 * 3_600_000, rate=0.0001) for i in range(1, 12)]
    stores[1].write(SYMBOL, rates)
    zone = FakeZone(rates=rates)

    run(zone, stores)

    assert dict(zone.asked)[f"funding:{SYMBOL}"] == rates[-1].ts - OVERLAP_FUNDING_MS


# --------------------------------------------------------------------------- #
# Deleting, which is the half that can lose data
# --------------------------------------------------------------------------- #


def test_nothing_is_deleted_unless_asked(stores: tuple[ParquetStore, FundingStore]) -> None:
    """The safe half is the default. Disk on the Pi is cheaper than a hole in
    the history that surfaces months later in a backtest."""
    zone = FakeZone(bars(0, 50))

    run(zone, stores)

    assert zone.pruned == []
    assert len(zone.frame) == 50


def test_pruning_removes_only_what_the_archive_confirms_it_holds(
    stores: tuple[ParquetStore, FundingStore],
) -> None:
    zone = FakeZone(bars(0, 50))

    report = run(zone, stores, prune=True)

    # Funding is not pruned here: its archive holds nothing, so there is
    # nothing it could confirm.
    assert zone.pruned == [(f"ohlcv:{SYMBOL}:H1", stores[0].last_ts(SYMBOL, H1))]
    assert report.pruned == 50
    assert len(zone.frame) == 0


def test_a_failed_write_deletes_nothing(stores: tuple[ParquetStore, FundingStore]) -> None:
    """The test this module exists for.

    A sync that removes a row it believes it filed, after a write that did not
    land, puts a hole in the history that is indistinguishable from a quiet
    market. Deleting on the strength of having *sent* the rows is the specific
    mistake; the write has to have succeeded and the archive has to have been
    re-read.
    """
    broken = BrokenStore(stores[0].root)
    zone = FakeZone(bars(0, 50))

    report = drain(
        zone,
        broken,
        stores[1],
        symbols=[SYMBOL],
        timeframes=[H1],
        prune=True,
    )

    assert zone.pruned == []
    assert len(zone.frame) == 50
    assert report.failures


def test_pruning_an_archive_that_holds_nothing_deletes_nothing(
    stores: tuple[ParquetStore, FundingStore],
) -> None:
    """`last_ts` returning None is "the archive has nothing", which is a
    different state from "the archive has nothing new" -- and the one where a
    delete would be unbacked by anything at all."""
    zone = FakeZone(bars(0, 0))

    run(zone, stores, prune=True)

    assert not any(series.startswith("ohlcv") for series, _ in zone.pruned)


# --------------------------------------------------------------------------- #
# One bad series must not stop the others
# --------------------------------------------------------------------------- #


def test_a_failure_in_one_series_leaves_the_others_drained(tmp_path: Path) -> None:
    """Four symbols across five timeframes is twenty independent jobs. A venue
    that revised one candle badly should not leave nineteen undrained."""

    class SelectivelyBroken(ParquetStore):
        def write(self, symbol: str, timeframe: Timeframe, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
            if symbol == "BADUSDT":
                raise ValueError("refused")
            return super().write(symbol, timeframe, *args, **kwargs)  # type: ignore[arg-type]

    store = SelectivelyBroken(tmp_path / "ohlcv")
    zone = FakeZone(bars(0, 20))

    report = drain(
        zone,
        store,
        FundingStore(tmp_path / "funding"),
        symbols=["BADUSDT", "GOODUSDT"],
        timeframes=[H1],
    )

    failed = {result.series for result in report.failures}
    assert f"ohlcv:BADUSDT:{H1.value}" in failed
    assert len(store.read("GOODUSDT", H1)) == 20


def test_a_failure_is_described_rather_than_swallowed(tmp_path: Path) -> None:
    zone = FakeZone(bars(0, 20))

    report = drain(
        zone,
        BrokenStore(tmp_path / "ohlcv"),
        FundingStore(tmp_path / "funding"),
        symbols=[SYMBOL],
        timeframes=[H1],
    )

    assert "OSError" in report.failures[0].error
    assert "FEHLER" in report.failures[0].describe()


def test_the_report_counts_what_moved(stores: tuple[ParquetStore, FundingStore]) -> None:
    zone = FakeZone(bars(0, 7), rates=[FundingRate(ts=8 * 3_600_000, rate=0.0)])

    report = run(zone, stores)

    assert report.rows == 8
    assert not report.failures
    assert "8 Zeilen" in report.describe()


# --------------------------------------------------------------------------- #
# The four statements, against a real server
# --------------------------------------------------------------------------- #


def test_the_postgres_landing_zone_round_trips(pg_test_url: str, tmp_path: Path) -> None:
    """Skips when no database answers, which is most of the time on a laptop
    while the Pi is off. It is here so that the SQL is exercised at all --
    column order, timeframe spelling, the `<=` in the delete."""
    migrate(pg_test_url)
    zone = PostgresLandingZone(pg_test_url)
    written = bars(0, 25)
    with pool_for(pg_test_url).connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ohlcv WHERE symbol = %s", (SYMBOL,))
        for row in written.itertuples(index=False):
            cur.execute(
                "INSERT INTO ohlcv (symbol, timeframe, ts, open, high, low, close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (SYMBOL, H1.value, row.ts, row.open, row.high, row.low, row.close, row.volume),
            )
        conn.commit()

    report = drain(
        zone,
        ParquetStore(tmp_path / "ohlcv"),
        FundingStore(tmp_path / "funding"),
        symbols=[SYMBOL],
        timeframes=[H1],
        prune=True,
    )

    assert report.rows == 25
    assert report.pruned == 25
    assert zone.ohlcv_since(SYMBOL, H1, 0).empty


# --------------------------------------------------------------------------- #
# The two machines must agree on what there is to drain
# --------------------------------------------------------------------------- #


def test_the_sync_drains_every_frame_the_collector_writes() -> None:
    """The bug this function exists to prevent, caught before it shipped.

    The collector gathers the context frames *and* the execution frame. The
    first draft of the sync drained the context frames only, so M1 -- sixty
    rows for every hourly one, and by far the largest table -- would have
    accumulated in the landing zone with nothing to empty it. Nothing in either
    program said the two lists had to match, so they did not.
    """
    context = [Timeframe.W1, Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15]

    collected = collected_timeframes(context, Timeframe.M1)

    assert Timeframe.M1 in collected
    assert collected[: len(context)] == context


def test_an_execution_frame_already_in_the_context_is_not_doubled() -> None:
    """A duplicate would drain the same series twice and report it twice --
    harmless, and the kind of harmless that makes a report untrustworthy."""
    collected = collected_timeframes([Timeframe.H1, Timeframe.M15], Timeframe.M15)

    assert collected == [Timeframe.H1, Timeframe.M15]
