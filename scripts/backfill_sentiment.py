"""Fetch the crypto Fear & Greed index.

    python scripts/backfill_sentiment.py

The whole history arrives in one request -- a few thousand daily rows going back
to 2018 -- so there is no paging, no resume and nothing to interrupt. Run it
again whenever the local copy has fallen behind; rows merge by date.

Why this one and not headlines: the index is published once a day and never
revised, so the value for a past day is the value that existed on that day.
A headline archive cannot say when anyone read it, and a backtest built on one
measures hindsight.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from traidingbrain.analysis.context import SENTIMENT_FILE
from traidingbrain.config.settings import load_config
from traidingbrain.data.sentiment import (
    SentimentStore,
    SentimentUnavailableError,
    classify,
    fetch,
)


def main() -> int:
    config = load_config()
    path = config.engine.paths.data_dir / SENTIMENT_FILE

    print("fetching the Fear & Greed index ...")
    try:
        frame = fetch()
    except SentimentUnavailableError as error:
        print(f"  {error}", file=sys.stderr)
        return 1

    store = SentimentStore(path)
    total = store.write(frame)

    first = datetime.fromtimestamp(int(frame["ts"].iloc[0]) / 1000, tz=UTC).date()
    last = datetime.fromtimestamp(int(frame["ts"].iloc[-1]) / 1000, tz=UTC).date()
    newest = int(frame["value"].iloc[-1])

    print(f"  {len(frame):,} daily readings, {first} to {last}")
    print(f"  newest: {newest}/100 ({classify(newest)})")
    print(f"  {total:,} rows on disk at {path}")
    print("\nA decision never sees the reading for its own day; one day of")
    print("staleness is cheaper than a question about what the index already knew.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
