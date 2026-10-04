"""Does the cost floor throw away winners or losers?

    python scripts/study_cost_floor.py

It is the single largest filter on how many trades the system takes: a setup
whose stop is too tight to pay for the round trip is refused before it exists.
Severin's standing complaint is that 1.9 trades a day is too few, and this is
the rule standing between him and more of them. So relax it and look at what
comes through.

**Measured on 02.10.2026, four markets, four years.** It is the clearest result
the project has produced, and the only strongly positive one:

    Decke 0.15   2734 Trades   -0.0904 R    <- as shipped
    Decke 0.25   3803 Trades   -0.1103 R
    Decke 0.40   4575 Trades   -0.1418 R
    Decke 1.00   5277 Trades   -0.2076 R    <- floor off

    the extra trades alone:  -0.161 R, -0.218 R, -0.334 R each

Nearly twice as many trades are available and they are reliably worse -- the
ones refused today lose about three times what the ones allowed do. Monotone
across four settings over samples of one to two and a half thousand, which is
what a real effect looks like; `compare_exits.py` is what a null one looks
like, 0.36 standard errors with the sign flipping between subsets.

**The caveat, the same one as in `compare_exits.py`:** these are four different
sets of trades, not the same trades under different rules, because a trade that
ends early frees the next entry. There it destroyed the result. Here it does
not, because the difference is several times larger than any reshuffling could
account for.

The analysis is built once per symbol and shared across the four ceilings. It
does not depend on the risk configuration, and rebuilding it each time costs 76
seconds per symbol to recompute the same numbers -- most of the run.
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

BOOT = 2000
CEILINGS = (0.15, 0.25, 0.40, 1.00)

#: Fewest trades before a group's mean is worth an interval. Below this the
#: interval is wider than the scale and says so by being absurd, which is less
#: useful than saying the sample is too small.
MIN_GROUP = 8


def interval(values: list[float], seed: int = 11) -> str:
    if len(values) < MIN_GROUP:
        return "zu wenige"
    rng = np.random.default_rng(seed)
    sample = np.array(values, dtype="float64")
    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)
    low, high = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
    return f"[{low:+.3f}, {high:+.3f}]" + ("" if low < 0 < high else "  <- Null ausgeschlossen")


def main() -> int:
    base = load_config()
    store = ParquetStore(base.engine.paths.parquet_dir)
    funding_store = FundingStore(base.engine.paths.funding_dir)
    symbols = list(base.engine.symbols.active)

    results: dict[float, list[float]] = {c: [] for c in CEILINGS}
    refused: dict[float, int] = {c: 0 for c in CEILINGS}

    for symbol in symbols:
        started = time.perf_counter()
        frames = {tf: store.read(symbol, tf) for tf in base.engine.timeframes.context}
        minutes = store.read(symbol, base.engine.timeframes.execution)
        if any(f.empty for f in frames.values()) or minutes.empty:
            print(f"{symbol}: keine Daten", flush=True)
            continue

        analysis = MultiFrameAnalysis(frames, base.engine)
        funding = funding_store.read(symbol)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        print(f"{symbol}: Analyse in {time.perf_counter() - started:.0f}s", flush=True)

        for ceiling in CEILINGS:
            config = base.model_copy(
                update={
                    "risk": base.risk.model_copy(
                        update={
                            "limits": base.risk.limits.model_copy(
                                update={"max_cost_fraction_of_risk": ceiling}
                            )
                        }
                    )
                }
            )
            engine = BacktestEngine(
                symbol,
                analysis,
                minute_frame=minutes,
                spec=spec,
                config=config,
                funding=funding,
                history=None,
            )
            result = engine.run(GuidePool.for_config(config))
            results[ceiling].extend(f.r_multiple for f in result.fills)
            refused[ceiling] += result.intents_rejected_by_risk
            print(
                f"   Decke {ceiling:4.2f}: {len(result.fills):4d} Trades, "
                f"{result.intents_rejected_by_risk:4d} abgelehnt",
                flush=True,
            )

    print("\n" + "=" * 78)
    print("Alle vier Märkte, vier Jahre\n")
    for ceiling in CEILINGS:
        rs = results[ceiling]
        if not rs:
            continue
        wins = sum(1 for r in rs if r > 0)
        print(
            f"Decke {ceiling:4.2f}  n={len(rs):5d}  {np.mean(rs):+.4f} R  "
            f"Treffer {100 * wins / len(rs):3.0f}%  Summe {sum(rs):+8.1f} R  "
            f"abgelehnt {refused[ceiling]:5d}  {interval(rs)}"
        )

    # The question is not whether more trades is better but what the extra ones
    # did. Everything above the shipped ceiling is a trade the floor refuses.
    print("\nWas die zusätzlichen Trades allein gebracht hätten:")
    baseline = len(results[CEILINGS[0]])
    for ceiling in CEILINGS[1:]:
        rs = results[ceiling]
        extra = len(rs) - baseline
        if extra <= 0:
            continue
        print(
            f"  bis {ceiling:4.2f}: {extra:5d} Trades mehr, "
            f"Summe {sum(rs) - sum(results[CEILINGS[0]]):+7.1f} R, "
            f"im Mittel {(sum(rs) - sum(results[CEILINGS[0]])) / extra:+.4f} R pro Stück"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
