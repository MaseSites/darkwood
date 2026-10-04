"""Does the liquidity lean improve the system, or only shrink it?

    python scripts/study_lean_filter.py

The same question every lever got today, and the one that separates a finding
from a number that merely looks good: dropping setup A improved the *sum* by
taking 730 fewer trades at a negative expectancy while making the per-trade
figure worse. Any filter can do that. The test is whether the trades it keeps
are better than the ones it had before.

So two things are reported together and neither alone is enough:

* **Per trade.** Did the kept trades improve? A filter that removes losers
  raises this; one that removes trades at random does not move it.
* **In sum.** What the account would have done. A filter can improve this
  purely by trading less, which is why it is never read on its own.

The filter under test refuses a long when nearly all untouched pivot weight
sits above the price, and a short when nearly all of it sits below. Measured
over 619,037 bars, that condition precedes the worst week in the record --
-0.195 ATR against a baseline of +0.761.

**The honest worry, stated before the result.** The lean was measured on the
same markets and the same years this now backtests. A threshold found by
looking at these data and then justified on them describes them rather than the
world. The extreme bucket was not chosen by search -- it is one end of a scale
fixed before looking -- but 0.6 was, and the forward journal is where this has
to prove itself.
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
from traidingbrain.reporting.resume import Partial
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool
from traidingbrain.strategies.lean_filter import LEAN_FRAME, LeanFiltered, LeanTimeline

BOOT = 3000
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
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)

    signature = f"{config.engine.simulation.initial_equity}|{config.engine.setups.enabled}|lean"
    partial = Partial.load(config.engine.paths.data_dir / "study_lean_filter.json", signature)
    done = partial.symbols_done("ohne Filter")
    if done:
        print(f"Fortsetzung: {', '.join(done)} liegen vor\n", flush=True)

    for symbol in config.engine.symbols.active[:4]:
        # Per variant rather than per market: the run that died had already
        # finished BTC's unfiltered arm, and skipping only whole markets would
        # have spent twelve minutes recomputing a number already on disk.
        if all(partial.has(symbol, label) for label in ("ohne Filter", "mit Filter")):
            continue
        started = time.perf_counter()
        frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
        minutes = store.read(symbol, config.engine.timeframes.execution)
        if any(f.empty for f in frames.values()) or minutes.empty:
            print(f"{symbol}: keine Daten", flush=True)
            continue

        analysis = MultiFrameAnalysis(frames, config.engine)
        timeline = LeanTimeline(frames[LEAN_FRAME], config)
        funding = funding_store.read(symbol)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        print(f"{symbol}: vorbereitet in {time.perf_counter() - started:.0f}s", flush=True)

        plain = GuidePool.for_config(config)
        variants = [
            ("ohne Filter", plain),
            ("mit Filter", LeanFiltered(inner=GuidePool.for_config(config), timeline=timeline)),
        ]
        for label, strategy in variants:
            if partial.has(symbol, label):
                print(
                    f"   {label:14s} {len(partial.cells[Partial.key(symbol, label)]):5d} "
                    "Trades (lag vor)",
                    flush=True,
                )
                continue
            engine = BacktestEngine(
                symbol,
                analysis,
                minute_frame=minutes,
                spec=spec,
                config=config,
                funding=funding,
                history=None,
            )
            result = engine.run(strategy)
            partial.put(symbol, label, [f.r_multiple for f in result.fills])
            refused = getattr(strategy, "refused", 0)
            print(
                f"   {label:14s} {len(result.fills):5d} Trades"
                + (f", {refused} vom Filter abgelehnt" if refused else ""),
                flush=True,
            )

    print("\n" + "=" * 78)
    # Only the markets both arms have finished. A market whose unfiltered arm is
    # done and whose filtered arm is still running would otherwise be counted on
    # one side only, and the difference that falls out of that is an artefact of
    # which arm got there first rather than anything the filter did.
    arms = ("ohne Filter", "mit Filter")
    shared = set.intersection(*(set(partial.symbols_done(label)) for label in arms))
    if not shared:
        print("Noch kein Markt in beiden Armen fertig")
        return 0

    print(f"{len(shared)} Märkte, vier Jahre: {', '.join(sorted(shared))}\n")

    def pool(label: str) -> list[float]:
        out: list[float] = []
        for sym in sorted(shared):
            out.extend(partial.cells[Partial.key(sym, label)])
        return out

    base_sum = sum(pool(arms[0]))
    for label in arms:
        rs = pool(label)
        if not rs:
            continue
        wins = sum(1 for r in rs if r > 0)
        diff = "" if label == "ohne Filter" else f"  Differenz {sum(rs) - base_sum:+7.1f} R"
        print(
            f"{label:14s} n={len(rs):5d}  {np.mean(rs):+.4f} R  "
            f"Treffer {100 * wins / len(rs):3.0f}%  Summe {sum(rs):+8.1f} R  "
            f"{interval(rs)}{diff}"
        )
    print(
        "\nBeide Zeilen zaehlen. Pro Trade sagt, ob die behaltenen Trades besser sind;\n"
        "die Summe sagt, was das Konto getan haette. Ein Filter kann die Summe allein\n"
        "dadurch verbessern, dass er weniger handelt."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
