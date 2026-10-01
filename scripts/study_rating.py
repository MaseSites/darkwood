"""Does the rating predict anything at all?

The one question worth asking before anybody risks money on this screen. The
dashboard now shows a number from 1 to 100 and says how clear the picture is.
Whether a clear picture is followed by a move in the direction it pointed is a
separate claim, and nothing in the system has ever checked it.

    python scripts/study_rating.py --horizon 24

**What it measures.** At every sampled bar: the rating, the direction it
leaned, and what price did over the next `horizon` bars, in ATR -- signed so
that positive always means "the lean was right". Then the bars are grouped by
rating and each group's mean is reported with a bootstrap interval.

**Three things that would make the answer a lie, and what is done about them.**

*Overlapping windows.* Bars are sampled `horizon` apart, so no two measurements
share a single hour of future. Sampling every bar would multiply the apparent
sample size by the horizon while adding almost no information, and the
intervals would come out far too narrow -- the classic way an observational
study of a time series manufactures significance.

*Scale.* The move is divided by the ATR at the decision bar, so a quiet week on
BTC and a violent one on SOL contribute comparably. Measuring in per cent would
let whichever symbol happened to be volatile decide the result.

*Direction.* Signed by the lean, never by what happened. A study that took the
absolute move would report that volatility follows a clear picture, which is a
different and much less useful claim.

**What it cannot tell you.** Nothing here is a trade. There is no stop, no
target, no fee and no slippage -- so a positive number means the lean pointed
the right way on average, not that a strategy built on it would have made
money. `run_backtest.py` is the thing that answers that, and the cost floor it
enforces is why the two can disagree.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Bias
from traidingbrain.score.rating import rate
from traidingbrain.score.reading import score_at

#: How many resamples the confidence interval is built from.
BOOTSTRAP = 2000

#: Fewest measurements before a group is worth reporting a mean for. Two is
#: the floor at which a bootstrap is defined at all, not a floor at which it
#: means anything -- the printed sample size is what says that.
MIN_SAMPLES = 2

#: Rating boundaries the sample is grouped by. The bands the screen uses, so
#: that the answer is about what a person actually reads rather than about a
#: statistic nobody sees.
GROUPS: tuple[tuple[int, int, str], ...] = (
    (1, 29, "Durcheinander"),
    (30, 49, "unklar"),
    (50, 73, "gemischt"),
    (74, 87, "deutlich"),
    (88, 100, "eindeutig"),
)


@dataclass
class Sample:
    rating: int
    moved_atr: float
    """Signed by the lean: positive means the direction was right."""

    bullish: bool
    raw_atr: float
    """The move with the market's own sign, before the lean was applied.

    Kept for the one check that decides whether any of this means anything: a
    system that leans long most of the time, measured over years in which the
    market rose, scores positive without knowing a thing. Comparing the two
    sides separately is what tells drift apart from skill."""


@dataclass
class Study:
    samples: list[Sample] = field(default_factory=list)

    def of(self, low: int, high: int) -> np.ndarray:
        return np.array(
            [s.moved_atr for s in self.samples if low <= s.rating <= high], dtype="float64"
        )


def interval(values: np.ndarray, seed: int = 7) -> tuple[float, float]:
    """A 95% bootstrap interval for the mean.

    Bootstrap rather than a t-interval because the forward moves are not
    normal -- they are fat-tailed, which is the whole character of the thing
    being measured, and a parametric interval would quietly report a precision
    the data does not have.
    """
    if len(values) < MIN_SAMPLES:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(BOOTSTRAP, len(values)), replace=True).mean(axis=1)
    return (float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5)))


def collect(symbol: str, horizon: int, bars: int) -> list[Sample]:
    config = load_config().engine
    store = ParquetStore(config.paths.parquet_dir)
    frames = {tf: store.read(symbol, tf) for tf in config.timeframes.context}
    if any(frame.empty for frame in frames.values()):
        return []

    multi = MultiFrameAnalysis(frames, config)
    signal = multi.signal
    closes = signal.column("close")
    total = len(signal)
    first = max(0, total - bars)

    out: list[Sample] = []
    # Stepping by the horizon is what keeps the windows from overlapping.
    for index in range(first, total - horizon, horizon):
        reading = score_at(multi, index)
        if reading is None:
            continue
        rating = rate(reading.score)
        if rating.direction is Bias.NEUTRAL:
            continue
        unit = signal.atr_at(index)
        if not np.isfinite(unit) or unit <= 0:
            continue
        move = (float(closes[index + horizon]) - float(closes[index])) / unit
        lean = 1.0 if rating.direction is Bias.BULLISH else -1.0
        out.append(
            Sample(
                rating=rating.value,
                moved_atr=move * lean,
                bullish=rating.direction is Bias.BULLISH,
                raw_atr=move,
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=24, help="bars ahead to measure")
    parser.add_argument("--bars", type=int, default=20_000, help="how far back to go")
    parser.add_argument("--symbol", action="append", help="limit to these symbols")
    args = parser.parse_args()

    symbols = args.symbol or list(load_config().engine.symbols.active)
    study = Study()
    for symbol in symbols:
        found = collect(symbol, args.horizon, args.bars)
        study.samples.extend(found)
        print(f"{symbol}: {len(found)} unabhängige Messungen", flush=True)

    if not study.samples:
        print("nichts gemessen", file=sys.stderr)
        return 1

    everything = np.array([s.moved_atr for s in study.samples], dtype="float64")
    low, high = interval(everything)
    print(f"\n{len(everything)} Messungen, {args.horizon} Kerzen voraus, in ATR")
    print(f"alle zusammen      {everything.mean():+.3f}  [{low:+.3f}, {high:+.3f}]")
    print()

    for start, end, name in GROUPS:
        values = study.of(start, end)
        if len(values) < MIN_SAMPLES:
            print(f"{name:14s} ({start:3d}-{end:3d})  zu wenige Fälle: {len(values)}")
            continue
        low, high = interval(values)
        verdict = "" if low < 0 < high else "  <- schliesst die Null aus"
        print(
            f"{name:14s} ({start:3d}-{end:3d})  n={len(values):5d}  "
            f"{values.mean():+.3f}  [{low:+.3f}, {high:+.3f}]{verdict}"
        )

    # The confound that would make everything above meaningless.
    longs = np.array([s.raw_atr for s in study.samples if s.bullish], dtype="float64")
    shorts = np.array([s.raw_atr for s in study.samples if not s.bullish], dtype="float64")
    drift = np.array([s.raw_atr for s in study.samples], dtype="float64")
    print(f"\nRichtungsverteilung: {len(longs)} aufwärts, {len(shorts)} abwärts")
    print(f"Marktdrift über alle Messungen: {drift.mean():+.3f} ATR")
    for values, word in ((longs, "aufwärts"), (shorts, "abwärts")):
        if len(values) < MIN_SAMPLES:
            continue
        low, high = interval(values)
        print(
            f"  wenn {word} gelehnt, lief der Markt "
            f"{values.mean():+.3f}  [{low:+.3f}, {high:+.3f}]"
        )

    # The question in one line: do the clear bars beat the messy ones?
    clear = study.of(74, 100)
    messy = study.of(1, 49)
    if len(clear) >= MIN_SAMPLES and len(messy) >= MIN_SAMPLES:
        print(
            f"\ndeutlich/eindeutig minus unklar/Durcheinander: "
            f"{clear.mean() - messy.mean():+.3f} ATR"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
