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

BOOT = 2000
# Tighter, not looser. The first run of this study went the other way -- 0.15
# up to 1.00 -- and answered a question Severin had asked ("why so few
# trades?"). The question that matters came later: with the entries measured at
# a gross expectancy of -0.01 R [-0.070, +0.051], indistinguishable from zero,
# the whole net loss of -0.063 R is the toll. Fees scale with position size and
# risk does not, so the cost in R is set by how wide the stop is -- and a
# tighter ceiling admits only the wider stops.
#
# What this cannot do is make the system profitable. If the gross edge really
# is zero, cutting the toll walks the result up towards zero and stops there.
# It is worth measuring because the gross interval reaches +0.05, and because
# knowing the shape of the curve says whether the ceiling that ships is in the
# right place.
CEILINGS = (0.05, 0.075, 0.10, 0.15)

#: How many markets the curve is measured over.
#:
#: Four, the same four as every other study here, so the numbers can be read
#: next to each other. It used to be all twelve, which at the M15 cadence is
#: one cell every twenty-two minutes and seventeen hours for the run -- longer
#: than the laptop stays on, so the extra eight markets produced nothing at all
#: rather than more precision.
MARKETS = 4

#: Below this the per-market table has nothing to say: agreement between
#: markets is the whole point of printing it, and one market cannot disagree.
MIN_MARKETS_TO_COMPARE = 2

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


