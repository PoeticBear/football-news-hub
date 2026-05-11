from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from loguru import logger
from openai import OpenAI

_SYSTEM_PROMPT = """你是一位专业的足球新闻主播。你的任务是将提供的足球新闻文章整理成一份适合新闻播报的文字稿。

要求：
1. 以新闻播报的风格撰写，语言流畅自然，适合朗读
2. 开头需要有简短的开场白，例如"各位观众朋友大家好，欢迎收看今天的足球新闻"
3. 每条新闻之间有自然的过渡语
4. 对重要新闻可以适当展开解读，但保持客观中立
5. 结尾需要有简短的结束语
6. 保持原文的核心事实和数据准确
7. 文字稿格式使用 Markdown，包含标题、分段等

输出格式：
# 足球新闻播报稿

**播报日期**：{date}

---

## 开场

[开场白]

## 新闻一：[新闻标题]

[播报内容]

## 新闻二：[新闻标题]

[播报内容]

...

## 结束语

[结束语]
"""


class LLMGenerator:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.minimaxi.com/v1",
        model: str = "MiniMax-M2.5",
    ) -> None:
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.base_url = base_url
        self.model = model
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self.api_key:
                raise ValueError("MINIMAX_API_KEY is not set. Please set it via environment variable or config.")
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    def generate_broadcast_script(
        self,
        articles: list[dict],
        output_path: str | Path | None = None,
    ) -> str:
        if not articles:
            raise ValueError("No articles provided for script generation")

        articles_text = self._format_articles(articles)
        date_str = datetime.now().strftime("%Y年%m月%d日")
        system_prompt = _SYSTEM_PROMPT.format(date=date_str)

        logger.info(f"Generating broadcast script from {len(articles)} articles using {self.model}")

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请根据以下足球新闻文章，生成一份新闻播报文字稿：\n\n{articles_text}"},
            ],
            temperature=1.0,
            max_tokens=8192,
        )

        script = response.choices[0].message.content or ""
        logger.info(f"Generated broadcast script: {len(script)} characters")

        if output_path:
            self._save_script(script, output_path, date_str)

        return script

    def _format_articles(self, articles: list[dict]) -> str:
        parts = []
        for i, article in enumerate(articles, 1):
            parts.append(f"### 文章 {i}")
            parts.append(f"**标题**：{article.get('title', '无标题')}")
            if article.get("category"):
                parts.append(f"**分类**：{article['category']}")
            if article.get("published_at"):
                parts.append(f"**发布时间**：{article['published_at']}")
            if article.get("content"):
                parts.append(f"**正文**：\n{article['content']}")
            else:
                parts.append("**正文**：（无正文内容）")
            parts.append("")
        return "\n".join(parts)

    def _save_script(self, script: str, output_path: str | Path, date_str: str) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(script)
        logger.info(f"Broadcast script saved to {output_path}")
        return output_path
