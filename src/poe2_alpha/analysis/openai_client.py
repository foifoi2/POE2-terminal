from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..models import Analysis, Comment, Post


ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "categories": {"type": "array", "items": {"type": "string"}},
        "is_poe2": {"type": "boolean"},
        "economic_impact": {"type": "integer", "minimum": 0, "maximum": 100},
        "actionability": {"type": "integer", "minimum": 0, "maximum": 100},
        "irreversibility": {"type": "integer", "minimum": 0, "maximum": 100},
        "novelty": {"type": "integer", "minimum": 0, "maximum": 100},
        "information_asymmetry": {"type": "integer", "minimum": 0, "maximum": 100},
        "credibility": {"type": "integer", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "economic_reason": {"type": "string"},
        "affected_entities": {"type": "array", "items": {"type": "string"}},
        "core_items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "name": {"type": "string"}, "role": {"type": "string"},
                "required_conditions": {"type": "array", "items": {"type": "string"}},
                "substitute_names": {"type": "array", "items": {"type": "string"}},
                "demand_concentration": {"type": "integer", "minimum": 0, "maximum": 100},
                "evidence": {"type": "string"},
            },
            "required": ["name", "role", "required_conditions", "substitute_names", "demand_concentration", "evidence"],
        }},
        "decision_keywords": {"type": "array", "items": {"type": "string"}},
        "evidence_for": {"type": "array", "items": {"type": "string"}},
        "evidence_against": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "needs_deep_analysis": {"type": "boolean"},
    },
    "required": ["categories", "is_poe2", "economic_impact", "actionability", "irreversibility",
                 "novelty", "information_asymmetry", "credibility", "summary", "economic_reason",
                 "affected_entities", "core_items", "decision_keywords", "evidence_for",
                 "evidence_against", "confidence", "needs_deep_analysis"],
}


@dataclass(slots=True)
class Usage:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    request_id: str | None


class OpenAIAnalyzer:
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str, reasoning_effort: str):
        self.api_key = api_key
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.last_usage: Usage | None = None

    def analyze(self, post: Post, comments: list[Comment] | None = None, deep: bool = False) -> Analysis:
        comment_text = "\n".join(f"- score={c.score}: {c.body[:700]}" for c in (comments or [])[:25])
        prompt = f"""Analyze this public r/{post.subreddit} submission as an early POE2 economic signal.
Do not use unstated game knowledge as evidence. Separate claims from reproduced facts. POE1 information must not
be treated as POE2. A core item must be causally required or strongly preferred, not merely worn by the author.
Low popularity can mean early alpha or simply weak evidence. Scores are 0-100. Set needs_deep_analysis when a
larger model should inspect build mechanics, economic propagation, contradictions, or potential core-item demand.

TITLE: {post.title}
BODY: {post.body[:9000]}
CURRENT METADATA: score={post.score}, comments={post.comment_count}, age is evaluated separately by code
COMMENTS AVAILABLE AT THIS SNAPSHOT:
{comment_text or '(none captured)'}
"""
        payload = {
            "model": self.model,
            "instructions": "Return evidence-bound POE2 analysis using the supplied strict schema.",
            "input": prompt,
            "reasoning": {"effort": self.reasoning_effort},
            "text": {"verbosity": "low", "format": {
                "type": "json_schema", "name": "poe2_post_analysis", "strict": True, "schema": ANALYSIS_SCHEMA,
            }},
            "store": False,
            "max_output_tokens": 4000,
        }
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"OpenAI API returned HTTP {exc.code}: {detail}") from exc
        usage = raw.get("usage") or {}
        self.last_usage = Usage(raw.get("model", self.model), usage.get("input_tokens", 0),
                                usage.get("output_tokens", 0), usage.get("total_tokens", 0), raw.get("id"))
        output_text = raw.get("output_text")
        if not output_text:
            for item in raw.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        output_text = content.get("text")
                        break
        if not output_text:
            raise RuntimeError(f"OpenAI response {raw.get('id')} contained no output_text")
        return Analysis.from_dict(json.loads(output_text))
