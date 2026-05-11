from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from football_news_hub.config import SourceConfig
from football_news_hub.models import Article, CrawlResult, SourceName


class BaseCrawler(ABC):
    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self.name = config.name
        self.base_url = config.base_url
        self.selectors = config.selectors
        self.max_pages = config.max_pages
        self.request_delay = config.request_delay
        self.incremental_max_pages = getattr(config, 'incremental_max_pages', 5)
        self.stop_on_seen_articles = getattr(config, 'stop_on_seen_articles', True)
        self.fetch_content = getattr(config, 'fetch_content', False)
        self.content_delay = getattr(config, 'content_delay', 1.0)

    @abstractmethod
    async def parse_article_list(self, page: Page) -> list[Article]:
        ...

    @abstractmethod
    async def get_page_url(self, page_num: int) -> str:
        ...

    async def on_page_loaded(self, page: Page) -> None:
        pass

    async def parse_article_content(self, page: Page) -> str | None:
        return None

    async def crawl(self) -> CrawlResult:
        return await self._crawl(max_pages=self.max_pages)

    async def crawl_incremental(self, known_urls: set[str]) -> CrawlResult:
        return await self._crawl(
            max_pages=self.incremental_max_pages,
            known_urls=known_urls,
        )

    async def _crawl(
        self,
        max_pages: int,
        known_urls: set[str] | None = None,
    ) -> CrawlResult:
        logger.info(f"Starting crawl for source: {self.config.display_name}, max_pages={max_pages}")
        articles: list[Article] = []
        error: str | None = None
        stopped_early = False

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await self._create_context(browser)
                try:
                    for page_num in range(1, max_pages + 1):
                        page_url = await self.get_page_url(page_num)
                        logger.info(f"Crawling page {page_num}: {page_url}")

                        page = await context.new_page()
                        try:
                            await page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
                            await self.on_page_loaded(page)
                            page_articles = await self.parse_article_list(page)
                            logger.info(f"Found {len(page_articles)} articles on page {page_num}")

                            if known_urls and self.stop_on_seen_articles:
                                new_articles = [a for a in page_articles if a.url not in known_urls]
                                seen_count = len(page_articles) - len(new_articles)
                                if seen_count > 0 and page_num > 1:
                                    logger.info(f"Stopped early: {seen_count} articles already known")
                                    stopped_early = True
                                    break
                                articles.extend(new_articles)
                            else:
                                articles.extend(page_articles)

                        except Exception as e:
                            logger.error(f"Error crawling page {page_num}: {e}")
                            error = str(e)
                        finally:
                            await page.close()

                        if page_num < max_pages:
                            await asyncio.sleep(self.request_delay)
                finally:
                    await context.close()
                    await browser.close()
        except Exception as e:
            logger.error(f"Browser error: {e}")
            error = str(e)

        result = CrawlResult(
            source=self.name,
            articles=articles,
            crawled_at=datetime.now(),
            error=error,
            stopped_early=stopped_early,
        )
        logger.info(f"Crawl finished: {len(articles)} articles from {self.config.display_name}, stopped_early={stopped_early}")

        if self.fetch_content and articles:
            await self._fetch_article_contents(articles)

        return result

    async def _fetch_article_contents(self, articles: list[Article]) -> None:
        articles_with_url = [a for a in articles if a.url and not a.content]
        if not articles_with_url:
            return

        logger.info(f"Fetching content for {len(articles_with_url)} articles")
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await self._create_context(browser)
                try:
                    for i, article in enumerate(articles_with_url):
                        page = await context.new_page()
                        try:
                            await page.goto(article.url, wait_until="domcontentloaded", timeout=30_000)
                            await page.wait_for_load_state("networkidle", timeout=10_000)
                            content = await self.parse_article_content(page)
                            if content:
                                article.content = content
                                logger.info(f"Fetched content for: {article.title[:40]}...")
                            else:
                                logger.warning(f"No content extracted for: {article.title[:40]}...")
                        except Exception as e:
                            logger.error(f"Error fetching content for {article.url}: {e}")
                        finally:
                            await page.close()

                        if i < len(articles_with_url) - 1:
                            await asyncio.sleep(self.content_delay)
                finally:
                    await context.close()
                    await browser.close()
        except Exception as e:
            logger.error(f"Browser error during content fetch: {e}")

    async def _create_context(self, browser: Browser) -> BrowserContext:
        return await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )


CRAWLER_REGISTRY: dict[SourceName, type[BaseCrawler]] = {}


def register_crawler(name: SourceName):
    def wrapper(cls: type[BaseCrawler]):
        CRAWLER_REGISTRY[name] = cls
        return cls
    return wrapper


def get_crawler_class(name: SourceName) -> type[BaseCrawler]:
    if name not in CRAWLER_REGISTRY:
        raise ValueError(f"Unknown crawler: {name}. Available: {list(CRAWLER_REGISTRY.keys())}")
    return CRAWLER_REGISTRY[name]
