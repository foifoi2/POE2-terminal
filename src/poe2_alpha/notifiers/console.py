from __future__ import annotations

from ..models import TopicResult
from ..storage.sqlite import SQLiteRepository


class ConsoleNotifier:
    def __init__(self, repo: SQLiteRepository):
        self.repo = repo

    def notify(self, results: list[TopicResult]) -> int:
        created = 0
        for result in results:
            if not result.alert_reasons:
                continue
            key = f"topic:{result.topic_id}:stage:{result.stage}:alpha:{int(result.alpha_score // 5) * 5}"
            if self.repo.save_alert(result.topic_id, key, result.alert_reasons, {
                "name": result.name, "trend": result.trend_score, "alpha": result.alpha_score,
                "confidence": result.confidence, "market_status": result.market_status,
            }):
                created += 1
                print(f"ALERT | {result.name} | Alpha {result.alpha_score:.0f} | "
                      f"Trend {result.trend_score:.0f} | Confidence {result.confidence:.0f}")
                print("  " + "; ".join(result.alert_reasons))
        return created
