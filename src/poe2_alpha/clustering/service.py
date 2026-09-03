from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from ..analysis.content import stable_topic_name
from ..models import Analysis, Post
from ..storage.sqlite import SQLiteRepository


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return -1.0
    denom = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / denom if denom else 0.0


class HashingEmbedder:
    """Deterministic offline fallback for tests/demo, not production semantic quality."""

    model = "hashing-embedding-v1"

    def __init__(self, dimensions: int = 256):
        self.dimensions = dimensions
        self.last_usage = None

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-z0-9']+", text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            idx = int.from_bytes(digest, "big") % self.dimensions
            sign = 1.0 if digest[0] & 1 else -1.0
            vector[idx] += sign
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]


@dataclass(slots=True)
class EmbeddingUsage:
    model: str
    input_tokens: int
    total_tokens: int
    request_id: str | None


class OpenAIEmbedder:
    endpoint = "https://api.openai.com/v1/embeddings"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.last_usage: EmbeddingUsage | None = None

    def embed(self, text: str) -> list[float]:
        payload = {"model": self.model, "input": text[:24000], "encoding_format": "float"}
        req = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.api_key}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"OpenAI embeddings returned HTTP {exc.code}: {detail}") from exc
        usage = raw.get("usage") or {}
        self.last_usage = EmbeddingUsage(raw.get("model", self.model), usage.get("prompt_tokens", 0),
                                         usage.get("total_tokens", 0), raw.get("id"))
        return [float(x) for x in raw["data"][0]["embedding"]]


class ClusteringService:
    def __init__(self, repo: SQLiteRepository, embedder: HashingEmbedder | OpenAIEmbedder,
                 threshold: float = 0.82):
        self.repo = repo
        self.embedder = embedder
        self.threshold = threshold

    def assign(self, post: Post, analysis: Analysis, text: str, content_hash: str,
               assigned_at: datetime) -> int:
        existing = self.repo.topic_for_post(post.reddit_id)
        if existing is not None:
            return existing
        vector = self.repo.embedding(post.reddit_id, content_hash)
        if vector is None:
            vector = self.embedder.embed(text)
            self.repo.save_embedding(post.reddit_id, content_hash, self.embedder.model, vector)
            usage = getattr(self.embedder, "last_usage", None)
            if usage:
                self.repo.record_usage("embedding", usage.model, usage.input_tokens, 0,
                                       usage.total_tokens, usage.request_id)
        best_topic, best_similarity = None, -1.0
        for topic in self.repo.topics():
            candidate = json.loads(topic["centroid_json"])
            similarity = cosine(vector, candidate)
            if similarity > best_similarity:
                best_topic, best_similarity = int(topic["id"]), similarity
        if best_topic is not None and best_similarity >= self.threshold:
            self.repo.assign_topic(best_topic, post.reddit_id, best_similarity, vector, assigned_at)
            return best_topic
        topic_id = self.repo.create_topic(stable_topic_name(post, analysis), vector, assigned_at)
        self.repo.assign_new_topic(topic_id, post.reddit_id, assigned_at)
        return topic_id
