from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(slots=True)
class Post:
    reddit_id: str
    subreddit: str
    title: str
    body: str
    author: str | None
    created_at: datetime
    url: str
    permalink: str
    score: int
    upvote_ratio: float | None
    comment_count: int
    flair: str | None = None
    crosspost_parent: str | None = None
    source_lists: list[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Comment:
    reddit_id: str
    post_id: str
    parent_id: str | None
    author: str | None
    body: str
    score: int
    created_at: datetime
    fetched_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class CoreItem:
    name: str
    role: str
    required_conditions: list[str] = field(default_factory=list)
    substitute_names: list[str] = field(default_factory=list)
    demand_concentration: int = 0
    evidence: str = ""


@dataclass(slots=True)
class Analysis:
    categories: list[str]
    is_poe2: bool
    economic_impact: int
    actionability: int
    irreversibility: int
    novelty: int
    information_asymmetry: int
    credibility: int
    summary: str
    economic_reason: str
    affected_entities: list[str]
    core_items: list[CoreItem]
    decision_keywords: list[str]
    evidence_for: list[str]
    evidence_against: list[str]
    confidence: int
    needs_deep_analysis: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Analysis":
        data = dict(raw)
        data["core_items"] = [x if isinstance(x, CoreItem) else CoreItem(**x) for x in data.get("core_items", [])]
        return cls(**data)


@dataclass(slots=True)
class PostSignals:
    post_id: str
    age_hours: float
    upvote_velocity: float
    comment_velocity: float
    acceleration: float
    engagement_anomaly: float
    recency: float
    latest_score: int
    latest_comments: int


@dataclass(slots=True)
class TopicResult:
    topic_id: int
    name: str
    trend_score: float
    alpha_score: float
    alert_priority: float
    stage: int
    stage_direction: str
    confidence: float
    related_posts: int
    unique_authors: int
    first_detected: datetime
    latest_update: datetime
    summary: str
    why_it_matters: str
    affected_entities: list[str]
    core_items: list[CoreItem]
    representative_urls: list[str]
    score_breakdown: dict[str, float]
    alert_reasons: list[str]
    market_status: str = "unverified"
