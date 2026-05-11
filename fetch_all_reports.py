#!/usr/bin/env python3
"""Fetch all remaining Arsenal match reports."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from football_news_hub.config import load_config
from football_news_hub.crawler.arsenal import ArsenalCrawler


async def fetch_all_reports():
    config = load_config(Path("config/sources.yaml"))
    arsenal_source = config.get_source("arsenal")
    crawler = ArsenalCrawler(arsenal_source)

    with open("data/arsenal_matches.json", "r") as f:
        matches = json.load(f)

    # Get existing report files
    reports_dir = Path("data/arsenal_reports")
    existing_files = set(f.name for f in reports_dir.glob("*.json"))
    print(f"Existing report files: {len(existing_files)}")

    # Filter matches that have report_url and don't have existing reports
    matches_with_reports = []
    for m in matches:
        if not m.get("report_url"):
            continue
        safe_name = m["opponent"].lower().replace(" ", "-")
        expected_files = [
            f"arsenal_{m['date'][:10]}_{safe_name}.json",
            f"report_{m['date'][:10]}_{safe_name}.json",
        ]
        # Check if any of the possible filenames already exist
        if any(f in existing_files for f in expected_files):
            continue
        matches_with_reports.append(m)

    print(f"Matches needing reports: {len(matches_with_reports)}")

    if not matches_with_reports:
        print("All reports already fetched!")
        return

    # Fetch each missing report
    for i, m in enumerate(matches_with_reports, 1):
        safe_name = m["opponent"].lower().replace(" ", "-")
        print(f"[{i}/{len(matches_with_reports)}] Fetching: {m['opponent']} ({m['date'][:10]})")

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

            filename = f"report_{m['date'][:10]}_{safe_name}.json"
            filepath = reports_dir / filename
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)

            print(f"  -> Saved: {filename}")
        else:
            print(f"  -> FAILED to fetch report")

        # Small delay to be polite to the server
        await asyncio.sleep(0.5)

    print(f"\nDone! Fetched {len(matches_with_reports)} reports.")


if __name__ == "__main__":
    asyncio.run(fetch_all_reports())