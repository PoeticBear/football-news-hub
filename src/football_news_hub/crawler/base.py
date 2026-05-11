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

    @abstractmethod
    async def parse_article_list(self, page: Page) -> list[Article]:
        ...

    @abstractmethod
    async def get_page_url(self, page_num: int) -> str:
        ...

    async def on_page_loaded(self, page: Page) -> None:
        pass

    async def crawl(self) -> CrawlResult:
        logger.info(f"Starting crawl for source: {self.config.display_name}")
        articles: list[Article] = []
        error: str | None = None

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await self._create_context(browser)
                try:
                    for page_num in range(1, self.max_pages + 1):
                        page_url = await self.get_page_url(page_num)
                        logger.info(f"Crawling page {page_num}: {page_url}")

                        page = await context.new_page()
                        try:
                            await page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
                            await self.on_page_loaded(page)
                            page_articles = await self.parse_article_list(page)
                            logger.info(f"Found {len(page_articles)} articles on page {page_num}")
                            articles.extend(page_articles)
                        except Exception as e:
                            logger.error(f"Error crawling page {page_num}: {e}")
                            error = str(e)
                        finally:
                            await page.close()

                        if page_num < self.max_pages:
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
        )
        logger.info(f"Crawl finished: {len(articles)} articles from {self.config.display_name}")
        return result

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
