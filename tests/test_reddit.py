from __future__ import annotations

import unittest

from poe2_alpha.collectors.reddit import RedditCollector


class FakeCollector(RedditCollector):
    def _get(self, path, params):
        return {"data": {"children": [{"data": {
            "id": "abc", "subreddit": "PathOfExile2", "title": "A", "selftext": "B",
            "author": "u", "created_utc": 1_700_000_000, "url": "https://example/a",
            "permalink": "/r/PathOfExile2/comments/abc", "score": 12, "upvote_ratio": 0.9,
            "num_comments": 4, "link_flair_text": "Discussion",
        }}]}}


class RedditParsingTests(unittest.TestCase):
    def test_duplicate_listings_merge_source_names_and_keep_one_post(self) -> None:
        collector = FakeCollector("id", "secret", "script:test:1.0 by tester")
        posts = collector.collect_posts("PathOfExile2", ("new", "rising", "hot"), 100)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].source_lists, ["new", "rising", "hot"])
        self.assertEqual(posts[0].comment_count, 4)


if __name__ == "__main__":
    unittest.main()
