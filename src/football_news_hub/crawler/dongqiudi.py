from __future__ import annotations

import re
from datetime import datetime

from loguru import logger
from playwright.async_api import Page

from football_news_hub.crawler.base import BaseCrawler, register_crawler
from football_news_hub.config import SourceConfig
from football_news_hub.models import Article, SourceName


_EXTRACT_JS = """
() => {
    const articles = [];

    const headline = document.querySelector('.headline');
    if (headline) {
        const titleEl = headline.querySelector('.headline__title');
        const imgEl = headline.querySelector('.headline__img');
        const categoryEl = headline.querySelector('.headline__category');
        const tagEls = headline.querySelectorAll('.headline__tag');
        const metaEl = headline.querySelector('.headline__meta');

        if (titleEl) {
            const tags = Array.from(tagEls).map(t => t.textContent.trim()).join(' ');
            articles.push({
                title: titleEl.textContent.trim(),
                url: '',
                image_url: imgEl ? imgEl.src : null,
                badge: categoryEl ? categoryEl.textContent.trim() : null,
                category: tags || (categoryEl ? categoryEl.textContent.trim() : null),
                meta: metaEl ? metaEl.textContent.trim() : null,
                is_headline: true,
            });
        }
    }

    const cards = document.querySelectorAll('.news-card');
    cards.forEach(card => {
        const articleId = card.getAttribute('id');
        const titleEl = card.querySelector('.news-card__title');
        const imgEl = card.querySelector('.news-card__image img');
        const badgeEl = card.querySelector('.news-card__badge');
        const tagEls = card.querySelectorAll('.news-card__tag');
        const commentsEl = card.querySelector('.news-card__comments');
        const infoEl = card.querySelector('.news-card__info');
        const imageLarge = card.getAttribute('imagelarge');

        if (!titleEl) return;

        const tags = Array.from(tagEls).map(t => t.textContent.trim()).join(' ');
        let timeText = '';
        if (infoEl) {
            const spans = infoEl.querySelectorAll('span');
            spans.forEach(span => {
                const text = span.textContent.trim();
                if (text && !text.includes('评')) {
                    timeText = text;
                }
            });
        }

        articles.push({
            title: titleEl.textContent.trim(),
            url: articleId ? `https://www.dongqiudi.com/news/${articleId}.html` : '',
            image_url: imgEl ? imgEl.src : (imageLarge || null),
            badge: badgeEl ? badgeEl.textContent.trim() : null,
            category: tags || (badgeEl ? badgeEl.textContent.trim() : null),
            comment_text: commentsEl ? commentsEl.textContent.trim() : null,
            time_text: timeText || null,
            is_headline: false,
        });
    });

    return articles;
}
"""


def _parse_comment_count(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    patterns = [
        (r"(\d{2}-\d{2}\s+\d{2}:\d{2})", "%m-%d %H:%M"),
        (r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", "%Y-%m-%d %H:%M"),
        (r"(\d{2}:\d{2})", "%H:%M"),
    ]
    for pattern, fmt in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                dt = datetime.strptime(match.group(1), fmt)
                if dt.year == 1900:
                    dt = dt.replace(year=datetime.now().year)
                return dt
            except ValueError:
                pass
    return None


@register_crawler(SourceName.DONGQIUDI)
class DongqiudiCrawler(BaseCrawler):
    def __init__(self, config: SourceConfig) -> None:
        super().__init__(config)

    async def get_page_url(self, page_num: int) -> str:
        if page_num == 1:
            return self.base_url
        return f"{self.base_url}?page={page_num}"

    async def on_page_loaded(self, page: Page) -> None:
        await page.wait_for_load_state("networkidle", timeout=15_000)
        await page.wait_for_timeout(2000)

    async def parse_article_list(self, page: Page) -> list[Article]:
        raw_articles = await page.evaluate(_EXTRACT_JS)

        if not raw_articles:
            logger.warning("No articles extracted from page")
            return []

        articles: list[Article] = []
        seen_titles: set[str] = set()

        for raw in raw_articles:
            title = raw.get("title", "").strip()
            url = raw.get("url", "").strip()

            if not title or title in seen_titles:
                continue

            seen_titles.add(title)

            comment_count = _parse_comment_count(raw.get("comment_text"))
            published_at = _parse_time(raw.get("time_text"))

            if not published_at and raw.get("meta"):
                meta = raw["meta"]
                comment_match = re.search(r"(\d+)\s*评", meta)
                if comment_match and not comment_count:
                    comment_count = int(comment_match.group(1))
                time_match = re.search(r"(\d{2}-\d{2}\s+\d{2}:\d{2})", meta)
                if time_match and not published_at:
                    try:
                        published_at = datetime.strptime(time_match.group(1), "%m-%d %H:%M")
                        published_at = published_at.replace(year=datetime.now().year)
                    except ValueError:
                        pass

            articles.append(
                Article(
                    title=title,
                    url=url,
                    image_url=raw.get("image_url"),
                    category=raw.get("category"),
                    comment_count=comment_count,
                    published_at=published_at,
                    source=SourceName.DONGQIUDI,
                )
            )

        return articles
