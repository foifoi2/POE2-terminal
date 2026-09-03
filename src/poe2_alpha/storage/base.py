from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import Analysis, Comment, Post


class Repository(Protocol):
    """Storage boundary; a PostgreSQL implementation can replace SQLite."""

    def initialize(self) -> None: ...
    def save_post(self, post: Post) -> None: ...
    def save_comments(self, comments: list[Comment]) -> None: ...
    def posts_as_of(self, as_of: datetime) -> list[Post]: ...
    def save_analysis(self, post_id: str, content_hash: str, level: str, model: str,
                      analysis: Analysis, source_as_of: datetime) -> None: ...
