"""Is a target that gets hit worth more than one that pays more?

    python scripts/study_modest_target.py
    python scripts/study_modest_target.py --symbols ETHUSDT

Severin asked what was different about the trades that won. Over 2,734
journalled trades, bucketed by the planned reward-to-risk ratio and without
looking at the outcome:

    <= 1.75     1258 Trades   -0.0261 R   41% Treffer   [-0.097, +0.044]
    1.75-2.00    173 Trades   -0.2634 R   25% Treffer
    2.00-2.25    685 Trades   -0.0965 R   31% Treffer
    2.25-2.50    128 Trades   -0.0677 R   27% Treffer
    2.50 +       490 Trades   -0.1933 R   18% Treffer   [-0.351, -0.032]
    alle        2734 Trades   -0.0908 R   33% Treffer

Half the sample sits at breakeven inside its interval; the ambitious half is
the worst group in the record. The winners' planned ratio averaged 1.90 against
the losers' 2.27, a difference of -0.368 with interval [-0.445, -0.295].

**Why this is measured again here rather than believed.** That table is over
trades that *happened*. Removing a trade frees the slot it occupied and another
setup fills it, so a count made on the journal cannot say what the account
would have done -- it is the same objection that would have invalidated the
setup comparison earlier the same day, and the only answer to it is a backtest
with the rule in place.

**The honest worry, stated before the result.** 1.75 is the upper edge of the
best of five buckets, and the buckets between the ends do not order: 1.75-2.00
came out worse than 2.00-2.25. So the scale has signal at its ends and noise in
its middle, and a threshold read off the best bucket describes this sample to
some unknown degree. Four levers measured that day looked at least this good
before being measured properly, and all four failed.

**Two arms, because they are different bets.** `abgelehnt` drops the proposal:
fewer trades, better ones. `gekuerzt` keeps the trade and pulls the target in
to the cap -- the same number of trades, which is what Severin wants, but it
overrides what every setup asked for rather than choosing among them.

**Read the hit rate first.** It has to *rise*: a nearer target is reached more
often and that is the entire mechanism. If it does not rise, the journal result
was an artefact of the slots the filter quietly left empty.
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
from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.reporting.resume import Partial
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool
from traidingbrain.strategies.modest_target import CAP, Action, ModestTarget

BOOT = 3000
MIN_GROUP = 8
MARKETS = 4

PLAIN = "ohne"


def interval(values: list[float], seed: int = 11) -> str:
    if len(values) < MIN_GROUP:
        return "zu wenige"
    rng = np.random.default_rng(seed)
    sample = np.array(values, dtype="float64")
    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)
    low, high = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
    return f"[{low:+.3f}, {high:+.3f}]" + ("" if low < 0 < high else "  <- Null ausgeschlossen")


def parse_args() -> argparse.Namespace:
    """Which markets this process is responsible for.

    Three arms at twenty-two minutes each is over an hour per market, which
    outlives the window a single process gets here. One process per market
    fits, they all write into the same resumable file, and the summary reads
    whatever has landed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        help="Comma-separated markets to compute, e.g. ETHUSDT. Default: the first four.",
    )
    return parser.parse_args()


def report(partial: Partial, labels: list[str], ceiling: float) -> None:
    """The arms as they stand, over whatever cells have landed.

    Read from the file rather than from this process own results: the run
    is split one process per market, and none of them measures the whole.
    """
    print("\n" + "=" * 78)
    # Only the markets every arm has finished. The run is split one process per
    # market and they do not finish together, so pooling whatever is present
    # would compare an arm measured on two markets against one measured on one
    # -- and that difference is an artefact of which process got there first.
    # It read as +42.9 R in favour of widening before this line existed.
    shared = set.intersection(*(set(partial.symbols_done(label)) for label in labels))
    if not shared:
        print(f"Kostendecke {ceiling:.2f}: noch kein Markt in allen Armen fertig")
        return

    print(f"{len(shared)} Märkte, Kostendecke {ceiling:.2f}: {', '.join(sorted(shared))}\n")

    def pool(label: str) -> list[float]:
        out: list[float] = []
        for sym in sorted(shared):
            out.extend(partial.cells[Partial.key(sym, label)])
        return out

    base = pool(PLAIN)
    for label in labels:
        rs = pool(label)
        if not rs:
            continue
        wins = 100 * sum(1 for r in rs if r > 0) / len(rs)
        touched = sum(int(partial.note(sym, label, "touched") or 0) for sym in sorted(shared))
        diff = "" if label == PLAIN else f"  Differenz {sum(rs) - sum(base):+7.1f} R"
        print(
            f"{label:18s} n={len(rs):5d}  {np.mean(rs):+.4f} R  Treffer {wins:3.0f}%  "
            f"Summe {sum(rs):+8.1f} R  {interval(rs)}{diff}"
            + (f"  ({touched} betroffen)" if touched else "")
        )

    print(
        "\nDie Trefferquote ist hier die ehrlichste Spalte. Ein verbreiterter Stop\n"
        "steht nicht mehr dort, wo das Setup die Idee fuer widerlegt haelt; faellt\n"
        "die Quote nicht, ist das eher ein Fehler als ein Fund."
    )


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)

    ceiling = config.risk.limits.max_cost_fraction_of_risk
    signature = (
        f"{config.engine.simulation.initial_equity}|{config.engine.setups.enabled}"
        f"|{ceiling}|modest-{CAP}"
    )
    partial = Partial.load(config.engine.paths.data_dir / "study_modest_target.json", signature)

    labels = [PLAIN, *(a.value for a in Action)]
    done = partial.symbols_done(PLAIN)
    if done:
        print(f"Fortsetzung: {', '.join(done)} liegen vor", flush=True)
        print(flush=True)

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:MARKETS])
    )

    for symbol in symbols:
        if all(partial.has(symbol, label) for label in labels):
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

        for label in labels:
            if partial.has(symbol, label):
                n = len(partial.cells[Partial.key(symbol, label)])
                print(f"   {label:18s} {n:5d} Trades (lag vor)", flush=True)
                continue

            if label == PLAIN:
                strategy: object = GuidePool.for_config(config)
            else:
                strategy = ModestTarget(
                    inner=GuidePool.for_config(config),
                    action=Action(label),
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
            rs = [f.r_multiple for f in result.fills]
            partial.put(
                symbol,
                label,
                rs,
                touched=getattr(strategy, "touched", 0),
                refused=result.intents_rejected_by_risk,
            )
            extra = getattr(strategy, "touched", 0)
            print(
                f"   {label:18s} {len(rs):5d} Trades"
                + (f", {extra} Ziele betroffen" if extra else ""),
                flush=True,
            )

    report(partial, labels, ceiling)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
