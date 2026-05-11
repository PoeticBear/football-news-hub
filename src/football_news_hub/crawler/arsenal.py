from __future__ import annotations

import json
import re
from datetime import datetime

import httpx
from loguru import logger

from football_news_hub.crawler.base import BaseCrawler, register_crawler
from football_news_hub.config import SourceConfig
from football_news_hub.models import Article, SourceName


@register_crawler(SourceName.ARSENAL)
class ArsenalCrawler(BaseCrawler):
    """Crawler for Arsenal official website match results using Drupal Views AJAX API."""

    ARSENAL_LOGO = "https://www.arsenal.com/sites/default/files/styles/feed_crest_thumbnail/public/logos/arsenal-1.png"

    async def get_page_url(self, page_num: int) -> str:
        return "https://www.arsenal.com/views/ajax"

    async def on_page_loaded(self, page) -> None:
        pass

    async def parse_article_list(self, page) -> list[Article]:
        return await self._fetch_via_http()

    async def _fetch_via_http(self) -> list[Article]:
        """Fetch match results via Drupal Views AJAX API."""
        articles: list[Article] = []
        seen_urls: set[str] = set()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/html, */*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.arsenal.com/results",
        }

        data = {
            "view_name": "fixtures_page",
            "view_display_id": "block_3",
            "view_args": "1",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.post(
                    "https://www.arsenal.com/views/ajax",
                    headers=headers,
                    data=data,
                )

                if response.status_code != 200:
                    logger.error(f"Arsenal API returned status {response.status_code}")
                    return []

                content = response.text
                textarea_match = re.search(r'<textarea>(.*?)</textarea>', content, re.DOTALL)

                if not textarea_match:
                    logger.error("No textarea found in Arsenal response")
                    return []

                json_str = textarea_match.group(1)
                json_data = json.loads(json_str)

                html_content = ""
                for item in json_data:
                    if item.get("command") == "insert" and item.get("data"):
                        html_content = item.get("data", "")
                        break

                if not html_content:
                    logger.error("No HTML content found in Arsenal response")
                    return []

                matches = self._extract_matches(html_content)
                logger.info(f"Found {len(matches)} Arsenal matches")

                for match in matches:
                    url = match.get("url", "").strip()
                    if not url or url in seen_urls:
                        continue

                    if url.startswith("/"):
                        url = f"https://www.arsenal.com{url}"

                    seen_urls.add(url)

                    title = match.get("title", "Arsenal Match")
                    score = match.get("score")
                    if score:
                        title = f"{title} {score}"

                    competition = match.get("competition", "")
                    if competition:
                        title = f"{competition}: {title}"

                    published_at = self._parse_datetime(match.get("date"))

                    articles.append(
                        Article(
                            title=title,
                            url=url,
                            image_url=None,
                            category=competition,
                            comment_count=None,
                            published_at=published_at,
                            content=score,  # Using content to store score
                            source=SourceName.ARSENAL,
                        )
                    )

        except Exception as e:
            logger.error(f"Error fetching Arsenal matches: {e}")

        return articles

    def _extract_matches(self, html: str) -> list[dict]:
        """Extract match data from HTML content."""
        matches = []

        # Split by article tags to get individual matches
        article_blocks = re.split(r'<article[^>]*data-article-id=', html)[1:]

        for block in article_blocks:
            # URL
            url_match = re.search(r'href="(/fixture/arsenal/[^"]+)"', block)
            if not url_match:
                continue
            url = url_match.group(1)

            # Date/time
            date_match = re.search(r'<time datetime="([^"]+)"', block)
            date_str = date_match.group(1) if date_match else None

            # Score
            score_matches = re.findall(r'<span class="scores__score[^"]*">(\d+)</span>', block)
            score = f"{score_matches[0]} - {score_matches[1]}" if len(score_matches) >= 2 else None

            # Competition
            comp_match = re.search(r'<div class="event-info__extra">([^<]+)</div>', block)
            competition = comp_match.group(1).strip() if comp_match else ""

            # Venue
            venue_match = re.search(r'<div class="event-info__venue">([^<]+)</div>', block)
            venue = venue_match.group(1).strip() if venue_match else ""

            # Opponent name - extract from the about attribute
            # Format: about="/fixture/arsenal/2026-May-10/west-ham-united"
            about_match = re.search(r'about="([^"]+)"', block)
            opponent = ""
            if about_match:
                about = about_match.group(1)
                parts = about.split('/')
                if len(parts) >= 5:
                    # parts: ["", "fixture", "arsenal", "2026-May-10", "west-ham-united"]
                    opponent = parts[-1].replace("-", " ").title()

            # Arsenal logo (fixed)
            arsenal_logo = self.ARSENAL_LOGO

            # Opponent logo - find the img src for non-Arsenal team
            opponent_logo = None
            logo_matches = re.findall(r'<img[^>]*src="([^"]*logos/[^"]*\.png[^"]*)"[^>]*alt="[^"]*([^-]+)[^"]*"', block)
            for logo_url, alt_text in logo_matches:
                if "Arsenal" not in alt_text:
                    opponent_logo = logo_url
                    break

            # Fallback: try to find logo in team-crest__crest img
            if not opponent_logo:
                crest_match = re.search(r'<img[^>]*class="team-crest__crest"[^>]*src="([^"]+)"', block)
                if crest_match:
                    logo_src = crest_match.group(1)
                    if "arsenal" not in logo_src.lower():
                        opponent_logo = logo_src

            title = f"Arsenal vs {opponent}" if opponent else "Arsenal Match"

            matches.append({
                "url": url,
                "title": title,
                "date": date_str,
                "score": score,
                "competition": competition,
                "venue": venue,
                "arsenal_logo": arsenal_logo,
                "opponent_logo": opponent_logo,
                "opponent": opponent,
            })

        return matches

    def _parse_datetime(self, date_str: str | None) -> datetime | None:
        """Parse datetime from ISO format."""
        if not date_str:
            return None

        try:
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

        return None

    async def _fetch_report_url(self, detail_page_url: str) -> str | None:
        """
        Fetch the REPORT card link from a match detail page.
        The REPORT card contains the match report and is found in the NEWS & VIDEO section.
        Returns the URL of the REPORT page if found, None otherwise.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Referer": "https://www.arsenal.com/results",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(detail_page_url, headers=headers)

                if response.status_code != 200:
                    logger.warning(f"Failed to fetch detail page: {response.status_code}")
                    return None

                content = response.text

                # Find the REPORT card by looking for:
                # 1. Link containing "match-report"
                # 2. Title/alt containing "Report:"
                report_url_match = re.search(
                    r'<a[^>]*href="(/fixture/arsenal/[^"]*match-report[^"]*)"[^>]*class="responsive-card__wrapper"',
                    content
                )

                if report_url_match:
                    report_url = report_url_match.group(1)
                    # Verify this is the actual report page, not just a link
                    if "match-report" in report_url:
                        return f"https://www.arsenal.com{report_url}"

                # Alternative: look for the img with alt containing "Report:"
                report_alt_match = re.search(
                    r'alt="(Report:[^"]+)"[^>]*src="([^"]+)"',
                    content
                )
                if report_alt_match:
                    # The href should be nearby - look for it before this match
                    alt_text = report_alt_match.group(1)
                    # Find the closest href before this alt
                    alt_pos = content.find(alt_text)
                    if alt_pos > 0:
                        # Search backwards for href
                        search_start = max(0, alt_pos - 2000)
                        search_end = alt_pos
                        search_block = content[search_start:search_end]
                        href_match = re.search(r'href="(/fixture/arsenal/[^"]+)"', search_block)
                        if href_match:
                            href = href_match.group(1)
                            if "match-report" in href:
                                return f"https://www.arsenal.com{href}"

                logger.debug(f"No REPORT card found for: {detail_page_url}")
                return None

        except Exception as e:
            logger.error(f"Error fetching REPORT URL from {detail_page_url}: {e}")
            return None

    async def _fetch_match_report(self, report_url: str) -> dict | None:
        """
        Fetch and parse a match report detail page.

        Extracts:
        - title: from JSON-LD headline
        - author: from JSON-LD author.name
        - published_at: from JSON-LD datePublished
        - image_url: from JSON-LD image.url
        - article_body: from HTML paragraphs in article body

        Returns a dict with all extracted data, or None if parsing fails.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Referer": "https://www.arsenal.com/results",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(report_url, headers=headers)

                if response.status_code != 200:
                    logger.warning(f"Failed to fetch report page: {response.status_code}")
                    return None

                content = response.text
                result = {"url": report_url}

                # Extract JSON-LD structured data
                jsonld_match = re.search(
                    r'<script type="application/ld\+json">(.*?)</script>',
                    content,
                    re.DOTALL
                )

                if jsonld_match:
                    try:
                        jsonld_data = json.loads(jsonld_match.group(1))
                        # Handle @graph format
                        if "@graph" in jsonld_data:
                            article_data = jsonld_data["@graph"][0]
                        else:
                            article_data = jsonld_data

                        result["title"] = article_data.get("headline", "")
                        result["author"] = (
                            article_data.get("author", {}).get("name", "")
                            if isinstance(article_data.get("author"), dict)
                            else str(article_data.get("author", ""))
                        )
                        result["published_at"] = self._parse_report_date(
                            article_data.get("datePublished", "")
                        )
                        result["image_url"] = (
                            article_data.get("image", {}).get("url", "")
                            if isinstance(article_data.get("image"), dict)
                            else article_data.get("image", "")
                        )
                        result["description"] = article_data.get("description", "")

                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON-LD: {e}")

                # Extract article body paragraphs
                article_paragraphs = self._extract_article_body(content)
                result["article_body"] = article_paragraphs

                # Extract goal scorers information
                scorers = self._extract_scorers(content)
                result["scorers"] = scorers

                return result

        except Exception as e:
            logger.error(f"Error fetching match report from {report_url}: {e}")
            return None

    def _parse_report_date(self, date_str: str) -> datetime | None:
        """Parse date from JSON-LD format like 'Sun, 10/05/2026 - 18:40'."""
        if not date_str:
            return None

        # Try JSON-LD format: Sun, 10/05/2026 - 18:40
        match = re.search(r'(\d{1,2}/\d{2}/\d{4})\s*-\s*(\d{1,2}:\d{2})', date_str)
        if match:
            date_part = match.group(1)  # DD/MM/YYYY
            time_part = match.group(2)  # HH:MM
            try:
                dt = datetime.strptime(f"{date_part} {time_part}", "%d/%m/%Y %H:%M")
                return dt
            except ValueError:
                pass

        # Try ISO format
        return self._parse_datetime(date_str)

    def _extract_article_body(self, html: str) -> str:
        """Extract article body text from HTML content."""
        # Find all paragraphs in the article body
        # Article content is typically in paragraphs after the header/metadata section
        paragraphs = re.findall(r'<p[^>]*>([^<]+)</p>', html)

        # Filter to substantial content (more than 50 chars, exclude navigation/menu text)
        article_paragraphs = []
        skip_keywords = [
            "menu", "navigation", "Sign up", "Copyright", "All rights reserved",
            "Privacy Policy", "Terms of Use", "Cookie", "Accessibility"
        ]

        for p in paragraphs:
            p = p.strip()
            # Skip short paragraphs and navigation content
            if len(p) < 50:
                continue
            if any(kw.lower() in p.lower() for kw in skip_keywords):
                continue
            # Skip single word paragraphs
            if len(p.split()) < 5:
                continue
            article_paragraphs.append(p)

        return "\n\n".join(article_paragraphs)

    def _extract_scorers(self, html: str) -> list[dict]:
        """
        Extract goal scorer information from the match report page.
        Returns a list of dicts with player name, minute (as string), type (pen/og), and team.
        Format examples:
        - {'player': 'Trossard', 'minute': 82, 'type': None, 'team': 'Arsenal'}
        - {'player': 'J. Alvarez', 'minute': 55, 'type': 'pen', 'team': 'Atletico Madrid'}
        """
        scorers = []

        # Find each team crest block which contains team name and scorers
        # Structure: <figure class="team-crest"> ... <div class="team-crest__name-value">TeamName</div> ... scorers ...
        team_blocks = re.findall(
            r'<figure class="team-crest">(.*?)</figure>',
            html,
            re.DOTALL
        )

        for team_block in team_blocks:
            # Extract team name
            team_name = None
            team_name_match = re.search(r'class="team-crest__name-value">\s*([^<]+)\s*</div>', team_block)
            if team_name_match:
                team_name = team_name_match.group(1).strip()

            # Extract all scorers for this team
            scorer_blocks = re.findall(
                r'class="team-crest__name-scorer">([^<]+)</(?:div|span)>',
                team_block
            )

            for block in scorer_blocks:
                block = block.strip()

                # Extract type (pen, og)
                goal_type = None
                if ' pen' in block.lower():
                    goal_type = 'pen'
                elif ' og' in block.lower():
                    goal_type = 'og'

                # Extract player name and minutes
                clean_block = re.sub(r'\s+(pen|og)\s*(?=\)$)', '', block, flags=re.IGNORECASE)
                match = re.match(r'^(.+?)\s*\((.+)\)$', clean_block)

                if match:
                    player_name = match.group(1).strip()
                    minutes_str = match.group(2).strip()

                    # Parse minutes
                    if ',' in minutes_str or '+' in minutes_str:
                        minute = minutes_str
                    else:
                        try:
                            minute = int(minutes_str)
                        except ValueError:
                            minute = minutes_str

                    scorers.append({
                        'player': player_name,
                        'minute': minute,
                        'type': goal_type,
                        'team': team_name,
                    })

        return scorers