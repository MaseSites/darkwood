"""Does the liquidity balance say anything about what price does next?

    python scripts/study_liquidity.py
    python scripts/study_liquidity.py --timeframe H4 --horizons 4,12,24

The indicator's hypothesis, from the TikTok it was copied from: price travels
toward the heavier untouched side. More weight above should mean price tends to
rise.

**Tested as a feature, not as a strategy, and that order is deliberate.** The
usual way round is to build entry rules on the feature, backtest them, and read
the result. Six levers were measured that way today -- markets, cadence, which
setup, a score veto, a breakeven stop, the cost ceiling -- and every one changed
how often the system traded without changing whether it made money, because
none of them touched the entry signal. The measurement that mattered was the
one taken last: gross expectancy, before costs, is -0.01 R with an interval of
[-0.070, +0.051]. The entries are a coin.

So the question for anything new is not "does a strategy built on it profit",
which confounds the feature with the rules wrapped around it. It is "does this
number, known at the close of a bar, relate to the return that follows". If it
does not, no strategy built on it can, and a backtest that says otherwise is
describing its own parameters.

**What is measured.** At every bar, the share of live zone weight above the
price. Then the return over the next N bars, in ATR so markets and eras
compare. Grouped into buckets by lean, reported with bootstrap intervals, and
tested for the one thing the hypothesis actually claims: monotonicity. If price
goes where the weight is, the buckets must step in order. A single bucket that
looks good is what noise produces.

Both directions are reported, because the prompt is right that the opposite is
equally plausible: a level above can be a target or it can be resistance.

**Measured on 04.10.2026, twelve markets, 619,037 bars.** The hypothesis is
wrong and its opposite is closer to right, but neither is the finding. What the
data says is one-sided:

    168 Kerzen (eine Woche)        Grundlinie +0.761 ATR
      Gewicht fast ganz unten      +1.068   (+0.31)
      mehrheitlich unten           +0.937   (+0.18)
      ausgeglichen                 +1.122   (+0.36)
      mehrheitlich oben            +0.537   (-0.22)
      fast ganz oben               -0.195   (-0.96)

The bottom four buckets do not order. The top one does something no other
condition in the whole record does: it goes negative, in markets that rose,
and sits a full ATR below the average week. The slope grows linearly with the
horizon -- -0.117, -0.224, -0.477, -0.710 at 24, 48, 96 and 168 bars -- which
is a drift relationship rather than a short-lived inefficiency.

**The intervals were too narrow, and are now corrected.** Forward returns from
consecutive bars overlap: at a 168-bar horizon two neighbouring observations
share 167 of their 168 bars. The first version resampled all 619,037 as though
they were independent, when the effective count is closer to 619,037 / 168 ~
3,700 -- so it printed "Null ausgeschlossen" on lines that had not earned it,
and said so in this docstring while shipping the verdict anyway.

The fix is the block bootstrap from `reporting.intervals`, with the block long
enough that overlapping observations cannot be split apart. For the baseline
that length is the horizon. For a bucket it is the horizon scaled by the
bucket's share of the bars, because a bucket holding a fifth of them has its
members about five bars apart and a 168-bar window therefore spans about 34 of
them, not 168. `suggested_block` is a floor on top of that, since a trending
market carries serial correlation beyond the overlap alone.

The report now prints the block length and how much wider the correction made
the interval, so the factor is a measurement rather than this docstring's
estimate. The slope line got the same treatment; it was the most confident line
in the output and had exactly the same flaw.
"""

from __future__ import annotations

import argparse
import math
import sys
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.analysis.indicators import atr
from traidingbrain.analysis.liquidity_levels import balance_at, find_zones
from traidingbrain.analysis.structure import StructureTimeline
from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.reporting.intervals import (
    Interval,
    block_bootstrap,
    suggested_block,
)

BOOT = 3000

#: Bars skipped at the start so the volume baseline and the swings are warm.
WARMUP = 700

#: Lean buckets. Lean is above-minus-below over the total, so -1 is all weight
#: below the price and +1 is all above.
EDGES = (-0.6, -0.2, 0.2, 0.6)

#: Fewest observations before a bucket is reported with an interval.
MIN_BUCKET = 200

#: Buckets needed before "monotone" means anything. Two always step one way.
MIN_FOR_SHAPE = 3


