"""Fetch research transcripts for the curated Daytrading YouTube corpus.

This is a research helper, not part of the trading runtime.  It preserves
timestamps and transcript provenance so that the final guide can cite videos
without reproducing their transcripts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi


PLAYLIST_VIDEOS = [
    {
        "id": "W9rc0RQvf0s",
        "title": "In nur 10 Minuten Daytrading verstehen! (für Anfänger erklärt)",
        "creator": "Finanzfluss",
        "topic": "Grundlagen",
    },
    {
        "id": "B6xG-m2fn78",
        "title": "Als Anfänger SCHNELL Traden lernen! (Schritt-für-Schritt Anleitung)",
        "creator": "Henry F.",
        "topic": "Grundlagen / Trading-Prozess",
    },
    {
        "id": "tW13N4Hll88",
        "title": "The ONLY Candlestick Pattern Guide You'll EVER NEED",
        "creator": "TradingLab",
        "topic": "Candlesticks",
    },
    {
        "id": "9NbmBDUysOA",
        "title": "Secret Formula For Drawing Support & Resistances",
        "creator": "TradingLab",
        "topic": "Support & Resistance",
    },
    {
        "id": "yJDaddL6SB4",
        "title": "FVG Trading Strategy Explained (Fair Value Gaps)",
        "creator": "Trader Tips",
        "topic": "Fair Value Gaps",
    },
    {
        "id": "8nIoOnGOZU8",
        "title": "The ONLY Trendline Trading Video You NEED in 2026!",
        "creator": "TradingLab",
        "topic": "Trendlines",
    },
    {
        "id": "WbMnfiknBoc",
        "title": "Der BESTE Leitfaden zu CHART-MUSTER-Preisaktionen",
        "creator": "The Moving Average",
        "topic": "Chart Patterns",
    },
    {
        "id": "ZudTPpJCbbA",
        "title": "How to Avoid False Breakouts (My Secret Technique)",
        "creator": "TradingLab",
        "topic": "False Breakouts",
    },
    {
        "id": "fPSQ_NnmqWI",
        "title": "The ULTIMATE Supply & Demand Guide (My Secrets)",
        "creator": "TradingLab",
        "topic": "Supply & Demand",
    },
    {
        "id": "Skn0eSmryO8",
        "title": "Liquidity Sweep Trading Strategy Explained",
        "creator": "Trader Tips",
        "topic": "Liquidity Sweeps",
    },
    {
        "id": "AwxIbna0By4",
        "title": "So erkennst du einen Orderblock",
        "creator": "Noc Trading",
        "topic": "Order Blocks",
    },
    {
        "id": "qmsGqitE2LE",
        "title": "I Found a Secret To Orderblocks",
        "creator": "TradingLab",
        "topic": "Order Blocks",
    },
    {
        "id": "ZTMregh_428",
        "title": "I Found A Secret To Fair Value Gaps",
        "creator": "TradingLab",
        "topic": "Fair Value Gaps",
    },
]


def choose_transcript(api: YouTubeTranscriptApi, video_id: str):
    transcripts = api.list(video_id)
    preferred = ["de", "en", "en-US"]
    for finder in (
        transcripts.find_manually_created_transcript,
        transcripts.find_generated_transcript,
    ):
        try:
            return finder(preferred)
        except Exception:
            pass
    return next(iter(transcripts))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research/transcripts"),
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    api = YouTubeTranscriptApi()
    manifest: list[dict[str, object]] = []
    for position, video in enumerate(PLAYLIST_VIDEOS, start=1):
        record = dict(video)
        record["position"] = position
        record["url"] = f"https://www.youtube.com/watch?v={video['id']}"
        try:
            transcript = choose_transcript(api, str(video["id"]))
            fetched = transcript.fetch()
            lines = [
                f"[{item.start:09.3f}] {item.text.replace(chr(10), ' ')}"
                for item in fetched
            ]
            output_path = args.output / f"{position:02d}_{video['id']}.txt"
            output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            record.update(
                {
                    "transcript_available": True,
                    "transcript_complete": True,
                    "language": transcript.language,
                    "language_code": transcript.language_code,
                    "is_generated": transcript.is_generated,
                    "segments": len(fetched),
                    "duration_seconds": round(
                        max((item.start + item.duration for item in fetched), default=0),
                        3,
                    ),
                    "file": str(output_path),
                }
            )
        except Exception as error:
            record.update(
                {
                    "transcript_available": False,
                    "transcript_complete": False,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
        manifest.append(record)

    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
