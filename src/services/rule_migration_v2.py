"""Legacy YAML → V2 expanded skeleton migration with golden regression."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.rule_skeleton_generator_v2 import RuleSkeletonGeneratorV2


ROOT_LEGACY_OVERRIDE_KEYS = (
    "mode",
    "version",
    "presets",
    "dimension_strategy",
    "additional_dimension_measures",
    "coverage_ignore_required",
    "coverage_ignore_when_parent",
    "post_processors",
    "remove_attributes",
    "generated_from",
)


@dataclass(frozen=True)
class GoldenRegressionCase:
    product_type: str
    sku: str


@dataclass
class RuleMigrationResult:
    product_type: str
    legacy_attribute_count: int
    skeleton_attribute_count: int
    migrated_attribute_count: int
    added_attribute_names: List[str] = field(default_factory=list)
    preserved_attribute_names: List[str] = field(default_factory=list)
    mode: str = ""
    rules: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "legacy_attribute_count": self.legacy_attribute_count,
            "skeleton_attribute_count": self.skeleton_attribute_count,
            "migrated_attribute_count": self.migrated_attribute_count,
            "added_attribute_names": self.added_attribute_names,
            "preserved_attribute_names": self.preserved_attribute_names,
            "mode": self.mode,
            "warnings": self.warnings,
        }


@dataclass
class GoldenRegressionCaseResult:
    product_type: str
    sku: str
    passed: bool
    baseline_attribute_count: int
    migrated_attribute_count: int
    differences: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "sku": self.sku,
            "passed": self.passed,
            "baseline_attribute_count": self.baseline_attribute_count,
            "migrated_attribute_count": self.migrated_attribute_count,
            "differences": self.differences,
        }


@dataclass
class GoldenRegressionReport:
    status: str
    passed: int
    failed: int
    total: int
    cases: List[GoldenRegressionCaseResult] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "cases": [case.as_dict() for case in self.cases],
        }


class RuleMigrationV2:
    """Merge schema skeletons with legacy YAML while preserving full attribute blocks."""

    DEFAULT_GOLDEN_CASES = (
        GoldenRegressionCase("SOFA", "meow25110865jrz"),
        GoldenRegressionCase("CABINET", "meow251115FC0ie"),
        GoldenRegressionCase("HOME_MIRROR", "meow251108CqW5i"),
        GoldenRegressionCase("OTTOMAN", "meow2511088jSUW"),
    )

    def __init__(
        self,
        schema_service: Any = None,
        rule_loader: AttributeRuleLoader | None = None,
    ):
        self.schema_service = schema_service
        self.rule_loader = rule_loader or AttributeRuleLoader()

    def migrate_rules(
        self,
        product_type: str,
        legacy_rules: Dict[str, Any],
        skeleton_rules: Dict[str, Any] | None = None,
    ) -> RuleMigrationResult:
        normalized = str(product_type or "").strip().upper()
        legacy = copy.deepcopy(legacy_rules or {})
        skeleton = copy.deepcopy(
            skeleton_rules
            or RuleSkeletonGeneratorV2(
                schema_service=self.schema_service,
                rule_loader=self.rule_loader,
            ).generate(normalized, write=False).rules
        )

        legacy_attrs = dict(legacy.get("attributes") or {})
        skeleton_attrs = dict(skeleton.get("attributes") or {})
        warnings: List[str] = []
        mode = str(legacy.get("mode") or skeleton.get("mode") or AttributeRuleLoader.DEFAULT_MODE)

        merged = copy.deepcopy(skeleton)
        merged["product_type"] = normalized
        merged["mode"] = mode

        for key in ROOT_LEGACY_OVERRIDE_KEYS:
            if key in legacy:
                merged[key] = copy.deepcopy(legacy[key])

        if mode == AttributeRuleLoader.LIVE_ELIGIBLE_MODE:
            merged["attributes"] = copy.deepcopy(legacy_attrs)
            if skeleton_attrs.keys() - legacy_attrs.keys():
                warnings.append(
                    "live_eligible migration preserved legacy attributes only; "
                    "skeleton-only attributes were not added"
                )
            added_names: List[str] = []
            preserved_names = sorted(legacy_attrs.keys())
        else:
            merged_attrs = copy.deepcopy(skeleton_attrs)
            for name, block in legacy_attrs.items():
                skeleton_block = skeleton_attrs.get(name)
                if skeleton_block and self._should_prefer_skeleton_structure(block, skeleton_block):
                    merged_attrs[name] = self._merge_structural_attribute(block, skeleton_block)
                    warnings.append(f"Replaced flat placeholder block with skeleton children: {name}")
                else:
                    merged_attrs[name] = copy.deepcopy(block)
            merged["attributes"] = merged_attrs
            added_names = sorted(set(merged_attrs) - set(legacy_attrs))
            preserved_names = sorted(legacy_attrs.keys())

        if not merged.get("dimension_strategy") and skeleton.get("dimension_strategy"):
            merged["dimension_strategy"] = skeleton["dimension_strategy"]
        if not merged.get("coverage_ignore_required"):
            merged["coverage_ignore_required"] = copy.deepcopy(
                skeleton.get("coverage_ignore_required")
                or ["merchant_shipping_group", "merchant_suggested_asin"]
            )

        merged["generated_from"] = "rule_migration_v2"
        return RuleMigrationResult(
            product_type=normalized,
            legacy_attribute_count=len(legacy_attrs),
            skeleton_attribute_count=len(skeleton_attrs),
            migrated_attribute_count=len(merged.get("attributes") or {}),
            added_attribute_names=added_names,
            preserved_attribute_names=preserved_names,
            mode=mode,
            rules=merged,
            warnings=warnings,
        )

    @classmethod
    def _should_prefer_skeleton_structure(
        cls,
        legacy_block: Dict[str, Any],
        skeleton_block: Dict[str, Any],
    ) -> bool:
        if legacy_block.get("children"):
            return False
        if not skeleton_block.get("children"):
            return False
        return cls._legacy_block_is_flat_placeholder(legacy_block)

    @classmethod
    def _legacy_block_is_flat_placeholder(cls, block: Dict[str, Any]) -> bool:
        sources = block.get("sources") or []
        if not sources:
            return bool(block.get("children") is None)
        return all(
            "TODO:" in str(source.get("evidence") or "")
            or (
                source.get("default") is None
                and "path" not in source
                and "llm" not in source
            )
            for source in sources
        )

    @classmethod
    def _merge_structural_attribute(
        cls,
        legacy_block: Dict[str, Any],
        skeleton_block: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = copy.deepcopy(skeleton_block)
        for key in ("level", "manual_review", "transform", "shape"):
            if key in legacy_block:
                merged[key] = legacy_block[key]
        if not skeleton_block.get("children") and legacy_block.get("sources"):
            merged["sources"] = copy.deepcopy(legacy_block["sources"])
        return merged

    def migrate_product_type(self, product_type: str) -> RuleMigrationResult:
        normalized = str(product_type or "").strip().upper()
        legacy_rules = self.rule_loader.load(normalized)
        return self.migrate_rules(normalized, legacy_rules)

    def evaluate_golden_regression(
        self,
        db: Any,
        cases: Iterable[GoldenRegressionCase] | None = None,
    ) -> GoldenRegressionReport:
        from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
        from src.services.review_adapter_v2 import ReviewAdapterV2

        engine = ListingPayloadEngineV2(db=db)
        review = ReviewAdapterV2(db=db)
        evaluated: List[GoldenRegressionCaseResult] = []

        for case in cases or self.DEFAULT_GOLDEN_CASES:
            product_type = str(case.product_type or "").strip().upper()
            sku = str(case.sku or "").strip()
            baseline_rules = self.rule_loader.load(product_type)
            migrated_rules = self.migrate_rules(product_type, baseline_rules).rules
            overrides = review.build_overrides_from_decisions(
                category=product_type,
                sku=sku,
            ) or None

            baseline_plan = engine.build_read_only_plan(
                product_type=product_type,
                sku=sku,
                rules=baseline_rules,
                overrides=overrides,
            )
            migrated_plan = engine.build_read_only_plan(
                product_type=product_type,
                sku=sku,
                rules=migrated_rules,
                overrides=overrides,
            )
            differences = self._attribute_differences(
                baseline_plan.attributes,
                migrated_plan.attributes,
            )
            evaluated.append(
                GoldenRegressionCaseResult(
                    product_type=product_type,
                    sku=sku,
                    passed=not differences,
                    baseline_attribute_count=len(baseline_plan.attributes or {}),
                    migrated_attribute_count=len(migrated_plan.attributes or {}),
                    differences=differences,
                )
            )

        failed = sum(1 for item in evaluated if not item.passed)
        passed = len(evaluated) - failed
        return GoldenRegressionReport(
            status="go" if failed == 0 else "no_go",
            passed=passed,
            failed=failed,
            total=len(evaluated),
            cases=evaluated,
        )

    @staticmethod
    def _attribute_differences(
        baseline: Dict[str, Any],
        migrated: Dict[str, Any],
    ) -> List[str]:
        if baseline == migrated:
            return []
        differences: List[str] = []
        baseline_keys = set(baseline or {})
        migrated_keys = set(migrated or {})
        for key in sorted(baseline_keys - migrated_keys):
            differences.append(f"missing_attribute:{key}")
        for key in sorted(migrated_keys - baseline_keys):
            differences.append(f"added_attribute:{key}")
        for key in sorted(baseline_keys & migrated_keys):
            if baseline[key] != migrated[key]:
                differences.append(f"changed_attribute:{key}")
        return differences

    def write_migrated_rules(
        self,
        result: RuleMigrationResult,
        *,
        backup: bool = True,
    ) -> Tuple[Path, Optional[Path]]:
        import yaml

        target_path = self.rule_loader.config_dir / f"{result.product_type.lower()}.yaml"
        backup_path = None
        if backup and target_path.exists():
            backup_path = target_path.with_suffix(target_path.suffix + ".pre_s6_migration")
            backup_path.write_text(target_path.read_text(encoding="utf-8"), encoding="utf-8")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            yaml.safe_dump(result.rules, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        return target_path, backup_path

    @staticmethod
    def summarize_attribute_diff(
        baseline: Dict[str, Any],
        migrated: Dict[str, Any],
        attribute_name: str,
    ) -> str:
        return json.dumps(
            {
                "baseline": baseline.get(attribute_name),
                "migrated": migrated.get(attribute_name),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
