"""Discover supplemental YouTube education videos for the Daytrading guide."""

from __future__ import annotations

import json
from pathlib import Path

import yt_dlp

QUERIES = {
    "grundlagen_market_structure": "day trading complete course price action market structure",
    "candlesticks": "candlestick patterns day trading complete guide",
    "support_resistance": "support resistance day trading strategy full course",
    "trendlines": "trendline trading strategy full course",
    "chart_patterns_breakouts": "chart patterns breakout false breakout trading course",
    "supply_demand": "supply and demand trading full course",
    "liquidity": "liquidity sweep trading strategy full course",
    "bos_choch_mss": "BOS CHOCH MSS market structure trading full course",
    "order_breaker_blocks": "order block breaker block trading full course",
    "fvg_ifvg": "fair value gap inverse FVG trading full course",
    "entries_exits_risk": "trading entries stop loss take profit risk reward position sizing",
    "sessions_news_mtf": "day trading sessions news volatility multi timeframe analysis",
    "psychology_management": "trading psychology trade management full course",
    "backtesting_journaling": "trading backtesting journaling full course",
}


def main() -> None:
    output = Path("research/supplemental/candidates.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    options = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    records: dict[str, dict[str, object]] = {}
    with yt_dlp.YoutubeDL(options) as downloader:
        for topic, query in QUERIES.items():
            result = downloader.extract_info(f"ytsearch25:{query}", download=False)
            for rank, entry in enumerate(result.get("entries") or [], start=1):
                if not entry or not entry.get("id"):
                    continue
                video_id = str(entry["id"])
                record = records.setdefault(
                    video_id,
                    {
                        "id": video_id,
                        "title": entry.get("title"),
                        "creator": entry.get("channel") or entry.get("uploader"),
                        "creator_id": entry.get("uploader_id"),
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "duration_seconds": entry.get("duration"),
                        "views": entry.get("view_count"),
                        "verified": entry.get("channel_is_verified"),
                        "description": entry.get("description"),
                        "matches": [],
                    },
                )
                record["matches"].append(
                    {"topic": topic, "query": query, "rank": rank}
                )

    ranked = sorted(
        records.values(),
        key=lambda item: (
            not bool(item.get("verified")),
            -(int(item.get("views") or 0)),
            str(item.get("title") or ""),
        ),
    )
    output.write_text(
        json.dumps(ranked, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{len(ranked)} unique candidates -> {output}")


if __name__ == "__main__":
    main()
