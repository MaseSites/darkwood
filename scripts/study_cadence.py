"""How often should the system look at the chart?

    python scripts/study_cadence.py

The decision loop runs once per *signal* candle. With `signal: H1` that is once
an hour -- and the fifteen-minute chart finishes four candles an hour, so
**seventy-two of its ninety-six candles a day are never examined.** A setup that
formed at 08:15 and completed by 08:45 was never offered, because nobody looked
until 09:00.

Severin's words: "du kannst doch auch in 15 Minuten Trades machen". He is
right, and this is why it was not happening. It is the same family of defect as
"the setups only ran on the hourly chart", found two weeks ago: not a rule that
is too strict, a chart nobody read.

So this measures the cadence rather than arguing about it. Same rules, same
markets, same four years; only how often the loop asks changes.

**Measured on 04.10.2026, four markets, four years.** The cadence is worth
half again as many trades and costs nothing per trade:

    Takt H1    n=2768   1.93 Trades/Tag   -0.0920 R   Summe -254.8 R
    Takt M15   n=4138   2.89 Trades/Tag   -0.0768 R   Summe -317.7 R

    the extra trades alone: 1370 of them, -0.0460 R each

The extra trades are *better* than the average they join, so the expectancy per
trade improves slightly while the count rises by half. Set that against
`study_cost_floor.py`, where loosening a rule bought twice the trades at three
times the loss: that is what a rule doing its job looks like, and this is what
a chart nobody was reading looks like.

What it does not do is make the system profitable. More trades at a negative
expectancy is more loss -- the sum goes from -255 R to -318 R. Trading faster
does not improve the direction, it only gets there sooner.

**What moves with the cadence, and is held fixed here.** A pending order waits
`entry_expiry_bars` *signal candles*, so at M15 it would wait two hours instead
of eight. That is a different rule, not a different cadence, and changing two
things at once measures neither -- so the expiry is converted to the same wall
time in every run.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.reporting.resume import Partial
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool

BOOT = 2000
MIN_GROUP = 8
DAY_MS = 86_400_000

#: Cadences to compare. H1 is what ships.
CADENCES: tuple[Timeframe, ...] = (Timeframe.H1, Timeframe.M15)


def interval(values: list[float], seed: int = 11) -> str:
    if len(values) < MIN_GROUP:
        return "zu wenige"
    rng = np.random.default_rng(seed)
    sample = np.array(values, dtype="float64")
    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)
    low, high = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
    return f"[{low:+.3f}, {high:+.3f}]" + ("" if low < 0 < high else "  <- Null ausgeschlossen")


def tuned(base: AppConfig, signal: Timeframe) -> AppConfig:
    """The same configuration at a different cadence, with the expiry held fixed.

    `entry_expiry_bars` counts signal candles, so leaving it alone would shorten
    the life of a resting order fourfold at M15 -- and then the comparison would
    be measuring two changes at once.
    """
    hours = base.engine.simulation.entry_expiry_bars * timeframe_ms(base.engine.timeframes.signal)
    bars = max(1, round(hours / timeframe_ms(signal)))
    return base.model_copy(
        update={
            "engine": base.engine.model_copy(
                update={
                    "timeframes": base.engine.timeframes.model_copy(update={"signal": signal}),
                    "simulation": base.engine.simulation.model_copy(
                        update={"entry_expiry_bars": bars}
                    ),
                }
            )
        }
    )


def main() -> int:
    base = load_config()
    store = ParquetStore(base.engine.paths.parquet_dir)
    funding_store = FundingStore(base.engine.paths.funding_dir)

    # Four markets at a fifteen-minute cadence is hours of work, and the laptop
    # gets shut down. Two runs have now died on the last of four markets and
    # thrown away the first three, which makes the study unfinishable rather
    # than slow. Each market is written as it completes.
    signature = f"{base.engine.simulation.initial_equity}|{[tf.value for tf in CADENCES]}"
    partial = Partial.load(base.engine.paths.data_dir / "study_cadence.json", signature)
    done = partial.symbols_done(CADENCES[-1].value)
    if done:
        print(f"Fortsetzung: {', '.join(done)} liegen schon vor\n", flush=True)

    results: dict[str, list[float]] = {tf.value: [] for tf in CADENCES}
    spans: dict[str, tuple[int, int]] = {}

    for symbol in base.engine.symbols.active[:4]:
        started = time.perf_counter()
        frames = {tf: store.read(symbol, tf) for tf in base.engine.timeframes.context}
        minutes = store.read(symbol, base.engine.timeframes.execution)
        if any(f.empty for f in frames.values()) or minutes.empty:
            print(f"{symbol}: keine Daten", flush=True)
            continue

        funding = funding_store.read(symbol)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        print(f"{symbol}: gelesen in {time.perf_counter() - started:.0f}s", flush=True)

        for signal in CADENCES:
            if partial.has(symbol, signal.value):
                continue
            config = tuned(base, signal)
            # The analysis depends on the signal timeframe, so it cannot be
            # shared across cadences the way the other studies share it.
            analysis = MultiFrameAnalysis(frames, config.engine)
            engine = BacktestEngine(
                symbol,
                analysis,
                minute_frame=minutes,
                spec=spec,
                config=config,
                funding=funding,
                history=None,
            )
            result = engine.run(GuidePool())
            partial.put(
                symbol,
                signal.value,
                [f.r_multiple for f in result.fills],
                first_ts=result.first_ts,
                last_ts=result.last_ts,
                refused=result.intents_rejected_by_risk,
            )
            print(
                f"   Takt {signal.value:3s}: {len(result.fills):5d} Trades, "
                f"{result.intents_rejected_by_risk:5d} abgelehnt "
                f"({time.perf_counter() - started:.0f}s)",
                flush=True,
            )

    # Pooled from disk rather than from this process, so a resumed run reports
    # every market and not only the ones it happened to compute itself.
    for signal in CADENCES:
        results[signal.value] = partial.collect(signal.value)
        stamps = [
            (
                partial.note(sym, signal.value, "first_ts"),
                partial.note(sym, signal.value, "last_ts"),
            )
            for sym in partial.symbols_done(signal.value)
        ]
        usable = [(a, b) for a, b in stamps if a and b]
        if usable:
            spans[signal.value] = (min(a for a, _ in usable), max(b for _, b in usable))

    print("\n" + "=" * 78)
    print("Alle vier Märkte, vier Jahre\n")
    for signal in CADENCES:
        rs = results[signal.value]
        if not rs:
            continue
        wins = sum(1 for r in rs if r > 0)
        first, last = spans.get(signal.value, (0, 0))
        days = max(1.0, (last - first) / DAY_MS)
        print(
            f"Takt {signal.value:3s}  n={len(rs):5d}  {len(rs) / days:5.2f} Trades/Tag  "
            f"{np.mean(rs):+.4f} R  Treffer {100 * wins / len(rs):3.0f}%  "
            f"Summe {sum(rs):+8.1f} R  {interval(rs)}"
        )

    extra = len(results[Timeframe.M15.value]) - len(results[Timeframe.H1.value])
    if extra > 0:
        gained = sum(results[Timeframe.M15.value]) - sum(results[Timeframe.H1.value])
        print(
            f"\nDie zusätzlichen Trades allein: {extra} Stück, {gained:+.1f} R, "
            f"im Mittel {gained / extra:+.4f} R pro Stück"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
