#!/usr/bin/env python3
"""Fetch Arsenal match reports."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from football_news_hub.config import load_config
from football_news_hub.crawler.arsenal import ArsenalCrawler


async def fetch_report(match_num: int):
    config = load_config(Path("config/sources.yaml"))
    arsenal_source = config.get_source("arsenal")
    crawler = ArsenalCrawler(arsenal_source)

    with open("data/arsenal_matches.json", "r") as f:
        matches = json.load(f)

    count = 0
    for m in matches:
        if m.get("report_url"):
            count += 1
            if count == match_num:
                print(f"Match #{count}: {m['opponent']} ({m['date'][:10]})")
                result = await crawler._fetch_match_report(m["report_url"])

                if result:
                    report_data = {
                        "match_info": {
                            "url": m["url"],
                            "report_url": m["report_url"],
                            "date": m["date"],
                            "score": m["score"],
                            "opponent": m["opponent"],
                            "competition": m["competition"],
                            "venue": m["venue"],
                        },
                        "report": {
                            "title": result.get("title", ""),
                            "author": result.get("author", ""),
                            "published_at": (
                                str(result.get("published_at", ""))
                                if result.get("published_at")
                                else ""
                            ),
                            "image_url": result.get("image_url", ""),
                            "description": result.get("description", ""),
                            "article_body": result.get("article_body", ""),
                            "scorers": result.get("scorers", []),
                        },
                    }

                    safe_name = m["opponent"].lower().replace(" ", "-")
                    filename = f"data/arsenal_reports/arsenal_{m['date'][:10]}_{safe_name}.json"
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump(report_data, f, ensure_ascii=False, indent=2)

                    print(f"Saved: {filename}")
                    print(f"Title: {report_data['report']['title']}")
                    print(f"Scorers: {report_data['report']['scorers']}")
                else:
                    print("FAILED to fetch report")
                return

    print(f"Match #{match_num} not found")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch_report.py <match_number>")
        sys.exit(1)

    match_num = int(sys.argv[1])
    asyncio.run(fetch_report(match_num))