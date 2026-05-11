from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SourceName(str, Enum):
    DONGQIUDI = "dongqiudi"
    ARSENAL = "arsenal"


class Article(BaseModel):
    title: str
    url: str
    image_url: str | None = None
    category: str | None = None
    comment_count: int | None = None
    published_at: datetime | None = None
    content: str | None = None
    source: SourceName
    crawled_at: datetime = Field(default_factory=datetime.now)

    @property
    def uid(self) -> str:
        return f"{self.source.value}:{self.url}"


class CrawlResult(BaseModel):
    source: SourceName
    articles: list[Article]
    crawled_at: datetime = Field(default_factory=datetime.now)
    error: str | None = None
    stopped_early: bool = False
