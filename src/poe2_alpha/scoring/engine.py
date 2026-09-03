from __future__ import annotations

import math
import statistics
from datetime import datetime

from ..analysis.content import content_hash
from ..config import Settings
from ..models import Analysis, CoreItem, Post, PostSignals, TopicResult, parse_time
from ..storage.sqlite import SQLiteRepository


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def percentile_ranks(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values.values())
    if len(ordered) == 1:
        return {key: 50.0 for key in values}
    result: dict[str, float] = {}
    for key, value in values.items():
        below = sum(candidate < value for candidate in ordered)
        equal = sum(candidate == value for candidate in ordered)
        result[key] = 100.0 * (below + 0.5 * equal) / len(ordered)
    return result


class ScoringEngine:
    def __init__(self, repo: SQLiteRepository, settings: Settings):
        self.repo = repo
        self.settings = settings

    def post_signals(self, posts: list[Post], as_of: datetime) -> dict[str, PostSignals]:
        raw_upvote: dict[str, float] = {}
        raw_comment: dict[str, float] = {}
        raw_anomaly: dict[str, float] = {}
        age_buckets: dict[str, str] = {}
        raw_acceleration: dict[str, float] = {}
        basics: dict[str, tuple[float, int, int]] = {}
        for post in posts:
            rows = self.repo.snapshots(post.reddit_id, as_of)
            age = max((as_of - post.created_at).total_seconds() / 3600.0, 1 / 60)
            basics[post.reddit_id] = (age, post.score, post.comment_count)
            age_buckets[post.reddit_id] = next(
                label for upper, label in ((1, "0-1h"), (3, "1-3h"), (6, "3-6h"),
                                           (12, "6-12h"), (24, "12-24h"), (48, "24-48h"),
                                           (float("inf"), "48h+")) if age <= upper
            )
            if len(rows) >= 2:
                last, previous = rows[-1], rows[-2]
                hours = max((parse_time(last["captured_at"]) - parse_time(previous["captured_at"])).total_seconds() / 3600, 1 / 60)
                current_up = max(0.0, (last["score"] - previous["score"]) / hours)
                current_comments = max(0.0, (last["comment_count"] - previous["comment_count"]) / hours)
            else:
                current_up = max(0.0, post.score / max(age, 0.25))
                current_comments = max(0.0, post.comment_count / max(age, 0.25))
            earlier_velocity = current_up
            if len(rows) >= 3:
                first, previous = rows[0], rows[-2]
                hours = max((parse_time(previous["captured_at"]) - parse_time(first["captured_at"])).total_seconds() / 3600, 1 / 60)
                earlier_velocity = max(0.0, (previous["score"] - first["score"]) / hours)
            snapshot_age = max((as_of - parse_time(rows[-1]["captured_at"])).total_seconds() / 3600, 0) if rows else age
            freshness = math.exp(-math.log(2) * snapshot_age / 6)
            raw_upvote[post.reddit_id] = math.log1p(current_up) * freshness
            raw_comment[post.reddit_id] = math.log1p(current_comments) * freshness
            raw_acceleration[post.reddit_id] = clamp(50 + 25 * math.log2((current_up + 1) / (earlier_velocity + 1)))
            # Comparable across ages without letting the first few minutes explode.
            raw_anomaly[post.reddit_id] = math.log1p(max(0, post.score) / math.sqrt(max(age, 0.5)))
        upvote_rank = percentile_ranks(raw_upvote)
        comment_rank = percentile_ranks(raw_comment)
        global_anomaly_rank = percentile_ranks(raw_anomaly)
        anomaly_rank: dict[str, float] = {}
        for bucket in set(age_buckets.values()):
            cohort = {key: raw_anomaly[key] for key in raw_anomaly if age_buckets[key] == bucket}
            ranks = percentile_ranks(cohort) if len(cohort) >= 3 else {}
            for key in cohort:
                anomaly_rank[key] = ranks.get(key, global_anomaly_rank[key])
        return {
            post_id: PostSignals(
                post_id=post_id, age_hours=age,
                upvote_velocity=upvote_rank[post_id], comment_velocity=comment_rank[post_id],
                acceleration=raw_acceleration[post_id], engagement_anomaly=anomaly_rank[post_id],
                recency=clamp(100 * math.exp(-math.log(2) * age / 12)),
                latest_score=score, latest_comments=comments,
            )
            for post_id, (age, score, comments) in basics.items()
        }

    def rank(self, as_of: datetime) -> list[TopicResult]:
        posts = self.repo.posts_as_of(as_of)
        post_by_id = {p.reddit_id: p for p in posts}
        signals = self.post_signals(posts, as_of)
        results: list[TopicResult] = []
        for topic in self.repo.topics():
            topic_id = int(topic["id"])
            members = [post_by_id[x] for x in self.repo.topic_members(topic_id, as_of) if x in post_by_id]
            if not members:
                continue
            analyses: list[Analysis] = []
            paired: list[tuple[Post, Analysis]] = []
            for post in members:
                analysis = self.repo.analysis_as_of(post.reddit_id, content_hash(post.title, post.body), as_of)
                if analysis and analysis.is_poe2:
                    analyses.append(analysis)
                    paired.append((post, analysis))
            if not analyses:
                continue
            unique_authors = len({p.author for p in members if p.author})
            latest = min(as_of, max(p.fetched_at for p in members))
            first = parse_time(topic["created_at"])
            recent_posts = sum((as_of - p.created_at).total_seconds() <= 6 * 3600 for p in members)
            prior_posts = sum(6 * 3600 < (as_of - p.created_at).total_seconds() <= 24 * 3600 for p in members)
            mean_up = statistics.fmean(signals[p.reddit_id].upvote_velocity for p in members)
            mean_comment = statistics.fmean(signals[p.reddit_id].comment_velocity for p in members)
            mean_anomaly = statistics.fmean(signals[p.reddit_id].engagement_anomaly for p in members)
            mean_recency = statistics.fmean(signals[p.reddit_id].recency for p in members)
            growth_ratio = (recent_posts + 1) / (prior_posts / 3 + 1)
            topic_momentum = clamp(20 * recent_posts + 8 * unique_authors + 25 * math.log2(growth_ratio + 1) + 0.25 * mean_up)
            trend_parts = {
                "upvote_velocity": mean_up, "comment_velocity": mean_comment,
                "engagement_anomaly": mean_anomaly, "recency": mean_recency,
                "topic_momentum": topic_momentum,
            }
            trend = sum(trend_parts[k] * w for k, w in self.settings.trend_weights.items())
            semantic = {
                key: statistics.fmean(getattr(a, key) for a in analyses)
                for key in ("economic_impact", "actionability", "irreversibility", "novelty",
                            "information_asymmetry", "credibility")
            }
            # Reduce asymmetry as observed reach grows; never turn zero-engagement noise into alpha by itself.
            observed_reach = clamp(statistics.fmean(math.log1p(max(p.score, 0)) * 15 for p in members))
            semantic["information_asymmetry"] = clamp(
                0.65 * semantic["information_asymmetry"] + 0.35 * (100 - observed_reach)
            )
            alpha_parts = {**semantic, "topic_momentum": topic_momentum}
            alpha = sum(alpha_parts[k] * w for k, w in self.settings.alpha_weights.items())
            confidence = statistics.fmean(a.confidence for a in analyses)
            priority = clamp(alpha * (0.65 + 0.35 * confidence / 100) + max(0, trend - 60) * 0.15)
            max_score = max(p.score for p in members)
            if trend >= 70 or max_score >= 500:
                stage = 2
            elif len(members) >= 2 or unique_authors >= 2 or sum(p.comment_count for p in members) >= 8:
                stage = 1
            else:
                stage = 0
            previous = self.repo.previous_stage(topic_id, as_of)
            direction = f"{previous} → {stage}" if previous is not None and previous != stage else str(stage)
            alerts: list[str] = []
            if alpha >= 75:
                alerts.append("Alpha Score >= 75")
            if alpha >= 65 and topic_momentum >= 70:
                alerts.append("Alpha >= 65 and Topic Momentum >= 70")
            if trend >= 75 and statistics.fmean(signals[p.reddit_id].acceleration for p in members) >= 65:
                alerts.append("Trend and engagement acceleration are both high")
            if previous == 0 and stage == 1:
                alerts.append("Propagation stage moved 0 → 1")
            core_items = self._dedupe_items(analyses)
            affected = list(dict.fromkeys(x for a in analyses for x in a.affected_entities))[:20]
            best_post, best_analysis = max(paired, key=lambda pair: pair[1].confidence)
            breakdown = {**trend_parts, **alpha_parts, "analysis_confidence": confidence}
            result = TopicResult(
                topic_id=topic_id, name=topic["name"], trend_score=round(trend, 1),
                alpha_score=round(alpha, 1), alert_priority=round(priority, 1), stage=stage,
                stage_direction=direction, confidence=round(confidence, 1), related_posts=len(members),
                unique_authors=unique_authors, first_detected=first, latest_update=latest,
                summary=best_analysis.summary, why_it_matters=best_analysis.economic_reason,
                affected_entities=affected, core_items=core_items,
                representative_urls=[p.permalink for p in sorted(members, key=lambda p: p.score, reverse=True)[:3]],
                score_breakdown={k: round(v, 1) for k, v in breakdown.items()}, alert_reasons=alerts,
            )
            self.repo.save_topic_metrics(topic_id, as_of, trend, alpha, priority, stage, confidence, breakdown)
            results.append(result)
        return sorted(results, key=lambda x: (x.alpha_score, x.alert_priority, x.trend_score), reverse=True)

    @staticmethod
    def _dedupe_items(analyses: list[Analysis]) -> list[CoreItem]:
        chosen: dict[str, CoreItem] = {}
        for analysis in analyses:
            for item in analysis.core_items:
                key = item.name.casefold()
                if key not in chosen or item.demand_concentration > chosen[key].demand_concentration:
                    chosen[key] = item
        return sorted(chosen.values(), key=lambda x: x.demand_concentration, reverse=True)[:10]
