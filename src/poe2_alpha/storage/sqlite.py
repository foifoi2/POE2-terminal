from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from ..models import Analysis, Comment, Post, iso, parse_time, utc_now


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS posts (
  reddit_id TEXT PRIMARY KEY,
  subreddit TEXT NOT NULL,
  author TEXT,
  created_at TEXT NOT NULL,
  url TEXT NOT NULL,
  permalink TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL REFERENCES posts(reddit_id) ON DELETE CASCADE,
  captured_at TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  flair TEXT,
  crosspost_parent TEXT,
  source_lists_json TEXT NOT NULL,
  UNIQUE(post_id, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_post_versions_asof ON post_versions(post_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS post_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL REFERENCES posts(reddit_id) ON DELETE CASCADE,
  captured_at TEXT NOT NULL,
  score INTEGER NOT NULL,
  upvote_ratio REAL,
  comment_count INTEGER NOT NULL,
  UNIQUE(post_id, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_asof ON post_snapshots(post_id, captured_at);

CREATE TABLE IF NOT EXISTS comments (
  reddit_id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(reddit_id) ON DELETE CASCADE,
  parent_id TEXT,
  author TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comment_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  comment_id TEXT NOT NULL REFERENCES comments(reddit_id) ON DELETE CASCADE,
  captured_at TEXT NOT NULL,
  body TEXT NOT NULL,
  score INTEGER NOT NULL,
  UNIQUE(comment_id, captured_at)
);

CREATE TABLE IF NOT EXISTS llm_analysis (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL REFERENCES posts(reddit_id) ON DELETE CASCADE,
  content_hash TEXT NOT NULL,
  analysis_level TEXT NOT NULL,
  model TEXT NOT NULL,
  analyzed_at TEXT NOT NULL,
  source_as_of TEXT NOT NULL,
  result_json TEXT NOT NULL,
  UNIQUE(post_id, content_hash, analysis_level, model)
);
CREATE INDEX IF NOT EXISTS idx_analysis_asof ON llm_analysis(post_id, source_as_of DESC);

CREATE TABLE IF NOT EXISTS embeddings (
  post_id TEXT PRIMARY KEY REFERENCES posts(reddit_id) ON DELETE CASCADE,
  content_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  vector_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  centroid_json TEXT NOT NULL,
  centroid_dimensions INTEGER NOT NULL,
  member_count INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topic_posts (
  topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  post_id TEXT NOT NULL REFERENCES posts(reddit_id) ON DELETE CASCADE,
  similarity REAL NOT NULL,
  assigned_at TEXT NOT NULL,
  PRIMARY KEY(topic_id, post_id),
  UNIQUE(post_id)
);
CREATE TABLE IF NOT EXISTS topic_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  calculated_at TEXT NOT NULL,
  trend_score REAL NOT NULL,
  alpha_score REAL NOT NULL,
  alert_priority REAL NOT NULL,
  stage INTEGER NOT NULL,
  confidence REAL NOT NULL,
  metrics_json TEXT NOT NULL,
  UNIQUE(topic_id, calculated_at)
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  alert_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operation TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  request_id TEXT,
  created_at TEXT NOT NULL
);
"""


class SQLiteRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def initialize(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        for suffix in ("-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()
        self.initialize()

    def save_post(self, post: Post) -> None:
        from ..analysis.content import content_hash
        stamp = iso(post.fetched_at)
        with self.connect() as con:
            con.execute(
                """INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reddit_id) DO UPDATE SET
                  subreddit=excluded.subreddit, author=excluded.author,
                  url=excluded.url, permalink=excluded.permalink,
                  last_seen_at=excluded.last_seen_at""",
                (post.reddit_id, post.subreddit, post.author, iso(post.created_at), post.url,
                 post.permalink, stamp, stamp),
            )
            con.execute(
                """INSERT OR IGNORE INTO post_versions
                (post_id,captured_at,title,body,content_hash,flair,crosspost_parent,source_lists_json)
                VALUES (?,?,?,?,?,?,?,?)""",
                (post.reddit_id, stamp, post.title, post.body, content_hash(post.title, post.body),
                 post.flair, post.crosspost_parent, json.dumps(sorted(set(post.source_lists)))),
            )
            con.execute(
                """INSERT OR REPLACE INTO post_snapshots
                (post_id,captured_at,score,upvote_ratio,comment_count) VALUES (?,?,?,?,?)""",
                (post.reddit_id, stamp, post.score, post.upvote_ratio, post.comment_count),
            )

    def save_comments(self, comments: list[Comment]) -> None:
        with self.connect() as con:
            for item in comments:
                con.execute(
                    """INSERT INTO comments VALUES (?,?,?,?,?) ON CONFLICT(reddit_id) DO UPDATE SET
                    author=excluded.author, parent_id=excluded.parent_id""",
                    (item.reddit_id, item.post_id, item.parent_id, item.author, iso(item.created_at)),
                )
                con.execute(
                    """INSERT OR REPLACE INTO comment_versions
                    (comment_id,captured_at,body,score) VALUES (?,?,?,?)""",
                    (item.reddit_id, iso(item.fetched_at), item.body, item.score),
                )

    def posts_as_of(self, as_of: datetime) -> list[Post]:
        cutoff = iso(as_of)
        sql = """
        SELECT p.*, v.title, v.body, v.flair, v.crosspost_parent, v.source_lists_json,
               v.captured_at AS version_at, s.score, s.upvote_ratio, s.comment_count,
               s.captured_at AS snapshot_at
        FROM posts p
        JOIN post_versions v ON v.id = (
          SELECT id FROM post_versions WHERE post_id=p.reddit_id AND captured_at<=?
          ORDER BY captured_at DESC LIMIT 1)
        JOIN post_snapshots s ON s.id = (
          SELECT id FROM post_snapshots WHERE post_id=p.reddit_id AND captured_at<=?
          ORDER BY captured_at DESC LIMIT 1)
        WHERE p.created_at<=?
        ORDER BY p.created_at DESC
        """
        with self.connect() as con:
            rows = con.execute(sql, (cutoff, cutoff, cutoff)).fetchall()
        return [Post(
            reddit_id=r["reddit_id"], subreddit=r["subreddit"], title=r["title"], body=r["body"],
            author=r["author"], created_at=parse_time(r["created_at"]), url=r["url"],
            permalink=r["permalink"], score=r["score"], upvote_ratio=r["upvote_ratio"],
            comment_count=r["comment_count"], flair=r["flair"], crosspost_parent=r["crosspost_parent"],
            source_lists=json.loads(r["source_lists_json"]), fetched_at=parse_time(r["snapshot_at"]),
        ) for r in rows]

    def snapshots(self, post_id: str, as_of: datetime) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM post_snapshots WHERE post_id=? AND captured_at<=? ORDER BY captured_at",
                (post_id, iso(as_of)),
            ).fetchall()

    def comments_as_of(self, post_id: str, as_of: datetime) -> list[Comment]:
        cutoff = iso(as_of)
        sql = """SELECT c.*, v.body, v.score, v.captured_at FROM comments c
        JOIN comment_versions v ON v.id=(SELECT id FROM comment_versions
          WHERE comment_id=c.reddit_id AND captured_at<=? ORDER BY captured_at DESC LIMIT 1)
        WHERE c.post_id=? AND c.created_at<=? ORDER BY v.score DESC"""
        with self.connect() as con:
            rows = con.execute(sql, (cutoff, post_id, cutoff)).fetchall()
        return [Comment(r["reddit_id"], r["post_id"], r["parent_id"], r["author"], r["body"],
                        r["score"], parse_time(r["created_at"]), parse_time(r["captured_at"])) for r in rows]

    def save_analysis(self, post_id: str, content_hash: str, level: str, model: str,
                      analysis: Analysis, source_as_of: datetime) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT OR IGNORE INTO llm_analysis
                (post_id,content_hash,analysis_level,model,analyzed_at,source_as_of,result_json)
                VALUES (?,?,?,?,?,?,?)""",
                (post_id, content_hash, level, model, iso(utc_now()), iso(source_as_of),
                 json.dumps(analysis.to_dict(), ensure_ascii=False)),
            )

    def analysis_as_of(self, post_id: str, content_hash: str, as_of: datetime) -> Analysis | None:
        with self.connect() as con:
            row = con.execute(
                """SELECT result_json FROM llm_analysis WHERE post_id=? AND content_hash=?
                AND source_as_of<=? ORDER BY CASE analysis_level WHEN 'deep' THEN 0 ELSE 1 END,
                source_as_of DESC LIMIT 1""",
                (post_id, content_hash, iso(as_of)),
            ).fetchone()
        return Analysis.from_dict(json.loads(row[0])) if row else None

    def save_embedding(self, post_id: str, content_hash: str, model: str, vector: list[float]) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?,?,?)""",
                (post_id, content_hash, model, len(vector), json.dumps(vector), iso(utc_now())),
            )

    def embedding(self, post_id: str, content_hash: str) -> list[float] | None:
        with self.connect() as con:
            row = con.execute("SELECT vector_json FROM embeddings WHERE post_id=? AND content_hash=?",
                              (post_id, content_hash)).fetchone()
        return json.loads(row[0]) if row else None

    def topics(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute("SELECT * FROM topics ORDER BY id").fetchall()

    def create_topic(self, name: str, centroid: list[float], at: datetime) -> int:
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO topics(name,centroid_json,centroid_dimensions,member_count,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (name, json.dumps(centroid), len(centroid), 1, iso(at), iso(at)),
            )
            return int(cur.lastrowid)

    def assign_topic(self, topic_id: int, post_id: str, similarity: float, vector: list[float], at: datetime) -> None:
        with self.connect() as con:
            old = con.execute("SELECT topic_id FROM topic_posts WHERE post_id=?", (post_id,)).fetchone()
            if old:
                return
            topic = con.execute("SELECT centroid_json,member_count FROM topics WHERE id=?", (topic_id,)).fetchone()
            count = int(topic["member_count"])
            centroid = json.loads(topic["centroid_json"])
            updated = [(centroid[i] * count + vector[i]) / (count + 1) for i in range(len(vector))]
            con.execute("INSERT INTO topic_posts VALUES(?,?,?,?)", (topic_id, post_id, similarity, iso(at)))
            con.execute("UPDATE topics SET centroid_json=?,member_count=?,updated_at=? WHERE id=?",
                        (json.dumps(updated), count + 1, iso(at), topic_id))

    def assign_new_topic(self, topic_id: int, post_id: str, at: datetime) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO topic_posts VALUES(?,?,?,?)", (topic_id, post_id, 1.0, iso(at)))

    def topic_members(self, topic_id: int, as_of: datetime) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT post_id FROM topic_posts WHERE topic_id=? AND assigned_at<=? ORDER BY assigned_at",
                (topic_id, iso(as_of)),
            ).fetchall()
        return [r[0] for r in rows]

    def topic_for_post(self, post_id: str) -> int | None:
        with self.connect() as con:
            row = con.execute("SELECT topic_id FROM topic_posts WHERE post_id=?", (post_id,)).fetchone()
        return int(row[0]) if row else None

    def save_topic_metrics(self, topic_id: int, at: datetime, trend: float, alpha: float,
                           priority: float, stage: int, confidence: float, metrics: dict[str, Any]) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT OR REPLACE INTO topic_metrics
                (topic_id,calculated_at,trend_score,alpha_score,alert_priority,stage,confidence,metrics_json)
                VALUES(?,?,?,?,?,?,?,?)""",
                (topic_id, iso(at), trend, alpha, priority, stage, confidence,
                 json.dumps(metrics, ensure_ascii=False)),
            )

    def save_alert(self, topic_id: int, key: str, reasons: list[str], payload: dict[str, Any]) -> bool:
        with self.connect() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO alerts(topic_id,alert_key,created_at,reasons_json,payload_json) VALUES(?,?,?,?,?)",
                (topic_id, key, iso(utc_now()), json.dumps(reasons), json.dumps(payload, ensure_ascii=False)),
            )
            return cur.rowcount > 0

    def previous_stage(self, topic_id: int, before: datetime) -> int | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT stage FROM topic_metrics WHERE topic_id=? AND calculated_at<? ORDER BY calculated_at DESC LIMIT 1",
                (topic_id, iso(before)),
            ).fetchone()
        return int(row[0]) if row else None

    def record_usage(self, operation: str, model: str, input_tokens: int, output_tokens: int,
                     total_tokens: int, request_id: str | None) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO model_usage VALUES(NULL,?,?,?,?,?,?,?)",
                        (operation, model, input_tokens, output_tokens, total_tokens, request_id, iso(utc_now())))

    def usage_summary(self) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(
                """SELECT model,operation,COUNT(*) calls,SUM(input_tokens) input_tokens,
                SUM(output_tokens) output_tokens,SUM(total_tokens) total_tokens
                FROM model_usage GROUP BY model,operation ORDER BY total_tokens DESC"""
            ).fetchall()
