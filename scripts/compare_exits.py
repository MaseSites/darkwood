"""Does moving the stop to the entry help, or does it just cut the winners?

    python scripts/compare_exits.py --at 1.0 0.5

The journal says 19% of two thousand trades were at least one R in profit and
ended as losses, and 35% were stopped by a wick the bar closed back through.
Only 8% never went our way at all. That points at the exit, and this measures
whether the obvious fix is one.

**The rule runs inside the simulator, not beside it.** An earlier version of
this replayed the minute bars in a separate script, and its own self-check
caught it being wrong by 0.074 R -- almost as large as the effect being
measured. It had missed gaps through the stop, liquidations and V08's runner,
each of which the simulator already handles. A rule tested beside the engine is
a second answer to the same question, and the second answer was wrong.

**It cuts both ways by construction.** A stop at the entry saves the trades
that gave a point back and scratches the ones that dipped before running. The
whole question is which of the two is bigger, so a result near zero is a real
answer rather than a failed measurement.

**One history, several rules.** The best of four is the best of four draws.
Intervals are printed; a winner here has earned a forward test, not a promotion.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.sim.engine import load_engine
from traidingbrain.strategies.guide import GuidePool


def run(symbol: str, breakeven: float | None) -> list[float]:
    """Every trade's R for one symbol under one exit rule."""
    config = load_config()
    if breakeven is not None:
        simulation = config.engine.simulation.model_copy(update={"breakeven_at_r": breakeven})
        engine_config = config.engine.model_copy(update={"simulation": simulation})
        config = config.model_copy(update={"engine": engine_config})

    store = ParquetStore(config.engine.paths.parquet_dir)
    frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
    minutes = store.read(symbol, config.engine.timeframes.execution)
    if any(frame.empty for frame in frames.values()) or minutes.empty:
        return []

    engine = load_engine(
        symbol,
        frames,
        minute_frame=minutes,
        spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
        config=config,
        funding=FundingStore(config.engine.paths.funding_dir).read(symbol),
        history=None,
    )
    result = engine.run(GuidePool.for_config(config))
    return [fill.r_multiple for fill in result.fills]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--at",
        type=float,
        nargs="*",
        default=[1.0, 0.5],
        help="move the stop to entry at these R multiples",
    )
    parser.add_argument("--symbol", action="append")
    args = parser.parse_args()

    symbols = args.symbol or list(load_config().engine.symbols.active)
    rules: list[tuple[str, float | None]] = [("ohne (original)", None)]
    rules += [(f"Einstand bei {at:g} R", at) for at in args.at]

    print(f"{len(symbols)} Märkte, Guide-Setups\n")
    baseline: float | None = None
    for label, at in rules:
        values: list[float] = []
        for symbol in symbols:
            values.extend(run(symbol, at))
        if not values:
            print(f"  {label:22s} keine Trades")
            continue
        sample = np.array(values, dtype="float64")
        mean = float(sample.mean())
        error = float(sample.std(ddof=1) / np.sqrt(len(sample)))
        if baseline is None:
            baseline = mean
        # Against the noise, not against the line above. A difference smaller
        # than the standard error is one the data cannot see, and printing it
        # without that comparison invites reading it as one.
        gap = mean - baseline
        verdict = "" if abs(gap) < error else "  <- groesser als der Standardfehler"
        print(
            f"  {label:22s} n={len(sample):5d}  {mean:+.4f} R  +/-{1.96 * error:.4f}"
            f"   Differenz {gap:+.4f}{verdict}"
        )

    print(
        "\nDie Trade-Zahlen unterscheiden sich, weil ein früher beendeter Trade "
        "den nächsten\nEinstieg freigibt. Verglichen werden damit nicht dieselben "
        "Trades mit anderen\nAusstiegen, sondern zwei verschiedene Mengen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
