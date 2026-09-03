from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import Comment, Post
from .storage.sqlite import SQLiteRepository


def seed_demo(repo: SQLiteRepository, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    definitions = [
        {
            "id": "alpha_build_1", "age": 5.0,
            "title": "Tested: Fluxweave Crown makes Ember Lance boss damage absurd",
            "body": "New POE2 build interaction. Unique Fluxweave Crown is required because it converts ignite stacks. "
                    "I tested 40 boss runs; kill time fell by 61%. Build planner and video included. The item is still cheap.",
            "author": "tester_one", "scores": [3, 9, 24, 52], "comments": [0, 2, 6, 13],
        },
        {
            "id": "alpha_build_2", "age": 2.0,
            "title": "Confirmed Fluxweave Crown Ember Lance interaction works",
            "body": "I reproduced the Fluxweave Crown Ember Lance setup from yesterday. Unique Fluxweave Crown enables "
                    "the damage loop. Tested on three pinnacle bosses. Cheap build guide soon.",
            "author": "tester_two", "scores": [2, 8, 20, 35], "comments": [0, 1, 4, 8],
        },
        {
            "id": "meme_1", "age": 3.0,
            "title": "When the boss deletes you after one hour mapping [Meme]",
            "body": "Just a meme screenshot. No build or mechanic information.",
            "author": "meme_user", "scores": [100, 390, 720, 980], "comments": [10, 30, 60, 85],
        },
        {
            "id": "farm_1", "age": 8.0,
            "title": "PSA tested: avoid the Hollow Temple atlas node",
            "body": "After 100 maps, taking this Atlas Passive removes the valuable breach room. "
                    "Average profit dropped from 7 div/hour to 3 div/hour. Do not take it until confirmed or patched.",
            "author": "atlas_tester", "scores": [1, 5, 18, 48], "comments": [0, 1, 5, 15],
        },
        {
            "id": "known_guide", "age": 30.0,
            "title": "Beginner guide: standard cold build explained",
            "body": "A commonly known beginner setup repeated without measurements.",
            "author": "guide_author", "scores": [80, 140, 160, 165], "comments": [5, 13, 20, 21],
        },
    ]
    for item in definitions:
        created = now - timedelta(hours=item["age"])
        captures = [created + (now - created) * fraction for fraction in (0.08, 0.3, 0.65, 1.0)]
        for captured, score, comments in zip(captures, item["scores"], item["comments"]):
            post = Post(
                reddit_id=item["id"], subreddit="PathOfExile2", title=item["title"], body=item["body"],
                author=item["author"], created_at=created,
                url=f"https://www.reddit.com/r/PathOfExile2/comments/{item['id']}",
                permalink=f"https://www.reddit.com/r/PathOfExile2/comments/{item['id']}",
                score=score, upvote_ratio=0.92, comment_count=comments, source_lists=["new", "rising"],
                fetched_at=captured,
            )
            repo.save_post(post)
    repo.save_comments([
        Comment("demo_c1", "alpha_build_1", "t3_alpha_build_1", "replicator", "Confirmed, works on my character too.", 12,
                now - timedelta(hours=2), now - timedelta(hours=1)),
        Comment("demo_c2", "alpha_build_1", "t3_alpha_build_1", "skeptic", "Could be fixed; needs testing without the helmet.", 8,
                now - timedelta(hours=1.5), now - timedelta(hours=1)),
    ])
    return now
