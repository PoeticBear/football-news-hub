from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from loguru import logger

from football_news_hub.models import Article, CrawlResult, SourceName


class Storage:
    def __init__(self, db_path: str | Path = "data/articles.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                image_url TEXT,
                category TEXT,
                comment_count INTEGER,
                published_at TEXT,
                content TEXT,
                source TEXT NOT NULL,
                crawled_at TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                extra_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source);
            CREATE INDEX IF NOT EXISTS idx_articles_uid ON articles(uid);
            CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
            CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);

            CREATE TABLE IF NOT EXISTS crawl_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                articles_count INTEGER NOT NULL,
                crawled_at TEXT NOT NULL,
                error TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_crawl_logs_source ON crawl_logs(source);
        """)

        self._ensure_content_column(conn)
        conn.commit()

    def _ensure_content_column(self, conn: sqlite3.Connection) -> None:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(articles)").fetchall()]
        if "content" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN content TEXT")

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def save_crawl_result(self, result: CrawlResult) -> int:
        conn = self._get_conn()
        saved = 0

        for article in result.articles:
            try:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO articles (uid, title, url, image_url, category, comment_count, published_at, content, source, crawled_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article.uid,
                        article.title,
                        article.url,
                        article.image_url,
                        article.category,
                        article.comment_count,
                        article.published_at.isoformat() if article.published_at else None,
                        article.content,
                        article.source.value,
                        article.crawled_at.isoformat(),
                    ),
                )
                if cursor.rowcount > 0:
                    saved += 1
                elif article.content:
                    conn.execute(
                        "UPDATE articles SET content = ? WHERE uid = ? AND (content IS NULL OR content = '')",
                        (article.content, article.uid),
                    )
            except sqlite3.IntegrityError:
                pass

        conn.execute(
            """
            INSERT INTO crawl_logs (source, articles_count, crawled_at, error)
            VALUES (?, ?, ?, ?)
            """,
            (
                result.source.value,
                len(result.articles),
                result.crawled_at.isoformat(),
                result.error,
            ),
        )
        conn.commit()
        logger.info(f"Saved {saved} new articles from {result.source.value}")
        return saved

    def get_articles(
        self,
        source: SourceName | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Article]:
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[str | int] = []

        if source:
            conditions.append("source = ?")
            params.append(source.value)
        if category:
            conditions.append("category = ?")
            params.append(category)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT * FROM articles {where}
            ORDER BY crawled_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [limit, offset]).fetchall()

        return [self._row_to_article(row) for row in rows]

    def search_articles(self, keyword: str, limit: int = 20) -> list[Article]:
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM articles
            WHERE title LIKE ?
            ORDER BY crawled_at DESC
            LIMIT ?
            """,
            (f"%{keyword}%", limit),
        ).fetchall()
        return [self._row_to_article(row) for row in rows]

    def get_categories(self, source: SourceName | None = None) -> list[dict]:
        conn = self._get_conn()
        if source:
            rows = conn.execute(
                "SELECT category, COUNT(*) as count FROM articles WHERE source = ? AND category IS NOT NULL GROUP BY category ORDER BY count DESC",
                (source.value,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT category, COUNT(*) as count FROM articles WHERE category IS NOT NULL GROUP BY category ORDER BY count DESC"
            ).fetchall()
        return [{"category": row["category"], "count": row["count"]} for row in rows]

    def get_known_urls(self, source: SourceName) -> set[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT url FROM articles WHERE source = ?",
            (source.value,),
        ).fetchall()
        return {row["url"] for row in rows if row["url"]}

    def get_stats(self) -> dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*) as count FROM articles GROUP BY source"
        ).fetchall()
        last_crawl = conn.execute(
            "SELECT source, MAX(crawled_at) as last_crawled FROM crawl_logs GROUP BY source"
        ).fetchall()
        return {
            "total_articles": total,
            "by_source": {row["source"]: row["count"] for row in by_source},
            "last_crawl": {row["source"]: row["last_crawled"] for row in last_crawl},
        }

    def _row_to_article(self, row: sqlite3.Row) -> Article:
        return Article(
            title=row["title"],
            url=row["url"],
            image_url=row["image_url"],
            category=row["category"],
            comment_count=row["comment_count"],
            published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
            content=row["content"] if "content" in row.keys() else None,
            source=SourceName(row["source"]),
            crawled_at=datetime.fromisoformat(row["crawled_at"]),
        )

    def export_json(
        self,
        output_path: str | Path,
        source: SourceName | None = None,
        category: str | None = None,
        keyword: str | None = None,
        with_content: bool = True,
    ) -> int:
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[str] = []

        if source:
            conditions.append("source = ?")
            params.append(source.value)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if keyword:
            conditions.append("title LIKE ?")
            params.append(f"%{keyword}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(f"SELECT * FROM articles {where} ORDER BY crawled_at DESC", params).fetchall()

        articles_data = []
        for row in rows:
            article = self._row_to_article(row)
            entry = {
                "title": article.title,
                "url": article.url,
                "image_url": article.image_url,
                "category": article.category,
                "comment_count": article.comment_count,
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "source": article.source.value,
                "crawled_at": article.crawled_at.isoformat(),
            }
            if with_content:
                entry["content"] = article.content
            articles_data.append(entry)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(articles_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Exported {len(articles_data)} articles to {output_path}")
        return len(articles_data)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
