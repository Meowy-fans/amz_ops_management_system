#!/usr/bin/env python3
"""S7 multi-category acceptance runner for Listing Rule Authoring V2."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from infrastructure.db_pool import SessionLocal
from src.repositories.product_listing_repository import ProductListingRepository
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
from src.services.listing_payload_v2_validation_compare import ValidationCompareCase
from src.services.product_listing_api_plan_builder import ProductListingAPIPlanBuilder
from src.services.product_listing_service import ProductListingService
from src.services.review_adapter_v2 import ReviewAdapterV2
from src.services.rule_skeleton_generator_v2 import RuleSkeletonGeneratorV2
from src.services.rule_tree_utils_v2 import count_placeholder_leaves, iter_leaf_rules
from src.services.amazon_schema_service import AmazonSchemaService
from src.services.validation_preview_v2 import ValidationPreviewV2


@dataclass
class SkuOfflineResult:
    sku: str
    missing_count: int
    pending_count: int
    blocking: bool
    status: str
    missing_paths: List[str] = field(default_factory=list)
    pending_paths: List[str] = field(default_factory=list)


@dataclass
class SkuPreviewResult:
    sku: str
    preview_status: str
    amazon_issues: int
    v2_findings: int
    unexplained_amazon_only: int
    error_message: Optional[str] = None


def _pool_skus(db, product_type: str) -> List[str]:
    repo = ProductListingRepository(db)
    all_skus = repo.get_pending_listing_skus()
    mapping = dict(repo.get_sku_to_category_mapping(all_skus))
    return [sku for sku in all_skus if mapping.get(sku) == product_type]


def _offline_status(plan) -> str:
    missing = len(plan.missing_required_paths or [])
    pending = len(plan.pending_review_paths or [])
    if missing > 0 and pending > 0:
        return "missing_and_review"
    if missing > 0:
        return "missing_only"
    if pending > 0:
        return "pending_review"
    if plan.findings:
        return "findings_only"
    return "clean"


def evaluate_offline(
    db,
    product_type: str,
    skus: List[str],
) -> List[SkuOfflineResult]:
    engine = ListingPayloadEngineV2(db=db)
    loader = AttributeRuleLoader()
    review = ReviewAdapterV2(db=db)
    rules = loader.load(product_type)
    results: List[SkuOfflineResult] = []
    for sku in skus:
        overrides = review.build_overrides_from_decisions(category=product_type, sku=sku)
        plan = engine.build_read_only_plan(
            product_type=product_type,
            sku=sku,
            rules=rules,
            overrides=overrides or None,
        )
        blocking = any(
            str(finding.get("code") or "").startswith("MISSING_")
            or finding.get("code") == "NEEDS_REVIEW_REQUIRED_ATTRIBUTE"
            for finding in (plan.findings or [])
        ) or bool(plan.missing_required_paths)
        results.append(
            SkuOfflineResult(
                sku=sku,
                missing_count=len(plan.missing_required_paths or []),
                pending_count=len(plan.pending_review_paths or []),
                blocking=blocking,
                status=_offline_status(plan),
                missing_paths=list(plan.missing_required_paths or []),
                pending_paths=list(plan.pending_review_paths or []),
            )
        )
    return results


def evaluate_preview(
    db,
    product_type: str,
    skus: List[str],
) -> List[SkuPreviewResult]:
    service = ProductListingService(db=db)
    service.listing_payload_engine_mode = "v2"
    plan_builder = ProductListingAPIPlanBuilder(service)
    preview = ValidationPreviewV2(db=db)
    loader = AttributeRuleLoader()
    rules = loader.load(product_type)
    ignored_roots = rules.get("coverage_ignore_required") or []
    results: List[SkuPreviewResult] = []
    for sku in skus:
        plan = plan_builder.build_v2_payload_plan_for_sku(product_type, sku)
        result = preview.preview(plan)
        comparison = preview.compare(plan, result)
        unexplained = ValidationPreviewV2.unexplained_amazon_only(
            comparison,
            ignored_attribute_roots=ignored_roots,
        )
        results.append(
            SkuPreviewResult(
                sku=sku,
                preview_status=result.status,
                amazon_issues=len(result.issues),
                v2_findings=len(plan.findings or []),
                unexplained_amazon_only=len(unexplained),
                error_message=result.error_message,
            )
        )
    return results


def summarize_offline(product_type: str, rows: List[SkuOfflineResult]) -> Dict[str, Any]:
    zero_missing = sum(1 for row in rows if row.missing_count == 0)
    not_missing_only = sum(1 for row in rows if row.status != "missing_only")
    clean = sum(1 for row in rows if row.status == "clean")
    return {
        "product_type": product_type,
        "sku_count": len(rows),
        "zero_missing": zero_missing,
        "not_missing_only": not_missing_only,
        "clean": clean,
        "by_status": _count_by(rows, "status"),
        "rows": [asdict(row) for row in rows],
    }


def summarize_preview(product_type: str, rows: List[SkuPreviewResult]) -> Dict[str, Any]:
    passed = [
        row
        for row in rows
        if row.preview_status == "validation_preview_passed"
    ]
    return {
        "product_type": product_type,
        "sku_count": len(rows),
        "validation_preview_passed": len(passed),
        "passed_skus": [row.sku for row in passed],
        "by_status": _count_by(rows, "preview_status"),
        "rows": [asdict(row) for row in rows],
    }


def _count_by(rows: List[Any], attr: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, attr))
        counts[key] = counts.get(key, 0) + 1
    return counts


def evaluate_bed_frame_skeleton(db) -> Dict[str, Any]:
    generator = RuleSkeletonGeneratorV2(schema_service=AmazonSchemaService(db))
    result = generator.generate("BED_FRAME", write=False, overwrite=False)
    attributes = result.rules.get("attributes") or {}
    return {
        "product_type": "BED_FRAME",
        "attribute_count": result.attribute_count,
        "leaf_path_count": result.leaf_path_count,
        "placeholder_leaf_count": result.placeholder_leaf_count,
        "dimension_strategy": result.rules.get("dimension_strategy"),
        "generated": True,
        "warnings": result.warnings,
    }


def evaluate_rule_yaml(product_type: str) -> Dict[str, Any]:
    rules = AttributeRuleLoader().load(product_type)
    attributes = rules.get("attributes") or {}
    leaf_count = sum(1 for _ in iter_leaf_rules(attributes))
    placeholder_count = count_placeholder_leaves(attributes)
    rate = (placeholder_count / leaf_count) if leaf_count else 0.0
    return {
        "product_type": product_type,
        "rule_file_exists": bool(attributes),
        "leaf_count": leaf_count,
        "placeholder_leaf_count": placeholder_count,
        "placeholder_rate": round(rate, 4),
        "dimension_strategy": rules.get("dimension_strategy"),
        "mode": rules.get("mode"),
    }


def main() -> int:
    run_preview = "--preview" in sys.argv
    categories = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    if not categories:
        categories = ["CHAIR", "TABLE", "BED_FRAME"]

    report: Dict[str, Any] = {
        "acceptance": "S7-listing-rule-authoring-v2",
        "preview_enabled": run_preview,
        "categories": {},
        "gates": {},
    }

    with SessionLocal() as db:
        for product_type in categories:
            product_type = product_type.upper()
            category_report: Dict[str, Any] = {
                "rule_yaml": evaluate_rule_yaml(product_type),
            }

            if product_type == "BED_FRAME":
                category_report["skeleton"] = evaluate_bed_frame_skeleton(db)
                skus = _pool_skus(db, product_type)
                category_report["pool_size"] = len(skus)
                if skus:
                    offline = evaluate_offline(db, product_type, skus)
                    category_report["offline"] = summarize_offline(product_type, offline)
                    if run_preview:
                        preview = evaluate_preview(db, product_type, skus)
                        category_report["preview"] = summarize_preview(product_type, preview)
                report["categories"][product_type] = category_report
                continue

            skus = _pool_skus(db, product_type)
            category_report["pool_size"] = len(skus)
            offline = evaluate_offline(db, product_type, skus)
            category_report["offline"] = summarize_offline(product_type, offline)

            if run_preview and skus:
                preview = evaluate_preview(db, product_type, skus)
                category_report["preview"] = summarize_preview(product_type, preview)

            report["categories"][product_type] = category_report

    chair = report["categories"].get("CHAIR", {})
    table = report["categories"].get("TABLE", {})
    bed = report["categories"].get("BED_FRAME", {})

    report["gates"] = {
        "chair_preview_passed_ge_1": (
            chair.get("preview", {}).get("validation_preview_passed", 0) >= 1
            if run_preview
            else None
        ),
        "chair_zero_missing_all": chair.get("offline", {}).get("zero_missing", 0)
        == chair.get("pool_size", 0),
        "chair_placeholder_rate_lt_20pct": (
            chair.get("rule_yaml", {}).get("placeholder_rate", 1.0) < 0.2
        ),
        "table_not_missing_only_ge_1": table.get("offline", {}).get("not_missing_only", 0) >= 1,
        "bed_frame_skeleton_generated": bed.get("skeleton", {}).get("generated", False),
        "bed_frame_preview_passed_all": (
            bed.get("preview", {}).get("validation_preview_passed", 0)
            == bed.get("pool_size", 0)
            if run_preview and bed.get("pool_size")
            else None
        ),
    }

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
