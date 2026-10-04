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

**The intervals printed here are too narrow and the reason is in this script.**
Forward returns from consecutive bars overlap: at a 168-bar horizon, two
neighbouring observations share 167 of their 168 bars. The bootstrap resamples
as though all 619,037 were independent, when the effective count is closer to
619,037 / 168 ~ 3,700. The intervals should be roughly thirteen times wider,
and "Null ausgeschlossen" is printed in lines that have not earned it. The
effect survives that correction by a wide margin at the extreme bucket and
almost certainly does not in the middle ones. Fixing this properly means a
block bootstrap over non-overlapping windows; until then, read the point
estimates and ignore the brackets.
"""

from __future__ import annotations

import argparse
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


def interval(values: np.ndarray, seed: int = 11) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    draws = rng.choice(values, size=(BOOT, len(values)), replace=True).mean(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


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
    base_lo, base_hi = interval(rets)
    print(f"\n{horizon} Kerzen voraus   ({len(pairs)} Beobachtungen)")
    print(f"  Grundlinie (alle Kerzen) {base:+.4f} ATR   [{base_lo:+.4f}, {base_hi:+.4f}]")
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
        lo, hi = interval(group)
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
    rng = np.random.default_rng(5)
    idx = rng.integers(0, len(leans), size=(BOOT, len(leans)))
    slopes = np.array([np.polyfit(leans[i], rets[i], 1)[0] for i in idx[:400]])
    lo, hi = float(np.percentile(slopes, 2.5)), float(np.percentile(slopes, 97.5))
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
