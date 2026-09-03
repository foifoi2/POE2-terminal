from __future__ import annotations

import hashlib
import re

from ..models import Analysis, Post


def content_hash(title: str, body: str) -> str:
    normalized = " ".join(f"{title}\n{body}".split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def embedding_text(post: Post, analysis: Analysis) -> str:
    entities = ", ".join(sorted(analysis.affected_entities))
    items = ", ".join(sorted(item.name for item in analysis.core_items))
    return "\n".join([
        post.title,
        analysis.summary,
        analysis.economic_reason,
        f"categories: {', '.join(analysis.categories)}",
        f"entities: {entities}",
        f"core items: {items}",
    ])


def stable_topic_name(post: Post, analysis: Analysis) -> str:
    if analysis.core_items:
        suffix = " Build Signal" if "Build" in analysis.categories else " Market Signal"
        return analysis.core_items[0].name[:70] + suffix
    if analysis.affected_entities:
        return " / ".join(analysis.affected_entities[:2])[:90]
    cleaned = re.sub(r"\s+", " ", post.title).strip()
    return cleaned[:90] or f"Topic {post.reddit_id}"
