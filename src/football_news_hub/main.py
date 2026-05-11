from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from football_news_hub.config import load_config
from football_news_hub.crawler.base import get_crawler_class
from football_news_hub.models import SourceName
from football_news_hub.storage import Storage

console = Console()
app = typer.Typer(name="football-news", help="Football News Hub - Configurable football news crawler")


def _ensure_crawlers_registered() -> None:
    import football_news_hub.crawler.dongqiudi  # noqa: F401


_ensure_crawlers_registered()


@app.command()
def crawl(
    source: Optional[str] = typer.Argument(None, help="Data source name (e.g. dongqiudi). Omit to crawl all enabled sources."),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Crawl articles from data sources."""
    config = load_config(config_path)
    storage = Storage(config.storage_path)

    if source:
        source_enum = SourceName(source)
        source_config = config.get_source(source_enum)
        if not source_config:
            console.print(f"[red]Source '{source}' not found or disabled[/red]")
            raise typer.Exit(1)
        sources = [source_config]
    else:
        sources = config.get_enabled_sources()
        if not sources:
            console.print("[yellow]No enabled sources found[/yellow]")
            raise typer.Exit(0)

    for source_config in sources:
        console.print(f"\n[bold blue]Crawling: {source_config.display_name}[/bold blue]")
        crawler_cls = get_crawler_class(source_config.name)
        crawler = crawler_cls(source_config)

        result = asyncio.run(crawler.crawl())
        saved = storage.save_crawl_result(result)

        console.print(f"  Found: {len(result.articles)} articles, New: {saved}")
        if result.error:
            console.print(f"  [red]Error: {result.error}[/red]")

        if result.articles:
            table = Table(show_header=True, header_style="bold")
            table.add_column("Title", max_width=60)
            table.add_column("Category", max_width=10)
            table.add_column("Comments", max_width=8)
            table.add_column("Published", max_width=16)
            for article in result.articles[:15]:
                table.add_row(
                    article.title[:60],
                    article.category or "-",
                    str(article.comment_count) if article.comment_count else "-",
                    article.published_at.strftime("%m-%d %H:%M") if article.published_at else "-",
                )
            console.print(table)

    storage.close()


@app.command()
def sources(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """List configured data sources."""
    config = load_config(config_path)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Display Name")
    table.add_column("URL")
    table.add_column("Enabled")

    for s in config.sources:
        table.add_row(
            s.name.value,
            s.display_name,
            s.base_url,
            "[green]Yes[/green]" if s.enabled else "[red]No[/red]",
        )
    console.print(table)


@app.command()
def query(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter by source"),
    category: Optional[str] = typer.Option(None, "--category", "-cat", help="Filter by category"),
    keyword: Optional[str] = typer.Option(None, "--keyword", "-k", help="Search keyword"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Query stored articles."""
    config = load_config(config_path)
    storage = Storage(config.storage_path)

    if keyword:
        articles = storage.search_articles(keyword, limit=limit)
    else:
        source_enum = SourceName(source) if source else None
        articles = storage.get_articles(source=source_enum, category=category, limit=limit)

    if not articles:
        console.print("[yellow]No articles found[/yellow]")
        storage.close()
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Title", max_width=50)
    table.add_column("Source", max_width=10)
    table.add_column("Category", max_width=8)
    table.add_column("Comments", max_width=8)
    table.add_column("Published", max_width=16)

    for a in articles:
        table.add_row(
            a.title[:50],
            a.source.value,
            a.category or "-",
            str(a.comment_count) if a.comment_count else "-",
            a.published_at.strftime("%m-%d %H:%M") if a.published_at else "-",
        )
    console.print(table)
    console.print(f"\nTotal: {len(articles)} articles")
    storage.close()


@app.command()
def stats(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Show crawling statistics."""
    config = load_config(config_path)
    storage = Storage(config.storage_path)

    s = storage.get_stats()
    categories = storage.get_categories()

    console.print(f"\n[bold]Total Articles:[/bold] {s['total_articles']}")

    if s["by_source"]:
        console.print("\n[bold]By Source:[/bold]")
        for src, count in s["by_source"].items():
            console.print(f"  {src}: {count}")

    if categories:
        console.print("\n[bold]Top Categories:[/bold]")
        for cat in categories[:10]:
            console.print(f"  {cat['category']}: {cat['count']}")

    if s["last_crawl"]:
        console.print("\n[bold]Last Crawl:[/bold]")
        for src, ts in s["last_crawl"].items():
            console.print(f"  {src}: {ts}")

    storage.close()


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind"),
    port: int = typer.Option(8765, "--port", "-p", help="Port to bind"),
) -> None:
    """Start the web dashboard."""
    import uvicorn

    from football_news_hub.web import create_app

    web_app = create_app()
    console.print(f"[bold green]Starting Football News Hub Dashboard...[/bold green]")
    console.print(f"  Open [bold blue]http://{host}:{port}[/bold blue] in your browser")
    uvicorn.run(web_app, host=host, port=port, log_level="info")


@app.command()
def serve(
    config_path: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to config file"),
) -> None:
    """Start the MCP server."""
    from football_news_hub.mcp_server import run_mcp_server

    console.print("[bold green]Starting Football News Hub MCP Server...[/bold green]")
    run_mcp_server()


if __name__ == "__main__":
    app()
