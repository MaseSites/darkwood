"""Run a challenger against the champion, and only then look at the holdout.

    python scripts/challenge.py --arm zeitausstieg_24h --max-hold-hours 24
    python scripts/challenge.py --arm zeitausstieg_24h --max-hold-hours 24 --holdout

This is what makes the ratchet a tool rather than a decoration. `scripts/
ratchet.py` holds the champion and the register; this measures something
against it and files the result.

**Two windows, and the order matters.** Everything before the reserved stretch
is free to look at as often as wanted -- that is where candidates come from,
and a number from it is never a verdict. The reserved stretch at the end is
read only with `--holdout`, because reading it spends it: consult it twenty
times and pick the best and it has become a validation fold with extra steps.
`Register.consultations()` counts the spending and divides the confidence
budget among the attempts.

**The confidence level is taken before the measurement, never after.**
`Register.judge` reports `required_confidence` without being shown an
interval, and that number is passed to `two_group_difference` as its `level`.
Choosing the level after seeing the result is choosing it to pass, and
`study_winners.py` did exactly that once -- it printed a Bonferroni threshold
of 0.005 and then read a 95% interval.

**What a challenger has to clear.** Not a higher mean: all eight hypotheses
rejected on 05.10.2026 looked like a higher mean first. The interval on the
difference has to exclude zero at the corrected level, over at least
`MIN_HOLDOUT_TRADES` trades.

**What this does not do.** It never edits config. A win prints what to change
and leaves the change to a human, because a system that rewrites its own
trading rules from its own measurements is what the confirm-before-execute rule
exists to prevent -- and it would do it invisibly.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.version import run_signature
from traidingbrain.learn.register import (
    MIN_HOLDOUT_TRADES,
    Register,
    Result,
    Stage,
)
from traidingbrain.reporting.intervals import block_bootstrap, two_group_difference
from traidingbrain.sim.engine import BacktestEngine
from traidingbrain.strategies.guide import GuidePool
from traidingbrain.strategies.vol_breakout import VolBreakout

DAY_MS = 86_400_000

#: Days reserved at the end that exploration never touches.
#:
#: Six months, because the forward cadence is about 2.5 trades a day per market
#: and a verdict needs tens of trades. Shorter and the holdout cannot answer;
#: longer and there is too little left to find anything with.
HOLDOUT_DAYS = 180.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, help="Name under which this is filed, for good.")
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument(
        "--strategy",
        default="champion",
        choices=("champion", "vol-breakout"),
        help=(
            "Which entry logic the challenger uses. 'champion' keeps the shipped "
            "setups and varies only configuration; 'vol-breakout' replaces the "
            "entry logic entirely, which is how a whole strategy family is tested."
        ),
    )
    parser.add_argument(
        "--max-hold-hours",
        type=float,
        help="The challenger: close a position held this long. The champion has none.",
    )
    parser.add_argument(
        "--holdout",
        action="store_true",
        help=(
            "Read the reserved window and file a verdict. Spends part of the "
            "holdout's value and tightens the bar for every later arm, so it "
            "is a deliberate act rather than a default."
        ),
    )
    parser.add_argument("--holdout-days", type=float, default=HOLDOUT_DAYS)
    return parser.parse_args()


def challenger_config(config: AppConfig, *, max_hold_hours: float | None) -> AppConfig:
    """The champion's configuration with one thing changed, and only one.

    Rebuilt through the model rather than mutated: `AppConfig` is frozen on
    purpose, and an arm that quietly differs in two places is not a measurement
    of either.
    """
    if max_hold_hours is None:
        return config
    simulation = config.engine.simulation.model_copy(update={"max_hold_hours": max_hold_hours})
    engine = config.engine.model_copy(update={"simulation": simulation})
    return config.model_copy(update={"engine": engine})


def net_r(result: object) -> list[float]:
    """Each trade's outcome in multiples of its planned risk.

    R rather than currency, so markets and account sizes compare and so the
    number means the same thing as every other figure in this project.
    """
    out: list[float] = []
    for fill in result.fills:  # type: ignore[attr-defined]
        if fill.risk_amount > 0:
            out.append(fill.net_pnl / fill.risk_amount)
    return out


def run_arm(
    symbols: list[str],
    config: AppConfig,
    *,
    start_ts: int | None,
    end_ts: int | None,
    strategy: str = "champion",
) -> list[float]:
    """One arm over one window, pooled across markets.

    `strategy` chooses the entry logic. The champion's own logic is the
    default so that a configuration-only arm is compared against exactly the
    same entries, and a whole-family arm replaces them -- the engine tells
    the two apart through `wants_analysis`, so neither needs a snapshot it
    will not read."""
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding = FundingStore(config.engine.paths.funding_dir)
    pooled: list[float] = []
    for symbol in symbols:
        frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
        minutes = store.read(symbol, config.engine.timeframes.execution)
        if any(frame.empty for frame in frames.values()) or minutes.empty:
            print(f"  {symbol}: keine Daten", flush=True)
            continue
        engine = BacktestEngine(
            symbol,
            MultiFrameAnalysis(frames, config.engine),
            minute_frame=minutes,
            spec=SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
            config=config,
            funding=funding.read(symbol),
        )
        arm = VolBreakout() if strategy == "vol-breakout" else GuidePool.for_config(config)
        result = engine.run(arm, start_ts=start_ts, end_ts=end_ts)
        trades = net_r(result)
        pooled.extend(trades)
        print(f"  {symbol}: {len(trades)} Trades", flush=True)
    return pooled


def line(name: str, values: list[float]) -> str:
    if not values:
        return f"  {name:22s} keine Trades"
    interval = block_bootstrap(values)
    bounds = interval.labelled() if interval is not None else "zu wenige"
    mean = sum(values) / len(values)
    hits = 100 * sum(1 for v in values if v > 0) / len(values)
    return f"  {name:22s} n={len(values):5d}  {mean:+.4f} R  Treffer {hits:3.0f}%  {bounds}"


def main() -> int:
    args = parse_args()
    config = load_config()
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )
    register = Register(config.engine.paths.data_dir / "experiments.sqlite")
    champion = register.champion()
    if champion is None:
        print("Kein Champion. Erst `python scripts/ratchet.py --seed`.")
        return 1

    store = ParquetStore(config.engine.paths.parquet_dir)
    last = max(
        (store.last_ts(s, config.engine.timeframes.signal) or 0) for s in symbols
    )
    if last == 0:
        print("Keine Daten.")
        return 1
    boundary = last - int(args.holdout_days * DAY_MS)

    challenger = challenger_config(config, max_hold_hours=args.max_hold_hours)
    parts = []
    if args.strategy != "champion":
        parts.append(f"Einstiegslogik = {args.strategy}")
    if args.max_hold_hours is not None:
        parts.append(f"max_hold_hours = {args.max_hold_hours}")
    change = ", ".join(parts) if parts else "nichts geaendert"

    print("=" * 78)
    print(champion.describe())
    print(f"Herausforderer: {args.arm}  ({change})")
    print(f"Prueffenster: die letzten {args.holdout_days:.0f} Tage, zurueckbehalten.")

    # Always the explorable window first. A verdict that skipped it would be a
    # verdict on an arm nobody had ever looked at.
    print("\n--- vor dem Prueffenster (so oft lesbar wie man will, kein Urteil) ---")
    print("Champion:", flush=True)
    base_open = run_arm(symbols, config, start_ts=None, end_ts=boundary)
    print("Herausforderer:", flush=True)
    arm_open = run_arm(
        symbols, challenger, start_ts=None, end_ts=boundary, strategy=args.strategy
    )
    print()
    print(line("Champion", base_open))
    print(line(args.arm, arm_open))
    register.record(
        Result(
            arm=args.arm,
            stage=Stage.TEST,
            n=len(arm_open),
            mean_r=sum(arm_open) / len(arm_open) if arm_open else 0.0,
            low=0.0,
            high=0.0,
            note=f"{change}; vor dem Prueffenster, kein Urteil",
        ),
        run_signature=run_signature(config),
        now_ms=int(datetime.now(tz=UTC).timestamp() * 1000),
        strategy=args.strategy,
    )

    if not args.holdout:
        judgement = register.judge(
            Result(arm=args.arm, stage=Stage.TEST, n=0, mean_r=0, low=0, high=0)
        )
        print(
            f"\nKein Urteil. Mit --holdout wird das zurueckbehaltene Fenster gelesen;\n"
            f"das waere Konsultation {judgement.attempts} und verlangt dann ein "
            f"{100 * judgement.required_confidence:.2f}%-Intervall."
        )
        return 0

    # The level is fixed before the measurement, which is the whole point.
    return consult_holdout(
        arm=args.arm,
        symbols=symbols,
        config=config,
        challenger=challenger,
        register=register,
        boundary=boundary,
        change=change,
        now_ms=int(datetime.now(tz=UTC).timestamp() * 1000),
    )


def consult_holdout(
    *,
    arm: str,
    symbols: list[str],
    config: AppConfig,
    challenger: AppConfig,
    register: Register,
    boundary: int,
    change: str,
    now_ms: int,
    strategy: str,
) -> int:
    """Read the reserved window once, at a level fixed before the reading."""
    planned = register.judge(
        Result(arm=arm, stage=Stage.HOLDOUT, n=MIN_HOLDOUT_TRADES, mean_r=0, low=0, high=0)
    )
    level = planned.required_confidence
    print(
        f"\n--- das Prueffenster, Konsultation {planned.attempts} ---\n"
        f"Niveau {100 * level:.2f}%, VOR der Messung festgelegt."
    )
    print("Champion:", flush=True)
    base_hold = run_arm(symbols, config, start_ts=boundary, end_ts=None)
    print("Herausforderer:", flush=True)
    arm_hold = run_arm(
        symbols, challenger, start_ts=boundary, end_ts=None, strategy=strategy
    )
    print()
    print(line("Champion", base_hold))
    print(line(arm, arm_hold))

    difference = two_group_difference(arm_hold, base_hold, level=level)
    if difference is None:
        print("\n  Zu wenige Trades in einer der Gruppen fuer ein Intervall.")
        return 0
    base_mean = sum(base_hold) / len(base_hold)
    print(f"\n  Unterschied {difference.mean:+.4f} R   {difference.labelled()}")

    result = Result(
        arm=arm,
        stage=Stage.HOLDOUT,
        n=len(arm_hold),
        # Shifted onto the champion's scale so `judge` compares like with like:
        # it asks whether the arm's interval excludes the champion's mean, and
        # the difference interval is centred on zero.
        mean_r=base_mean + difference.mean,
        low=base_mean + difference.low,
        high=base_mean + difference.high,
        note=f"{change}; Niveau {100 * level:.2f}%, {planned.attempts}. Konsultation",
    )
    register.record(result, run_signature=run_signature(challenger), now_ms=now_ms)
    verdict = register.judge(result)
    print(f"\n  URTEIL: {verdict.verdict.value}")
    print(f"  {verdict.reason}")
    if verdict.replaces:
        print(
            f"\n  Dieser Arm darf den Champion ersetzen. Zu aendern: {change}\n"
            "  in config/settings.yaml, dann `scripts/ratchet.py` neu kroenen.\n"
            "  Das macht dieses Skript nicht selbst: ein System, das seine eigenen\n"
            "  Handelsregeln aus seinen eigenen Messungen umschreibt, ist genau das,\n"
            "  was die Bestaetigungsregel verhindern soll -- und es taete es unsichtbar."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
