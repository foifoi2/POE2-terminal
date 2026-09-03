from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from ..models import Comment, Post, utc_now


class RedditCollector:
    """Approved OAuth Data API client. It never falls back to HTML scraping."""

    token_url = "https://www.reddit.com/api/v1/access_token"
    api_base = "https://oauth.reddit.com"

    def __init__(self, client_id: str, client_secret: str, user_agent: str, timeout: int = 30):
        if not all((client_id, client_secret, user_agent)):
            raise ValueError("Reddit client_id, client_secret and descriptive user_agent are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        req = urllib.request.Request(
            self.token_url,
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            method="POST",
            headers={"Authorization": f"Basic {basic}", "User-Agent": self.user_agent,
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        raw = self._request(req)
        if "access_token" not in raw:
            raise RuntimeError(f"Reddit OAuth response did not contain access_token: {raw}")
        self._token = raw["access_token"]
        self._token_expires_at = time.time() + int(raw.get("expires_in", 3600))
        return self._token

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        query = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{self.api_base}{path}?{query}",
            headers={"Authorization": f"Bearer {self._access_token()}", "User-Agent": self.user_agent},
        )
        return self._request(req)

    def _request(self, req: urllib.request.Request) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
                if exc.code in (401, 403):
                    self._token = None
                if exc.code == 429 or 500 <= exc.code < 600:
                    retry_after = exc.headers.get("Retry-After")
                    delay = min(60.0, float(retry_after)) if retry_after and retry_after.isdigit() else 2.0 ** attempt
                    last_error = RuntimeError(f"Reddit API returned HTTP {exc.code}: {detail}")
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"Reddit API returned HTTP {exc.code}: {detail}") from exc
            except OSError as exc:
                last_error = exc
                time.sleep(2.0 ** attempt)
        raise RuntimeError(f"Reddit API request failed after retries: {last_error}") from last_error

    def collect_posts(self, subreddit: str, sorts: tuple[str, ...], limit: int) -> list[Post]:
        fetched_at = utc_now()
        merged: dict[str, Post] = {}
        for sort in sorts:
            listing = self._get(f"/r/{subreddit}/{sort}", {"limit": min(limit, 100), "raw_json": 1})
            for child in listing.get("data", {}).get("children", []):
                item = child.get("data", {})
                post_id = item.get("id")
                if not post_id:
                    continue
                if post_id in merged:
                    merged[post_id].source_lists.append(sort)
                    continue
                merged[post_id] = Post(
                    reddit_id=post_id, subreddit=item.get("subreddit", subreddit),
                    title=item.get("title") or "", body=item.get("selftext") or "",
                    author=item.get("author"),
                    created_at=datetime.fromtimestamp(float(item.get("created_utc", 0)), timezone.utc),
                    url=item.get("url") or f"https://www.reddit.com{item.get('permalink', '')}",
                    permalink=f"https://www.reddit.com{item.get('permalink', '')}",
                    score=int(item.get("score") or 0), upvote_ratio=item.get("upvote_ratio"),
                    comment_count=int(item.get("num_comments") or 0),
                )
                # Assign fields not accepted above explicitly to keep API parsing readable.
                merged[post_id].flair = item.get("link_flair_text")
                merged[post_id].crosspost_parent = item.get("crosspost_parent")
                merged[post_id].source_lists = [sort]
                merged[post_id].fetched_at = fetched_at
        return list(merged.values())

    def collect_comments(self, post_id: str, limit: int) -> list[Comment]:
        fetched_at = utc_now()
        listing = self._get(f"/comments/{post_id}", {
            "limit": min(limit, 100), "depth": 2, "sort": "confidence", "raw_json": 1,
        })
        if not isinstance(listing, list) or len(listing) < 2:
            return []
        result: list[Comment] = []

        def walk(children: list[dict[str, Any]]) -> None:
            for child in children:
                if child.get("kind") != "t1":
                    continue
                data = child.get("data", {})
                if not data.get("id") or data.get("body") in ("[deleted]", "[removed]"):
                    continue
                result.append(Comment(
                    reddit_id=data["id"], post_id=post_id, parent_id=data.get("parent_id"),
                    author=data.get("author"), body=data.get("body") or "", score=int(data.get("score") or 0),
                    created_at=datetime.fromtimestamp(float(data.get("created_utc", 0)), timezone.utc),
                    fetched_at=fetched_at,
                ))
                replies = data.get("replies")
                if isinstance(replies, dict):
                    walk(replies.get("data", {}).get("children", []))

        walk(listing[1].get("data", {}).get("children", []))
        return result[:limit]
