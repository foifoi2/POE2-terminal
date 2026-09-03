from __future__ import annotations

import re

from ..models import Analysis, Comment, CoreItem, Post


CATEGORY_TERMS = {
    "Build": ("build", "dps", "damage", "boss", "clear speed", "setup"),
    "Item": ("item", "gear", "equipment"),
    "Unique Item": ("unique",),
    "Skill": ("skill", "gem"),
    "Support Gem": ("support gem", "support"),
    "Passive": ("passive", "node"),
    "Atlas": ("atlas",),
    "Farming": ("farm", "profit", "div/hour", "div per hour"),
    "Currency": ("currency", "divine", "exalt"),
    "Trading": ("trade", "market", "price"),
    "Crafting": ("craft",),
    "Drop": ("drop", "loot"),
    "Bug": ("bug", "broken", "not working"),
    "Exploit": ("exploit", "dupe", "abuse"),
    "Patch": ("patch", "hotfix"),
    "Nerf": ("nerf",),
    "Buff": ("buff",),
    "PSA": ("psa", "warning", "heads up"),
    "Guide": ("guide", "how to"),
    "Question": ("?", "question"),
    "Discovery": ("discovered", "tested", "interaction", "confirmed", "found"),
}
DECISION_TERMS = ("psa", "do not", "don't", "avoid", "never", "trap", "brick", "broken",
                  "bug", "exploit", "op", "overpowered", "nerf", "buff", "farm", "profit",
                  "drop", "worth", "hidden", "secret", "tested", "confirmed", "warning", "heads up")
FALSE_POSITIVE_TERMS = ("meme", "fan art", "cosplay", "giveaway", "rant", "fluff")
EVIDENCE_TERMS = ("tested", "test results", "confirmed", "sample", "runs", "dps", "%", "seconds", "video")
ACTION_TERMS = ("use ", "equip", "buy", "avoid", "take this", "do not take", "farm", "swap", "craft")


class HeuristicAnalyzer:
    """Offline fallback and deterministic demo analyzer; not a substitute for semantic review."""

    model = "heuristic-v1"

    def analyze(self, post: Post, comments: list[Comment] | None = None, deep: bool = False) -> Analysis:
        text = f"{post.title}\n{post.body}".lower()
        comments = comments or []
        categories = [name for name, terms in CATEGORY_TERMS.items() if any(term in text for term in terms)]
        categories = categories or ["Other"]
        false_positive = any(term in text for term in FALSE_POSITIVE_TERMS)
        is_build = "Build" in categories
        is_economic = any(c in categories for c in ("Farming", "Currency", "Trading", "Crafting", "Drop", "Item", "Unique Item"))
        is_discovery = "Discovery" in categories or "PSA" in categories
        evidence_count = sum(term in text for term in EVIDENCE_TERMS)
        independent_confirmation = sum(any(t in c.body.lower() for t in ("confirmed", "works", "reproduced", "tested")) for c in comments)

        economic = min(100, (55 if is_build else 0) + (55 if is_economic else 0) + (15 if is_discovery else 0))
        action = min(100, (50 if any(t in text for t in ACTION_TERMS) else 20) + (25 if is_build else 0) + (15 if is_discovery else 0))
        irreversible = 45 if any(t in text for t in ("expensive", "atlas", "investment", "league start")) else 20
        novelty = 75 if is_discovery else 45
        asymmetry = max(20, min(90, 85 - post.score // 8))
        credibility = min(95, 25 + evidence_count * 12 + independent_confirmation * 15)
        if false_positive:
            economic, action, novelty = min(economic, 15), min(action, 15), min(novelty, 20)

        entities = self._entities(post)
        core_items = self._core_items(post)
        reason = "Build adoption may concentrate demand in required skills or items." if is_build else (
            "The claim may change farming output, supply, or player demand." if is_economic else
            "No concrete POE2 economic transmission mechanism was found by the offline analyzer."
        )
        evidence_for = [x for x in ("Contains measured or test language" if evidence_count else "",
                                    "Has independent confirmation in comments" if independent_confirmation else "") if x]
        evidence_against = [] if evidence_count else ["No explicit measurement or reproducible test detected"]
        confidence = min(90, 30 + evidence_count * 10 + independent_confirmation * 12 + (10 if post.body else 0))
        return Analysis(
            categories=categories, is_poe2=not bool(re.search(r"\bpoe\s*1\b|path of exile 1", text)),
            economic_impact=economic, actionability=action, irreversibility=irreversible,
            novelty=novelty, information_asymmetry=asymmetry, credibility=credibility,
            summary=post.title.strip()[:240], economic_reason=reason, affected_entities=entities,
            core_items=core_items, decision_keywords=[t for t in DECISION_TERMS if t in text],
            evidence_for=evidence_for, evidence_against=evidence_against, confidence=confidence,
            needs_deep_analysis=(economic >= 50 or is_build or is_discovery) and not false_positive,
        )

    @staticmethod
    def _entities(post: Post) -> list[str]:
        candidates = re.findall(r"\b[A-Z][A-Za-z0-9']+(?:\s+[A-Z][A-Za-z0-9']+){0,3}\b", f"{post.title} {post.body}")
        blocked = {"I", "The", "This", "PSA", "POE", "POE2", "Reddit", "Build", "Guide"}
        result: list[str] = []
        for value in candidates:
            value = value.strip()
            if value not in blocked and value not in result and len(value) > 2:
                result.append(value)
        return result[:12]

    @staticmethod
    def _core_items(post: Post) -> list[CoreItem]:
        text = f"{post.title}\n{post.body}"
        patterns = (
            r"(?:unique|item|amulet|ring|staff|helmet|boots|gloves|armour)\s+[\"']?([A-Z][A-Za-z0-9']+(?:\s+[A-Z][A-Za-z0-9']+){0,2})",
            r"([A-Z][A-Za-z0-9']+(?:\s+[A-Z][A-Za-z0-9']+){1,2})\s+(?:is|required|enables|mandatory)",
        )
        names: list[str] = []
        for pattern in patterns:
            names.extend(re.findall(pattern, text))
        cleaned = [re.sub(r"^(?:Unique|Item)\s+", "", n.strip()) for n in names]
        unique_names = list(dict.fromkeys(n for n in cleaned if len(n) > 2))[:5]
        return [CoreItem(name=n, role="possible_enabler", demand_concentration=65,
                         evidence="Name appears near requirement/enabler language; manual verification required.")
                for n in unique_names]
