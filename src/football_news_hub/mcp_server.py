from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

from fastmcp import FastMCP
from loguru import logger

from football_news_hub.config import AppConfig, SourceConfig, load_config
from football_news_hub.crawler.base import BaseCrawler, CRAWLER_REGISTRY, get_crawler_class
from football_news_hub.models import SourceName
from football_news_hub.storage import Storage


def _ensure_crawlers_registered() -> None:
    import football_news_hub.crawler.dongqiudi  # noqa: F401


_ensure_crawlers_registered()

mcp = FastMCP(
    name="football-news-hub",
    instructions=(
        "Football News Hub MCP Server. "
        "Provides tools to crawl football news from configurable data sources, "
        "query stored articles, and manage data sources."
    ),
)

_config: AppConfig | None = None
_storage: Storage | None = None


def _get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_storage() -> Storage:
    global _storage
    if _storage is None:
        config = _get_config()
        _storage = Storage(config.storage_path)
    return _storage


def _build_crawler(source_config: SourceConfig) -> BaseCrawler:
    crawler_cls = get_crawler_class(source_config.name)
    return crawler_cls(source_config)


@mcp.tool()
def list_sources() -> list[dict]:
    """List all configured data sources and their status."""
    config = _get_config()
    return [
        {
            "name": s.name.value,
            "display_name": s.display_name,
            "base_url": s.base_url,
            "enabled": s.enabled,
        }
        for s in config.sources
    ]


@mcp.tool()
def crawl_source(source_name: str) -> dict:
    """Crawl articles from a specific data source.

    Args:
        source_name: Name of the data source (e.g. 'dongqiudi')
    """
    config = _get_config()
    source = config.get_source(SourceName(source_name))
    if not source:
        return {"error": f"Source '{source_name}' not found or disabled"}

    crawler = _build_crawler(source)
    result = asyncio.run(crawler.crawl())

    storage = _get_storage()
    saved = storage.save_crawl_result(result)

    return {
        "source": result.source.value,
        "total_articles": len(result.articles),
        "new_articles": saved,
        "error": result.error,
        "articles": [
            {
                "title": a.title,
                "url": a.url,
                "category": a.category,
                "comment_count": a.comment_count,
                "published_at": a.published_at.isoformat() if a.published_at else None,
            }
            for a in result.articles[:20]
        ],
    }


@mcp.tool()
def crawl_all() -> dict:
    """Crawl articles from all enabled data sources."""
    config = _get_config()
    sources = config.get_enabled_sources()
    results = {}

    for source in sources:
        try:
            crawler = _build_crawler(source)
            result = asyncio.run(crawler.crawl())
            storage = _get_storage()
            saved = storage.save_crawl_result(result)
            results[source.name.value] = {
                "total": len(result.articles),
                "new": saved,
                "error": result.error,
            }
        except Exception as e:
            logger.error(f"Error crawling {source.name.value}: {e}")
            results[source.name.value] = {"total": 0, "new": 0, "error": str(e)}

    return results


@mcp.tool()
def query_articles(
    source: str | None = None,
    category: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Query stored articles with optional filters.

    Args:
        source: Filter by source name (e.g. 'dongqiudi')
        category: Filter by category (e.g. '中超', '英超')
        keyword: Search keyword in article titles
        limit: Maximum number of articles to return
    """
    storage = _get_storage()

    if keyword:
        articles = storage.search_articles(keyword, limit=limit)
    else:
        source_enum = SourceName(source) if source else None
        articles = storage.get_articles(source=source_enum, category=category, limit=limit)

    return [
        {
            "title": a.title,
            "url": a.url,
            "image_url": a.image_url,
            "category": a.category,
            "comment_count": a.comment_count,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "source": a.source.value,
        }
        for a in articles
    ]


@mcp.tool()
def get_stats() -> dict:
    """Get crawling statistics."""
    storage = _get_storage()
    stats = storage.get_stats()
    categories = storage.get_categories()
    return {**stats, "categories": categories[:20]}


def run_mcp_server() -> None:
    mcp.run()