def report_widening(rets: np.ndarray, corrected: Interval) -> None:
    """What the overlap correction cost, measured rather than estimated.

    The docstring used to put the factor at "roughly thirteen times" from the
    effective sample size. This prints the actual number, and with it the
    verdict the uncorrected interval would have claimed -- which is the whole
    point, because that verdict was printed for weeks.
    """
    naive = block_bootstrap(rets, block=1, draws=BOOT)
    if naive is None or naive.high <= naive.low:
        return
    widening = (corrected.high - corrected.low) / (naive.high - naive.low)
    claimed = " und schloss die Null aus" if naive.excludes_zero else ""
    print(
        f"  Blocklaenge {corrected.block} Kerzen -> {widening:.1f}x breiter "
        "als ohne Ueberlappungskorrektur."
    )
    print(f"  Unkorrigiert waere es {naive}{claimed} gewesen.")


def overlap_block(n_group: int, n_all: int, horizon: int) -> int:
    """How many consecutive observations of a group share bars with each other.

    Two forward returns starting fewer than `horizon` bars apart overlap, so a
    resample that can split them apart treats dependent observations as
    independent and reports an interval far narrower than the data supports.
    Keeping them inside one block is the standard treatment for overlapping
    returns.

    The horizon alone would be right for the baseline, which uses every bar.
    For a bucket it over-corrects: a bucket holding a share `p` of the bars has
    its members roughly `1/p` bars apart, so a window of `horizon` bars spans
    only about `horizon * p` of them. Scaling by the share is what makes the
    correction match the actual overlap instead of the worst case.
    """
    share = n_group / n_all if n_all else 1.0
    return max(1, math.ceil(horizon * share))


def interval(values: np.ndarray, *, horizon: int, n_all: int, seed: int = 11) -> Interval | None:
    """A block bootstrap, with the block long enough to hold the overlap.

    `suggested_block` is a floor, not an override: it measures the serial
    correlation that is actually in the series, which can run longer than the
    overlap alone when the market itself trends.
    """
    block = max(overlap_block(len(values), n_all, horizon), suggested_block(values))
    return block_bootstrap(values, block=block, draws=BOOT, seed=seed)


def slope_interval(
    leans: np.ndarray, rets: np.ndarray, *, horizon: int, draws: int = 400, seed: int = 5
) -> tuple[float, float]:
    """The same correction for the slope, which overlaps exactly as much.

    The earlier version resampled indices independently, so it inherited the
    whole problem the buckets had, and it was the line that printed "Null
    ausgeschlossen" most confidently.
    """
    n = len(leans)
    length = max(overlap_block(n, n, horizon), suggested_block(rets))
    count = math.ceil(n / length)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(draws, count))
    offsets = np.arange(length)
    picks = (starts[:, :, None] + offsets[None, None, :]) % n
    flat = picks.reshape(draws, count * length)[:, :n]
    slopes = np.array([np.polyfit(leans[row], rets[row], 1)[0] for row in flat])
    return float(np.percentile(slopes, 2.5)), float(np.percentile(slopes, 97.5))


def bucket_of(lean: float) -> int:
    for i, edge in enumerate(EDGES):
        if lean < edge:
            return i
    return len(EDGES)


def label_of(i: int) -> str:
    if i == 0:
        return f"lean < {EDGES[0]}"
    if i == len(EDGES):
        return f"lean >= {EDGES[-1]}"
    return f"{EDGES[i - 1]} .. {EDGES[i]}"


def collect(
    symbols: list[str], timeframe: Timeframe, horizons: list[int]
) -> dict[int, list[tuple[float, float]]]:
    """Every (lean, forward return in ATR) pair, per horizon."""
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    out: dict[int, list[tuple[float, float]]] = {h: [] for h in horizons}

    for symbol in symbols:
        frame = store.read(symbol, timeframe)
        if frame.empty or len(frame) < WARMUP * 2:
            print(f"  {symbol}: zu wenig Daten", flush=True)
            continue

        structure = StructureTimeline(
            frame,
            lookback=config.engine.structure.swing_lookback,
            max_sequence_length=config.engine.structure.max_sequence_length,
        )
        zones = find_zones(frame, structure)
        units = atr(frame, config.engine.indicators.atr_period).to_numpy(dtype="float64")
        closes = frame["close"].to_numpy(dtype="float64")
        longest = max(horizons)

        pairs = 0
        for i in range(WARMUP, len(frame) - longest):
            unit = units[i]
            if not np.isfinite(unit) or unit <= 0:
                continue
            lean = balance_at(zones, i, float(closes[i])).lean
            if lean is None:
                continue
            for h in horizons:
                out[h].append((lean, float((closes[i + h] - closes[i]) / unit)))
            pairs += 1
        print(f"  {symbol}: {pairs} Kerzen, {len(zones)} Zonen", flush=True)
    return out


