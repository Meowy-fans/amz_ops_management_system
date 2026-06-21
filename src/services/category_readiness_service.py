"""Readiness checks for API-native listing categories."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.services.amazon_schema_service import AmazonSchemaService
from src.services.attribute_rule_loader import AttributeRuleLoader


@dataclass
class CategoryReadiness:
    """Preparedness summary for one Amazon product type."""

    product_type: str
    status: str
    pending_count: int = 0
    mapped_category_count: int = 0
    schema_cached: bool = False
    rule_exists: bool = False
    rule_mode: str = "dry_run"
    required_count: int = 0
    missing_required_rules: List[str] = field(default_factory=list)
    manual_review_count: int = 0
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "status": self.status,
            "pending_count": self.pending_count,
            "mapped_category_count": self.mapped_category_count,
            "schema_cached": self.schema_cached,
            "rule_exists": self.rule_exists,
            "rule_mode": self.rule_mode,
            "required_count": self.required_count,
            "missing_required_rules": self.missing_required_rules,
            "manual_review_count": self.manual_review_count,
            "warnings": self.warnings,
        }


class CategoryReadinessService:
    """Evaluates whether mapped categories are ready for API-native listing."""

    _GENERIC_BUILDER_ATTRIBUTES = {
        "item_name",
        "product_description",
        "bullet_point",
        "brand",
        "manufacturer",
        "part_number",
        "model_number",
        "item_type_keyword",
        "item_type_name",
        "target_audience_base",
        "condition_type",
        "color",
        "material",
        "style",
        "country_of_origin",
        "main_product_image_locator",
        "purchasable_offer",
        "list_price",
        "fulfillment_availability",
        "item_width",
        "item_depth",
        "item_height",
        "item_weight",
        "parentage_level",
        "variation_theme",
        "child_parent_sku_relationship",
        "supplier_declared_dg_hz_regulation",
        "externally_assigned_product_identifier",
        "supplier_declared_has_product_identifier_exemption",
    }

    def __init__(
        self,
        db: Session,
        schema_service: AmazonSchemaService | None = None,
        rule_loader: AttributeRuleLoader | None = None,
    ):
        self.db = db
        self.schema_service = schema_service or AmazonSchemaService(db)
        self.rule_loader = rule_loader or AttributeRuleLoader()

    def list_readiness(self) -> List[CategoryReadiness]:
        rows = self._category_rows()
        return [self._readiness_from_row(row) for row in rows]

    def pending_counts(self) -> List[Dict[str, Any]]:
        return [
            {
                "product_type": item.product_type,
                "pending_count": item.pending_count,
                "status": item.status,
            }
            for item in self.list_readiness()
            if item.pending_count > 0
        ]

    def _category_rows(self) -> List[Any]:
        query = text("""
            SELECT
                COALESCE(NULLIF(UPPER(scm.standard_category_name), ''), 'UNMAPPED') AS product_type,
                COUNT(DISTINCT scm.supplier_category_code) AS mapped_category_count,
                COUNT(DISTINCT CASE
                    WHEN r."seller-sku" IS NULL
                     AND psr.is_oversize IS NOT TRUE
                     AND psr.raw_data -> 'sellerInfo' ->> 'sellerType' = 'GENERAL'
                     AND pbp.sku_available IS TRUE
                    THEN m.meow_sku
                    END
                ) AS pending_count
            FROM supplier_categories_map scm
                LEFT JOIN giga_product_sync_records psr
                    ON LOWER(psr.category_code) = LOWER(scm.supplier_category_code)
                LEFT JOIN meow_sku_map m
                    ON m.vendor_sku = psr.giga_sku
                    AND m.vendor_source = 'giga'
                LEFT JOIN giga_product_base_prices pbp
                    ON pbp.giga_sku = psr.giga_sku
                LEFT JOIN amz_all_listing_report r
                    ON r."seller-sku" = m.meow_sku
            WHERE scm.supplier_platform = 'giga'
            GROUP BY 1
            ORDER BY 3 DESC, 1;
        """)
        return self.db.execute(query).fetchall()

    def _readiness_from_row(self, row: Any) -> CategoryReadiness:
        product_type = str(row[0] or "UNMAPPED").upper()
        pending_count = int(row[2] or 0)
        mapped_category_count = int(row[1] or 0)
        if product_type == "UNMAPPED":
            return CategoryReadiness(
                product_type=product_type,
                status="unmapped",
                pending_count=pending_count,
                mapped_category_count=mapped_category_count,
            )

        schema = self.schema_service.get_cached_schema(product_type)
        schema_cached = bool(schema)
        required = list((schema or {}).get("required_properties") or [])
        rules = self.rule_loader.load(product_type)
        rule_path = self.rule_loader.config_dir / f"{product_type.lower()}.yaml"
        rule_exists = rule_path.exists() or bool((rules.get("attributes") or {}))
        rule_attrs = set((rules.get("attributes") or {}).keys())
        covered = rule_attrs | self._GENERIC_BUILDER_ATTRIBUTES
        missing_required = [name for name in required if name not in covered]
        manual_review_count = sum(
            1
            for rule in (rules.get("attributes") or {}).values()
            if isinstance(rule, dict) and rule.get("manual_review")
        )
        warnings: List[str] = []
        if not schema_cached:
            warnings.append("schema_not_cached")
        if not rule_exists:
            warnings.append("rules_missing")
        if missing_required:
            warnings.append("required_rules_missing")
        if manual_review_count:
            warnings.append("manual_review_required")

        status = self._status(
            schema_cached=schema_cached,
            rule_exists=rule_exists,
            rule_mode=str(rules.get("mode") or "dry_run"),
            missing_required=missing_required,
            manual_review_count=manual_review_count,
        )
        return CategoryReadiness(
            product_type=product_type,
            status=status,
            pending_count=pending_count,
            mapped_category_count=mapped_category_count,
            schema_cached=schema_cached,
            rule_exists=rule_exists,
            rule_mode=str(rules.get("mode") or "dry_run"),
            required_count=len(required),
            missing_required_rules=missing_required,
            manual_review_count=manual_review_count,
            warnings=warnings,
        )

    @staticmethod
    def _status(
        schema_cached: bool,
        rule_exists: bool,
        rule_mode: str,
        missing_required: List[str],
        manual_review_count: int,
    ) -> str:
        if not schema_cached:
            return "mapped_no_schema"
        if not rule_exists:
            return "schema_only"
        if missing_required or manual_review_count:
            return "needs_rule_review"
        if rule_mode == AttributeRuleLoader.LIVE_ELIGIBLE_MODE:
            return "ready_live"
        return "ready_dry_run"
