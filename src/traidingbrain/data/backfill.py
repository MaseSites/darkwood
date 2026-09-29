"""Paginated history download, resumable and idempotent.

The loop is simple, but three details are what make it safe to re-run:

* It resumes from what is already stored, so interrupting it costs one page.
* It refuses to loop forever when a venue keeps returning the same page, which is
  how a paginating client normally hangs.
* Every page goes through the store, which validates before it writes. Bad data
  never lands.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from traidingbrain.clock import SystemClock
from traidingbrain.data.frames import bars_to_frame, normalise, timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.data.validate import ValidationReport, validate_ohlcv
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.protocols import Clock, DataSource

#: Page size requested per call. Bybit caps this at 1000.
PAGE_SIZE = 1000

#: Stop rather than spin if the venue stops advancing the cursor.
MAX_EMPTY_PAGES = 3

#: Pages buffered before writing to the store. Small enough that a crash costs
#: seconds of re-download, large enough that the store is not rewritten per page.
FLUSH_EVERY_PAGES = 200

ProgressFn = Callable[[str, Timeframe, int, int], None]


@dataclass(frozen=True)
class BackfillResult:
    symbol: str
    timeframe: Timeframe
    bars_fetched: int
    """Rows received from the venue, overlap included.

    Deliberately not the number of distinct candles stored -- pages overlap on
    resume and a stalled venue repeats itself, and counting distinct bars would
    mean holding every timestamp in memory for the length of a two-million-bar
    run. `report.rows` is the stored count.
    """

    pages: int
    report: ValidationReport

    @property
    def bars_stored(self) -> int:
        return self.report.rows

    def summary(self) -> str:
        return (
            f"{self.symbol} {self.timeframe}: received {self.bars_fetched} rows "
            f"in {self.pages} pages\n  {self.report.summary()}"
        )


class Backfiller:
    """Pull history for one symbol and timeframe into the store."""

    def __init__(
        self,
        source: DataSource,
        store: ParquetStore,
        clock: Clock | None = None,
        page_size: int = PAGE_SIZE,
        flush_every_pages: int = FLUSH_EVERY_PAGES,
    ) -> None:
        self.source = source
        self.store = store
        self.clock: Clock = clock or SystemClock()
        self.page_size = page_size
        self.flush_every_pages = max(1, flush_every_pages)

    def run(
        self,
        symbol: str,
        timeframe: Timeframe,
        since_ms: int,
        until_ms: int | None = None,
        *,
        resume: bool = True,
        progress: ProgressFn | None = None,
    ) -> BackfillResult:
        step = timeframe_ms(timeframe)
        end = until_ms if until_ms is not None else self.clock.now_ms()

        cursor = since_ms
        if resume:
            stored_first = self.store.first_ts(symbol, timeframe)
            stored_last = self.store.last_ts(symbol, timeframe)
            if stored_last is not None:
                # Resume forward only when the request actually starts inside what
                # is already held. Taking the maximum unconditionally is what this
                # did before, and it meant a request to reach *further back* jumped
                # the cursor past its own end window, fetched nothing, and reported
                # a clean store and a successful run. A silent no-op that looks
                # like success is worse than a failure.
                if stored_first is None or since_ms >= stored_first:
                    # Re-fetch the last stored bar rather than starting after it:
                    # if it was still forming when written, this pass corrects it.
                    # `merge` prefers the newer copy.
                    cursor = max(cursor, stored_last)
                elif end > stored_first:
                    # Filling a hole before what is held. Stop at the existing
                    # data rather than re-downloading years of it.
                    end = min(end, stored_first)

        # Pages are batched rather than merged one at a time: merging into a
        # growing frame is quadratic, invisible on 200 hourly bars and minutes of
        # wasted work on two million minute bars.
        #
        # They are also flushed periodically rather than held to the end. A minute
        # backfill is two thousand requests against a venue that does occasionally
        # fail mid-run; losing an hour of downloading to a transient server error
        # on the last page is a bad trade for one extra write per thousand pages.
        pages_data: list[pd.DataFrame] = []
        pages = 0
        empty_streak = 0
        bars_total = 0

        def flush() -> None:
            nonlocal pages_data
            if not pages_data:
                return
            chunk = normalise(pd.concat(pages_data, ignore_index=True))
            self.store.write(symbol, timeframe, chunk)
            pages_data = []

        while cursor <= end:
            bars = self.source.fetch_ohlcv(symbol, timeframe, cursor, self.page_size)
            pages += 1

            if not bars:
                empty_streak += 1
                if empty_streak >= MAX_EMPTY_PAGES:
                    break
                cursor += step * self.page_size
                continue

            empty_streak = 0
            page = bars_to_frame(bars)
            page = page.loc[page["ts"] <= end].reset_index(drop=True)
            if page.empty:
                break

            pages_data.append(page)
            bars_total += len(page)
            newest = int(page["ts"].iloc[-1])

            if progress is not None:
                progress(symbol, timeframe, bars_total, newest)

            if len(pages_data) >= self.flush_every_pages:
                flush()

            if newest < cursor + step:
                # The venue did not advance. Continuing would spin on the same page.
                break
            cursor = newest + step

        flush()
        if bars_total == 0:
            return BackfillResult(
                symbol=symbol,
                timeframe=timeframe,
                bars_fetched=0,
                pages=pages,
                report=self.store.report(symbol, timeframe),
            )

        # The whole series, not the last flush. `store.write` reports on the
        # chunk it wrote, and printing that as though it were the total said "116
        # bars" for a store holding 259 -- believable enough to be acted on, and
        # wrong. One extra read at the end of a run that just downloaded two
        # million bars is not the expensive part.
        return BackfillResult(
            symbol=symbol,
            timeframe=timeframe,
            bars_fetched=bars_total,
            pages=pages,
            report=self.store.report(symbol, timeframe),
        )

    def run_many(
        self,
        symbol: str,
        timeframes: list[Timeframe],
        since_ms: int,
        until_ms: int | None = None,
        *,
        progress: ProgressFn | None = None,
    ) -> list[BackfillResult]:
        """Backfill several timeframes, coarsest first.

        Order is deliberate: the weekly frame finishes in a handful of pages and
        confirms the symbol and connection work before the minute frame spends
        hundreds of requests discovering the same problem.
        """
        ordered = sorted(timeframes, key=lambda tf: tf.minutes, reverse=True)
        results: list[BackfillResult] = []
        for timeframe in ordered:
            results.append(self.run(symbol, timeframe, since_ms, until_ms, progress=progress))
            # A request spanning both ends of what is stored needs two passes: the
            # first fills the hole before, this one extends past. One pass can only
            # move the cursor in one direction, and doing it silently is how the
            # earlier version reported success for a range it never touched.
            stored_last = self.store.last_ts(symbol, timeframe)
            wanted_end = until_ms if until_ms is not None else self.clock.now_ms()
            if stored_last is not None and wanted_end > stored_last + timeframe_ms(timeframe):
                results.append(
                    self.run(symbol, timeframe, stored_last, until_ms, progress=progress)
                )
        return results


def verify_store(store: ParquetStore, symbol: str, timeframe: Timeframe) -> ValidationReport:
    """Re-read everything on disk and check it end to end."""
    return validate_ohlcv(store.read(symbol, timeframe), symbol, timeframe)
