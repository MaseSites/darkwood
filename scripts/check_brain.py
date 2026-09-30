"""Ask the brain one real question, and say exactly what broke if it fails.

    python scripts/check_brain.py
    python scripts/check_brain.py --brain api --symbol ETHUSDT

This is the first thing to run after setting up access. It takes the newest
snapshot from stored data, sends it down the full path -- prompt, model, schema,
guard, scoring -- and prints the answer. One call, so it costs a cent at most and
proves the part that cannot be proved offline.

The three ways this goes wrong -- not signed in, no data, no key -- look identical
from the outside and have three different fixes, so each is reported as the thing
to do rather than as a stack trace.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.analysis.context import load_context
from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.brain.factory import BRAIN_NAMES, make_brain
from traidingbrain.brain.subscription import SubscriptionUnavailableError
from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.domain.verdict import BrainDecision

#: How far back to look for a complete snapshot. The newest bars can still be
#: warming up on the weekly frame, which is a normal answer rather than a fault.
SEARCH_BARS = 200


def _latest_snapshot(builder: SnapshotBuilder, bars: int) -> MarketSnapshot | None:
    for index in range(bars - 1, max(bars - SEARCH_BARS, 0), -1):
        snapshot = builder.build(index)
        if snapshot is not None:
            return snapshot
    return None


def _print_plan(decision: BrainDecision) -> None:
    """The plan, or the reason there is none.

    A guard rejection and a considered no-trade are both empty plans, and telling
    them apart is the difference between a prompt that needs work and a model that
    was simply not interested.
    """
    plan = decision.plan
    if plan is not None:
        print(
            f"\n  plan        {plan.side.value} entry {plan.entry:.2f} "
            f"stop {plan.stop:.2f} target {plan.target:.2f}  (R:R {plan.reward_risk:.2f})"
        )
        return
    reason = "guard rejected it" if not decision.guard.passed else "no trade proposed"
    print(f"\n  plan        none -- {reason}")
    for violation in decision.guard.violations:
        print(f"    rejected: {violation}")


def _print_decision(decision: BrainDecision) -> None:
    verdict = decision.verdict
    print(f"  bias        {verdict.bias.value}")
    print(f"  decision    {verdict.decision.value}")
    print(f"  risk        {verdict.risk.value}")
    print(f"  confidence  {decision.confidence:.0f} / 100   (weighted by Python, not the model)")
    print("\n  factors")
    for factor in verdict.factor_scores:
        print(
            f"    {factor.factor.value:<11s} {factor.score:+.2f} "
            f"(sure to {factor.confidence:.0%})  {factor.reasoning[:70]}"
        )
    print("\n  reasoning")
    for line in verdict.reasoning:
        print(f"    - {line[:100]}")
    _print_plan(decision)


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--brain", choices=BRAIN_NAMES, default="subscription")
    parser.add_argument("--symbol", default=config.engine.symbols.active[0])
    args = parser.parse_args(argv)

    store = ParquetStore(config.engine.paths.parquet_dir)
    frames = {tf: store.read(args.symbol, tf) for tf in config.engine.timeframes.context}
    if any(frame.empty for frame in frames.values()):
        print(
            f"No stored data for {args.symbol}.\n"
            f"  python scripts/backfill.py {args.symbol} --since 2023-01-01",
            file=sys.stderr,
        )
        return 1

    analysis = MultiFrameAnalysis(frames, config.engine)
    context = load_context(args.symbol, analysis.signal.frame, config.engine)
    print(f"  context: {context.description}\n")
    builder = SnapshotBuilder(
        args.symbol,
        analysis,
        config.engine,
        positioning=context.positioning,
        calendar=context.calendar,
        sentiment=context.sentiment,
    )
    snapshot = _latest_snapshot(builder, len(analysis.signal))
    if snapshot is None:
        print(f"Could not build a snapshot for {args.symbol}.", file=sys.stderr)
        return 1

    print(f"asking the {args.brain} brain about {args.symbol}, one snapshot ...\n")
    try:
        brain = make_brain(args.brain, config)
        decision = brain.decide(snapshot)
    except SubscriptionUnavailableError as error:
        print(f"Not signed in.\n\n{error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    _print_decision(decision)
    print(f"\n  {brain.usage.summary()}")
    if args.brain == "subscription":
        print("  (the dollar figure is what this would have cost on the API, not a charge)")
    print("\nThe brain works. Nothing was sent to any exchange.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
