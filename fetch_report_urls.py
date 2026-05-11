#!/usr/bin/env python3
"""Fetch REPORT URLs for all 65 matches and update the JSON file."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from football_news_hub.crawler.arsenal import ArsenalCrawler
from football_news_hub.config import load_config


async def fetch_report_urls():
    # Load matches from JSON
    json_path = Path(__file__).parent / "data" / "arsenal_matches.json"
    with open(json_path, "r", encoding="utf-8") as f:
        matches = json.load(f)

    print(f"Loaded {len(matches)} matches from {json_path}")

    # Initialize crawler
    config = load_config(Path(__file__).parent / "config" / "sources.yaml")
    source = config.get_source("arsenal")
    crawler = ArsenalCrawler(source)

    # Process each match
    for i, match in enumerate(matches, 1):
        detail_url = match.get("url", "")
        if not detail_url:
            print(f"[{i}/{len(matches)}] No URL found for match")
            match["report_url"] = None
            continue

        print(f"[{i}/{len(matches)}] Fetching REPORT URL from: {detail_url}")

        # Fetch REPORT URL using the existing method
        report_url = await crawler._fetch_report_url(detail_url)
        match["report_url"] = report_url

        if report_url:
            print(f"  -> Found: {report_url}")
        else:
            print(f"  -> Not found")

        # Small delay to be polite to the server
        await asyncio.sleep(0.5)

    # Save updated JSON
    output_path = json_path
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)

    print(f"\nUpdated {len(matches)} matches saved to {output_path}")

    # Show summary
    found = sum(1 for m in matches if m.get("report_url"))
    not_found = len(matches) - found
    print(f"REPORT URLs found: {found}")
    print(f"REPORT URLs not found: {not_found}")


if __name__ == "__main__":
    asyncio.run(fetch_report_urls())