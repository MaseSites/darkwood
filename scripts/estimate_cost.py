"""What an LLM backtest would cost, before spending anything.

    python scripts/estimate_cost.py
    python scripts/estimate_cost.py --symbols BTCUSDT ETHUSDT SOLUSDT XRPUSDT
    python scripts/estimate_cost.py --model claude-sonnet-5-5 --batch

This runs the real gate over the real data and counts how many bars would actually
reach the model. That count is the whole answer: the prompt size is known and the
per-token prices are known, so the only unknown worth measuring is how often the
cheap filter lets something through -- and guessing that wrong is the difference
between a twenty dollar run and a four hundred dollar one.

Token counts are estimated from characters when no API key is present, and
measured through `count_tokens` when there is one. The estimate is labelled as
such, because a dry run that quietly lies about the bill is worse than no dry run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.analysis.snapshot import SnapshotBuilder
from traidingbrain.brain import prompt as prompts
from traidingbrain.brain.client import BATCH_DISCOUNT, PRICING
from traidingbrain.brain.trigger import Trigger
from traidingbrain.config.settings import load_config, load_secrets
from traidingbrain.data.store import ParquetStore

#: Characters per token, for the offline estimate. English prose sits near four;
#: this payload is dense JSON with many digits and punctuation marks, which
#: tokenises worse, so the divisor is deliberately low -- an estimate that comes in
#: under the real bill is the wrong kind of wrong.
CHARS_PER_TOKEN = 3.2

#: Output tokens per call, from the shape of the schema plus reasoning text.
#: Adjustable, and worth re-measuring after the first real run.
ASSUMED_OUTPUT_TOKENS = 900

#: The system prompt is identical on every call after the first, so it is billed
#: at the cache read rate rather than the input rate.
CACHE_READ_MULTIPLIER = 0.05

#: Minimum cacheable prefix on the current models. Below it, a prompt silently
#: never caches and every call pays full input price.
MIN_CACHEABLE_TOKENS = 512

#: Snapshots are near-identical in size, so the payload is measured on a sample.
PAYLOAD_SAMPLE = 20


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbols", nargs="+", default=config.engine.symbols.active)
    parser.add_argument("--model", default=config.engine.brain.model, choices=sorted(PRICING))
    parser.add_argument(
        "--batch", action="store_true", help="price it through the Batch API (half)"
    )
    args = parser.parse_args(argv)

    secrets = load_secrets()
    have_key = bool(secrets.anthropic_api_key.get_secret_value())

    store = ParquetStore(config.engine.paths.parquet_dir)
    system_text = "".join(str(block["text"]) for block in prompts.system_blocks())
    system_tokens = estimate_tokens(system_text)

    print(f"model            {args.model}")
    print(f"prompt version   {prompts.PROMPT_VERSION}")
    print(f"system prompt    ~{system_tokens:,} tokens (cached after the first call)")
    if system_tokens < MIN_CACHEABLE_TOKENS:
        print("  WARNING: below the 512-token minimum, so it will never cache and")
        print("           every call pays the full input price.")
    print()

    total_calls, total_snapshot_tokens = _count_calls(args.symbols, config, store)

    if not total_calls:
        print("\nNothing would be asked. Either there is no data or the gate is too tight.")
        return 0

    rates = PRICING[args.model]
    input_rate, output_rate, cache_rate = rates

    # The first call writes the cache; every later one reads it.
    cached_input = system_tokens * (total_calls - 1) * cache_rate
    first_input = system_tokens * input_rate
    fresh_input = total_snapshot_tokens * input_rate
    output = total_calls * ASSUMED_OUTPUT_TOKENS * output_rate
    gross = (cached_input + first_input + fresh_input + output) / 1_000_000
    final = gross * (BATCH_DISCOUNT if args.batch else 1.0)

    naive = (
        (system_tokens + total_snapshot_tokens // max(1, total_calls) + ASSUMED_OUTPUT_TOKENS)
        * total_calls
        * max(input_rate, output_rate)
        / 1_000_000
    )

    print("\n" + "=" * 70)
    print(f"  calls            {total_calls:,}")
    print(f"  assumed output   {ASSUMED_OUTPUT_TOKENS} tokens per call")
    print(f"  pricing          ${input_rate}/${output_rate} per MTok, cache read ${cache_rate}")
    if args.batch:
        print("  batch API        yes (half price)")
    print(f"\n  ESTIMATE         ${final:,.2f}")
    print(f"  without caching  ${naive:,.2f}  -- what the same run costs if the prompt")
    print("                             prefix ever stops being byte-identical")
    print(
        "\n  Token counts are "
        + (
            "still estimated from characters; set ANTHROPIC_API_KEY and this will"
            if not have_key
            else "estimated from characters here; the client uses"
        )
        + "\n  use count_tokens for the real figure."
    )
    print(f"  Budget in settings.yaml: ${config.engine.brain.max_usd_per_backtest:,.2f}")
    if final > config.engine.brain.max_usd_per_backtest:
        print("  -> over budget. The run would stop partway through.")
    return 0


def _count_calls(symbols, config, store) -> tuple[int, int]:
    """Run the real gate over the real data and count what would reach the model.

    This is the only unknown worth measuring. Prompt size and per-token prices are
    both known; how often the cheap filter lets something through is not, and
    guessing it wrong is the difference between a twenty dollar run and a four
    hundred dollar one.
    """
    total_calls = 0
    total_tokens = 0

    for symbol in symbols:
        frames = {tf: store.read(symbol, tf) for tf in config.engine.timeframes.context}
        if any(frame.empty for frame in frames.values()):
            print(f"  {symbol}: no data, skipped")
            continue

        analysis = MultiFrameAnalysis(frames, config.engine)
        builder = SnapshotBuilder(symbol, analysis, config.engine)
        trigger = Trigger(config.engine.trigger)

        first = analysis.first_ready_index()
        if first is None:
            print(f"  {symbol}: not enough history")
            continue

        sampled = 0
        payload_tokens = 0
        for index in range(first, len(analysis.signal)):
            snapshot = builder.build(index)
            if snapshot is None or not trigger.should_ask(snapshot, index):
                continue
            if sampled < PAYLOAD_SAMPLE:
                payload_tokens += estimate_tokens(prompts.user_content(snapshot.to_brain_input()))
                sampled += 1

        per_call = payload_tokens // sampled if sampled else 0
        total_calls += trigger.stats.fired
        total_tokens += trigger.stats.fired * per_call

        print(f"  {symbol}")
        print(f"    {trigger.stats.summary()}")
        print(f"    snapshot payload ~{per_call:,} tokens per call")

    return total_calls, total_tokens


if __name__ == "__main__":
    raise SystemExit(main())
