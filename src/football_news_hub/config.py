from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from football_news_hub.models import SourceName

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "sources.yaml"


class SelectorConfig(BaseModel):
    article_list: str
    title: str
    url: str
    image: str
    category: str | None = None
    comment_count: str | None = None
    published_at: str | None = None
    next_page: str | None = None


class SourceConfig(BaseModel):
    name: SourceName
    display_name: str
    base_url: str
    enabled: bool = True
    crawler_module: str
    crawler_class: str
    selectors: SelectorConfig
    max_pages: int = 1
    request_delay: float = Field(default=2.0, description="Delay between page requests in seconds")
    incremental_max_pages: int = Field(default=5, description="Max pages for incremental crawl")
    stop_on_seen_articles: bool = Field(default=True, description="Stop crawling when encountering already seen articles")
    fetch_content: bool = Field(default=False, description="Fetch full article content")
    content_delay: float = Field(default=1.0, description="Delay between content fetch requests in seconds")
    extra: dict | None = None


class LLMConfig(BaseModel):
    provider: str = "minimax"
    api_key: str = ""
    base_url: str = "https://api.minimaxi.com/v1"
    model: str = "MiniMax-M2.5"
    output_dir: str = "data/scripts"


class TTSConfig(BaseModel):
    model: str = "speech-2.8-hd"
    voice_id: str = "moss_audio_ce44fc67-7ce3-11f0-8de5-96e35d26fb85"
    speed: float = 1.0
    emotion: str = "calm"
    output_dir: str = "data/audio"


class AppConfig(BaseModel):
    sources: list[SourceConfig]
    storage_path: str = "data/articles.db"
    log_level: str = "INFO"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)

    def get_source(self, name: SourceName) -> SourceConfig | None:
        for source in self.sources:
            if source.name == name and source.enabled:
                return source
        return None

    def get_enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(path) as f:
        raw = yaml.safe_load(f)
    return AppConfig.model_validate(raw)