def report(horizon: int, pairs: list[tuple[float, float]]) -> None:
    if not pairs:
        print(f"\n{horizon} Kerzen voraus: keine Daten")
        return
    leans = np.array([p[0] for p in pairs], dtype="float64")
    rets = np.array([p[1] for p in pairs], dtype="float64")

    # The unconditional mean, first and always. Without it a bucket mean cannot
    # be read: BTC rose 305% over this period, so "+0.16 ATR over 24 bars"
    # could be well above the drift or well below it. The first version of this
    # report printed the buckets and left out the line they have to be read
    # against, which made every number in it uninterpretable.
    base = float(np.mean(rets))
    n_all = len(rets)
    base_iv = interval(rets, horizon=horizon, n_all=n_all)
    if base_iv is None:
        print(f"\n{horizon} Kerzen voraus: zu wenige Beobachtungen")
        return
    print(f"\n{horizon} Kerzen voraus   ({n_all} Beobachtungen)")
    print(f"  Grundlinie (alle Kerzen) {base:+.4f} ATR   {base_iv.labelled()}")

    # What the overlap correction costs, measured rather than estimated. The
    # docstring used to say "roughly thirteen times wider" from the effective
    # sample size; this prints the actual factor, and it is the number that
    # decides which lines below have earned their verdict.
    report_widening(rets, base_iv)
    print(
        f"  {'Gewicht oberhalb':24s} {'n':>7s} {'Rendite':>10s} "
        f"{'ggue. Grundlinie':>17s}   Intervall"
    )
    means: list[float] = []
    for i in range(len(EDGES) + 1):
        mask = np.array([bucket_of(x) == i for x in leans])
        group = rets[mask]
        if len(group) < MIN_BUCKET:
            print(f"  {label_of(i):24s} {len(group):>7d}   zu wenige")
            means.append(float("nan"))
            continue
        group_iv = interval(group, horizon=horizon, n_all=n_all)
        if group_iv is None:
            print(f"  {label_of(i):24s} {len(group):>7d}   zu wenige")
            means.append(float("nan"))
            continue
        lo, hi = group_iv.low, group_iv.high
        mean = float(np.mean(group))
        means.append(mean)
        # Against the drift, not against zero. In a market that tripled,
        # "better than nothing" is the wrong bar -- the question is whether
        # knowing the lean beats not knowing it.
        flag = "" if lo < base < hi else "  <- vom Durchschnitt unterscheidbar"
        print(
            f"  {label_of(i):24s} {len(group):>7d} {mean:>+10.4f} {mean - base:>+17.4f}   "
            f"[{lo:+.4f}, {hi:+.4f}]{flag}"
        )

    usable = [m for m in means if np.isfinite(m)]
    if len(usable) >= MIN_FOR_SHAPE:
        rising = all(a <= b for a, b in pairwise(usable))
        falling = all(a >= b for a, b in pairwise(usable))
        spread = max(usable) - min(usable)
        print(f"  Spanne ueber die Eimer: {spread:.4f} ATR")
        if rising:
            print("  Monoton steigend -- in Richtung der Hypothese (Kurs laeuft zum Gewicht).")
        elif falling:
            print("  Monoton fallend -- Gegenteil der Hypothese (Gewicht wirkt als Widerstand).")
        else:
            print("  Nicht monoton. Die Hypothese verlangt eine Ordnung; hier ist keine.")

    # The straight line through the cloud. A monotone step pattern and a slope
    # are different claims, and the hypothesis is about both.
    slope, _ = np.polyfit(leans, rets, 1)
    lo, hi = slope_interval(leans, rets, horizon=horizon)
    mark = "" if lo < 0 < hi else "  <- Null ausgeschlossen"
    print(f"  Steigung {slope:+.4f} ATR je Einheit lean   [{lo:+.4f}, {hi:+.4f}]{mark}")


def main() -> int:
    config = load_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--horizons", default="4,12,24")
    parser.add_argument("--symbol", action="append")
    args = parser.parse_args()

    timeframe = Timeframe(args.timeframe)
    horizons = [int(x) for x in args.horizons.split(",")]
    symbols = args.symbol or list(config.engine.symbols.active)

    print(f"Liquidity-Balance gegen Folgerendite, {timeframe.value}, {len(symbols)} Maerkte\n")
    pairs = collect(symbols, timeframe, horizons)
    for horizon in horizons:
        report(horizon, pairs[horizon])

    print(
        "\nGemessen wird das Merkmal, nicht eine Strategie darauf. Ohne Zusammenhang\n"
        "hier kann keine Regel auf dieser Grundlage einen haben."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
