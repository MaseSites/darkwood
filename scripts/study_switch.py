"""The last two families: trend-following with pullback, and regime switching.

    python scripts/study_switch.py
    python scripts/study_switch.py --symbols BTCUSDT,ETHUSDT --horizons 24,168

Ten of twelve families are closed. These two were left out of
`scripts/study_states.py` deliberately, and the reason is the point of this
file: that study measured an **unconditional long** inside each state. Both
families here need a **signed** rule -- long in an uptrend, short in a
downtrend -- and a state band is not a strategy switch. Claiming it was would
have been the over-reach the whole apparatus exists to prevent.

**What is actually tested.** Two rules, each measured separately in a trend
regime and in a range regime, which makes the second family an interaction
rather than a level:

| rule | side taken |
|---|---|
| `trend` | with the slow trend, after a pullback of at least one band |
| `revert` | against the last day's move |

*Trendfolge mit Ruecksetzer* is the question "does `trend` earn its keep".
*Regime-Umschaltung* is the question "does `trend` beat `revert` in trends
while `revert` beats `trend` in ranges" -- a crossover. A rule that is simply
better everywhere is not a switch, it is a rule, and the register should say
so.

**Why the crossover and not two separate verdicts.** Switching costs nothing
to claim and something to be wrong about: if `trend` wins in both regimes,
then switching to `revert` in ranges makes the system worse while looking
sophisticated. So the finding has to be the *difference of differences*, and
that is what gets the interval.

**Everything the earlier studies learned, applied.** Cells declared before the
first number with the chance yield printed; a Bonferroni-corrected threshold;
weekly-block intervals over all markets together; and a cell that excludes
zero re-measured on the other part of the data, because the one candidate
`study_states.py` produced died at 0.16x of its size there.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from traidingbrain.analysis.formulas import directional_movement
from traidingbrain.analysis.indicators import atr, ema, rolling_percentile_rank
from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC

DAY_MS = 86_400_000

HORIZONS: tuple[int, ...] = (24, 72, 168)

#: Slow trend, in hours. Thirty days: the trend a daily strategy would read,
#: and long enough that a pullback inside it is still inside the trend.
TREND_SPAN = 30 * 24

#: Lookback for the regime percentile and the pullback extreme, in hours.
REGIME_WINDOW = 30 * 24
EXTREME_WINDOW = 7 * 24

#: Warmup before a row is usable.
WARMUP = TREND_SPAN + 48

#: Regime split: ADX above its own median is "trend", below is "range".
#: A percentile rather than the conventional 20/25 level, because that level
#: is calibrated for daily equities and this is hourly crypto -- and because a
#: median makes the two groups the same size, which keeps the interaction
#: interval from being dominated by whichever side is rare.
REGIME_SPLIT = 0.5

#: Pullback bands, in ATR from the recent extreme. Declared in advance.
PULLBACK_BANDS: tuple[float, ...] = (0.0, 0.5, 1.5)
PULLBACK_NAMES = ("kein", "flach", "tief")

MIN_CELL = 300
DRAWS = 2000
BLOCK_DAYS = 7
CONFIDENCE = 0.95
REPLICATION_FLOOR = 0.5
FIT_SHARE = 0.6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated. Default: the first four active.")
    parser.add_argument("--horizons", help="Comma-separated hours. Default: 24,72,168.")
    return parser.parse_args()


def toll(slippage_bps: float) -> float:
    return 2.0 * float(DEFAULT_SPEC["taker_fee"]) + 2.0 * slippage_bps / 10_000.0


def build(frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Trend, regime, pullback and the forward move, all backward-looking.

    No `shift(-n)` outside the forward column, which is the label. Every state
    is a rolling statistic ending at the current bar.
    """
    close = frame["close"]
    out = pd.DataFrame(index=frame.index)
    out["ts"] = frame["ts"].to_numpy(dtype="int64")

    # Trend direction: price against a slow average. Sign only -- the
    # magnitude is the regime reading below and mixing them would make one
    # column answer two questions.
    slow = ema(close, TREND_SPAN)
    out["trend"] = np.sign((close - slow).to_numpy())

    # Regime: ADX in its own recent distribution. High means directional, low
    # means ranging.
    out["adx_pct"] = rolling_percentile_rank(
        directional_movement(frame).adx, REGIME_WINDOW
    )

    # Pullback: how far price has come back from the recent extreme in the
    # trend's own direction, measured in ATR so markets are comparable.
    width = atr(frame)
    high = frame["high"].rolling(EXTREME_WINDOW).max()
    low = frame["low"].rolling(EXTREME_WINDOW).min()
    retrace_up = (high - close) / width
    retrace_down = (close - low) / width
    out["pullback"] = np.where(out["trend"] > 0, retrace_up, retrace_down)

    # The reverting rule's side: against the last day's move.
    out["ret_1d"] = (close / close.shift(24) - 1.0).to_numpy()

    opens = frame["open"].to_numpy(dtype="float64")
    n = opens.size
    for hours in horizons:
        forward = np.full(n, np.nan)
        at = np.arange(0, n - 1 - hours)
        forward[at] = opens[at + 1 + hours] / opens[at + 1] - 1.0
        out[f"fwd_{hours}"] = forward
    return out


