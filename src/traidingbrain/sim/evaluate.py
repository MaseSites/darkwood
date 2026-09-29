"""Measuring whether a result means anything.

Every number a backtest produces is in-sample until proven otherwise, and the
threshold in `max_cost_fraction_of_risk` is a live example: it was chosen after
looking at the distribution of stops in this data. The rule behind it is
principled -- transaction costs must be a small share of what is at stake -- but
the number 0.15 came from the data it is now being evaluated on. That is exactly
the kind of thing that looks like an edge and is not.

Three methods here, in increasing order of how much they can be trusted.

**A single split.** Fit on the first half, report on the second. Cheap, and it
catches the worst of it. Its weakness is that it gives one number from one market
period, and markets have moods.

**Walk-forward.** Several consecutive train/test pairs, each testing on data after
its own training window. The spread across folds is the useful output: a result
that holds in one fold and collapses in the next was a property of that fold.

**Block bootstrap.** Resampling contiguous blocks of trades rather than individual
ones. Trades are not independent -- they cluster in regimes -- and resampling them
one at a time understates the uncertainty by pretending they are.

None of this makes a result true. It makes the claim honest about how much the
data actually supports.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from traidingbrain.sim.broker import Fill
from traidingbrain.sim.engine import BacktestEngine, BacktestResult, Strategy
from traidingbrain.sim.metrics import Interval

#: Trades per resampled block. Long enough to keep a regime intact, short enough
#: that a few hundred trades still produce a varied resample.
BLOCK_SIZE = 10

#: Resamples for the block bootstrap.
BOOTSTRAP_SAMPLES = 4000

#: Fewest folds that can disagree with each other.
MIN_FOLDS = 2

#: Trades below which a single window establishes nothing.
MIN_TRADES_PER_WINDOW = 30

#: And across every fold together.
MIN_TRADES_TOTAL = 60


def human(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class Window:
    """A named time range."""

    name: str
    start_ts: int
    end_ts: int

    @property
    def days(self) -> float:
        return (self.end_ts - self.start_ts) / 86_400_000

    def __str__(self) -> str:
        return f"{self.name}: {human(self.start_ts)} to {human(self.end_ts)} ({self.days:.0f}d)"


def split(first_ts: int, last_ts: int, train_fraction: float = 0.5) -> tuple[Window, Window]:
    """Chronological split. Never random.

    A random split over time series leaks: the test set surrounds the training set,
    and the model is effectively told what happened on either side of every gap.
    """
    if not 0.0 < train_fraction < 1.0:
        raise ValueError(f"train_fraction must be strictly between 0 and 1, got {train_fraction}")
    boundary = first_ts + int((last_ts - first_ts) * train_fraction)
    return (
        Window("in-sample", first_ts, boundary),
        Window("out-of-sample", boundary, last_ts),
    )


def walk_forward(first_ts: int, last_ts: int, folds: int = 4) -> list[tuple[Window, Window]]:
    """Consecutive train/test pairs, each testing on data after its own training.

    Anchored rather than rolling: the training window always starts at the
    beginning and grows. That matches how the system would actually be operated --
    nothing is ever forgotten on purpose.
    """
    if folds < MIN_FOLDS:
        raise ValueError(f"at least {MIN_FOLDS} folds are needed to compare anything, got {folds}")
    span = last_ts - first_ts
    step = span // (folds + 1)
    pairs: list[tuple[Window, Window]] = []
    for fold in range(folds):
        train_end = first_ts + step * (fold + 1)
        test_end = min(last_ts, train_end + step)
        pairs.append(
            (
                Window(f"fold {fold + 1} train", first_ts, train_end),
                Window(f"fold {fold + 1} test", train_end, test_end),
            )
        )
    return pairs


def block_bootstrap(
    fills: list[Fill],
    *,
    block_size: int = BLOCK_SIZE,
    samples: int = BOOTSTRAP_SAMPLES,
    confidence: float = 0.95,
    seed: int = 17,
) -> Interval:
    """Expectancy interval that respects how trades cluster.

    Resampling single trades assumes they are independent. They are not: a strategy
    in a trending market takes a run of winners and then a run of losers when the
    trend ends, and treating those as interchangeable draws makes the interval
    narrower than the evidence supports. Resampling contiguous blocks keeps the
    clustering and produces an honest -- wider -- answer.
    """
    values = np.array([fill.r_multiple for fill in fills], dtype="float64")
    if values.size == 0:
        return Interval(0.0, 0.0, 0.0)
    if values.size <= block_size:
        return Interval(float(values.mean()), float(values.min()), float(values.max()))

    rng = np.random.default_rng(seed)
    blocks_needed = int(np.ceil(values.size / block_size))
    max_start = values.size - block_size

    means = np.empty(samples, dtype="float64")
    for i in range(samples):
        starts = rng.integers(0, max_start + 1, size=blocks_needed)
        drawn = np.concatenate([values[s : s + block_size] for s in starts])[: values.size]
        means[i] = drawn.mean()

    tail = (1.0 - confidence) / 2.0
    return Interval(
        value=float(values.mean()),
        low=float(np.quantile(means, tail)),
        high=float(np.quantile(means, 1.0 - tail)),
    )


@dataclass
class FoldResult:
    window: Window
    result: BacktestResult

    @property
    def expectancy(self) -> float:
        return self.result.metrics.expectancy_r.value

    @property
    def trades(self) -> int:
        return self.result.metrics.trades


@dataclass
class Evaluation:
    """What several runs of one strategy, over different periods, add up to."""

    strategy: str
    folds: list[FoldResult]

    @property
    def expectancies(self) -> list[float]:
        return [fold.expectancy for fold in self.folds if fold.trades > 0]

    @property
    def total_trades(self) -> int:
        return sum(fold.trades for fold in self.folds)

    @property
    def positive_folds(self) -> int:
        return sum(1 for value in self.expectancies if value > 0)

    @property
    def spread(self) -> float:
        """Standard deviation of expectancy across folds.

        The number that says how much of a headline result was the period rather
        than the strategy.
        """
        values = self.expectancies
        return float(np.std(values, ddof=1)) if len(values) > 1 else 0.0

    def verdict(self) -> str:
        values = self.expectancies
        if not values:
            return "no fold produced a trade"
        if self.total_trades < MIN_TRADES_TOTAL:
            return f"only {self.total_trades} trades across all folds -- nothing is established"
        if self.positive_folds == len(values):
            return f"positive in all {len(values)} folds (spread {self.spread:.2f}R)"
        if self.positive_folds == 0:
            return f"negative in all {len(values)} folds"
        return (
            f"positive in {self.positive_folds} of {len(values)} folds "
            f"(spread {self.spread:.2f}R) -- not consistent"
        )

    def report(self) -> str:
        lines = [f"{self.strategy}"]
        for fold in self.folds:
            metrics = fold.result.metrics
            if fold.trades == 0:
                lines.append(f"  {fold.window.name:<18s} no trades")
                continue
            lines.append(
                f"  {fold.window.name:<18s} "
                f"{human(fold.window.start_ts)}..{human(fold.window.end_ts)}  "
                f"{metrics.trades:>4d} trades  "
                f"E={metrics.expectancy_r.value:+.3f} "
                f"[{metrics.expectancy_r.low:+.3f},{metrics.expectancy_r.high:+.3f}]  "
                f"ret={metrics.total_return_pct:+6.1f}%  dd={metrics.max_drawdown_pct:4.1f}%"
            )
        lines.append(f"  -> {self.verdict()}")
        return "\n".join(lines)


def evaluate(
    engine: BacktestEngine,
    make_strategy: Callable[[], Strategy],
    windows: list[Window],
    label: str,
) -> Evaluation:
    """Run one strategy over several windows, with a fresh strategy each time.

    Fresh each time on purpose: a strategy that carries state -- a random seed, a
    trigger cooldown, an accumulating cache -- would otherwise let one window
    influence the next, which is the leak this whole module exists to avoid.
    """
    folds = [
        FoldResult(
            window=window,
            result=engine.run(make_strategy(), start_ts=window.start_ts, end_ts=window.end_ts),
        )
        for window in windows
    ]
    return Evaluation(strategy=label, folds=folds)


def compare_out_of_sample(in_sample: BacktestResult, out_of_sample: BacktestResult) -> str:
    """How much of an in-sample result survived contact with unseen data.

    A large drop is the normal outcome and worth saying plainly. The question is
    not whether the number falls but whether what remains is still distinguishable
    from zero.
    """
    before = in_sample.metrics.expectancy_r
    after = out_of_sample.metrics.expectancy_r
    lines = [
        f"  in-sample      {before}  over {in_sample.metrics.trades} trades",
        f"  out-of-sample  {after}  over {out_of_sample.metrics.trades} trades",
    ]

    if out_of_sample.metrics.trades < MIN_TRADES_PER_WINDOW:
        lines.append(
            "  -> too few out-of-sample trades to conclude anything; the in-sample "
            "number stands unverified."
        )
        return "\n".join(lines)

    decay = before.value - after.value
    if after.excludes_zero and after.value > 0:
        lines.append(f"  -> the edge survived (gave back {decay:+.3f}R) and still excludes zero.")
    elif after.value > 0:
        lines.append(
            f"  -> still positive but no longer distinguishable from zero "
            f"(gave back {decay:+.3f}R). This is what an in-sample artefact looks like."
        )
    else:
        lines.append(
            f"  -> the edge did not survive (gave back {decay:+.3f}R). The in-sample "
            f"result was a property of that period."
        )
    return "\n".join(lines)


@dataclass
class PooledResult:
    """Several symbols' trades treated as one sample.

    This is where the statistical power comes from. One symbol over two and a half
    years produces a hundred and fifty trades, and a hundred and fifty trades
    cannot distinguish a small edge from nothing. Four symbols over the same period
    produce six hundred, and six hundred can.

    The pooling is legitimate only because every symbol is run under identical
    rules and results are measured in R -- multiples of the amount risked -- which
    is unit-free and therefore comparable across instruments of wildly different
    price and volatility. Pooling raw profit would be meaningless.

    What it does not fix: the four symbols are all crypto majors and move together.
    Six hundred correlated trades are worth less than six hundred independent ones,
    which is why the block bootstrap is the interval to read.
    """

    label: str
    per_symbol: dict[str, BacktestResult]

    @property
    def fills(self) -> list[Fill]:
        pooled: list[Fill] = []
        for result in self.per_symbol.values():
            pooled.extend(result.fills)
        return sorted(pooled, key=lambda fill: fill.closed_ts)

    @property
    def trades(self) -> int:
        return len(self.fills)

    @property
    def expectancy(self) -> Interval:
        return block_bootstrap(self.fills)

    @property
    def win_rate(self) -> float:
        fills = self.fills
        if not fills:
            return 0.0
        return sum(1 for fill in fills if fill.net_pnl > 0) / len(fills)

    def report(self) -> str:
        lines = [f"{self.label}"]
        for symbol, result in sorted(self.per_symbol.items()):
            metrics = result.metrics
            lines.append(
                f"  {symbol:<9s} {metrics.trades:>4d} trades  "
                f"E={metrics.expectancy_r.value:+.3f}  "
                f"ret={metrics.total_return_pct:+6.1f}%  dd={metrics.max_drawdown_pct:4.1f}%"
            )
        interval = self.expectancy
        lines.append(
            f"  {'POOLED':<9s} {self.trades:>4d} trades  E={interval}  win {self.win_rate:.1%}"
        )
        lines.append(f"  -> {self._verdict(interval)}")
        return "\n".join(lines)

    def _verdict(self, interval: Interval) -> str:
        if self.trades < MIN_TRADES_TOTAL:
            return f"only {self.trades} trades pooled -- nothing is established"
        if not interval.excludes_zero:
            return (
                "the pooled expectancy interval spans zero: across every symbol and "
                "the whole window, this is not distinguishable from no edge"
            )
        direction = "positive" if interval.value > 0 else "negative"
        return (
            f"pooled expectancy is {direction} and excludes zero -- "
            f"note the symbols are correlated, so treat this as weaker than the count suggests"
        )
