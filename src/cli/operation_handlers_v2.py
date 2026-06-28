"""CLI handlers for Listing Payload Engine V2 tasks."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from src.services.validation_preview_v2 import ValidationPreviewV2

logger = logging.getLogger(__name__)


def handle_analyze_listing_requirements_v2(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
):
    """Read-only V2 requirement tree analysis for one SKU."""
    from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2

    sku = (sku_list or [None])[0]
    if not product_type:
        raise ValueError("--product-type or --category is required")
    if not sku:
        raise ValueError("--sku is required")

    print("\n" + "=" * 70)
    print("Listing Requirement Analysis V2 - READ ONLY")
    print("=" * 70)

    service = ListingPayloadEngineV2(db=db)
    result = service.analyze_requirements(product_type=product_type, sku=sku)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def handle_validate_listing_v2(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
):
    """Run Amazon VALIDATION_PREVIEW for a V2 plan without PUT."""
    from src.services.attribute_rule_loader import AttributeRuleLoader
    from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
    from src.services.review_adapter_v2 import ReviewAdapterV2

    sku = (sku_list or [None])[0]
    if not product_type:
        raise ValueError("--product-type or --category is required")
    if not sku:
        raise ValueError("--sku is required")

    print("\n" + "=" * 70)
    print("Listing Validation Preview V2 - AMAZON VALIDATION_PREVIEW (no PUT)")
    print("=" * 70)

    normalized = str(product_type).strip().upper()
    from src.services.attribute_rule_loader import AttributeRuleLoader
    from src.services.product_listing_service import ProductListingService

    rules = AttributeRuleLoader().load(normalized)
    service = ProductListingService(db=db)
    service.listing_payload_engine_mode = "v2"
    from src.services.product_listing_api_plan_builder import ProductListingAPIPlanBuilder

    plan = ProductListingAPIPlanBuilder(service).build_v2_payload_plan_for_sku(
        normalized,
        sku,
    )
    preview = ValidationPreviewV2(db=db)
    result = preview.preview(plan)
    comparison = preview.compare(plan, result)
    unexplained = ValidationPreviewV2.unexplained_amazon_only(
        comparison,
        ignored_attribute_roots=rules.get("coverage_ignore_required") or [],
    )

    print(
        f"\nSKU={sku} product_type={normalized} "
        f"status={result.status} request_id={result.amazon_request_id} "
        f"amazon_issues={len(result.issues)} "
        f"v2_findings={len(plan.findings or [])}"
    )
    if result.error_message:
        print(f"error_message={result.error_message}")
    print(
        f"comparison: matched={len(comparison.matched)} "
        f"amazon_only={len(comparison.amazon_only)} "
        f"v2_only={len(comparison.v2_only)} "
        f"unexplained_amazon_only={len(unexplained)}"
    )
    if comparison.amazon_only:
        print("\nAmazon flagged but V2 missed:")
        for issue in comparison.amazon_only:
            attrs = issue.get("attributeNames") or []
            print(f"  [{issue.get('code')}] {issue.get('message')} ({', '.join(attrs)})")
    if unexplained:
        print("\nUnexplained Amazon-only issues:")
        for issue in unexplained:
            attrs = issue.get("attributeNames") or []
            print(f"  [{issue.get('code')}] {issue.get('message')} ({', '.join(attrs)})")
    if comparison.v2_only:
        print("\nV2 flagged but Amazon accepted:")
        for finding in comparison.v2_only:
            print(f"  [{finding.get('code')}] {finding.get('path_key')}")
    return {
        "success": True,
        "status": result.status,
        "amazon_issues": len(result.issues),
        "v2_findings": len(plan.findings or []),
        "comparison": {
            "matched": len(comparison.matched),
            "amazon_only": len(comparison.amazon_only),
            "v2_only": len(comparison.v2_only),
            "unexplained_amazon_only": len(unexplained),
        },
    }


def handle_generate_rule_skeleton_v2(
    db: Session,
    product_type: Optional[str] = None,
    overwrite: bool = False,
):
    """Generate a V2 tree-aware YAML rule skeleton for one product type."""
    from src.services.amazon_schema_service import AmazonSchemaService
    from src.services.rule_skeleton_generator_v2 import RuleSkeletonGeneratorV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    print("\n" + "=" * 70)
    print("Generate Rule Skeleton V2")
    print("=" * 70)

    generator = RuleSkeletonGeneratorV2(schema_service=AmazonSchemaService(db))
    result = generator.generate(
        product_type=product_type,
        write=True,
        overwrite=overwrite,
    )

    print(f"\nProduct type: {result.product_type}")
    print(f"Rule file: {result.path}")
    print(f"Written: {result.written}")
    print(f"Already existed: {result.existed}")
    print(f"Attributes: {result.attribute_count}")
    print(f"Leaf path keys: {result.leaf_path_count}")
    print(f"Placeholder leaves: {result.placeholder_leaf_count}")
    print(f"Mode: {result.rules.get('mode')}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return result.as_dict()


def _load_and_write_rules(
    product_type: str,
    rules: dict,
    *,
    written_by: str,
) -> Path:
    """Persist merged rules back to the category YAML file."""
    from src.services.attribute_rule_loader import AttributeRuleLoader
    from src.services.rule_yaml_write_guard import write_rule_yaml

    loader = AttributeRuleLoader()
    target_path = loader.config_dir / f"{product_type.lower()}.yaml"
    return write_rule_yaml(
        target_path,
        rules,
        product_type=product_type,
        written_by=written_by,
    )


def handle_map_rule_fields_v2(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
    write: bool = True,
):
    """Auto-map Giga fields onto V2 YAML rule leaf sources."""
    from src.services.attribute_rule_loader import AttributeRuleLoader
    from src.services.rule_field_mapper_v2 import RuleFieldMapperV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    normalized = str(product_type).strip().upper()
    print("\n" + "=" * 70)
    print("Map Rule Fields V2")
    print("=" * 70)

    rules = AttributeRuleLoader().load(normalized)
    mapper = RuleFieldMapperV2(db=db)
    result = mapper.map_rules(
        product_type=normalized,
        rules=rules,
        sample_skus=sku_list,
    )

    if write:
        path = _load_and_write_rules(
            normalized,
            result.rules,
            written_by="map_rule_fields_v2",
        )
        print(f"Rule file written: {path}")
    else:
        print("Dry run only; YAML not written")

    print(f"\nProduct type: {result.product_type}")
    print(f"Sample SKUs: {result.sample_sku_count}")
    print(f"Placeholder leaves scanned: {result.leaf_count}")
    print(f"Mapped leaves: {result.mapped_leaf_count}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    for path_key in result.mapped_paths[:20]:
        print(f"  mapped: {path_key}")
    if len(result.mapped_paths) > 20:
        print(f"  ... and {len(result.mapped_paths) - 20} more")
    return result.as_dict()


def handle_learn_rules_from_feedback_v2(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
    write: bool = True,
):
    """Apply learned 90220 paths onto V2 YAML rules."""
    from src.services.attribute_rule_loader import AttributeRuleLoader
    from src.services.rule_feedback_adapter_v2 import RuleFeedbackAdapterV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    normalized = str(product_type).strip().upper()
    print("\n" + "=" * 70)
    print("Learn Rules From Feedback V2")
    print("=" * 70)

    rules = AttributeRuleLoader().load(normalized)
    adapter = RuleFeedbackAdapterV2(db=db)
    result = adapter.apply_learned_paths(
        product_type=normalized,
        rules=rules,
        sample_skus=sku_list,
    )

    if write:
        path = _load_and_write_rules(
            normalized,
            result.rules,
            written_by="learn_rules_from_feedback_v2",
        )
        print(f"Rule file written: {path}")
    else:
        print("Dry run only; YAML not written")

    print(f"\nProduct type: {result.product_type}")
    print(f"Learned paths: {result.learned_path_count}")
    print(f"Added rule entries: {result.added_path_count}")
    print(f"Mapped existing placeholders: {result.mapped_path_count}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    return result.as_dict()


def handle_reuse_rule_patterns_v2(
    db: Session,
    product_type: Optional[str] = None,
    reference_product_type: Optional[str] = None,
    write: bool = True,
):
    """Copy source chains from a reference category onto target rules."""
    from src.services.attribute_rule_loader import AttributeRuleLoader
    from src.services.rule_pattern_reuse_v2 import RulePatternReuseV2

    if not product_type:
        raise ValueError("--product-type or --category is required")
    if not reference_product_type:
        raise ValueError("--reference is required")

    normalized = str(product_type).strip().upper()
    reference = str(reference_product_type).strip().upper()
    print("\n" + "=" * 70)
    print(f"Reuse Rule Patterns V2 ({reference} -> {normalized})")
    print("=" * 70)

    loader = AttributeRuleLoader()
    target_rules = loader.load(normalized)
    reference_rules = loader.load(reference)
    result = RulePatternReuseV2().reuse_patterns(
        product_type=normalized,
        rules=target_rules,
        reference_rules=reference_rules,
        reference_product_type=reference,
    )

    if write:
        path = _load_and_write_rules(
            normalized,
            result.rules,
            written_by=f"reuse_rule_patterns_v2_from_{reference.lower()}",
        )
        print(f"Rule file written: {path}")
    else:
        print("Dry run only; YAML not written")

    print(f"\nProduct type: {result.product_type}")
    print(f"Reference: {result.reference_product_type}")
    print(f"Placeholder leaves scanned: {result.candidate_leaf_count}")
    print(f"Reused leaves: {result.reused_leaf_count}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    for path_key in result.reused_paths[:20]:
        print(f"  reused: {path_key}")
    if len(result.reused_paths) > 20:
        print(f"  ... and {len(result.reused_paths) - 20} more")
    return result.as_dict()


def handle_migrate_rules_v2(
    db: Session,
    product_type: Optional[str] = None,
    write: bool = False,
    require_golden: bool = True,
):
    """Migrate legacy YAML to V2 expanded skeleton with optional golden gate."""
    from src.services.amazon_schema_service import AmazonSchemaService
    from src.services.rule_migration_v2 import RuleMigrationV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    normalized = str(product_type).strip().upper()
    print("\n" + "=" * 70)
    print("Migrate Rules V2")
    print("=" * 70)

    migrator = RuleMigrationV2(schema_service=AmazonSchemaService(db))
    result = migrator.migrate_product_type(normalized)

    golden_report = None
    if require_golden and normalized in {
        case.product_type for case in RuleMigrationV2.DEFAULT_GOLDEN_CASES
    }:
        cases = [
            case
            for case in RuleMigrationV2.DEFAULT_GOLDEN_CASES
            if case.product_type == normalized
        ]
        golden_report = migrator.evaluate_golden_regression(db, cases=cases)
        print(
            f"\nGolden regression: status={golden_report.status} "
            f"passed={golden_report.passed}/{golden_report.total}"
        )
        for case in golden_report.cases:
            if not case.passed:
                print(f"  FAIL {case.product_type}/{case.sku}: {case.differences[:5]}")

    print(f"\nProduct type: {result.product_type}")
    print(f"Mode: {result.mode}")
    print(f"Legacy attributes: {result.legacy_attribute_count}")
    print(f"Skeleton attributes: {result.skeleton_attribute_count}")
    print(f"Migrated attributes: {result.migrated_attribute_count}")
    print(f"Added attributes: {len(result.added_attribute_names)}")
    for warning in result.warnings:
        print(f"Warning: {warning}")

    if write:
        if golden_report and golden_report.status != "go":
            raise RuntimeError("Golden regression failed; refusing to write migrated YAML")
        path, backup = migrator.write_migrated_rules(result)
        print(f"\nRule file written: {path}")
        if backup:
            print(f"Backup: {backup}")
    else:
        print("\nDry run only; YAML not written")

    payload = result.as_dict()
    if golden_report is not None:
        payload["golden_regression"] = golden_report.as_dict()
    return payload


def handle_evaluate_rules_v2_golden(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
):
    """Compare baseline vs migrated PayloadBuildPlan.attributes for golden SKUs."""
    from src.services.amazon_schema_service import AmazonSchemaService
    from src.services.rule_migration_v2 import GoldenRegressionCase, RuleMigrationV2

    print("\n" + "=" * 70)
    print("Evaluate Rules V2 Golden Regression")
    print("=" * 70)

    migrator = RuleMigrationV2(schema_service=AmazonSchemaService(db))
    if product_type and sku_list:
        cases = [
            GoldenRegressionCase(
                product_type=str(product_type).strip().upper(),
                sku=str(sku).strip(),
            )
            for sku in sku_list
            if str(sku).strip()
        ]
    elif product_type:
        cases = [
            case
            for case in RuleMigrationV2.DEFAULT_GOLDEN_CASES
            if case.product_type == str(product_type).strip().upper()
        ]
    else:
        cases = list(RuleMigrationV2.DEFAULT_GOLDEN_CASES)

    report = migrator.evaluate_golden_regression(db, cases=cases)
    print(
        f"\nstatus={report.status} passed={report.passed}/{report.total} "
        f"failed={report.failed}"
    )
    for case in report.cases:
        marker = "PASS" if case.passed else "FAIL"
        print(
            f"  {marker} {case.product_type}/{case.sku} "
            f"attrs={case.baseline_attribute_count}->{case.migrated_attribute_count}"
        )
        for diff in case.differences[:10]:
            print(f"    {diff}")
        if len(case.differences) > 10:
            print(f"    ... and {len(case.differences) - 10} more")
    return report.as_dict()


def handle_review_pending_rules(
    db: Session,
    product_type: Optional[str] = None,
):
    """List Layer 1 YAML rule review gaps for one category."""
    from src.services.rule_review_service_v2 import RuleReviewServiceV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    normalized = str(product_type).strip().upper()
    print("\n" + "=" * 70)
    print(f"Review Pending Rules V2 (Layer 1) - {normalized}")
    print("=" * 70)

    report = RuleReviewServiceV2().review_category(normalized, db=db)
    print(
        f"\nleaf_count={report.leaf_count} "
        f"placeholder_leaves={report.placeholder_leaf_count} "
        f"review_items={len(report.items)} "
        f"blocking_items={report.blocking_item_count}"
    )
    for item in report.items[:50]:
        marker = "BLOCK" if item.blocking else "INFO"
        print(f"  [{marker}][{item.issue_type}] {item.path_key}: {item.detail}")
    if len(report.items) > 50:
        print(f"  ... and {len(report.items) - 50} more")
    return report.as_dict()


def handle_approve_rule(
    db: Session,
    product_type: Optional[str] = None,
    path_key: Optional[str] = None,
    decision: Optional[str] = None,
    reviewer: Optional[str] = None,
    issue_type: Optional[str] = None,
    write: bool = False,
):
    """Approve one Layer 1 YAML rule review item and optionally write YAML."""
    from src.services.rule_review_service_v2 import RuleReviewServiceV2

    if not product_type:
        raise ValueError("--product-type or --category is required")
    if not path_key:
        raise ValueError("--path-key is required")
    if not decision:
        raise ValueError("--decision is required")
    if not reviewer:
        raise ValueError("--reviewer is required")

    normalized = str(product_type).strip().upper()
    print("\n" + "=" * 70)
    print(f"Approve Rule V2 (Layer 1) - {normalized}")
    print("=" * 70)

    result = RuleReviewServiceV2().approve_rule(
        product_type=normalized,
        path_key=path_key,
        decision=decision,
        reviewer=reviewer,
        issue_type=issue_type,
        write=write,
        db=db,
    )
    print(
        f"\ndecision={result.decision} path_key={result.path_key} "
        f"written={result.written} resolved={result.resolved_issue_types}"
    )
    if result.yaml_path:
        print(f"Rule file written: {result.yaml_path}")
    elif not write:
        print("Dry run only; YAML not written (use --no-dry-run to persist)")
    for key, value in result.patch_summary.items():
        print(f"  patch.{key}={value}")
    return result.as_dict()


def handle_promote_category_rules_v2(
    db: Session,
    product_type: Optional[str] = None,
    write: bool = False,
    reviewer: Optional[str] = None,
    require_preview: bool = False,
    min_preview_passed: int = 1,
    acceptance_file: Optional[str] = None,
):
    """Promote category rules to live_eligible when checklist passes."""
    from src.services.category_rule_promotion_v2 import CategoryRulePromotionV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    normalized = str(product_type).strip().upper()
    print("\n" + "=" * 70)
    print(f"Promote Category Rules V2 - {normalized}")
    print("=" * 70)

    acceptance_data = None
    if acceptance_file:
        acceptance_data = CategoryRulePromotionV2.load_acceptance_file(acceptance_file)
        print(f"Loaded acceptance file: {acceptance_file}")

    service = CategoryRulePromotionV2()
    report = service.promote(
        db,
        normalized,
        write=write,
        reviewer=reviewer,
        require_preview=require_preview,
        min_preview_passed=min_preview_passed,
        acceptance_data=acceptance_data,
    )

    print(f"\nstatus={report.status} passed={report.passed} written={report.written}")
    for check in report.checks:
        marker = "PASS" if check.passed else "FAIL"
        req = "required" if check.required else "optional"
        print(f"  [{marker}][{req}] {check.name}: {check.detail}")
    if report.yaml_path:
        print(f"Rule file written: {report.yaml_path}")
    if report.backup_path:
        print(f"Backup created: {report.backup_path}")
    elif not write and report.passed and not report.already_live_eligible:
        print("Dry run only; YAML not written (use --no-dry-run to promote)")

    if not report.passed:
        raise ValueError(f"Promotion checklist failed for {normalized}")
    return report.as_dict()


def handle_onboard_category_v2(
    db: Session,
    product_type: Optional[str] = None,
    reference_product_type: Optional[str] = None,
    sample_sku_limit: Optional[int] = None,
    overwrite_skeleton: bool = True,
    run_s7_offline: bool = False,
    run_s7_preview: bool = False,
):
    """Run full category rule onboarding pipeline."""
    from src.services.category_onboarding_v2 import CategoryOnboardingV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    normalized = str(product_type).strip().upper()
    print("\n" + "=" * 70)
    print(f"Onboard Category V2 - {normalized}")
    print("=" * 70)

    report = CategoryOnboardingV2(db=db).onboard(
        normalized,
        reference_product_type=reference_product_type,
        sample_sku_limit=sample_sku_limit,
        overwrite_skeleton=overwrite_skeleton,
        run_s7_offline=run_s7_offline,
        run_s7_preview=run_s7_preview,
    )

    print(f"\nstatus={report.status} pool_skus={len(report.pool_skus)}")
    print(f"yaml_path={report.yaml_path}")
    print(f"state_path={report.state_path}")
    print(f"acceptance_report_path={report.acceptance_report_path}")
    print(f"review_blocking_count={report.review_blocking_count}")
    for step in report.steps:
        print(f"  [{step.status}] {step.step}: {step.detail}")
    return report.as_dict()


def handle_analyze_listing_feedback_v2(
    db: Session,
    product_type: Optional[str] = None,
    limit: int = 50,
):
    """Classify Amazon listing feedback by rule vs content routing."""
    from src.services.listing_feedback_analyzer_v2 import ListingFeedbackAnalyzerV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    normalized = str(product_type).strip().upper()
    print("\n" + "=" * 70)
    print(f"Analyze Listing Feedback V2 - {normalized}")
    print("=" * 70)

    report = ListingFeedbackAnalyzerV2(db=db).analyze_category(
        normalized,
        limit=int(limit),
    )
    print(
        f"\nsubmissions_scanned={report.submissions_scanned} "
        f"issue_count={report.issue_count}"
    )
    for group in report.groups:
        print(
            f"  [{group.route}] code={group.code} count={group.count} "
            f"action={group.action}"
        )
        if group.attribute_names:
            print(f"    attributes={', '.join(group.attribute_names[:10])}")
    if report.omit_suggestions:
        print(f"omit_suggestions={report.omit_suggestions}")
    return report.as_dict()


def handle_learn_required_from_submissions(
    db: Session,
    product_type: Optional[str] = None,
):
    """Learn V2 required path_keys from Amazon 90220 missing-required feedback."""
    from src.services.feedback_learning_adapter_v2 import FeedbackLearningAdapterV2

    if not product_type:
        raise ValueError("--product-type or --category is required")

    print("\n" + "=" * 70)
    print(f"V2 Feedback Learning - Amazon 90220 missing-required (category={product_type})")
    print("=" * 70)

    adapter = FeedbackLearningAdapterV2(db=db)
    summary = adapter.learn_from_recent_submissions(category=product_type, limit=100)
    learned_paths = adapter.get_learned_required_paths(category=product_type)

    print(
        f"\nsubmissions_scanned={summary['submissions_scanned']} "
        f"paths_learned={summary['paths_learned']}"
    )
    print(f"learned required path_keys for {product_type}: {len(learned_paths)}")
    for path_key in learned_paths:
        print(f"  {path_key}")
    return {"success": True, **summary, "learned_paths": learned_paths}


def handle_report_listing_shadow_diff_v2(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
):
    """Report V1/V2 payload differences from V2 shadow audit rows."""
    from src.services.listing_payload_shadow_diff_v2 import ListingPayloadShadowDiffV2

    sku = (sku_list or [None])[0]
    limit = int(os.getenv("LISTING_V2_SHADOW_DIFF_LIMIT", "20"))

    print("\n" + "=" * 70)
    print("Listing Payload Shadow Diff V2 - READ ONLY")
    print("=" * 70)

    report = ListingPayloadShadowDiffV2(db=db).report(
        product_type=product_type,
        sku=sku,
        limit=limit,
    )
    summary = report["summary"]
    print(
        f"\nrows={report['count']} product_type={report.get('product_type') or '*'} "
        f"sku={report.get('sku') or '*'} limit={report['limit']}"
    )
    print(
        "summary: "
        f"shadow_built={summary['shadow_built']} "
        f"shadow_failed={summary['shadow_failed']} "
        f"v2_blocking={summary['v2_blocking']} "
        f"with_pending_review={summary['with_pending_review']} "
        f"with_missing_required={summary['with_missing_required']}"
    )
    for item in report["diffs"][:10]:
        print(
            f"  {item['sku']}: shadow={item['shadow_status']} "
            f"v1={item['v1_status']} "
            f"v1_attrs={item['v1_attribute_count']} "
            f"v2_attrs={item['v2_attribute_count']} "
            f"missing={len(item['v2_missing_required_paths'])} "
            f"pending={len(item['v2_pending_review_paths'])} "
            f"blocking_codes={','.join(item['v2_blocking_codes']) or '-'}"
        )
        _print_limited_paths("missing", item["v2_missing_required_paths"])
        _print_limited_paths("pending", item["v2_pending_review_paths"])
        _print_limited_paths(
            "low_confidence",
            item["v2_low_confidence_required_paths"],
        )
    if report["count"] > 10:
        print(f"  ... and {report['count'] - 10} more")
    return {"success": True, **report}


def handle_evaluate_listing_v2_regression(
    db: Session,
    product_type: Optional[str] = None,
):
    """Evaluate V2 shadow evidence for S14 cutover readiness."""
    from src.services.listing_payload_v2_regression import ListingPayloadV2Regression

    categories_text = os.getenv("LISTING_V2_REGRESSION_CATEGORIES", "")
    categories = [
        item.strip().upper()
        for item in categories_text.replace(",", "\n").splitlines()
        if item.strip()
    ]
    if product_type:
        categories = [product_type.strip().upper()]
    limit = int(os.getenv("LISTING_V2_REGRESSION_LIMIT", "20"))

    print("\n" + "=" * 70)
    print("Listing Payload Engine V2 Regression Evaluation - READ ONLY")
    print("=" * 70)

    report = ListingPayloadV2Regression(db=db).evaluate(
        product_types=categories or None,
        limit_per_category=limit,
    )
    print(
        f"\nstatus={report['status']} total={report['summary']['total']} "
        f"go={report['summary']['go']} no_go={report['summary']['no_go']} "
        f"limit_per_category={report['limit_per_category']}"
    )
    for item in report["categories"]:
        reasons = ",".join(item["reasons"]) or "-"
        blocking = ",".join(item["blocking_codes"]) or "-"
        print(
            f"  {item['product_type']}: decision={item['decision']} "
            f"mode={item['mode']} rows={item['shadow_rows']} "
            f"blocking={blocking} reasons={reasons}"
        )
    return {"success": True, **report}


def handle_evaluate_listing_v2_validation_compare(
    db: Session,
    product_type: Optional[str] = None,
    sku_list: Optional[List[str]] = None,
):
    """Evaluate V2 Amazon preview parity for representative canary SKUs."""
    from src.services.listing_payload_v2_validation_compare import (
        ListingPayloadV2ValidationCompare,
        ValidationCompareCase,
    )

    cases = None
    if product_type and sku_list:
        cases = [
            ValidationCompareCase(
                product_type=str(product_type).strip().upper(),
                sku=str(sku).strip(),
            )
            for sku in sku_list
            if str(sku).strip()
        ]
    elif product_type:
        cases = [
            ValidationCompareCase(
                product_type=str(product_type).strip().upper(),
                sku=str(item).strip(),
            )
            for item in os.getenv("LISTING_V2_COMPARE_SKUS", "").replace(",", "\n").splitlines()
            if str(item).strip()
        ]

    print("\n" + "=" * 70)
    print("Listing Payload Engine V2 Validation Compare - AMAZON VALIDATION_PREVIEW")
    print("=" * 70)

    from src.services.product_listing_api_plan_builder import ProductListingAPIPlanBuilder
    from src.services.product_listing_service import ProductListingService

    service = ProductListingService(db=db)
    service.listing_payload_engine_mode = "v2"
    plan_builder = ProductListingAPIPlanBuilder(service)
    report = ListingPayloadV2ValidationCompare(
        db=db,
        plan_builder=plan_builder,
    ).evaluate(cases=cases)
    print(
        f"\nstatus={report['status']} total={report['summary']['total']} "
        f"go={report['summary']['go']} no_go={report['summary']['no_go']}"
    )
    for item in report["cases"]:
        reasons = ",".join(item["reasons"]) or "-"
        print(
            f"  {item['product_type']}/{item['sku']}: decision={item['decision']} "
            f"preview={item['preview_status']} "
            f"amazon_issues={item['amazon_issue_count']} "
            f"v2_findings={item['v2_finding_count']} "
            f"unexplained_amazon_only={item['comparison']['unexplained_amazon_only']} "
            f"reasons={reasons}"
        )
    return {"success": True, **report}


def _print_limited_paths(label: str, paths: List[str], limit: int = 25) -> None:
    if not paths:
        return
    shown = paths[:limit]
    print(f"    {label}: {', '.join(shown)}")
    if len(paths) > limit:
        print(f"    {label}_truncated: {len(paths) - limit} more")
