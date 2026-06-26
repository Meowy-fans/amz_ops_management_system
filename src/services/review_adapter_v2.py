"""V2 review adapter bridging ResolutionTree and path-level review persistence."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.repositories.amazon_listing_pending_review_v2_repository import (
    AmazonListingPendingReviewV2Repository,
)
from src.services.requirement_models_v2 import ResolutionNode


class ReviewAdapterV2:
    """Bridge between V2 ResolutionTree and V2 path-level review table."""

    def __init__(
        self,
        db: Any = None,
        repository: AmazonListingPendingReviewV2Repository | None = None,
        review_agent: Any = None,
        engine: Any = None,
        rule_loader: Any = None,
    ):
        self.db = db
        self.repository = repository or (
            AmazonListingPendingReviewV2Repository(db) if db is not None else None
        )
        self.review_agent = review_agent
        self._engine = engine
        self._rule_loader = rule_loader

    def persist_pending_paths(
        self,
        category: str,
        sku: str,
        parent_sku: Optional[str],
        path_key_version: str,
        plan_snapshot: Dict[str, Any],
        resolution_root: ResolutionNode,
    ) -> int:
        items = self._extract_pending_paths(resolution_root)
        if not items:
            return 0
        enriched = [
            {
                **item,
                "category": category,
                "sku": sku,
                "parent_sku": parent_sku,
                "path_key_version": path_key_version,
                "plan_snapshot": plan_snapshot,
            }
            for item in items
        ]
        self.repository.upsert_pending_paths(enriched)
        return len(enriched)

    def review_pending_paths(
        self,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        rows = self.repository.list_pending(
            category=category,
            status="pending",
            limit=limit,
        )
        reviewed = 0
        human_required = 0
        for row in rows:
            if row.get("route") != "ai_agent":
                human_required += 1
                continue
            verdict = self._review_agent().review(row.get("plan_snapshot") or {}, row)
            reviewed += 1
            if verdict.verdict == "correct":
                self.repository.save_decision(
                    review_id=row["id"],
                    decision="approved",
                    reviewer="attribute_review_agent",
                    verdict=verdict.as_dict(),
                    review_status="completed",
                )
            else:
                self.repository.save_decision(
                    review_id=row["id"],
                    decision="needs_human",
                    reviewer="attribute_review_agent",
                    verdict=verdict.as_dict(),
                    review_status="in_progress",
                )
                human_required += 1
        return {
            "reviewed": reviewed,
            "human_required": human_required,
            "rows": len(rows),
        }

    def build_overrides_from_decisions(
        self,
        category: str,
        sku: str,
    ) -> Dict[str, Dict[str, Any]]:
        rows = self.repository.list_approved_for_sku(category=category, sku=sku)
        overrides: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            overrides[row["path_key"]] = {
                "value": row.get("value"),
                "evidence": row.get("evidence") or "Reviewed path override",
                "confidence": row.get("confidence_label") or "high",
                "confidence_score": row.get("confidence_score"),
                "review_status": "completed",
                "review_route": row.get("route") or "human",
                "source": "review_override",
                "safe_default": False,
            }
        return overrides

    def submit_reviewed_paths(
        self,
        category: Optional[str] = None,
        dry_run: bool = True,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Rebuild V2 plans with approved overrides and return coverage results.

        Does not PUT to Amazon. Actual submission is deferred to S14 cutover.
        """
        sku_rows = self.repository.list_completed_skus(category=category, limit=limit)
        results: List[Dict[str, Any]] = []
        for sku_row in sku_rows:
            sku = sku_row["sku"]
            product_type = sku_row["category"]
            overrides = self.build_overrides_from_decisions(
                category=product_type, sku=sku
            )
            if not overrides:
                continue
            rules = self._get_rule_loader().load(product_type)
            plan = self._get_engine().build_read_only_plan(
                product_type=product_type,
                sku=sku,
                rules=rules,
                overrides=overrides,
            )
            results.append({
                "sku": sku,
                "product_type": product_type,
                "status": "blocked_attribute_coverage" if plan.findings else "dry_run_preview",
                "missing_required_paths": plan.missing_required_paths,
                "pending_review_paths": plan.pending_review_paths,
                "findings_count": len(plan.findings),
                "findings": plan.findings,
            })
        return results

    @staticmethod
    def _extract_pending_paths(
        resolution_root: ResolutionNode,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for node in ReviewAdapterV2._walk_leaves(resolution_root):
            if not ReviewAdapterV2._is_pending_leaf(node):
                continue
            items.append({
                "path_key": node.path_key,
                "attribute": _attribute_from_path_key(node.path_key),
                "display_label": node.path_key,
                "value": node.value,
                "evidence": node.evidence,
                "confidence_label": node.confidence,
                "confidence_score": node.confidence_score,
                "route": node.review_route,
            })
        return items

    @staticmethod
    def _walk_leaves(node: ResolutionNode):
        if not node.children:
            yield node
            return
        for child in node.children:
            yield from ReviewAdapterV2._walk_leaves(child)

    @staticmethod
    def _is_pending_leaf(node: ResolutionNode) -> bool:
        if node.children:
            return False
        if node.value in (None, ""):
            return False
        if node.review_route not in {"ai_agent", "human"}:
            return False
        return bool(node.blocking)

    def _review_agent(self):
        if self.review_agent is None:
            from src.services.attribute_review_agent import AttributeReviewAgent

            self.review_agent = AttributeReviewAgent()
        return self.review_agent

    def _get_engine(self):
        if self._engine is None:
            from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2

            self._engine = ListingPayloadEngineV2(self.db)
        return self._engine

    def _get_rule_loader(self):
        if self._rule_loader is None:
            from src.services.attribute_rule_loader import AttributeRuleLoader

            self._rule_loader = AttributeRuleLoader()
        return self._rule_loader


def _attribute_from_path_key(path_key: str) -> str:
    head = str(path_key or "").split(".")[0]
    return head.split("{")[0]
