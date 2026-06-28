"""Orchestrate new category rule onboarding (S8)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.repositories.product_listing_repository import ProductListingRepository
from src.services.amazon_schema_service import AmazonSchemaService
from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.category_rule_promotion_v2 import CategoryRulePromotionV2
from src.services.rule_field_mapper_v2 import RuleFieldMapperV2
from src.services.rule_pattern_reuse_v2 import RulePatternReuseV2
from src.services.rule_review_service_v2 import RuleReviewServiceV2
from src.services.rule_skeleton_generator_v2 import RuleSkeletonGeneratorV2


@dataclass
class OnboardingStepResult:
    step: str
    status: str
    detail: str
    payload: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "status": self.status,
            "detail": self.detail,
            "payload": self.payload,
        }


@dataclass
class OnboardingReport:
    product_type: str
    status: str
    steps: List[OnboardingStepResult] = field(default_factory=list)
    yaml_path: Optional[str] = None
    acceptance_report_path: Optional[str] = None
    state_path: Optional[str] = None
    pool_skus: List[str] = field(default_factory=list)
    review_blocking_count: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "status": self.status,
            "yaml_path": self.yaml_path,
            "acceptance_report_path": self.acceptance_report_path,
            "state_path": self.state_path,
            "pool_skus": self.pool_skus,
            "review_blocking_count": self.review_blocking_count,
            "steps": [step.as_dict() for step in self.steps],
        }


class CategoryOnboardingV2:
    """Run skeleton → reuse → map → review → S7 acceptance for one category."""

    def __init__(
        self,
        db: Session,
        schema_service: AmazonSchemaService | None = None,
        rule_loader: AttributeRuleLoader | None = None,
        state_dir: Path | None = None,
        report_dir: Path | None = None,
    ):
        self.db = db
        self.schema_service = schema_service or AmazonSchemaService(db)
        self.rule_loader = rule_loader or AttributeRuleLoader()
        project_root = Path(__file__).resolve().parents[2]
        default_state = (
            project_root
            / "config"
            / "amz_listing_data_mapping"
            / "category_rule_state"
        )
        default_reports = project_root / "docs" / "test-reports"
        self.state_dir = Path(state_dir) if state_dir else default_state
        self.report_dir = Path(report_dir) if report_dir else default_reports

    def onboard(
        self,
        product_type: str,
        *,
        reference_product_type: Optional[str] = None,
        sample_sku_limit: Optional[int] = None,
        overwrite_skeleton: bool = True,
        run_s7_offline: bool = True,
        run_s7_preview: bool = False,
    ) -> OnboardingReport:
        normalized = str(product_type or "").strip().upper()
        steps: List[OnboardingStepResult] = []
        report = OnboardingReport(product_type=normalized, status="failed")

        pool_skus = self._pool_skus(normalized, sample_sku_limit)
        report.pool_skus = pool_skus
        steps.append(self._validate_prerequisites(normalized, pool_skus))

        skeleton = RuleSkeletonGeneratorV2(
            schema_service=self.schema_service,
            rule_loader=self.rule_loader,
        ).generate(
            product_type=normalized,
            write=True,
            overwrite=overwrite_skeleton,
        )
        steps.append(
            OnboardingStepResult(
                step="generate_rule_skeleton_v2",
                status="ok",
                detail=f"attributes={skeleton.attribute_count} placeholders={skeleton.placeholder_leaf_count}",
                payload=skeleton.as_dict(),
            )
        )
        report.yaml_path = str(skeleton.path)

        rules = self.rule_loader.load(normalized)
        if reference_product_type:
            reference = str(reference_product_type).strip().upper()
            reuse = RulePatternReuseV2().reuse_patterns(
                product_type=normalized,
                rules=rules,
                reference_rules=self.rule_loader.load(reference),
                reference_product_type=reference,
            )
            self._write_rules(normalized, reuse.rules, written_by=f"onboard_v2_from_{reference.lower()}")
            rules = reuse.rules
            steps.append(
                OnboardingStepResult(
                    step="reuse_rule_patterns_v2",
                    status="ok",
                    detail=f"reused={reuse.reused_leaf_count} from {reference}",
                    payload=reuse.as_dict(),
                )
            )
        else:
            steps.append(
                OnboardingStepResult(
                    step="reuse_rule_patterns_v2",
                    status="skipped",
                    detail="No --reference provided",
                )
            )

        mapper = RuleFieldMapperV2(db=self.db)
        mapped = mapper.map_rules(
            product_type=normalized,
            rules=rules,
            sample_skus=pool_skus,
        )
        yaml_path = self._write_rules(
            normalized,
            mapped.rules,
            written_by="onboard_category_v2_map",
        )
        report.yaml_path = str(yaml_path)
        steps.append(
            OnboardingStepResult(
                step="map_rule_fields_v2",
                status="ok",
                detail=f"mapped={mapped.mapped_leaf_count} sample_skus={mapped.sample_sku_count}",
                payload=mapped.as_dict(),
            )
        )

        review = RuleReviewServiceV2(rule_loader=self.rule_loader).review_category(
            normalized,
            db=self.db,
        )
        report.review_blocking_count = review.blocking_item_count
        steps.append(
            OnboardingStepResult(
                step="review_pending_rules",
                status="ok",
                detail=(
                    f"review_items={len(review.items)} "
                    f"blocking_items={review.blocking_item_count}"
                ),
                payload=review.as_dict(),
            )
        )

        acceptance_payload: Dict[str, Any] = {}
        if run_s7_offline or run_s7_preview:
            promotion = CategoryRulePromotionV2(rule_loader=self.rule_loader)
            if run_s7_offline:
                offline = promotion._offline_summary(self.db, normalized, acceptance_data=None)
                acceptance_payload["offline"] = offline
            if run_s7_preview:
                preview = promotion._preview_summary(self.db, normalized, acceptance_data=None)
                acceptance_payload["preview"] = preview
            acceptance_doc = {
                "acceptance": "S8-onboard-category-v2",
                "product_type": normalized,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "pool_skus": pool_skus,
                **acceptance_payload,
            }
            report.acceptance_report_path = str(
                self._write_acceptance_report(normalized, acceptance_doc)
            )
            steps.append(
                OnboardingStepResult(
                    step="s7_acceptance",
                    status="ok",
                    detail=f"report={report.acceptance_report_path}",
                    payload=acceptance_payload,
                )
            )
        else:
            steps.append(
                OnboardingStepResult(
                    step="s7_acceptance",
                    status="skipped",
                    detail="Offline/preview not requested",
                )
            )

        report.steps = steps
        report.status = "completed"
        report.state_path = str(self._write_state(normalized, report, acceptance_payload))
        return report

    def _validate_prerequisites(
        self,
        product_type: str,
        pool_skus: List[str],
    ) -> OnboardingStepResult:
        cached = self.schema_service.get_cached_schema(product_type)
        if cached is None:
            raise ValueError(
                f"No cached schema for {product_type}; fetch schema before onboarding"
            )
        if not pool_skus:
            raise ValueError(f"No pending pool SKUs found for category {product_type}")
        return OnboardingStepResult(
            step="validate_prerequisites",
            status="ok",
            detail=f"schema_cached=true pool_skus={len(pool_skus)}",
            payload={"pool_skus": pool_skus},
        )

    def _pool_skus(self, product_type: str, limit: Optional[int]) -> List[str]:
        repo = ProductListingRepository(self.db)
        all_skus = repo.get_pending_listing_skus()
        mapping = dict(repo.get_sku_to_category_mapping(all_skus))
        skus = [sku for sku in all_skus if mapping.get(sku) == product_type]
        if limit is not None and int(limit) > 0:
            return skus[: int(limit)]
        return skus

    def _write_rules(self, product_type: str, rules: Dict[str, Any], *, written_by: str) -> Path:
        from src.services.rule_yaml_write_guard import write_rule_yaml

        target_path = self.rule_loader.config_dir / f"{product_type.lower()}.yaml"
        merged = dict(rules)
        merged.setdefault("mode", AttributeRuleLoader.DEFAULT_MODE)
        return write_rule_yaml(
            target_path,
            merged,
            product_type=product_type,
            written_by=written_by,
        )

    def _write_acceptance_report(self, product_type: str, payload: Dict[str, Any]) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = self.report_dir / f"{stamp}-{product_type.lower()}-onboard-acceptance.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _write_state(
        self,
        product_type: str,
        report: OnboardingReport,
        acceptance_payload: Dict[str, Any],
    ) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_dir / f"{product_type.lower()}.json"
        offline = acceptance_payload.get("offline") or {}
        preview = acceptance_payload.get("preview") or {}
        state = {
            "product_type": product_type,
            "last_onboard_at": datetime.now(timezone.utc).isoformat(),
            "status": report.status,
            "yaml_path": report.yaml_path,
            "acceptance_report_path": report.acceptance_report_path,
            "pool_skus": report.pool_skus,
            "review_blocking_count": report.review_blocking_count,
            "offline_zero_missing": offline.get("zero_missing"),
            "offline_sku_count": offline.get("sku_count"),
            "preview_passed": preview.get("validation_preview_passed"),
        }
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
