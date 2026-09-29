"""The data layer's acceptance criteria.

Four properties, in rough order of how much damage their absence would do:

1. The forming candle never reaches storage. It is the single most effective way
   to make a backtest look good and a live system disappoint.
2. Writes are idempotent down to the byte, so a changed backtest result means the
   code changed and not the write order.
3. Data that is wrong in a way we caused is refused rather than stored.
4. Pagination resumes, terminates, and does not spin when a venue stalls.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.fakes import (
    EPOCH,
    FakeCcxtExchange,
    FakeDataSource,
    StuckDataSource,
    bars_from_rows,
    synthetic_rows,
)
from traidingbrain.clock import FixedClock
from traidingbrain.data.backfill import Backfiller
from traidingbrain.data.exchange import BybitDataSource, to_ccxt_symbol
from traidingbrain.data.frames import (
    bars_to_frame,
    close_time_ms,
    drop_forming,
    empty_frame,
    is_aligned,
    is_closed,
    merge,
    normalise,
    slice_until,
    timeframe_ms,
)
from traidingbrain.data.store import ParquetStore, year_of
from traidingbrain.data.validate import DataQualityError, find_gaps, validate_ohlcv
from traidingbrain.domain.enums import Timeframe

H1 = Timeframe.H1
H1_MS = timeframe_ms(H1)


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    return ParquetStore(tmp_path / "ohlcv")


def frame_of(count: int, start: int = EPOCH, timeframe: Timeframe = H1) -> pd.DataFrame:
    return bars_to_frame(bars_from_rows(synthetic_rows(start, timeframe, count)))


# --------------------------------------------------------------------------- #
# 1. The forming candle
# --------------------------------------------------------------------------- #


def test_a_candle_is_closed_only_once_its_close_time_has_passed() -> None:
    opened = EPOCH
    closes_at = close_time_ms(opened, H1)
    assert not is_closed(opened, H1, now_ms=closes_at - 1)
    assert is_closed(opened, H1, now_ms=closes_at), "at exactly the close time it is done"
    assert is_closed(opened, H1, now_ms=closes_at + 1)


def test_drop_forming_removes_the_unfinished_tail() -> None:
    frame = frame_of(10)
    last_open = int(frame["ts"].iloc[-1])
    # Now sits one minute into the final candle: it is still being built.
    now = last_open + 60_000

    kept = drop_forming(frame, H1, now_ms=now)

    assert len(kept) == 9
    assert int(kept["ts"].iloc[-1]) == last_open - H1_MS


def test_exchange_adapter_never_returns_a_forming_candle() -> None:
    """Checked on the real adapter, not just the helper.

    The venue returns it; the boundary drops it. Dropping it anywhere further in
    would mean every future caller has to remember.
    """
    rows = synthetic_rows(EPOCH, H1, 24)
    last_open = int(rows[-1][0])
    exchange = FakeCcxtExchange(rows, timeframe=H1)
    source = BybitDataSource(exchange=exchange, clock=FixedClock(last_open + 60_000), testnet=True)

    bars = source.fetch_ohlcv("BTCUSDT", H1, since_ms=EPOCH, limit=1000)

    assert len(bars) == 23
    assert bars[-1].ts == last_open - H1_MS
    assert all(is_closed(b.ts, H1, last_open + 60_000) for b in bars)


def test_forming_candle_is_corrected_on_the_next_backfill(store: ParquetStore) -> None:
    """A bar written while forming must be replaced, not duplicated.

    The backfiller re-fetches its last stored bar for exactly this reason, and
    `merge` prefers the fresher copy.
    """
    rows = synthetic_rows(EPOCH, H1, 5)
    # What the final bar looked like a second after it opened: no range yet, and a
    # close equal to the open. Perfectly valid OHLC, and completely wrong.
    just_opened = bars_from_rows(rows)[-1]
    stale = just_opened.model_copy(
        update={
            "high": just_opened.open,
            "low": just_opened.open,
            "close": just_opened.open,
            "volume": 0.4,
        }
    )
    store.write("BTCUSDT", H1, frame_of(4))
    store.write("BTCUSDT", H1, pd.DataFrame([stale.model_dump()]))

    truth = bars_from_rows(rows)
    backfiller = Backfiller(
        FakeDataSource(truth), store, clock=FixedClock(int(rows[-1][0]) + H1_MS)
    )
    backfiller.run("BTCUSDT", H1, since_ms=EPOCH)

    stored = store.read("BTCUSDT", H1)
    assert len(stored) == 5, "the corrected bar replaced the stale one instead of joining it"
    assert float(stored["close"].iloc[-1]) == pytest.approx(rows[-1][4])


# --------------------------------------------------------------------------- #
# 2. Idempotent writes
# --------------------------------------------------------------------------- #


def test_writing_the_same_data_twice_produces_identical_bytes(store: ParquetStore) -> None:
    frame = frame_of(500)
    store.write("BTCUSDT", H1, frame)
    first = [p.read_bytes() for p in store.partitions("BTCUSDT", H1)]

    store.write("BTCUSDT", H1, frame)
    second = [p.read_bytes() for p in store.partitions("BTCUSDT", H1)]

    assert first == second


def test_write_order_does_not_change_the_result(store: ParquetStore) -> None:
    frame = frame_of(200)
    store.write("BTCUSDT", H1, frame.iloc[:120])
    store.write("BTCUSDT", H1, frame.iloc[80:])
    forwards = [p.read_bytes() for p in store.partitions("BTCUSDT", H1)]

    other = ParquetStore(store.root.parent / "other")
    other.write("BTCUSDT", H1, frame.iloc[80:])
    other.write("BTCUSDT", H1, frame.iloc[:120])
    backwards = [p.read_bytes() for p in other.partitions("BTCUSDT", H1)]

    assert forwards == backwards


def test_overlapping_writes_do_not_duplicate(store: ParquetStore) -> None:
    frame = frame_of(100)
    store.write("BTCUSDT", H1, frame.iloc[:60])
    report = store.write("BTCUSDT", H1, frame.iloc[40:])

    assert report.rows == 100
    assert report.duplicates == 0
    assert not report.is_fatal


def test_round_trip_preserves_values(store: ParquetStore) -> None:
    frame = frame_of(50)
    store.write("BTCUSDT", H1, frame)
    pd.testing.assert_frame_equal(store.read("BTCUSDT", H1), frame)


def test_partitions_split_by_year(store: ParquetStore) -> None:
    # 2024-12-31T12:00Z onward, so the range straddles new year.
    start = 1_735_646_400_000
    store.write("BTCUSDT", H1, frame_of(48, start=start))

    names = sorted(p.stem for p in store.partitions("BTCUSDT", H1))
    assert names == ["2024", "2025"]
    assert len(store.read("BTCUSDT", H1)) == 48


def test_last_ts_finds_the_newest_bar(store: ParquetStore) -> None:
    assert store.last_ts("BTCUSDT", H1) is None
    frame = frame_of(30)
    store.write("BTCUSDT", H1, frame)
    assert store.last_ts("BTCUSDT", H1) == int(frame["ts"].iloc[-1])


def test_reading_an_empty_store_returns_a_typed_frame(store: ParquetStore) -> None:
    result = store.read("ETHUSDT", H1)
    assert result.empty
    assert list(result.columns) == list(empty_frame().columns)


def test_duckdb_can_read_the_partitions(store: ParquetStore) -> None:
    store.write("BTCUSDT", H1, frame_of(120))
    result = store.query(f"SELECT count(*) AS n FROM read_parquet('{store.glob('BTCUSDT', H1)}')")
    assert int(result["n"].iloc[0]) == 120


# --------------------------------------------------------------------------- #
# 3. Bad data is refused
# --------------------------------------------------------------------------- #


def test_a_clean_frame_validates(store: ParquetStore) -> None:
    report = validate_ohlcv(frame_of(100), "BTCUSDT", H1)
    assert not report.is_fatal
    assert report.gaps == []
    assert "clean" in report.summary()


def test_gaps_are_reported_not_hidden() -> None:
    frame = frame_of(20)
    with_hole = pd.concat([frame.iloc[:8], frame.iloc[13:]], ignore_index=True)

    gaps = find_gaps(with_hole, H1)

    assert len(gaps) == 1
    assert gaps[0].missing_bars == 5
    report = validate_ohlcv(with_hole, "BTCUSDT", H1)
    assert not report.is_fatal, "an exchange outage is a fact, not a pipeline bug"
    assert report.missing_bars == 5


def test_weekly_candles_open_on_monday_not_on_the_epoch_grid() -> None:
    """The Unix epoch was a Thursday; exchanges open the week on Monday.

    A naive `ts % week == 0` check rejects every real weekly candle. This was
    caught by the validator on the first live fetch, which is exactly what it is
    for.
    """
    monday = 1_704_067_200_000  # 2024-01-01T00:00Z, a Monday
    thursday = monday - 4 * 24 * 60 * 60 * 1000  # lands on the naive epoch grid

    assert is_aligned(monday, Timeframe.W1)
    assert not is_aligned(thursday, Timeframe.W1)

    weekly = frame_of(20, start=monday, timeframe=Timeframe.W1)
    assert validate_ohlcv(weekly, "BTCUSDT", Timeframe.W1).misaligned == 0


@pytest.mark.parametrize(
    "timeframe", [Timeframe.M1, Timeframe.M15, Timeframe.H1, Timeframe.H4, Timeframe.D1]
)
def test_sub_weekly_frames_divide_the_epoch_evenly(timeframe: Timeframe) -> None:
    midnight_utc = 1_704_067_200_000
    assert is_aligned(midnight_utc, timeframe)
    assert not is_aligned(midnight_utc + 60_000 * 7, timeframe) or timeframe is Timeframe.M1


def test_misaligned_timestamps_are_fatal() -> None:
    frame = frame_of(10)
    frame.loc[5, "ts"] = int(frame.loc[5, "ts"]) + 137
    report = validate_ohlcv(frame, "BTCUSDT", H1)
    assert report.misaligned == 1
    assert report.is_fatal


def test_a_high_below_the_body_is_fatal() -> None:
    frame = frame_of(10)
    frame.loc[3, "high"] = float(frame.loc[3, "low"]) - 1.0
    report = validate_ohlcv(frame, "BTCUSDT", H1)
    assert report.ohlc_violations >= 1
    assert report.is_fatal


def test_negative_volume_is_fatal() -> None:
    frame = frame_of(10)
    frame.loc[2, "volume"] = -1.0
    assert validate_ohlcv(frame, "BTCUSDT", H1).is_fatal


def test_the_store_refuses_to_write_broken_data(store: ParquetStore) -> None:
    frame = frame_of(10)
    frame.loc[4, "high"] = float(frame.loc[4, "low"]) - 5.0

    with pytest.raises(DataQualityError, match="high/low"):
        store.write("BTCUSDT", H1, frame)

    assert store.partitions("BTCUSDT", H1) == []


def test_normalise_sorts_and_deduplicates() -> None:
    frame = frame_of(10)
    shuffled = pd.concat([frame.iloc[5:], frame.iloc[:7]], ignore_index=True)

    result = normalise(shuffled)

    assert len(result) == 10
    assert result["ts"].is_monotonic_increasing
    assert not result["ts"].duplicated().any()


def test_merge_prefers_the_newer_copy() -> None:
    old = frame_of(5)
    fresh = old.copy()
    fresh.loc[4, "close"] = 99_999.0

    result = merge(old, fresh)

    assert len(result) == 5
    assert float(result["close"].iloc[-1]) == pytest.approx(99_999.0)


def test_slice_until_is_inclusive_and_stops_there() -> None:
    frame = frame_of(10)
    cutoff = int(frame["ts"].iloc[4])
    sliced = slice_until(frame, cutoff)
    assert len(sliced) == 5
    assert int(sliced["ts"].iloc[-1]) == cutoff


# --------------------------------------------------------------------------- #
# 4. Pagination
# --------------------------------------------------------------------------- #


def test_backfill_pages_through_everything(store: ParquetStore) -> None:
    bars = bars_from_rows(synthetic_rows(EPOCH, H1, 250))
    source = FakeDataSource(bars, page_size=100)
    end = bars[-1].ts + H1_MS

    result = Backfiller(source, store, clock=FixedClock(end)).run("BTCUSDT", H1, since_ms=EPOCH)

    assert result.bars_fetched == 250
    assert result.pages >= 3
    assert len(store.read("BTCUSDT", H1)) == 250
    assert not result.report.is_fatal


def test_backfill_resumes_from_what_is_stored(store: ParquetStore) -> None:
    bars = bars_from_rows(synthetic_rows(EPOCH, H1, 100))
    store.write("BTCUSDT", H1, frame_of(60))
    source = FakeDataSource(bars, page_size=1000)
    end = bars[-1].ts + H1_MS

    Backfiller(source, store, clock=FixedClock(end)).run("BTCUSDT", H1, since_ms=EPOCH)

    first_request_since = source.fetch_calls[0][2]
    assert first_request_since >= int(frame_of(60)["ts"].iloc[-1]), (
        "resuming should start at the last stored bar, not at the beginning"
    )
    assert len(store.read("BTCUSDT", H1)) == 100


def test_backfill_stops_when_the_venue_stalls(store: ParquetStore) -> None:
    """A venue that keeps returning the same page must not become an infinite loop."""
    bars = bars_from_rows(synthetic_rows(EPOCH, H1, 5))
    source = StuckDataSource(bars)

    result = Backfiller(source, store, clock=FixedClock(EPOCH + H1_MS * 10_000)).run(
        "BTCUSDT", H1, since_ms=EPOCH
    )

    assert source.calls < 5, "the loop noticed the cursor was not advancing"
    assert result.bars_fetched == 5


def test_backfill_respects_the_end_of_the_requested_range(store: ParquetStore) -> None:
    bars = bars_from_rows(synthetic_rows(EPOCH, H1, 100))
    cutoff = bars[49].ts
    source = FakeDataSource(bars)

    Backfiller(source, store, clock=FixedClock(bars[-1].ts + H1_MS)).run(
        "BTCUSDT", H1, since_ms=EPOCH, until_ms=cutoff
    )

    stored = store.read("BTCUSDT", H1)
    assert int(stored["ts"].iloc[-1]) == cutoff
    assert len(stored) == 50


def test_run_many_starts_with_the_coarsest_frame(store: ParquetStore) -> None:
    """Weekly first: a handful of pages proves symbol and connection before the
    minute frame spends hundreds of requests learning the same thing."""
    seen: list[Timeframe] = []

    class Recorder(FakeDataSource):
        def fetch_ohlcv(self, symbol: str, timeframe: Timeframe, since_ms: int, limit: int) -> list:
            if timeframe not in seen:
                seen.append(timeframe)
            return []

    Backfiller(Recorder([]), store, clock=FixedClock(EPOCH + H1_MS)).run_many(
        "BTCUSDT", [Timeframe.M15, Timeframe.W1, Timeframe.H1], since_ms=EPOCH
    )

    assert seen == [Timeframe.W1, Timeframe.H1, Timeframe.M15]


# --------------------------------------------------------------------------- #
# Symbol naming and specs
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("plain", "ccxt_name"),
    [
        ("BTCUSDT", "BTC/USDT:USDT"),
        ("ETHUSDT", "ETH/USDT:USDT"),
        ("SOLUSDT", "SOL/USDT:USDT"),
        ("XRPUSDT", "XRP/USDT:USDT"),
        ("BTC/USDT:USDT", "BTC/USDT:USDT"),
    ],
)
def test_symbol_translation(plain: str, ccxt_name: str) -> None:
    assert to_ccxt_symbol(plain) == ccxt_name


def test_non_usdt_symbols_are_refused() -> None:
    with pytest.raises(ValueError, match="USDT-quoted"):
        to_ccxt_symbol("BTCBUSD")


def test_symbol_spec_comes_from_the_venue() -> None:
    exchange = FakeCcxtExchange(synthetic_rows(EPOCH, H1, 2))
    source = BybitDataSource(exchange=exchange, clock=FixedClock(EPOCH))

    spec = source.fetch_symbol_spec("BTCUSDT")

    assert spec.price_tick == pytest.approx(0.1)
    assert spec.qty_step == pytest.approx(0.001)
    assert spec.taker_fee == pytest.approx(0.00055)
    assert spec.maintenance_margin_rate == pytest.approx(0.005)


def test_year_partitioning_helper() -> None:
    assert year_of(EPOCH) == 2024
    assert year_of(1_735_689_600_000) == 2025
