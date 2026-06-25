"""Deterministic review helper for evidence-bound attribute candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class AttributeReviewVerdict:
    """Decision produced by the attribute review agent."""

    verdict: str
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {"verdict": self.verdict, "reason": self.reason}


class AttributeReviewAgent:
    """Verifies whether an attribute evidence snippet exists in the plan context."""

    def review(
        self,
        plan_snapshot: Dict[str, Any],
        pending_item: Dict[str, Any],
    ) -> AttributeReviewVerdict:
        evidence = str(pending_item.get("evidence") or "").strip()
        if not evidence:
            return AttributeReviewVerdict("uncertain", "missing_evidence")
        context = str(pending_item.get("context_text") or "").strip()
        if not context:
            context = self._plan_context(plan_snapshot)
        if evidence.casefold() in context.casefold():
            return AttributeReviewVerdict("correct", "evidence_matches_plan_snapshot")
        return AttributeReviewVerdict("uncertain", "evidence_not_found_in_plan_snapshot")

    @staticmethod
    def _plan_context(plan_snapshot: Dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("sku", "product_type"):
            parts.append(str(plan_snapshot.get(key) or ""))
        attrs = plan_snapshot.get("attributes") or {}
        parts.append(str(attrs))
        return "\n".join(parts)