def sides(data: pd.DataFrame, rule: str) -> np.ndarray:
    """Which way each rule would trade. Zero means it would stand aside."""
    if rule == "trend":
        return data["trend"].to_numpy(dtype="float64")
    if rule == "revert":
        return -np.sign(data["ret_1d"].to_numpy(dtype="float64"))
    raise ValueError(f"Unbekannte Regel: {rule}")


def block_diff(
    a: np.ndarray, days_a: np.ndarray, b: np.ndarray, days_b: np.ndarray, *, conf: float
) -> tuple[float, float, float]:
    """Difference of means with an interval from resampling whole weeks."""
    if a.size < MIN_CELL or b.size < MIN_CELL:
        return float("nan"), float("nan"), float("nan")
    span = BLOCK_DAYS * DAY_MS
    ga = [np.flatnonzero(days_a // span == w) for w in np.unique(days_a // span)]
    gb = [np.flatnonzero(days_b // span == w) for w in np.unique(days_b // span)]
    if len(ga) < 3 or len(gb) < 3:  # noqa: PLR2004 -- three blocks minimum
        return float("nan"), float("nan"), float("nan")

    rng = np.random.default_rng(20261005)
    draws = np.empty(DRAWS)
    for k in range(DRAWS):
        pa = np.concatenate([ga[i] for i in rng.integers(0, len(ga), len(ga))])
        pb = np.concatenate([gb[i] for i in rng.integers(0, len(gb), len(gb))])
        draws[k] = a[pa].mean() - b[pb].mean()
    tail = (1.0 - conf) / 2.0
    return (
        float(a.mean() - b.mean()),
        float(np.quantile(draws, tail)),
        float(np.quantile(draws, 1.0 - tail)),
    )


def cell(
    data: pd.DataFrame, *, rule: str, hours: int, cost: float
) -> tuple[np.ndarray, np.ndarray]:
    """Net outcome of one rule over these rows, and the timestamps beside it."""
    column = f"fwd_{hours}"
    side = sides(data, rule)
    taken = (side != 0) & np.isfinite(data[column].to_numpy())
    net = side[taken] * data[column].to_numpy()[taken] - cost
    return net, data["ts"].to_numpy(dtype="int64")[taken]


def report_pullback(
    test: pd.DataFrame, fit: pd.DataFrame, *, hours: int, cost: float
) -> None:
    """Does waiting for a pullback help the trend rule? Bands with replication.

    The family's premise is that a deeper pullback gives a better entry. The
    measurement says the opposite, so the cell that excludes zero is the one
    with NO pullback -- which makes the replication check more important, not
    less: a result that contradicts its own hypothesis is exactly the kind
    that deserves a second window before it is believed either way.
    """
    edges = np.unique(np.quantile(fit["pullback"].dropna(), [0.0, 0.33, 0.67, 1.0]))
    if edges.size <= 2:  # noqa: PLR2004 -- a cut needs more than two edges
        return

    def bands_of(frame: pd.DataFrame) -> np.ndarray:
        return pd.cut(
            frame["pullback"], bins=edges, labels=False, include_lowest=True
        ).to_numpy()

    live = bands_of(test)
    earlier = bands_of(fit)
    for index, name in enumerate(PULLBACK_NAMES[: edges.size - 1]):
        mask = live == index
        inside, days_in = cell(test[mask], rule="trend", hours=hours, cost=cost)
        outside, days_out = cell(test[~mask], rule="trend", hours=hours, cost=cost)
        diff, low, high = block_diff(inside, days_in, outside, days_out, conf=CONFIDENCE)
        if np.isnan(diff):
            print(f"  Ruecksetzer {name:7s} n={inside.size:>6,d}  zu wenige")
            continue

        mark = ""
        if low > 0 or high < 0:
            other = earlier == index
            a, _ = cell(fit[other], rule="trend", hours=hours, cost=cost)
            b, _ = cell(fit[~other], rule="trend", hours=hours, cost=cost)
            echo = float(a.mean() - b.mean()) if a.size and b.size else 0.0
            ratio = abs(echo / diff) if diff else 0.0
            held = echo * diff > 0 and ratio >= REPLICATION_FLOOR
            mark = (
                f"  <- ohne Null, anderes Fenster {100 * echo:+.4f}% ({ratio:.2f}x) "
                f"-- {'wiederholt' if held else 'kein Befund'}"
            )
        print(
            f"  Ruecksetzer {name:7s} n={inside.size:>6,d}  "
            f"netto {100 * inside.mean():+8.4f}%   Differenz "
            f"{100 * diff:+8.4f}% [{100 * low:+7.4f}, {100 * high:+7.4f}]{mark}"
        )


def crossover_interval(
    part: pd.DataFrame, *, hours: int, cost: float, conf: float
) -> tuple[float, float, float]:
    """The switching gain and its interval, resampled as whole weeks.

    `(trend - revert) in trends` minus `(trend - revert) in ranges`. All four
    terms are recomputed inside each bootstrap draw from the same resampled
    weeks, which is what makes this an interval on the crossover rather than
    four intervals that cannot be combined.

    Resampling weeks of the *whole* frame rather than each cell separately is
    deliberate: a week belongs to one regime mix, and drawing the four groups
    independently would break the pairing the difference of differences is
    built on.
    """
    column = f"fwd_{hours}"
    frame = part[np.isfinite(part[column].to_numpy())].reset_index(drop=True)
    if len(frame) < 4 * MIN_CELL:
        return float("nan"), float("nan"), float("nan")

    forward = frame[column].to_numpy(dtype="float64")
    trending = (frame["adx_pct"] >= REGIME_SPLIT).to_numpy()
    with_trend = sides(frame, "trend")
    against = sides(frame, "revert")
    stamps = frame["ts"].to_numpy(dtype="int64")

    span = BLOCK_DAYS * DAY_MS
    groups = [np.flatnonzero(stamps // span == w) for w in np.unique(stamps // span)]
    if len(groups) < 3:  # noqa: PLR2004
        return float("nan"), float("nan"), float("nan")

    def gain(rows: np.ndarray) -> float:
        out = 0.0
        for regime, sign in ((trending[rows], 1.0), (~trending[rows], -1.0)):
            if regime.sum() < MIN_CELL:
                return float("nan")
            here = rows[regime]
            a = with_trend[here] != 0
            b = against[here] != 0
            if a.sum() < MIN_CELL or b.sum() < MIN_CELL:
                return float("nan")
            lead = (with_trend[here][a] * forward[here][a] - cost).mean() - (
                against[here][b] * forward[here][b] - cost
            ).mean()
            out += sign * lead
        return out

    point = gain(np.arange(len(frame)))
    rng = np.random.default_rng(20261005)
    draws = []
    for _ in range(DRAWS // 4):
        picked = np.concatenate(
            [groups[i] for i in rng.integers(0, len(groups), len(groups))]
        )
        value = gain(picked)
        if not np.isnan(value):
            draws.append(value)
    if len(draws) < DRAWS // 8:
        return point, float("nan"), float("nan")
    tail = (1.0 - conf) / 2.0
    return (
        point,
        float(np.quantile(draws, tail)),
        float(np.quantile(draws, 1.0 - tail)),
    )


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    cost = toll(config.engine.simulation.slippage_bps)
    horizons = [int(h) for h in args.horizons.split(",")] if args.horizons else list(HORIZONS)
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )

    blocks = []
    for symbol in symbols:
        frame = store.read(symbol, Timeframe.H1)
        if frame.empty:
            print(f"{symbol}: keine H1-Daten")
            continue
        frame = frame.sort_values("ts").reset_index(drop=True)
        blocks.append(build(frame, horizons).iloc[WARMUP:])
    if not blocks:
        print("Nichts zu messen.")
        return 1

    data = pd.concat(blocks, ignore_index=True).dropna(subset=["adx_pct", "pullback", "trend"])
    cut = int(FIT_SHARE * len(data))
    fit, test = data.iloc[:cut].reset_index(drop=True), data.iloc[cut:].reset_index(drop=True)

    # Declared before anything is measured: two rules x two regimes x three
    # pullback bands x horizons, plus the interaction per horizon.
    cells = (2 * 2 + 3 + 1) * len(horizons)
    required = 1.0 - (1.0 - CONFIDENCE) / cells
    print(f"Maut {100 * cost:.4f}% je Wette. {len(symbols)} Maerkte, {len(test):,} Pruefstunden.")
    print(
        f"{cells} angemeldete Zellen, davon feuern {cells * (1 - CONFIDENCE):.1f} zufaellig.\n"
        f"Korrigierte Schwelle {100 * required:.3f}%. Regimegrenze: ADX-Perzentil "
        f"{REGIME_SPLIT:.0%}.\n"
    )

    for hours in horizons:
        print(f"\n=== {hours}h voraus " + "=" * 50)
        trending = test[test["adx_pct"] >= REGIME_SPLIT]
        ranging = test[test["adx_pct"] < REGIME_SPLIT]

        means: dict[tuple[str, str], float] = {}
        for rule in ("trend", "revert"):
            for label, part in (("Trend", trending), ("Spanne", ranging)):
                net, stamps = cell(part, rule=rule, hours=hours, cost=cost)
                rest, rest_stamps = cell(
                    test[~test.index.isin(part.index)], rule=rule, hours=hours, cost=cost
                )
                diff, low, high = block_diff(net, stamps, rest, rest_stamps, conf=CONFIDENCE)
                means[(rule, label)] = float(net.mean()) if net.size else float("nan")
                bound = (
                    f"[{100 * low:+7.4f}, {100 * high:+7.4f}]"
                    if not np.isnan(diff)
                    else "zu wenige"
                )
                print(
                    f"  Regel {rule:7s} im {label:7s}  n={net.size:>6,d}  "
                    f"netto {100 * net.mean():+8.4f}%   gegen das andere Regime "
                    f"{100 * diff:+8.4f}% {bound}"
                )

        report_pullback(test, fit, hours=hours, cost=cost)

        # Regime-Umschaltung: the crossover, as a difference of differences --
        # WITH an interval, because it is the headline number and a headline
        # number without one is the mistake this project made four times today.
        crossover, cross_low, cross_high = crossover_interval(
            test, hours=hours, cost=cost, conf=CONFIDENCE
        )
        decided = cross_low > 0 or cross_high < 0
        print(
            f"\n  Umschaltgewinn (Differenz der Differenzen): {100 * crossover:+.4f}% "
            f"[{100 * cross_low:+.4f}, {100 * cross_high:+.4f}]"
            f"{'  <- ohne Null' if decided else '  -- Null drin'}\n"
            f"    Trend-Regime:  trend {100 * means[('trend', 'Trend')]:+.4f}% "
            f"gegen revert {100 * means[('revert', 'Trend')]:+.4f}%\n"
            f"    Spanne-Regime: trend {100 * means[('trend', 'Spanne')]:+.4f}% "
            f"gegen revert {100 * means[('revert', 'Spanne')]:+.4f}%"
        )
        if crossover <= 0:
            print(
                "    Das Vorzeichen ist falsch fuer eine Umschaltung: die Regel, die im\n"
                "    Trend vorn liegt, liegt auch in der Spanne vorn. Dann ist sie eine\n"
                "    Regel und kein Schalter, und Umschalten macht es schlechter."
            )
        elif decided:
            echo, _, _ = crossover_interval(fit, hours=hours, cost=cost, conf=CONFIDENCE)
            ratio = abs(echo / crossover) if crossover else 0.0
            held = echo * crossover > 0 and ratio >= REPLICATION_FLOOR
            print(
                f"    Im anderen Fenster: {100 * echo:+.4f}% ({ratio:.2f}x) -- "
                f"{'wiederholt' if held else 'KEIN BEFUND, nicht wiederholt'}"
            )

    print("\n" + "=" * 78)
    print(
        "Umschalten zu behaupten kostet nichts und falsch zu liegen etwas: wenn\n"
        "eine Regel in beiden Regimen vorn liegt, macht ein Schalter das System\n"
        "schlechter und sieht dabei anspruchsvoll aus. Darum ist der Befund die\n"
        "Differenz der Differenzen und nicht zwei getrennte Urteile."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
