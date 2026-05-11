from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from football_news_hub.config import load_config
from football_news_hub.crawler.base import get_crawler_class
from football_news_hub.models import SourceName
from football_news_hub.storage import Storage

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _load_template() -> str:
    template_path = _TEMPLATE_DIR / "dashboard.html"
    return template_path.read_text(encoding="utf-8")


def _get_storage() -> Storage:
    config = load_config()
    return Storage(config.storage_path)


async def index(request: Request) -> HTMLResponse:
    html = _load_template()
    return HTMLResponse(html)


async def api_articles(request: Request) -> JSONResponse:
    source = request.query_params.get("source")
    category = request.query_params.get("category")
    keyword = request.query_params.get("keyword")
    limit = int(request.query_params.get("limit", "50"))

    storage = _get_storage()
    if keyword:
        articles = storage.search_articles(keyword, limit=limit)
    else:
        source_enum = SourceName(source) if source else None
        articles = storage.get_articles(source=source_enum, category=category, limit=limit)

    data = [
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
    storage.close()
    return JSONResponse(data)


async def api_stats(request: Request) -> JSONResponse:
    storage = _get_storage()
    stats = storage.get_stats()
    categories = storage.get_categories()
    storage.close()
    return JSONResponse({**stats, "categories": categories})


async def api_categories(request: Request) -> JSONResponse:
    storage = _get_storage()
    categories = storage.get_categories()
    storage.close()
    return JSONResponse(categories)


async def api_crawl(request: Request) -> JSONResponse:
    config = load_config()
    sources = config.get_enabled_sources()
    total_articles = 0
    new_articles = 0
    error = None

    for source_config in sources:
        try:
            crawler_cls = get_crawler_class(source_config.name)
            crawler = crawler_cls(source_config)
            result = await crawler.crawl()
            storage = _get_storage()
            saved = storage.save_crawl_result(result)
            storage.close()
            total_articles += len(result.articles)
            new_articles += saved
            if result.error:
                error = result.error
        except Exception as e:
            error = str(e)

    return JSONResponse({
        "total_articles": total_articles,
        "new_articles": new_articles,
        "error": error,
    })


def create_app() -> Starlette:
    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/articles", api_articles),
            Route("/api/stats", api_stats),
            Route("/api/categories", api_categories),
            Route("/api/crawl", api_crawl, methods=["POST"]),
        ],
    )
