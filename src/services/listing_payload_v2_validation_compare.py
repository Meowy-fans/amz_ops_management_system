"""Batch VALIDATION_PREVIEW compare evaluator for V2 cutover gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
from src.services.requirement_models_v2 import PayloadBuildPlan
from src.services.review_adapter_v2 import ReviewAdapterV2
from src.services.validation_preview_v2 import ValidationPreviewV2


@dataclass(frozen=True)
class ValidationCompareCase:
    product_type: str
    sku: str


class ListingPayloadV2ValidationCompare:
    """Evaluate Amazon preview parity for representative V2 canary SKUs."""

    DEFAULT_CASES = (
        ValidationCompareCase("CABINET", "meow251115FC0ie"),
        ValidationCompareCase("HOME_MIRROR", "meow251108CqW5i"),
        ValidationCompareCase("OTTOMAN", "meow2511088jSUW"),
    )

    def __init__(
        self,
        db: Session,
        engine: ListingPayloadEngineV2 | None = None,
        preview: ValidationPreviewV2 | None = None,
        review_adapter: ReviewAdapterV2 | None = None,
        rule_loader: Any = None,
        plan_builder: Any = None,
    ):
        self.db = db
        self.engine = engine or ListingPayloadEngineV2(db)
        self.preview = preview or ValidationPreviewV2(db)
        self.review_adapter = review_adapter or ReviewAdapterV2(db=db)
        self.rule_loader = rule_loader or AttributeRuleLoader()
        self.plan_builder = plan_builder

    def _build_plan(self, product_type: str, sku: str) -> PayloadBuildPlan:
        if self.plan_builder is not None:
            return self.plan_builder.build_v2_payload_plan_for_sku(product_type, sku)
        rules = self.rule_loader.load(product_type)
        overrides = self.review_adapter.build_overrides_from_decisions(
            category=product_type,
            sku=sku,
        )
        return self.engine.build_read_only_plan(
            product_type=product_type,
            sku=sku,
            rules=rules,
            overrides=overrides or None,
        )

    def evaluate(
        self,
        cases: Iterable[ValidationCompareCase] | None = None,
        allowed_codes: frozenset[str] | set[str] | None = None,
    ) -> Dict[str, Any]:
        evaluated = [
            self._evaluate_case(case, allowed_codes=allowed_codes)
            for case in (cases or self.DEFAULT_CASES)
        ]
        return {
            "status": "go" if all(item["decision"] == "go" for item in evaluated) else "no_go",
            "cases": evaluated,
            "summary": {
                "go": sum(1 for item in evaluated if item["decision"] == "go"),
                "no_go": sum(1 for item in evaluated if item["decision"] == "no_go"),
                "total": len(evaluated),
            },
        }

    def _evaluate_case(
        self,
        case: ValidationCompareCase,
        allowed_codes: frozenset[str] | set[str] | None,
    ) -> Dict[str, Any]:
        product_type = str(case.product_type or "").strip().upper()
        sku = str(case.sku or "").strip()
        rules = self.rule_loader.load(product_type)
        plan = self._build_plan(product_type, sku)
        result = self.preview.preview(plan)
        comparison = self.preview.compare(plan, result)
        ignored_roots = rules.get("coverage_ignore_required") or []
        unexplained = ValidationPreviewV2.unexplained_amazon_only(
            comparison,
            allowed_codes=allowed_codes,
            ignored_attribute_roots=ignored_roots,
        )
        reasons: List[str] = []
        if result.status == "validation_preview_failed":
            reasons.append("validation_preview_failed")
        if unexplained:
            reasons.append("unexplained_amazon_only_issues")
        return {
            "product_type": product_type,
            "sku": sku,
            "decision": "go" if not reasons else "no_go",
            "reasons": reasons,
            "preview_status": result.status,
            "amazon_issue_count": len(result.issues),
            "v2_finding_count": len(plan.findings or []),
            "comparison": {
                "matched": len(comparison.matched),
                "amazon_only": len(comparison.amazon_only),
                "v2_only": len(comparison.v2_only),
                "unexplained_amazon_only": len(unexplained),
            },
            "unexplained_amazon_only": unexplained,
            "v2_only": comparison.v2_only,
        }
