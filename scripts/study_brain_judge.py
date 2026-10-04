"""Is judgement worth anything over the rules' own selection?

    python scripts/study_brain_judge.py                     # arithmetic, free
    python scripts/study_brain_judge.py --symbols ETHUSDT
    python scripts/study_brain_judge.py --brain subscription

The question the day's measurements left open. The guide's entries have a gross
expectancy of -0.0102 R [-0.070, +0.051], indistinguishable from zero, so the
*selection* among them carries no information -- and three of the four levers
measured only moved the toll or the trade count, which arithmetically cannot
change that. The one that touched the selection, the liquidity-lean filter, made
it worse.

`BrainJudged` leaves the setup's entry, stop and target alone and gives the
model one job: whether this instance of a known pattern is one to take.

**The default brain here is `fake`, and that is the point rather than a
placeholder.** It scores the same factors through the same guard and the same
risk rules, deciding by arithmetic instead of by a model. So it answers the
narrow question -- is the *judgement* worth anything, with everything except
the judgement held constant -- and it costs nothing, which means the yardstick
exists before any decision about spending is made. A real model has to beat
this line, not the unfiltered pool.

**What a result here cannot be.** If the arithmetic judge improves things, that
is not evidence about a model; it says the snapshot and scoring layer sees
something the setups do not, which would be worth knowing on its own. If it
does nothing, a model may still help -- the arithmetic is deliberately dumb.
Either way the number to report is the same three: per trade, hit rate, and
sum, pooled only over markets both arms have finished.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.brain.factory import BRAIN_NAMES, make_brain
from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.reporting.resume import Partial
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.brain_judge import BrainJudged
from traidingbrain.strategies.guide import GuidePool

BOOT = 3000
MIN_GROUP = 8
MARKETS = 4

PLAIN = "ohne Urteil"
JUDGED = "mit Urteil"


def interval(values: list[float], seed: int = 11) -> str:
    if len(values) < MIN_GROUP:
        return "zu wenige"
    rng = np.random.default_rng(seed)
    sample = np.array(values, dtype="float64")
    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)
    low, high = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
    return f"[{low:+.3f}, {high:+.3f}]" + ("" if low < 0 < high else "  <- Null ausgeschlossen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument(
        "--brain",
        default="fake",
        choices=BRAIN_NAMES,
        help="Whose judgement. 'fake' is arithmetic and free; the others cost money or quota.",
    )
    return parser.parse_args()


def report(partial: Partial, brain_name: str) -> None:
    """The two arms, over the markets both have finished."""
    arms = (PLAIN, JUDGED)
    shared = set.intersection(*(set(partial.symbols_done(a)) for a in arms))
    print("\n" + "=" * 78)
    if not shared:
        print("Noch kein Markt in beiden Armen fertig")
        return

    print(f"Urteil von '{brain_name}', {len(shared)} Märkte: {', '.join(sorted(shared))}\n")

    def pool(label: str) -> list[float]:
        return [r for sym in sorted(shared) for r in partial.cells[Partial.key(sym, label)]]

    base = pool(PLAIN)
    for label in arms:
        rs = pool(label)
        wins = 100 * sum(1 for r in rs if r > 0) / len(rs)
        vetoed = sum(int(partial.note(sym, label, "vetoed") or 0) for sym in sorted(shared))
        diff = "" if label == PLAIN else f"  Differenz {sum(rs) - sum(base):+7.1f} R"
        print(
            f"{label:12s} n={len(rs):5d}  {np.mean(rs):+.4f} R  Treffer {wins:3.0f}%  "
            f"Summe {sum(rs):+8.1f} R  {interval(rs)}{diff}"
            + (f"  ({vetoed} abgelehnt)" if vetoed else "")
        )

    print("\nJe Markt, weil der gepoolte Mittelwert verdeckt, ob sie sich einig sind:")
    for sym in sorted(shared):
        a = float(np.mean(partial.cells[Partial.key(sym, PLAIN)]))
        b = float(np.mean(partial.cells[Partial.key(sym, JUDGED)]))
        print(f"  {sym:10s} ohne {a:+.4f}   mit {b:+.4f}   {'hilft' if b > a else 'schadet'}")

    print(
        "\nDies ist die Messlatte, nicht die Antwort. 'fake' urteilt per Arithmetik\n"
        "ueber dieselben Faktoren; ein echtes Modell muss diese Zeile schlagen,\n"
        "nicht den ungefilterten Pool."
    )


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)

    # The brain's name is in the signature: an arithmetic judgement and a
    # model's are different measurements, and a file that mixed them would
    # report a comparison nobody made.
    signature = (
        f"{config.engine.simulation.initial_equity}|{config.engine.setups.enabled}|"
        f"judge-{args.brain}"
    )
    partial = Partial.load(config.engine.paths.data_dir / "study_brain_judge.json", signature)

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:MARKETS])
    )
    done = partial.symbols_done(PLAIN)
    if done:
        print(f"Fortsetzung: {', '.join(done)} liegen vor", flush=True)

    for symbol in symbols:
        if all(partial.has(symbol, label) for label in (PLAIN, JUDGED)):
            continue
        started = time.perf_counter()
        frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
        minutes = store.read(symbol, config.engine.timeframes.execution)
        if any(f.empty for f in frames.values()) or minutes.empty:
            print(f"{symbol}: keine Daten", flush=True)
            continue

        analysis = MultiFrameAnalysis(frames, config.engine)
        funding = funding_store.read(symbol)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        print(f"{symbol}: vorbereitet in {time.perf_counter() - started:.0f}s", flush=True)

        for label in (PLAIN, JUDGED):
            if partial.has(symbol, label):
                n = len(partial.cells[Partial.key(symbol, label)])
                print(f"   {label:12s} {n:5d} Trades (lag vor)", flush=True)
                continue

            pool = GuidePool.for_config(config)
            strategy: object = pool
            if label == JUDGED:
                strategy = BrainJudged(
                    inner=pool,
                    brain=make_brain(args.brain, config),
                    builder=SnapshotBuilder(symbol, analysis, config.engine),
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
            result = engine.run(strategy)  # type: ignore[arg-type]
            tally = getattr(strategy, "tally", None)
            partial.put(
                symbol,
                label,
                [f.r_multiple for f in result.fills],
                vetoed=(tally.vetoed + tally.wrong_side) if tally else 0,
            )
            extra = f"\n{strategy.summary()}" if isinstance(strategy, BrainJudged) else ""
            print(f"   {label:12s} {len(result.fills):5d} Trades{extra}", flush=True)

    report(partial, args.brain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
