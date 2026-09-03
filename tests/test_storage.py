from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from poe2_alpha.models import Post
from poe2_alpha.storage.sqlite import SQLiteRepository


class StorageAsOfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = SQLiteRepository(Path(self.temp.name) / "test.db")
        self.repo.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_post_body_and_score_are_cut_off_at_as_of(self) -> None:
        origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first = Post("p1", "PathOfExile2", "Original", "initial body", "a", origin,
                     "https://example/p1", "https://example/p1", 3, 0.9, 1,
                     fetched_at=origin + timedelta(hours=1))
        edited = Post("p1", "PathOfExile2", "Edited later", "future body", "a", origin,
                      "https://example/p1", "https://example/p1", 300, 0.9, 40,
                      fetched_at=origin + timedelta(hours=3))
        self.repo.save_post(first)
        self.repo.save_post(edited)

        posts = self.repo.posts_as_of(origin + timedelta(hours=2))
        self.assertEqual(posts[0].title, "Original")
        self.assertEqual(posts[0].score, 3)

    def test_analysis_after_cutoff_is_not_visible(self) -> None:
        from poe2_alpha.analysis.content import content_hash
        from poe2_alpha.analysis.heuristic import HeuristicAnalyzer

        origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
        post = Post("p2", "PathOfExile2", "Tested build", "40 runs", "a", origin,
                    "https://example/p2", "https://example/p2", 10, 0.9, 2,
                    fetched_at=origin + timedelta(hours=1))
        self.repo.save_post(post)
        analysis = HeuristicAnalyzer().analyze(post)
        digest = content_hash(post.title, post.body)
        self.repo.save_analysis("p2", digest, "fast", "heuristic-v1", analysis,
                                origin + timedelta(hours=3))
        self.assertIsNone(self.repo.analysis_as_of("p2", digest, origin + timedelta(hours=2)))
        self.assertIsNotNone(self.repo.analysis_as_of("p2", digest, origin + timedelta(hours=4)))


if __name__ == "__main__":
    unittest.main()
