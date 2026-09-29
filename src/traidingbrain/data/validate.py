"""Data quality checks, run on every write.

Bad market data does not announce itself. A duplicated candle, a timestamp that
is not on a grid boundary, an exchange outage that left a six-hour hole -- none of
these raise anything. They just produce a strategy that behaves oddly in one
period, and weeks later someone is debugging indicator logic that was never
wrong.

So the store refuses to write a frame that fails these checks, and the gap report
is printed rather than swallowed: gaps are usually real (the exchange was down)
and the right response is to know about them, not to hide them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from traidingbrain.data.frames import grid_offset_ms, timeframe_ms
from traidingbrain.domain.enums import Timeframe


@dataclass(frozen=True)
class Gap:
    """A stretch of missing candles."""

    after_ts: int
    before_ts: int
    missing_bars: int

    def __str__(self) -> str:
        return f"{self.missing_bars} bars missing between {self.after_ts} and {self.before_ts}"


@dataclass
class ValidationReport:
    symbol: str
    timeframe: Timeframe
    rows: int
    first_ts: int | None
    last_ts: int | None
    duplicates: int = 0
    non_monotonic: int = 0
    misaligned: int = 0
    ohlc_violations: int = 0
    negative_volume: int = 0
    nan_rows: int = 0
    gaps: list[Gap] = field(default_factory=list)

    @property
    def missing_bars(self) -> int:
        return sum(gap.missing_bars for gap in self.gaps)

    @property
    def is_fatal(self) -> bool:
        """Gaps are tolerated and reported. Everything else means the data is wrong.

        An exchange can be down; that is a fact about the world. A duplicate bar or
        a low above a high is a fact about our pipeline.
        """
        return bool(
            self.duplicates
            or self.non_monotonic
            or self.misaligned
            or self.ohlc_violations
            or self.negative_volume
            or self.nan_rows
        )

    def problems(self) -> list[str]:
        found: list[str] = []
        if self.duplicates:
            found.append(f"{self.duplicates} duplicate timestamps")
        if self.non_monotonic:
            found.append(f"{self.non_monotonic} non-monotonic timestamps")
        if self.misaligned:
            found.append(f"{self.misaligned} timestamps off the {self.timeframe} grid")
        if self.ohlc_violations:
            found.append(f"{self.ohlc_violations} rows where high/low do not bound open/close")
        if self.negative_volume:
            found.append(f"{self.negative_volume} rows with negative volume")
        if self.nan_rows:
            found.append(f"{self.nan_rows} rows containing NaN")
        return found

    def summary(self) -> str:
        head = f"{self.symbol} {self.timeframe}: {self.rows} bars"
        if self.first_ts is not None and self.last_ts is not None:
            head += f" [{self.first_ts} .. {self.last_ts}]"
        problems = self.problems()
        if problems:
            head += "\n  FATAL: " + "; ".join(problems)
        if self.gaps:
            head += f"\n  {len(self.gaps)} gaps, {self.missing_bars} bars missing"
            for gap in self.gaps[:5]:
                head += f"\n    {gap}"
            if len(self.gaps) > 5:
                head += f"\n    ... and {len(self.gaps) - 5} more"
        if not problems and not self.gaps:
            head += " — clean"
        return head


def validate_ohlcv(frame: pd.DataFrame, symbol: str, timeframe: Timeframe) -> ValidationReport:
    """Check a frame and describe what is wrong with it, without changing it."""
    report = ValidationReport(
        symbol=symbol,
        timeframe=timeframe,
        rows=len(frame),
        first_ts=int(frame["ts"].iloc[0]) if len(frame) else None,
        last_ts=int(frame["ts"].iloc[-1]) if len(frame) else None,
    )
    if frame.empty:
        return report

    ts = frame["ts"]
    report.duplicates = int(ts.duplicated().sum())
    report.non_monotonic = int((ts.diff().dropna() <= 0).sum())

    step = timeframe_ms(timeframe)
    report.misaligned = int((((ts - grid_offset_ms(timeframe)) % step) != 0).sum())

    report.nan_rows = int(frame.isna().any(axis=1).sum())
    report.negative_volume = int((frame["volume"] < 0).sum())

    body_high = frame[["open", "close"]].max(axis=1)
    body_low = frame[["open", "close"]].min(axis=1)
    report.ohlc_violations = int(
        ((frame["high"] < body_high) | (frame["low"] > body_low) | (frame["high"] < frame["low"]))
        .fillna(False)
        .sum()
    )

    report.gaps = find_gaps(frame, timeframe)
    return report


def find_gaps(frame: pd.DataFrame, timeframe: Timeframe) -> list[Gap]:
    """Locate missing stretches on the timeframe grid.

    Only reported, never filled. Interpolating a candle the exchange never printed
    invents price action, and the analysis layer would treat the invention as
    fact.
    """
    if len(frame) < 2:
        return []
    step = timeframe_ms(timeframe)
    ts = frame["ts"].to_numpy()
    deltas = ts[1:] - ts[:-1]
    gaps: list[Gap] = []
    for i, delta in enumerate(deltas):
        if delta > step:
            gaps.append(
                Gap(
                    after_ts=int(ts[i]),
                    before_ts=int(ts[i + 1]),
                    missing_bars=int(delta // step) - 1,
                )
            )
    return gaps


class DataQualityError(RuntimeError):
    """Raised instead of writing data that is wrong in a way we caused."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(f"{report.symbol} {report.timeframe}: " + "; ".join(report.problems()))
        self.report = report
