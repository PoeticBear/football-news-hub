#!/usr/bin/env python3
"""Crawl Arsenal matches and save to JSON with full details."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from football_news_hub.config import load_config
from football_news_hub.crawler.arsenal import ArsenalCrawler


async def crawl_arsenal_matches():
    config_path = Path(__file__).parent / "config" / "sources.yaml"
    config = load_config(config_path)

    arsenal_source = config.get_source("arsenal")
    if not arsenal_source:
        print("ERROR: Arsenal source not found")
        return

    crawler = ArsenalCrawler(arsenal_source)

    # Fetch raw match data from the API
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/html, */*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://www.arsenal.com/results",
    }

    data = {
        "view_name": "fixtures_page",
        "view_display_id": "block_3",
        "view_args": "1",
    }

    import httpx
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.post(
            "https://www.arsenal.com/views/ajax",
            headers=headers,
            data=data,
        )

        import re
        content = response.text
        textarea_match = re.search(r'<textarea>(.*?)</textarea>', content, re.DOTALL)
        json_str = textarea_match.group(1)
        json_data = json.loads(json_str)

        html_content = ""
        for item in json_data:
            if item.get("command") == "insert" and item.get("data"):
                html_content = item.get("data", "")
                break

        # Extract matches with full details
        matches = crawler._extract_matches(html_content)

    # Convert to output format
    output_matches = []
    for m in matches:
        # Parse datetime
        date_str = m.get("date", "")
        parsed_dt = crawler._parse_datetime(date_str)

        output_matches.append({
            "url": f"https://www.arsenal.com{m['url']}" if m['url'].startswith("/") else m['url'],
            "date": parsed_dt.isoformat() if parsed_dt else None,
            "date_display": date_str,
            "score": m.get("score"),
            "opponent": m.get("opponent"),
            "competition": m.get("competition"),
            "venue": m.get("venue"),
            "arsenal_logo": m.get("arsenal_logo"),
            "opponent_logo": m.get("opponent_logo"),
            "title": m.get("title"),
        })

    # Sort by date descending
    output_matches.sort(key=lambda x: x["date"] or "", reverse=True)

    # Save to JSON
    output_path = Path(__file__).parent / "data" / "arsenal_matches.json"
    output_path.parent.mkdir(exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_matches, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(output_matches)} matches to {output_path}")

    # Show preview
    print("\n=== First 5 matches ===")
    for m in output_matches[:5]:
        print(f"\n{m['date'][:10]} | {m['competition']}")
        print(f"  {m['score']} | {m['opponent']} @ {m['venue']}")
        print(f"  URL: {m['url']}")
        print(f"  Arsenal Logo: {m['arsenal_logo']}")
        print(f"  Opponent Logo: {m['opponent_logo']}")


if __name__ == "__main__":
    asyncio.run(crawl_arsenal_matches())