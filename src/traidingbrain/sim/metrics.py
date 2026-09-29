"""Backtest metrics, reported with their uncertainty.

Win rate is the number everyone asks for and the least useful one here. A strategy
winning 70% of the time while losing three times what it makes is a losing
strategy, and one winning 35% can be excellent. Expectancy in R -- the average
result as a multiple of what was risked -- is the number that decides whether the
system makes money.

Every headline figure comes with a bootstrap confidence interval, because the
sample sizes involved are small. A year of hourly signals might produce eighty
trades, and eighty trades is not enough to tell a real edge from a lucky run. An
expectancy of +0.15R with an interval spanning -0.1R to +0.4R has not established
anything, and reporting the +0.15 alone would say it had.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from traidingbrain.domain.enums import ExitReason, TradeState
from traidingbrain.sim.broker import Fill

#: Resamples per bootstrap. Enough for a stable interval, cheap enough to run on
#: every backtest.
BOOTSTRAP_SAMPLES = 5000

#: Two-sided 95%.
CONFIDENCE = 0.95

#: Below this many trades, an interval is reported but a verdict is not.
MIN_TRADES_FOR_A_VERDICT = 30

#: A curve needs at least this many points before a return series exists.
MIN_CURVE_POINTS = 3

#: And at least this many returns before a deviation means anything.
MIN_RETURNS = 2

#: Hours in a year, for annualising an hourly-signal Sharpe.
HOURS_PER_YEAR = 24 * 365


@dataclass(frozen=True)
class Interval:
    """A point estimate with the range the data actually supports."""

    value: float
    low: float
    high: float

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0.0 or self.high < 0.0

    def __str__(self) -> str:
        return f"{self.value:+.3f} [{self.low:+.3f}, {self.high:+.3f}]"


def bootstrap_mean(
    values: np.ndarray,
    samples: int = BOOTSTRAP_SAMPLES,
    confidence: float = CONFIDENCE,
    seed: int = 7,
) -> Interval:
    """Resample the trades to see how much of the average is luck.

    Seeded, so a report is reproducible. The seed is not a parameter anyone should
    tune -- a result that depends on it is a result that is not there.
    """
    if values.size == 0:
        return Interval(0.0, 0.0, 0.0)
    if values.size == 1:
        single = float(values[0])
        return Interval(single, single, single)

    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(samples, values.size), replace=True)
    means = draws.mean(axis=1)
    tail = (1.0 - confidence) / 2.0
    return Interval(
        value=float(values.mean()),
        low=float(np.quantile(means, tail)),
        high=float(np.quantile(means, 1.0 - tail)),
    )


def max_drawdown(curve: list[tuple[int, float]]) -> tuple[float, float]:
    """Deepest peak-to-trough fall, as a fraction and in currency.

    Computed on the marked-to-market curve rather than on closed trades. An account
    that went 40% underwater before recovering did experience that, and a drawdown
    number that hides it is not a risk measure.
    """
    if not curve:
        return 0.0, 0.0
    values = np.array([value for _, value in curve], dtype="float64")
    running_peak = np.maximum.accumulate(values)
    falls = running_peak - values
    fractions = np.divide(falls, running_peak, out=np.zeros_like(falls), where=running_peak > 0)
    return float(fractions.max()), float(falls.max())


@dataclass
class BacktestMetrics:
    """Everything a run has to say about itself."""

    label: str
    trades: int
    wins: int
    losses: int
    liquidations: int
    expired_entries: int
    rejected_entries: int

    expectancy_r: Interval
    win_rate: Interval
    profit_factor: float
    total_return_pct: float
    max_drawdown_pct: float
    max_drawdown_abs: float
    sharpe: float
    gross_profit: float
    gross_loss: float
    fees: float
    funding: float
    final_equity: float
    initial_equity: float
    exit_reasons: dict[str, int] = field(default_factory=dict)

    @property
    def has_enough_trades(self) -> bool:
        return self.trades >= MIN_TRADES_FOR_A_VERDICT

    @property
    def verdict(self) -> str:
        """A one-line reading that refuses to overclaim."""
        if self.trades == 0:
            return "no trades"
        if not self.has_enough_trades:
            return (
                f"only {self.trades} trades -- too few to conclude anything "
                f"(need {MIN_TRADES_FOR_A_VERDICT})"
            )
        if not self.expectancy_r.excludes_zero:
            return "expectancy is not distinguishable from zero"
        return "positive expectancy" if self.expectancy_r.value > 0 else "negative expectancy"


def compute_metrics(
    label: str,
    fills: list[Fill],
    equity_curve: list[tuple[int, float]],
    initial_equity: float,
    *,
    expired_entries: int = 0,
    rejected_entries: int = 0,
    bars_per_year: float = HOURS_PER_YEAR,
) -> BacktestMetrics:
    if not fills:
        empty = Interval(0.0, 0.0, 0.0)
        final = equity_curve[-1][1] if equity_curve else initial_equity
        return BacktestMetrics(
            label=label,
            trades=0,
            wins=0,
            losses=0,
            liquidations=0,
            expired_entries=expired_entries,
            rejected_entries=rejected_entries,
            expectancy_r=empty,
            win_rate=empty,
            profit_factor=0.0,
            total_return_pct=(final / initial_equity - 1.0) * 100.0,
            max_drawdown_pct=0.0,
            max_drawdown_abs=0.0,
            sharpe=0.0,
            gross_profit=0.0,
            gross_loss=0.0,
            fees=0.0,
            funding=0.0,
            final_equity=final,
            initial_equity=initial_equity,
        )

    r_multiples = np.array([fill.r_multiple for fill in fills], dtype="float64")
    net = np.array([fill.net_pnl for fill in fills], dtype="float64")
    won = net > 0

    gross_profit = float(net[won].sum())
    gross_loss = float(-net[~won].sum())
    drawdown_pct, drawdown_abs = max_drawdown(equity_curve)
    final_equity = equity_curve[-1][1] if equity_curve else initial_equity

    reasons: dict[str, int] = {}
    for fill in fills:
        reasons[fill.reason.value] = reasons.get(fill.reason.value, 0) + 1

    return BacktestMetrics(
        label=label,
        trades=len(fills),
        wins=int(won.sum()),
        losses=int((~won).sum()),
        liquidations=sum(1 for f in fills if f.state is TradeState.CLOSED_LIQUIDATED),
        expired_entries=expired_entries,
        rejected_entries=rejected_entries,
        expectancy_r=bootstrap_mean(r_multiples),
        win_rate=bootstrap_mean(won.astype("float64")),
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        total_return_pct=(final_equity / initial_equity - 1.0) * 100.0,
        max_drawdown_pct=drawdown_pct * 100.0,
        max_drawdown_abs=drawdown_abs,
        sharpe=_sharpe(equity_curve, bars_per_year),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        fees=float(sum(f.fees for f in fills)),
        funding=float(sum(f.funding for f in fills)),
        final_equity=final_equity,
        initial_equity=initial_equity,
        exit_reasons=reasons,
    )


def _sharpe(curve: list[tuple[int, float]], bars_per_year: float) -> float:
    """Annualised Sharpe on the marked equity curve, with no risk-free rate.

    Reported because it is asked for, and worth less here than expectancy: it
    rewards a smooth curve, and a strategy that trades twenty times a year has a
    curve that is mostly flat by construction.
    """
    if len(curve) < MIN_CURVE_POINTS:
        return 0.0
    values = np.array([value for _, value in curve], dtype="float64")
    returns = np.diff(values) / values[:-1]
    returns = returns[np.isfinite(returns)]
    if returns.size < MIN_RETURNS:
        return 0.0
    deviation = returns.std(ddof=1)
    if deviation == 0:
        return 0.0
    return float(returns.mean() / deviation * np.sqrt(bars_per_year))


def compare(baseline: BacktestMetrics, candidate: BacktestMetrics) -> str:
    """Whether the difference between two runs is worth believing.

    The question is not which number is bigger. Two strategies whose expectancy
    intervals overlap have not been distinguished by this data, however different
    their point estimates look.
    """
    lines = [
        f"{'':28s} {baseline.label:>22s}  {candidate.label:>22s}",
        f"{'trades':28s} {baseline.trades:>22d}  {candidate.trades:>22d}",
        f"{'expectancy (R)':28s} {baseline.expectancy_r!s:>22s}  {candidate.expectancy_r!s:>22s}",
        f"{'win rate':28s} {baseline.win_rate.value:>21.1%}  {candidate.win_rate.value:>21.1%}",
        f"{'profit factor':28s} {baseline.profit_factor:>22.2f}  {candidate.profit_factor:>22.2f}",
        f"{'total return':28s} {baseline.total_return_pct:>21.1f}%  "
        f"{candidate.total_return_pct:>21.1f}%",
        f"{'max drawdown':28s} {baseline.max_drawdown_pct:>21.1f}%  "
        f"{candidate.max_drawdown_pct:>21.1f}%",
    ]

    overlap = not (
        candidate.expectancy_r.low > baseline.expectancy_r.high
        or candidate.expectancy_r.high < baseline.expectancy_r.low
    )
    if not (baseline.has_enough_trades and candidate.has_enough_trades):
        lines.append("\n  Too few trades on at least one side to compare them.")
    elif overlap:
        lines.append(
            "\n  The expectancy intervals overlap: this data does not distinguish "
            "the two, whatever the point estimates suggest."
        )
    else:
        ahead = candidate.expectancy_r.value > baseline.expectancy_r.value
        better = candidate.label if ahead else baseline.label
        lines.append(f"\n  {better} is ahead by more than the sampling noise.")
    return "\n".join(lines)


def format_metrics(metrics: BacktestMetrics) -> str:
    reasons = ", ".join(f"{k}={v}" for k, v in sorted(metrics.exit_reasons.items())) or "none"
    return "\n".join(
        [
            f"{metrics.label}",
            f"  trades          {metrics.trades} ({metrics.wins}W / {metrics.losses}L)",
            f"  expectancy (R)  {metrics.expectancy_r}",
            f"  win rate        {metrics.win_rate.value:.1%} "
            f"[{metrics.win_rate.low:.1%}, {metrics.win_rate.high:.1%}]",
            f"  profit factor   {metrics.profit_factor:.2f}",
            f"  return          {metrics.total_return_pct:+.1f}%  "
            f"({metrics.initial_equity:,.0f} -> {metrics.final_equity:,.0f})",
            f"  max drawdown    {metrics.max_drawdown_pct:.1f}%  ({metrics.max_drawdown_abs:,.0f})",
            f"  sharpe          {metrics.sharpe:.2f}",
            f"  costs           fees {metrics.fees:,.2f}, funding {metrics.funding:+,.2f}",
            f"  exits           {reasons}",
            f"  liquidations    {metrics.liquidations}",
            f"  unfilled        {metrics.expired_entries} expired, "
            f"{metrics.rejected_entries} rejected",
            f"  verdict         {metrics.verdict}",
        ]
    )


__all__ = [
    "BacktestMetrics",
    "ExitReason",
    "Interval",
    "bootstrap_mean",
    "compare",
    "compute_metrics",
    "format_metrics",
    "max_drawdown",
]
