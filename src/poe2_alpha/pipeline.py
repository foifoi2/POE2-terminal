from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .analysis.content import content_hash, embedding_text
from .analysis.heuristic import HeuristicAnalyzer
from .analysis.openai_client import OpenAIAnalyzer
from .clustering.service import ClusteringService, HashingEmbedder, OpenAIEmbedder
from .collectors.reddit import RedditCollector
from .config import Settings
from .models import Analysis, Post, TopicResult, utc_now
from .notifiers.console import ConsoleNotifier
from .scoring.engine import ScoringEngine
from .storage.sqlite import SQLiteRepository


@dataclass(slots=True)
class RunReport:
    collected_posts: int = 0
    collected_comments: int = 0
    analyzed_posts: int = 0
    deep_analyses: int = 0
    topic_count: int = 0
    alerts_created: int = 0
    errors: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(self, settings: Settings, repo: SQLiteRepository | None = None):
        self.settings = settings
        self.repo = repo or SQLiteRepository(settings.db_path)
        self.repo.initialize()

    def collect(self, with_comments: bool = True) -> RunReport:
        if not self.settings.reddit_configured:
            raise RuntimeError("Reddit OAuth is not configured. Obtain approval, then set REDDIT_CLIENT_ID, "
                               "REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT.")
        collector = RedditCollector(self.settings.reddit_client_id or "", self.settings.reddit_client_secret or "",
                                    self.settings.reddit_user_agent or "")
        report = RunReport()
        posts = collector.collect_posts(self.settings.subreddit, self.settings.listing_sorts,
                                        self.settings.listing_limit)
        for post in posts:
            self.repo.save_post(post)
        report.collected_posts = len(posts)
        if with_comments:
            heuristic = HeuristicAnalyzer()
            # Comments are fetched for semantic candidates OR unusual observed engagement; no keyword-only hard gate.
            candidates = [p for p in posts if heuristic.analyze(p).needs_deep_analysis
                          or p.comment_count >= 8 or p.score >= 40 or "rising" in p.source_lists]
            for post in candidates:
                try:
                    comments = collector.collect_comments(post.reddit_id, self.settings.comment_limit)
                    self.repo.save_comments(comments)
                    report.collected_comments += len(comments)
                except Exception as exc:  # one failed thread must not discard all snapshots
                    report.errors.append(f"comments {post.reddit_id}: {exc}")
        return report

    def analyze(self, as_of: datetime | None = None) -> RunReport:
        as_of = as_of or utc_now()
        report = RunReport()
        heuristic = HeuristicAnalyzer()
        if self.settings.openai_configured:
            fast = OpenAIAnalyzer(self.settings.openai_api_key or "", self.settings.fast_model, "low")
            deep = OpenAIAnalyzer(self.settings.openai_api_key or "", self.settings.deep_model, "medium")
            embedder = OpenAIEmbedder(self.settings.openai_api_key or "", self.settings.embedding_model)
        else:
            fast = deep = heuristic
            embedder = HashingEmbedder()
        clustering = ClusteringService(self.repo, embedder, self.settings.cluster_threshold)
        for post in self.repo.posts_as_of(as_of):
            digest = content_hash(post.title, post.body)
            existing = self.repo.analysis_as_of(post.reddit_id, digest, as_of)
            if existing is not None and self.repo.topic_for_post(post.reddit_id) is not None:
                continue
            comments = self.repo.comments_as_of(post.reddit_id, as_of)
            try:
                analysis = existing or fast.analyze(post, comments, deep=False)
                if existing is None:
                    self.repo.save_analysis(post.reddit_id, digest, "fast", fast.model, analysis, as_of)
                    self._record_analysis_usage(fast, "fast_analysis")
                    report.analyzed_posts += 1
                if analysis.needs_deep_analysis and self.settings.openai_configured:
                    deep_result = deep.analyze(post, comments, deep=True)
                    self.repo.save_analysis(post.reddit_id, digest, "deep", deep.model, deep_result, as_of)
                    self._record_analysis_usage(deep, "deep_analysis")
                    analysis = deep_result
                    report.deep_analyses += 1
                clustering.assign(post, analysis, embedding_text(post, analysis), digest, as_of)
            except Exception as exc:
                report.errors.append(f"analysis {post.reddit_id}: {exc}")
        report.topic_count = len(self.repo.topics())
        return report

    def rank(self, as_of: datetime | None = None, notify: bool = False) -> tuple[list[TopicResult], int]:
        as_of = as_of or utc_now()
        results = ScoringEngine(self.repo, self.settings).rank(as_of)
        created = ConsoleNotifier(self.repo).notify(results) if notify else 0
        return results, created

    def run_once(self) -> RunReport:
        collection = self.collect(with_comments=True)
        analysis = self.analyze()
        results, alerts = self.rank(notify=True)
        return RunReport(
            collected_posts=collection.collected_posts, collected_comments=collection.collected_comments,
            analyzed_posts=analysis.analyzed_posts, deep_analyses=analysis.deep_analyses,
            topic_count=len(results), alerts_created=alerts, errors=collection.errors + analysis.errors,
        )

    def _record_analysis_usage(self, analyzer: object, operation: str) -> None:
        usage = getattr(analyzer, "last_usage", None)
        if usage:
            self.repo.record_usage(operation, usage.model, usage.input_tokens, usage.output_tokens,
                                   usage.total_tokens, usage.request_id)