def parse_args() -> argparse.Namespace:
    """Which cells this process is responsible for.

    A whole run is twelve cells at twenty-two minutes each, which outlives the
    window any single process gets here. Splitting it by cell rather than
    shortening it keeps the measurement intact: every process writes into the
    same resumable file, and the summary reads whatever has landed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        help="Comma-separated markets to compute, e.g. ETHUSDT,SOLUSDT. Default: the first four.",
    )
    parser.add_argument(
        "--ceilings",
        help="Comma-separated subset of the ceilings to compute, e.g. 0.10. Default: all of them.",
    )
    return parser.parse_args()


def per_market(partial: Partial, labels: dict[float, str]) -> None:
    """The same ceilings, one market per row.

    The pooled mean hides the one thing that separates an effect from noise:
    whether the markets agree. BTC made the 0.100 ceiling look like the first
    positive expectancy the project had produced, at +0.0455 R; XRP put the
    same ceiling at -0.0958 R, worse than the one that ships. A rule whose sign
    flips between markets is describing those markets.

    It is printed rather than tested because four markets cannot settle it
    either way -- but a reader who sees the row cannot mistake the pooled
    number for agreement.
    """
    markets = sorted({sym for label in labels.values() for sym in partial.symbols_done(label)})
    if len(markets) < MIN_MARKETS_TO_COMPARE:
        return

    print("\nJe Markt, weil der gepoolte Mittelwert verdeckt, ob sie sich einig sind:")
    head = "".join(f"{labels[c].replace('Decke ', ''):>12s}" for c in CEILINGS)
    print(f"  {'Markt':10s}{head}")
    for sym in markets:
        cells = []
        for ceiling in CEILINGS:
            key = Partial.key(sym, labels[ceiling])
            values = partial.cells.get(key)
            cells.append(f"{np.mean(values):+12.4f}" if values else f"{'—':>12s}")
        print(f"  {sym:10s}{''.join(cells)}")

    # Which ceiling won, market by market. Unanimity is the claim; a split is
    # the absence of one.
    best: list[str] = []
    for sym in markets:
        scored = {
            c: float(np.mean(v))
            for c in CEILINGS
            if (v := partial.cells.get(Partial.key(sym, labels[c])))
        }
        if len(scored) > 1:
            best.append(f"{sym[:3]}:{max(scored, key=lambda c: scored[c]):g}")
    if best:
        print(f"  beste Decke je Markt -> {', '.join(best)}")


def report(partial: Partial, labels: dict[float, str]) -> None:
    """The curve as it stands, over whatever cells have landed.

    Read from the file rather than from this process's own results, because the
    run is split across processes and no single one of them has measured the
    whole thing.
    """
    print("\n" + "=" * 78)
    counted = sorted({sym for c in CEILINGS for sym in partial.symbols_done(labels[c])})
    print(f"{len(counted)} Märkte: {', '.join(counted)}\n")

    pooled = {c: partial.collect(labels[c]) for c in CEILINGS}
    for ceiling in CEILINGS:
        rs = pooled[ceiling]
        if not rs:
            continue
        wins = sum(1 for r in rs if r > 0)
        refused = sum(
            int(partial.note(sym, labels[ceiling], "refused") or 0)
            for sym in partial.symbols_done(labels[ceiling])
        )
        markets = ",".join(s[:3] for s in partial.symbols_done(labels[ceiling]))
        print(
            f"Decke {ceiling:5.3f}  n={len(rs):5d}  {np.mean(rs):+.4f} R  "
            f"Treffer {100 * wins / len(rs):3.0f}%  Summe {sum(rs):+8.1f} R  "
            f"abgelehnt {refused:5d}  {interval(rs)}  [{markets}]"
        )

    per_market(partial, labels)

    # Only comparable where the same markets were measured at both ceilings. A
    # difference taken across two different market sets is not a difference,
    # and the run is now split across processes, so that case is reachable.
    print("\nWas die zusätzlichen Trades allein gebracht hätten:")
    tightest = pooled[CEILINGS[0]]
    base_markets = set(partial.symbols_done(labels[CEILINGS[0]]))
    for ceiling in CEILINGS[1:]:
        rs = pooled[ceiling]
        if set(partial.symbols_done(labels[ceiling])) != base_markets:
            print(f"  bis {ceiling:5.3f}: andere Märkte gemessen, nicht vergleichbar")
            continue
        extra = len(rs) - len(tightest)
        if extra <= 0:
            continue
        print(
            f"  bis {ceiling:5.3f}: {extra:5d} Trades mehr, "
            f"Summe {sum(rs) - sum(tightest):+7.1f} R, "
            f"im Mittel {(sum(rs) - sum(tightest)) / extra:+.4f} R pro Stück"
        )


def main() -> int:
    args = parse_args()
    base = load_config()
    store = ParquetStore(base.engine.paths.parquet_dir)
    funding_store = FundingStore(base.engine.paths.funding_dir)
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(base.engine.symbols.active[:MARKETS])
    )
    # Which cells to *compute*. The signature below stays on the full tuple on
    # purpose: a subset must not look like a different study, or selecting one
    # ceiling would discard every cell already measured.
    wanted = tuple(float(c) for c in args.ceilings.split(",")) if args.ceilings else CEILINGS
    unknown = [c for c in wanted if c not in CEILINGS]
    if unknown:
        parser_choices = ", ".join(f"{c:g}" for c in CEILINGS)
        print(f"Unbekannte Decke {unknown}; zur Wahl stehen {parser_choices}", flush=True)
        return 2

    # Resumable, because this run has now been killed twice by a shutdown and
    # each death threw away hours. The signature carries the ceilings: the first
    # version of this study measured (0.15, 0.25, 0.40, 1.00), and a file that
    # silently mixed those cells with these would read as one curve over eight
    # points that was never measured as one.
    signature = f"{base.engine.simulation.initial_equity}|{base.engine.setups.enabled}|{CEILINGS}"
    partial = Partial.load(base.engine.paths.data_dir / "study_cost_floor.json", signature)

    labels = {c: f"Decke {c:5.3f}" for c in CEILINGS}
    done = partial.symbols_done(labels[CEILINGS[0]])
    if done:
        print(f"Fortsetzung: {', '.join(done)} liegen vor", flush=True)
        print(flush=True)

    for symbol in symbols:
        if all(partial.has(symbol, labels[c]) for c in wanted):
            continue
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

        for ceiling in wanted:
            if partial.has(symbol, labels[ceiling]):
                continue
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
            partial.put(
                symbol,
                labels[ceiling],
                [f.r_multiple for f in result.fills],
                refused=result.intents_rejected_by_risk,
            )
            print(
                f"   Decke {ceiling:4.2f}: {len(result.fills):4d} Trades, "
                f"{result.intents_rejected_by_risk:4d} abgelehnt",
                flush=True,
            )

    report(partial, labels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
