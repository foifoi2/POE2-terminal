from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(default_factory=lambda: Path(os.getenv("POE2_DB_PATH", "data/poe2_alpha.db")))
    subreddit: str = field(default_factory=lambda: os.getenv("POE2_SUBREDDIT", "PathOfExile2"))
    reddit_client_id: str | None = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_ID") or None)
    reddit_client_secret: str | None = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_SECRET") or None)
    reddit_user_agent: str | None = field(default_factory=lambda: os.getenv("REDDIT_USER_AGENT") or None)
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    fast_model: str = field(default_factory=lambda: os.getenv("POE2_FAST_MODEL", "gpt-5.6-luna"))
    deep_model: str = field(default_factory=lambda: os.getenv("POE2_DEEP_MODEL", "gpt-5.6-terra"))
    embedding_model: str = field(default_factory=lambda: os.getenv("POE2_EMBEDDING_MODEL", "text-embedding-3-large"))
    use_openai: bool = field(default_factory=lambda: _bool("POE2_USE_OPENAI", True))
    listing_limit: int = field(default_factory=lambda: int(os.getenv("POE2_LISTING_LIMIT", "100")))
    comment_limit: int = field(default_factory=lambda: int(os.getenv("POE2_COMMENT_LIMIT", "25")))
    cluster_threshold: float = field(default_factory=lambda: float(os.getenv("POE2_CLUSTER_THRESHOLD", "0.82")))
    watch_interval_seconds: int = field(default_factory=lambda: int(os.getenv("POE2_WATCH_INTERVAL_SECONDS", "600")))
    listing_sorts: tuple[str, ...] = ("new", "rising", "hot")
    trend_weights: dict[str, float] = field(default_factory=lambda: {
        "upvote_velocity": 0.40,
        "comment_velocity": 0.25,
        "engagement_anomaly": 0.15,
        "recency": 0.10,
        "topic_momentum": 0.10,
    })
    alpha_weights: dict[str, float] = field(default_factory=lambda: {
        "economic_impact": 0.25,
        "actionability": 0.20,
        "irreversibility": 0.15,
        "novelty": 0.15,
        "information_asymmetry": 0.10,
        "topic_momentum": 0.10,
        "credibility": 0.05,
    })

    @property
    def reddit_configured(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret and self.reddit_user_agent)

    @property
    def openai_configured(self) -> bool:
        return bool(self.use_openai and self.openai_api_key)
