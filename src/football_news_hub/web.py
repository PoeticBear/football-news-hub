from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from football_news_hub.config import load_config
from football_news_hub.crawler.base import get_crawler_class
from football_news_hub.llm import LLMGenerator
from football_news_hub.models import SourceName
from football_news_hub.storage import Storage
from football_news_hub.tts import TTSGenerator

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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
    storage = _get_storage()
    total_articles = 0
    new_articles = 0
    error = None

    for source_config in sources:
        try:
            known_urls = storage.get_known_urls(source_config.name)
            crawler_cls = get_crawler_class(source_config.name)
            crawler = crawler_cls(source_config)
            result = await crawler.crawl_incremental(known_urls)
            saved = storage.save_crawl_result(result)
            total_articles += len(result.articles)
            new_articles += saved
            if result.error:
                error = result.error
        except Exception as e:
            error = str(e)

    storage.close()
    return JSONResponse({
        "total_articles": total_articles,
        "new_articles": new_articles,
        "error": error,
    })


async def api_generate_script(request: Request) -> JSONResponse:
    config = load_config()
    llm_config = config.llm

    if not llm_config.api_key:
        return JSONResponse({"error": "LLM API key not configured. Please set MINIMAX_API_KEY or configure llm.api_key in sources.yaml"}, status_code=400)

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    source = body.get("source")
    category = body.get("category")
    keyword = body.get("keyword")
    limit = int(body.get("limit", "20"))

    storage = _get_storage()
    if keyword:
        articles = storage.search_articles(keyword, limit=limit)
    else:
        source_enum = SourceName(source) if source else None
        articles = storage.get_articles(source=source_enum, category=category, limit=limit)

    articles_with_content = [a for a in articles if a.content]
    if not articles_with_content:
        storage.close()
        return JSONResponse({"error": "No articles with content found. Please crawl with --with-content first."}, status_code=400)

    articles_data = [
        {
            "title": a.title,
            "url": a.url,
            "category": a.category,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "content": a.content,
        }
        for a in articles_with_content
    ]
    storage.close()

    date_str = datetime.now().strftime("%Y%m%d")
    output_path = Path(llm_config.output_dir) / f"broadcast_{date_str}.md"

    try:
        generator = LLMGenerator(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            model=llm_config.model,
        )
        script = await asyncio.to_thread(
            generator.generate_broadcast_script,
            articles_data,
            str(output_path),
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse({
        "script": script,
        "article_count": len(articles_with_content),
        "output_path": str(output_path),
        "model": llm_config.model,
    })


def _clean_script_for_tts(script: str) -> str:
    text = re.sub(r'^#{1,6}\s+', '', script, flags=re.MULTILINE)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


async def api_generate_audio(request: Request) -> JSONResponse:
    config = load_config()
    llm_config = config.llm
    tts_config = config.tts

    if not llm_config.api_key:
        return JSONResponse({"error": "API key not configured"}, status_code=400)

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    script_text = body.get("script", "")

    if not script_text:
        date_str = datetime.now().strftime("%Y%m%d")
        script_path = Path(llm_config.output_dir) / f"broadcast_{date_str}.md"
        if script_path.exists():
            script_text = script_path.read_text(encoding="utf-8")
        else:
            return JSONResponse({"error": "No script provided and no saved script found. Please generate a script first."}, status_code=400)

    clean_text = _clean_script_for_tts(script_text)
    if not clean_text:
        return JSONResponse({"error": "Script is empty after cleaning"}, status_code=400)

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(tts_config.output_dir) / f"broadcast_{date_str}.mp3"

    try:
        generator = TTSGenerator(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            model=tts_config.model,
            voice_id=tts_config.voice_id,
        )
        saved_path = await asyncio.to_thread(
            generator.generate_audio,
            clean_text,
            str(output_path),
            tts_config.speed,
            tts_config.emotion,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    audio_url = f"/audio/{saved_path.name}"
    return JSONResponse({
        "audio_url": audio_url,
        "output_path": str(saved_path),
        "text_length": len(clean_text),
        "model": tts_config.model,
        "voice_id": tts_config.voice_id,
    })


async def api_generate_single(request: Request) -> JSONResponse:
    config = load_config()
    llm_config = config.llm
    tts_config = config.tts

    if not llm_config.api_key:
        return JSONResponse({"error": "API key not configured"}, status_code=400)

    storage = _get_storage()
    articles_with_content = [a for a in storage.get_articles(limit=50) if a.content]
    storage.close()

    if not articles_with_content:
        return JSONResponse({"error": "No articles with content found. Please crawl with --with-content first."}, status_code=400)

    article = articles_with_content[0]
    articles_data = [
        {
            "title": article.title,
            "url": article.url,
            "category": article.category,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "content": article.content,
        }
    ]

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_path = Path(llm_config.output_dir) / f"single_{date_str}.md"
    audio_path = Path(tts_config.output_dir) / f"single_{date_str}.mp3"

    try:
        llm = LLMGenerator(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            model=llm_config.model,
        )
        script = await asyncio.to_thread(
            llm.generate_broadcast_script,
            articles_data,
            str(script_path),
        )
    except Exception as e:
        return JSONResponse({"error": f"Script generation failed: {e}"}, status_code=500)

    clean_text = _clean_script_for_tts(script)

    try:
        tts = TTSGenerator(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            model=tts_config.model,
            voice_id=tts_config.voice_id,
        )
        saved_path = await asyncio.to_thread(
            tts.generate_audio,
            clean_text,
            str(audio_path),
            tts_config.speed,
            tts_config.emotion,
        )
    except Exception as e:
        return JSONResponse({
            "script": script,
            "script_path": str(script_path),
            "title": article.title,
            "error": f"Audio generation failed: {e}",
        }, status_code=500)

    audio_url = f"/audio/{saved_path.name}"
    return JSONResponse({
        "title": article.title,
        "script": script,
        "script_path": str(script_path),
        "audio_url": audio_url,
        "audio_path": str(saved_path),
        "text_length": len(clean_text),
        "model": llm_config.model,
        "tts_model": tts_config.model,
    })


def create_app() -> Starlette:
    audio_dir = _PROJECT_ROOT / "data" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/articles", api_articles),
            Route("/api/stats", api_stats),
            Route("/api/categories", api_categories),
            Route("/api/crawl", api_crawl, methods=["POST"]),
            Route("/api/generate-script", api_generate_script, methods=["POST"]),
            Route("/api/generate-audio", api_generate_audio, methods=["POST"]),
            Route("/api/generate-single", api_generate_single, methods=["POST"]),
            Mount("/audio", app=StaticFiles(directory=str(audio_dir)), name="audio"),
        ],
    )
