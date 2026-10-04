"""Does rescuing an unaffordable stop buy trades worth having?

    python scripts/study_widen_stop.py

Nine of twelve forward accounts are stuck on one sentence -- *Setups
ausgeloest, alle von der Risikoschicht abgelehnt* -- while Severin's standing
request is ten trades a day. Every lever measured so far moves the trade count
by refusing more or refusing less. This one is the only move that raises the
count without relaxing the cost ceiling: a stop too tight to pay for its round
trip is pushed out to the cheapest distance that passes, and the position is
re-sized so the risk in CHF does not change.

**It is a trade, not a free lunch, and the direction of the cost is known in
advance.** A setup's stop is where the idea is wrong. Widening it means holding
a position whose premise has already failed. The hit rate has to fall. The
question is only whether it falls by less than the extra trades are worth --
and the honest prior, after a day in which six levers all turned out to be
noise, is that this is noise too.

So three numbers per arm, and all three are needed:

* **Pro Trade.** The expectancy. If the rescued trades are as good as the rest,
  this does not move; if they are worse, it falls.
* **Trefferquote.** Where the cost of abandoning the structural stop shows up.
  A result with more trades, equal expectancy and an unchanged hit rate would
  be too good to believe and should be read as a bug, not a finding.
* **Summe.** What the account would have done, which is the only thing Severin
  can spend -- and which a worse system can still improve by trading more.

**The comparison is between different sets of trades, not the same trades under
different rules.** A rescued trade occupies a slot the next setup would have
used, so the arms reshuffle rather than simply add. That destroyed the exit
study (`compare_exits.py`) and survived the cost-ceiling one, where the
difference was several times larger than reshuffling could explain. Which it
does here is decided by the size of the gap, not by argument.
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
from traidingbrain.strategies.widen_stop import Target, WidenedStop

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


def main() -> int:
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)

    ceiling = config.risk.limits.max_cost_fraction_of_risk
    signature = (
        f"{config.engine.simulation.initial_equity}|{config.engine.setups.enabled}|{ceiling}|widen"
    )
    partial = Partial.load(config.engine.paths.data_dir / "study_widen_stop.json", signature)

    labels = [PLAIN, *(m.value for m in Target)]
    done = partial.symbols_done(PLAIN)
    if done:
        print(f"Fortsetzung: {', '.join(done)} liegen vor", flush=True)
        print(flush=True)

    for symbol in config.engine.symbols.active[:MARKETS]:
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
                strategy = WidenedStop(
                    inner=GuidePool.for_config(config),
                    spec=spec,
                    config=config,
                    mode=Target(label),
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
                widened=getattr(strategy, "widened", 0),
                refused=result.intents_rejected_by_risk,
            )
            extra = getattr(strategy, "widened", 0)
            print(
                f"   {label:18s} {len(rs):5d} Trades"
                + (f", {extra} Stops verbreitert" if extra else ""),
                flush=True,
            )

    print("\n" + "=" * 78)
    print(f"{MARKETS} Märkte, vier Jahre, Kostendecke {ceiling:.2f}\n")
    base = partial.collect(PLAIN)
    for label in labels:
        rs = partial.collect(label)
        if not rs:
            continue
        wins = 100 * sum(1 for r in rs if r > 0) / len(rs)
        widened = sum(
            int(partial.note(sym, label, "widened") or 0) for sym in partial.symbols_done(label)
        )
        diff = "" if label == PLAIN else f"  Differenz {sum(rs) - sum(base):+7.1f} R"
        print(
            f"{label:18s} n={len(rs):5d}  {np.mean(rs):+.4f} R  Treffer {wins:3.0f}%  "
            f"Summe {sum(rs):+8.1f} R  {interval(rs)}{diff}"
            + (f"  ({widened} verbreitert)" if widened else "")
        )

    print(
        "\nDie Trefferquote ist hier die ehrlichste Spalte. Ein verbreiterter Stop\n"
        "steht nicht mehr dort, wo das Setup die Idee fuer widerlegt haelt; faellt\n"
        "die Quote nicht, ist das eher ein Fehler als ein Fund."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
