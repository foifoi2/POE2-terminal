from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from poe2_alpha.config import Settings
from poe2_alpha.pipeline import Pipeline
from poe2_alpha.sample import seed_demo
from poe2_alpha.storage.sqlite import SQLiteRepository


class ScoringBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "demo.db"
        self.settings = replace(Settings(), db_path=path, use_openai=False, cluster_threshold=0.76)
        self.repo = SQLiteRepository(path)
        self.repo.initialize()
        self.now = seed_demo(self.repo)
        self.pipeline = Pipeline(self.settings, self.repo)
        report = self.pipeline.analyze(self.now)
        self.assertEqual(report.errors, [])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_early_build_topic_survives_lower_trend(self) -> None:
        results, _ = self.pipeline.rank(self.now)
        build = next(x for x in results if "Fluxweave" in x.name)
        meme = next(x for x in results if "Meme" in x.name)
        self.assertGreater(build.alpha_score, meme.alpha_score)
        self.assertLess(build.trend_score, meme.trend_score)
        self.assertGreaterEqual(build.related_posts, 2)
        self.assertTrue(build.core_items)

    def test_alert_deduplication(self) -> None:
        _, first = self.pipeline.rank(self.now, notify=True)
        _, second = self.pipeline.rank(self.now, notify=True)
        self.assertGreaterEqual(first, 1)
        self.assertEqual(second, 0)

    def test_score_breakdown_is_exposed(self) -> None:
        results, _ = self.pipeline.rank(self.now)
        keys = results[0].score_breakdown
        self.assertIn("economic_impact", keys)
        self.assertIn("topic_momentum", keys)
        self.assertIn("analysis_confidence", keys)

    def test_topic_assignment_does_not_exist_before_analysis_cutoff(self) -> None:
        topic_id = self.repo.topic_for_post("alpha_build_1")
        self.assertIsNotNone(topic_id)
        self.assertEqual(self.repo.topic_members(topic_id, self.now - timedelta(seconds=1)), [])


if __name__ == "__main__":
    unittest.main()
