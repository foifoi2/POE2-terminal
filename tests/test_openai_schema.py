from __future__ import annotations

import unittest

from poe2_alpha.analysis.openai_client import ANALYSIS_SCHEMA
from poe2_alpha.models import Analysis


class StructuredOutputSchemaTests(unittest.TestCase):
    def test_required_fields_match_analysis_model(self) -> None:
        raw = {
            "categories": ["Build"], "is_poe2": True, "economic_impact": 80,
            "actionability": 70, "irreversibility": 30, "novelty": 75,
            "information_asymmetry": 70, "credibility": 60, "summary": "x",
            "economic_reason": "y", "affected_entities": ["Skill A"],
            "core_items": [{"name": "Item A", "role": "enabler", "required_conditions": [],
                            "substitute_names": [], "demand_concentration": 90, "evidence": "required"}],
            "decision_keywords": [], "evidence_for": [], "evidence_against": [],
            "confidence": 65, "needs_deep_analysis": True,
        }
        parsed = Analysis.from_dict(raw)
        self.assertEqual(parsed.core_items[0].name, "Item A")
        self.assertEqual(set(raw), set(ANALYSIS_SCHEMA["required"]))


if __name__ == "__main__":
    unittest.main()
