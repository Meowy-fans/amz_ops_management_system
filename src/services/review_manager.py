"""Manage pending attribute reviews and reviewed plan submission."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.repositories.amazon_listing_pending_review_repository import (
    AmazonListingPendingReviewRepository,
)


class ReviewManager:
    """Coordinates pending attribute review records for listing plans."""

    def __init__(
        self,
        db: Session,
        repository: AmazonListingPendingReviewRepository | None = None,
        review_agent: Any = None,
        coverage_gate: Any = None,
        submitter: Any = None,
    ):
        self.db = db
        self.repository = repository or AmazonListingPendingReviewRepository(db)
        self.review_agent = review_agent
        self.coverage_gate = coverage_gate
        self.submitter = submitter

    def persist_pending_plan(self, plan: Dict[str, Any]) -> Optional[int]:
        pending_items = self._pending_items(plan)
        if not pending_items:
            return None
        return self.repository.upsert_pending(
            category=str(plan.get("product_type") or ""),
            sku=str(plan.get("sku") or ""),
            parent_sku=self._parent_sku(plan),
            plan_snapshot=plan,
            pending_items=pending_items,
        )

    def review_pending_attributes(
        self,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        rows = self.repository.list_reviews(
            category=category,
            status="pending",
            limit=limit,
        )
        reviewed = 0
        completed = 0
        human_required = 0
        for row in rows:
            decisions = list(row.get("review_decisions") or [])
            decided_attrs = {item.get("attribute") for item in decisions}
            for item in row.get("pending_items") or []:
                if item.get("attribute") in decided_attrs:
                    continue
                if item.get("route") != "ai_agent":
                    human_required += 1
                    continue
                verdict = self._review_agent().review(row["plan_snapshot"], item)
                reviewed += 1
                if verdict.verdict == "correct":
                    decisions.append(self._approved_decision(item, verdict.as_dict()))
                else:
                    decisions.append(self._manual_decision(item, verdict.as_dict()))
                    human_required += 1
            status = (
                "completed"
                if self._all_pending_items_decided(row.get("pending_items") or [], decisions)
                else "in_progress"
            )
            if status == "completed":
                completed += 1
            self.repository.save_decisions(row["id"], decisions, status=status)
        return {
            "reviewed": reviewed,
            "completed": completed,
            "human_required": human_required,
            "rows": len(rows),
        }

    def submit_reviewed_plans(
        self,
        category: Optional[str] = None,
        dry_run: bool = True,
        validation_only: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        rows = self.repository.list_reviews(
            category=category,
            status="completed",
            limit=limit,
        )
        results: List[Dict[str, Any]] = []
        for row in rows:
            plan = self._plan_with_decisions(row["plan_snapshot"], row["review_decisions"])
            coverage = self._coverage_gate().evaluate(plan)
            if coverage.blocked:
                results.append({
                    "sku": plan.get("sku"),
                    "status": "blocked_attribute_coverage",
                    "issues": len(coverage.findings),
                    "blocking_codes": coverage.blocking_codes,
                    "attribute_coverage_findings": coverage.findings,
                })
                continue
            results.extend(
                self._submitter().submit(
                    [plan],
                    dry_run=dry_run,
                    validation_only=validation_only,
                )
            )
        return results

    @staticmethod
    def _pending_items(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for attribute, resolution in (plan.get("attribute_resolutions") or {}).items():
            if not ReviewManager._is_pending_llm_required(resolution):
                continue
            items.append({
                "attribute": attribute,
                "value": resolution.get("value"),
                "evidence": resolution.get("evidence"),
                "score": resolution.get("confidence_score"),
                "route": resolution.get("review_route") or "human",
                "confidence": resolution.get("confidence"),
                "shape": resolution.get("shape"),
                "state": resolution.get("state"),
                "context_text": resolution.get("review_context", ""),
            })
        return items

    @staticmethod
    def _is_pending_llm_required(resolution: Dict[str, Any]) -> bool:
        return (
            resolution.get("level") == "required"
            and resolution.get("source") == "llm"
            and resolution.get("state") == "needs_manual_review"
            and resolution.get("review_status") not in {"auto_approved", "completed"}
        )

    @staticmethod
    def _parent_sku(plan: Dict[str, Any]) -> Optional[str]:
        rel = (plan.get("attributes") or {}).get("child_parent_sku_relationship") or []
        if isinstance(rel, list) and rel:
            return rel[0].get("parent_sku")
        return None

    @staticmethod
    def _approved_decision(
        item: Dict[str, Any],
        verdict: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "attribute": item.get("attribute"),
            "decision": "approved",
            "value": item.get("value"),
            "evidence": item.get("evidence"),
            "route": item.get("route"),
            "reviewer": "attribute_review_agent",
            "verdict": verdict,
        }

    @staticmethod
    def _manual_decision(
        item: Dict[str, Any],
        verdict: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "attribute": item.get("attribute"),
            "decision": "needs_human",
            "value": item.get("value"),
            "evidence": item.get("evidence"),
            "route": "human",
            "reviewer": "attribute_review_agent",
            "verdict": verdict,
        }

    @staticmethod
    def _all_pending_items_decided(
        pending_items: List[Dict[str, Any]],
        decisions: List[Dict[str, Any]],
    ) -> bool:
        approved = {
            item.get("attribute")
            for item in decisions
            if item.get("decision") == "approved"
        }
        return all(item.get("attribute") in approved for item in pending_items)

    def _plan_with_decisions(
        self,
        plan: Dict[str, Any],
        decisions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        updated = dict(plan)
        attrs = dict(updated.get("attributes") or {})
        resolutions = dict(updated.get("attribute_resolutions") or {})
        for decision in decisions:
            if decision.get("decision") != "approved":
                continue
            attribute = str(decision.get("attribute") or "")
            resolution = dict(resolutions.get(attribute) or {})
            resolution.update({
                "value": decision.get("value"),
                "evidence": decision.get("evidence"),
                "source": "review_override",
                "state": "review_completed",
                "review_status": "completed",
                "blocking": False,
            })
            resolutions[attribute] = resolution
            attrs[attribute] = self._render_attribute(attribute, resolution)
        updated["attributes"] = attrs
        updated["attribute_resolutions"] = resolutions
        return updated

    @staticmethod
    def _render_attribute(attribute: str, resolution: Dict[str, Any]) -> List[Dict[str, Any]]:
        value = resolution.get("value")
        shape = resolution.get("shape")
        if shape == "list_value":
            values = value if isinstance(value, list) else [value]
            return [{"value": item} for item in values if item not in (None, "")]
        if shape in {"object", "nested_object"}:
            values = value if isinstance(value, list) else [value]
            return [item for item in values if isinstance(item, dict) and item]
        if shape == "measure":
            return [value] if isinstance(value, dict) else [{"value": value}]
        return [{"value": value}]

    def _review_agent(self):
        if self.review_agent is None:
            from src.services.attribute_review_agent import AttributeReviewAgent

            self.review_agent = AttributeReviewAgent()
        return self.review_agent

    def _coverage_gate(self):
        if self.coverage_gate is None:
            from src.services.amazon_listing_attribute_coverage_gate import (
                AmazonListingAttributeCoverageGate,
            )
            from src.services.amazon_schema_service import AmazonSchemaService

            self.coverage_gate = AmazonListingAttributeCoverageGate(
                schema_service=AmazonSchemaService(self.db)
            )
        return self.coverage_gate

    def _submitter(self):
        if self.submitter is None:
            from src.services.amazon_listing_submitter import AmazonListingSubmitter

            self.submitter = AmazonListingSubmitter(db=self.db)
        return self.submitter
