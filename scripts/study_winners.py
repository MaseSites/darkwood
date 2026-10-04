"""What was different about the trades that won?

    python scripts/study_winners.py
    python scripts/study_winners.py --symbols BTCUSDT

Severin's question, and the right one to ask. It is also the single easiest
analysis in this field to fool yourself with, so the shape of it matters more
than the result.

**Only what was knowable before the entry.** Winners held longer than losers in
every trading system ever built, because a loser hits a stop that sits close by
and a winner runs to a target that does not. "Winners are held longer" is a
restatement of winning, not a cause of it, and a rule built on it cannot be
followed -- at entry time nobody knows which this will be. So every feature
below is one the system had in hand *before* it submitted the order: the
setup's name, the chart it was found on, the planned reward-to-risk, how wide
the stop was, what the round trip was going to cost, the direction, the hour.
Features that only exist afterwards are printed in a separate block and
labelled as descriptions rather than levers.

**The honest worry, stated before the result.** Splitting any sample at zero
and comparing the halves finds differences whether or not any exist, because
the split is made using the outcome. With enough features, something always
separates. Three defences, all of them applied below:

* **Effect over noise.** Each contrast reports a bootstrap interval. A
  difference whose interval straddles zero is a difference in the sample and
  nothing more.
* **Do the markets agree?** A feature that favours longs on BTC and shorts on
  ETH has found the markets, not a mechanism. The per-market row is printed
  next to the pooled one.
* **Many questions, one correction.** Roughly thirty contrasts are examined, so
  at the five-percent level between one and two will look real by chance.
  Bonferroni's threshold is printed beside the nominal one, and only the
  figures that clear it are called findings.

**What makes a result here usable.** A difference that survives all three is
still only a candidate until it has been measured as an actual filter -- which
is the test four levers failed earlier today, every one of them because it
changed how many trades happened rather than how good they were. The last
section therefore turns each surviving contrast into the one number that
matters: what the expectancy would have been having kept only those trades, and
how many trades would have been left.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.sim.broker import Fill
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool

BOOT = 3000
MARKETS = 4

#: Fewest trades in a group before its mean is worth printing.
MIN_GROUP = 30

#: Nominal level, and the number of contrasts it is spread across.
ALPHA = 0.05

#: Fewest trades a single market needs before its sign is read.
#:
#: The per-market check asks only whether the markets point the same way, and a
#: market with three winners can point anywhere.
MIN_PER_MARKET = 5


@dataclass
class Trade:
    """One fill, reduced to what was knowable when the order went in.

    Plus the result, and the two descriptive fields -- which are kept apart
    from the rest precisely so they cannot be used as levers by accident.
    """

    symbol: str
    r: float
    setup: str
    side: Side
    stop_pct: float
    """Stop distance as a fraction of the entry price. The number the whole
    cost argument turns on: fees scale with position size and risk does not."""
    reward_risk: float
    cost_fraction: float
    """What the round trip cost, as a share of what was risked."""
    leverage: float
    hour: int
    weekday: int
    # -- known only afterwards --
    bars_held: float
    exit_reason: str


def to_trade(symbol: str, fill: Fill, signal_ms: int) -> Trade | None:
    stop_distance = fill.risk_amount / fill.qty if fill.qty > 0 else 0.0
    if stop_distance <= 0 or fill.entry_price <= 0 or fill.risk_amount <= 0:
        return None
    opened = datetime.fromtimestamp(fill.opened_ts / 1000, tz=UTC)
    target_distance = abs(fill.exit_price - fill.entry_price)
    return Trade(
        symbol=symbol,
        r=fill.r_multiple,
        setup=fill.setup or "?",
        side=fill.side,
        stop_pct=stop_distance / fill.entry_price,
        # The realised move over the risked one. Planned R:R is not on the
        # fill; this stands in for "how far did it have to go", and it is only
        # used for the descriptive block for that reason.
        reward_risk=target_distance / stop_distance,
        cost_fraction=fill.fees / fill.risk_amount,
        leverage=fill.leverage,
        hour=opened.hour,
        weekday=opened.weekday(),
        bars_held=(fill.closed_ts - fill.opened_ts) / signal_ms,
        exit_reason=fill.reason.value,
    )


def interval(values: list[float], seed: int = 11) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    sample = np.array(values, dtype="float64")
    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def contrast(
    winners: list[float], losers: list[float], seed: int = 11
) -> tuple[float, float, float]:
    """Winners minus losers, with a bootstrap interval on the difference."""
    rng = np.random.default_rng(seed)
    w = np.array(winners, dtype="float64")
    s = np.array(losers, dtype="float64")
    draws = rng.choice(w, size=(BOOT, len(w)), replace=True).mean(axis=1) - rng.choice(
        s, size=(BOOT, len(s)), replace=True
    ).mean(axis=1)
    return (
        float(w.mean() - s.mean()),
        float(np.percentile(draws, 2.5)),
        float(np.percentile(draws, 97.5)),
    )


#: The features, and whether the system had them before it submitted.
BEFORE: dict[str, Callable[[Trade], float]] = {
    "Stopweite % vom Preis": lambda t: 100 * t.stop_pct,
    "Kostenanteil % vom Risiko": lambda t: 100 * t.cost_fraction,
    "Hebel": lambda t: t.leverage,
    "Stunde (UTC)": lambda t: float(t.hour),
    "Wochentag": lambda t: float(t.weekday),
    "Long (1) / Short (0)": lambda t: 1.0 if t.side is Side.LONG else 0.0,
}

AFTER: dict[str, Callable[[Trade], float]] = {
    "Kerzen gehalten": lambda t: t.bars_held,
    "Weg in Stop-Einheiten": lambda t: t.reward_risk,
}


@dataclass
class Finding:
    name: str
    difference: float
    low: float
    high: float
    markets_agree: bool
    survives: bool = field(default=False)


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)
    signal_ms = {"M15": 900_000, "H1": 3_600_000}.get(
        config.engine.timeframes.signal.value, 3_600_000
    )

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:MARKETS])
    )

    trades: list[Trade] = []
    for symbol in symbols:
        started = time.perf_counter()
        frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
        minutes = store.read(symbol, config.engine.timeframes.execution)
        if any(f.empty for f in frames.values()) or minutes.empty:
            print(f"{symbol}: keine Daten", flush=True)
            continue
        analysis = MultiFrameAnalysis(frames, config.engine)
        engine = BacktestEngine(
            symbol,
            analysis,
            minute_frame=minutes,
            spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
            config=config,
            funding=funding_store.read(symbol),
            history=None,
        )
        result = engine.run(GuidePool.for_config(config))
        fresh = [t for f in result.fills if (t := to_trade(symbol, f, signal_ms)) is not None]
        trades.extend(fresh)
        print(
            f"{symbol}: {len(fresh)} Trades in {time.perf_counter() - started:.0f}s",
            flush=True,
        )

    if len(trades) < 2 * MIN_GROUP:
        print(f"\nNur {len(trades)} Trades -- zu wenige fuer die Frage.")
        return 1

    report(trades, symbols)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    return parser.parse_args()


def report(trades: list[Trade], symbols: list[str]) -> None:
    winners = [t for t in trades if t.r > 0]
    losers = [t for t in trades if t.r <= 0]

    print("\n" + "=" * 78)
    print(f"{len(trades)} Trades: {len(winners)} Gewinner, {len(losers)} Verlierer")
    low, high = interval([t.r for t in trades])
    print(f"Erwartung {np.mean([t.r for t in trades]):+.4f} R  [{low:+.3f}, {high:+.3f}]")
    print(
        f"Gewinner im Mittel {np.mean([t.r for t in winners]):+.3f} R, "
        f"Verlierer {np.mean([t.r for t in losers]):+.3f} R"
    )

    tests = len(BEFORE) + len(AFTER) + 2  # plus the setup and exit tables
    print(f"\nBonferroni: {tests} Vergleiche, Schwelle {ALPHA / tests:.4f} statt {ALPHA}")
    print("Ein Intervall, das die Null enthaelt, ist kein Befund.\n")

    findings = feature_table(winners, losers, symbols, trades)
    setup_table(trades)
    print("\n--- nur im Rueckblick bekannt, keine Hebel ---")
    for name, read in AFTER.items():
        diff, lo, hi = contrast([read(t) for t in winners], [read(t) for t in losers])
        print(f"  {name:28s} {diff:+8.2f}   [{lo:+.2f}, {hi:+.2f}]")
    print("  (Gewinner halten laenger, weil sie gewinnen. Das ist keine Ursache.)")

    as_filter(trades, findings)


def feature_table(
    winners: list[Trade], losers: list[Trade], symbols: list[str], trades: list[Trade]
) -> list[Finding]:
    print(f"{'Merkmal':28s}{'Gewinner':>10s}{'Verlierer':>11s}{'Differenz':>11s}  Intervall")
    findings: list[Finding] = []
    for name, read in BEFORE.items():
        w = [read(t) for t in winners]
        s = [read(t) for t in losers]
        diff, lo, hi = contrast(w, s)
        excludes_zero = lo > 0 or hi < 0

        agree = True
        if len(symbols) > 1:
            signs = set()
            for symbol in symbols:
                sw = [read(t) for t in winners if t.symbol == symbol]
                sl = [read(t) for t in losers if t.symbol == symbol]
                if len(sw) >= MIN_PER_MARKET and len(sl) >= MIN_PER_MARKET:
                    signs.add(float(np.mean(sw)) > float(np.mean(sl)))
            agree = len(signs) <= 1

        mark = ""
        if excludes_zero and agree:
            mark = "  <- Befund"
        elif excludes_zero:
            mark = "  <- Null aus, aber Maerkte uneinig"
        print(
            f"{name:28s}{np.mean(w):10.3f}{np.mean(s):11.3f}{diff:+11.3f}"
            f"  [{lo:+.3f}, {hi:+.3f}]{mark}"
        )
        findings.append(Finding(name, diff, lo, hi, agree, excludes_zero and agree))
    return findings


def setup_table(trades: list[Trade]) -> None:
    """Which rule earned its slots, per trade rather than by removal.

    By removal was the only way to ask before the setup name travelled with the
    fill, and it answers a different question: dropping a setup frees its slots
    for the others, so the comparison moves two things at once.
    """
    print("\n--- je Setup ---")
    grouped: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        grouped[t.setup].append(t.r)
    for setup, rs in sorted(grouped.items(), key=lambda kv: -float(np.mean(kv[1]))):
        if len(rs) < MIN_GROUP:
            print(f"  {setup:10s} n={len(rs):5d}  zu wenige")
            continue
        lo, hi = interval(rs)
        wins = 100 * sum(1 for r in rs if r > 0) / len(rs)
        flag = "  <- Null ausgeschlossen" if lo > 0 or hi < 0 else ""
        print(
            f"  {setup:10s} n={len(rs):5d}  {np.mean(rs):+.4f} R  Treffer {wins:3.0f}%  "
            f"Summe {sum(rs):+7.1f} R  [{lo:+.3f}, {hi:+.3f}]{flag}"
        )


def as_filter(trades: list[Trade], findings: list[Finding]) -> None:
    """Each surviving contrast, turned into the only number that counts.

    A difference between winners and losers is not yet a rule. The rule is
    "trade only where the feature is on the winners' side", and the question is
    whether the kept trades are better -- not whether the sum improved, which
    any filter achieves by trading less. This is the test four levers failed
    earlier today.
    """
    survivors = [f for f in findings if f.survives]
    print("\n--- und als Regel gerechnet ---")
    if not survivors:
        print("  Kein Merkmal hat Intervall und Markt-Einigkeit zugleich ueberstanden.")
        print("  Das ist die haeufigste und die ehrlichste Antwort auf diese Frage.")
        return

    base = float(np.mean([t.r for t in trades]))
    for finding in survivors:
        read = BEFORE[finding.name]
        values = sorted(read(t) for t in trades)
        middle = values[len(values) // 2]
        for label, above in (("obere Haelfte", True), ("untere Haelfte", False)):
            kept = [t.r for t in trades if (read(t) >= middle) is above]
            if len(kept) < MIN_GROUP:
                continue
            lo, hi = interval(kept)
            print(
                f"  {finding.name:28s} {label:14s} n={len(kept):5d}  "
                f"{np.mean(kept):+.4f} R (gegen {base:+.4f})  [{lo:+.3f}, {hi:+.3f}]"
            )


if __name__ == "__main__":
    raise SystemExit(main())
