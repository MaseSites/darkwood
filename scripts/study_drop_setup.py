"""What the pool does without each setup in it.

    python scripts/study_drop_setup.py

A setup's own row says how its trades did. It does not say what dropping it
would do to the whole, and those are different numbers: the pool takes the
first setup to fire, so removing one does not simply delete its trades -- it
lets whatever would have fired next on that bar through instead, and frees the
account for entries that were blocked while its position was open.

So this measures the thing the decision actually turns on. Each run is the same
pool minus one setup, over the same markets and the same four years.

**Setup C is the standing question.** It loses on all four timeframes with an
interval that excludes zero -- the most robust single finding in the project --
but it is Severin's rule and the decision is his. This keeps the number behind
the recommendation current instead of quoting a measurement taken before setup
B existed and before the search went multi-timeframe.

The analysis is built once per symbol and shared by every variant. It does not
depend on which setups are enabled, and rebuilding it costs about eighty
seconds per symbol to recompute the same numbers.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool
from traidingbrain.strategy.setups import TRADEABLE

BOOT = 2000

#: Fewest trades before a group's mean is worth an interval.
MIN_GROUP = 8


def interval(values: list[float], seed: int = 11) -> str:
    if len(values) < MIN_GROUP:
        return "zu wenige"
    rng = np.random.default_rng(seed)
    sample = np.array(values, dtype="float64")
    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)
    low, high = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
    return f"[{low:+.3f}, {high:+.3f}]" + ("" if low < 0 < high else "  <- Null ausgeschlossen")


def variants() -> list[tuple[str, GuidePool]]:
    """The full pool, then the pool without each setup in turn."""
    out = [("alle", GuidePool(name="guide-all", setups=TRADEABLE))]
    for dropped in TRADEABLE:
        kept = tuple(s for s in TRADEABLE if s is not dropped)
        out.append((f"ohne {dropped.key}", GuidePool(name=f"ohne-{dropped.key}", setups=kept)))
    return out


def main() -> int:
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)

    results: dict[str, list[float]] = {label: [] for label, _ in variants()}

    for symbol in config.engine.symbols.active:
        started = time.perf_counter()
        frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
        minutes = store.read(symbol, config.engine.timeframes.execution)
        if any(f.empty for f in frames.values()) or minutes.empty:
            print(f"{symbol}: keine Daten", flush=True)
            continue

        analysis = MultiFrameAnalysis(frames, config.engine)
        funding = funding_store.read(symbol)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        print(f"{symbol}: Analyse in {time.perf_counter() - started:.0f}s", flush=True)

        for label, pool in variants():
            engine = BacktestEngine(
                symbol,
                analysis,
                minute_frame=minutes,
                spec=spec,
                config=config,
                funding=funding,
                history=None,
            )
            result = engine.run(pool)
            results[label].extend(f.r_multiple for f in result.fills)
            print(f"   {label:10s} {len(result.fills):5d} Trades", flush=True)

    print("\n" + "=" * 78)
    print("Alle vier Märkte, vier Jahre\n")
    base = results["alle"]
    base_sum = sum(base)
    for label, _ in variants():
        rs = results[label]
        if not rs:
            continue
        wins = sum(1 for r in rs if r > 0)
        delta = "" if label == "alle" else f"  Differenz {sum(rs) - base_sum:+7.1f} R"
        print(
            f"{label:10s} n={len(rs):5d}  {np.mean(rs):+.4f} R  "
            f"Treffer {100 * wins / len(rs):3.0f}%  Summe {sum(rs):+8.1f} R  "
            f"{interval(rs)}{delta}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
