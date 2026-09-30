"""Select and fetch the supplemental YouTube transcript corpus.

The selection is mechanical and auditable: for every research topic, keep the
first 20 relevant search results that are long-form, have meaningful reach (or
a verified creator), and expose an English or German transcript.  One video may
support several topics; the manifest records all mappings.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from youtube_transcript_api import YouTubeTranscriptApi


PRIMARY_IDS = {
    "W9rc0RQvf0s",
    "B6xG-m2fn78",
    "tW13N4Hll88",
    "9NbmBDUysOA",
    "yJDaddL6SB4",
    "8nIoOnGOZU8",
    "WbMnfiknBoc",
    "ZudTPpJCbbA",
    "fPSQ_NnmqWI",
    "Skn0eSmryO8",
    "AwxIbna0By4",
    "qmsGqitE2LE",
    "ZTMregh_428",
}


TOPIC_CHAPTERS = {
    "grundlagen_market_structure": [1, 2, 3, 19, 30, 31, 32, 33, 34],
    "candlesticks": [4, 19, 30, 33, 34],
    "support_resistance": [5, 9, 10, 19, 20, 21, 30, 33, 34],
    "trendlines": [7, 8, 9, 10, 19, 30, 33, 34],
    "chart_patterns_breakouts": [8, 9, 10, 19, 30, 33, 34],
    "supply_demand": [5, 6, 11, 12, 15, 19, 30, 33, 34],
    "liquidity": [11, 12, 13, 14, 19, 30, 33, 34],
    "bos_choch_mss": [2, 3, 13, 14, 19, 30, 33, 34],
    "order_breaker_blocks": [6, 11, 15, 16, 19, 30, 33, 34],
    "fvg_ifvg": [11, 17, 18, 19, 30, 33, 34],
    "entries_exits_risk": [19, 20, 21, 22, 23, 26, 30, 31, 32, 33, 34],
    "sessions_news_mtf": [3, 24, 25, 30, 31, 32, 33, 34],
    "psychology_management": [26, 27, 30, 31, 32, 33, 34],
    "backtesting_journaling": [28, 29, 30, 31, 32, 33, 34],
}


def choose_transcript(api: YouTubeTranscriptApi, video_id: str):
    transcripts = api.list(video_id)
    preferred = ["en", "en-US", "de"]
    for finder in (
        transcripts.find_manually_created_transcript,
        transcripts.find_generated_transcript,
    ):
        try:
            return finder(preferred)
        except Exception:
            pass
    raise LookupError("No English or German transcript")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")[:120]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-topic", type=int, default=20)
    parser.add_argument("--min-views", type=int, default=20_000)
    parser.add_argument("--batch-start", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()

    base = Path("research/supplemental")
    candidates: list[dict[str, Any]] = json.loads(
        (base / "candidates.json").read_text(encoding="utf-8")
    )
    by_id = {str(item["id"]): item for item in candidates}

    ordered_ids: list[str] = []
    for topic in TOPIC_CHAPTERS:
        ranked: list[tuple[int, str]] = []
        for item in candidates:
            for match in item.get("matches") or []:
                if match.get("topic") == topic:
                    ranked.append((int(match.get("rank") or 999), str(item["id"])))
        ordered_ids.extend(video_id for _, video_id in sorted(ranked))
    ordered_ids = list(dict.fromkeys(ordered_ids))

    cache_path = base / "transcript_status.json"
    if cache_path.exists():
        cache: dict[str, dict[str, Any]] = json.loads(
            cache_path.read_text(encoding="utf-8")
        )
    else:
        cache = {}

    api = YouTubeTranscriptApi()
    batch = ordered_ids[args.batch_start : args.batch_start + args.batch_size]
    raw_dir = base / "transcripts"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for index, video_id in enumerate(batch, start=args.batch_start):
        if video_id in cache:
            continue
        item = by_id[video_id]
        duration = int(item.get("duration_seconds") or 0)
        views = int(item.get("views") or 0)
        eligible = (
            video_id not in PRIMARY_IDS
            and 300 <= duration <= 14_400
            and (bool(item.get("verified")) or views >= args.min_views)
        )
        if not eligible:
            cache[video_id] = {"eligible": False, "reason": "quality_filter"}
            continue
        try:
            transcript = choose_transcript(api, video_id)
            fetched = transcript.fetch()
            transcript_path = raw_dir / f"{safe_name(video_id)}.txt"
            transcript_path.write_text(
                "\n".join(
                    f"[{segment.start:09.3f}] {segment.text.replace(chr(10), ' ')}"
                    for segment in fetched
                )
                + "\n",
                encoding="utf-8",
            )
            cache[video_id] = {
                "eligible": True,
                "transcript_available": True,
                "transcript_complete": True,
                "language": transcript.language,
                "language_code": transcript.language_code,
                "is_generated": transcript.is_generated,
                "segments": len(fetched),
                "duration_seconds": round(
                    max(
                        (segment.start + segment.duration for segment in fetched),
                        default=0,
                    ),
                    3,
                ),
                "file": str(transcript_path),
            }
        except Exception as error:
            cache[video_id] = {
                "eligible": True,
                "transcript_available": False,
                "transcript_complete": False,
                "error": f"{type(error).__name__}: {error}",
            }
        if index % 10 == 0:
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"checked {index + 1}/{len(ordered_ids)}")

    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    selected_by_topic: dict[str, list[str]] = {}
    selected_ids: set[str] = set()
    for topic in TOPIC_CHAPTERS:
        ranked = []
        for item in candidates:
            for match in item.get("matches") or []:
                if match.get("topic") == topic:
                    ranked.append((int(match.get("rank") or 999), str(item["id"])))
        chosen = []
        for _, video_id in sorted(ranked):
            status = cache.get(video_id) or {}
            if status.get("transcript_available"):
                chosen.append(video_id)
                selected_ids.add(video_id)
            if len(chosen) >= args.per_topic:
                break
        selected_by_topic[topic] = chosen

    manifest = []
    for video_id in sorted(selected_ids):
        item = dict(by_id[video_id])
        topics = [topic for topic, ids in selected_by_topic.items() if video_id in ids]
        chapters = sorted(
            {chapter for topic in topics for chapter in TOPIC_CHAPTERS[topic]}
        )
        item.update(cache[video_id])
        item["topics"] = topics
        item["chapters"] = chapters
        manifest.append(item)

    (base / "selected_by_topic.json").write_text(
        json.dumps(selected_by_topic, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (base / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "checked": len(cache),
                "selected_unique": len(manifest),
                "per_topic": {
                    topic: len(ids) for topic, ids in selected_by_topic.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
