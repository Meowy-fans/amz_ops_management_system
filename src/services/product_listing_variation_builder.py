"""Variation row builder for Amazon listing generation."""
import logging
import uuid
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


class ProductListingVariationBuilder:
    """Builds parent/child rows and logs for variation families."""

    def __init__(
        self,
        product_data_repo,
        data_mapper,
        variation_helper,
        variation_theme_service,
        category_config,
        llm_service,
    ):
        self.product_data_repo = product_data_repo
        self.data_mapper = data_mapper
        self.variation_helper = variation_helper
        self.variation_theme_service = variation_theme_service
        self.category_config = category_config
        self.llm_service = llm_service

    def process_variations(
        self,
        families: List[List[str]],
        template_rules: Dict,
    ) -> Tuple[List[Dict[str, Any]], List[Dict]]:
        """Process all variation families."""
        rows = []
        logs = []

        for family in families:
            try:
                family_rows, family_logs = self.process_single_family(family, template_rules)
                rows.extend(family_rows)
                logs.extend(family_logs)
            except Exception as e:
                logger.error(f"  处理变体家族失败: {e}")
                continue

        logger.info(f"  成功处理 {len(families)} 个变体家族，生成 {len(rows)} 行")
        return rows, logs

    def process_single_family(
        self,
        family_skus: List[str],
        template_rules: Dict,
    ) -> Tuple[List[Dict[str, Any]], List[Dict]]:
        """Process one variation family."""
        rows = []
        logs = []

        parent_sku = f"PARENT-{uuid.uuid4().hex[:12].upper()}"

        family_full_data = []
        for sku in family_skus:
            product_data = self.product_data_repo.get_full_product_data(sku)
            if product_data:
                family_full_data.append(product_data)

        if not family_full_data:
            logger.warning("  跳过家族: 无法获取任何SKU数据")
            return rows, logs

        variation_theme, child_attributes_map = self._determine_variation_attributes(
            family_full_data,
            template_rules,
        )
        variation_mapping = template_rules.get("variation_mapping", {})

        parent_row = self._build_parent_row(
            family_full_data[0],
            template_rules,
            parent_sku,
            variation_theme,
        )
        rows.append(parent_row)

        for child_sku in family_skus:
            child_product = self.product_data_repo.get_full_product_data(child_sku)

            if not child_product:
                continue

            child_row = self._build_child_row(
                child_product,
                template_rules,
                parent_sku,
                variation_theme,
            )

            if child_sku in child_attributes_map:
                child_row.update(
                    self._to_amazon_attributes(
                        child_attributes_map[child_sku],
                        variation_mapping,
                    )
                )

            rows.append(child_row)
            logs.append({
                "meow_sku": child_sku,
                "parent_sku": parent_sku,
                "variation_attributes": child_attributes_map.get(child_sku, {}),
                "listing_batch_id": None,
                "status": "GENERATED",
                "variation_theme": variation_theme,
            })

        return rows, logs

    def _determine_variation_attributes(
        self,
        family_full_data: List[Dict[str, Any]],
        template_rules: Dict,
    ) -> Tuple[str | None, Dict]:
        variation_theme = None
        child_attributes_map = {}

        if not self.variation_theme_service:
            return variation_theme, child_attributes_map

        try:
            valid_themes = self.extract_valid_themes(template_rules)
            priority_themes = template_rules.get("priority_themes", [])

            logger.info("  调用LLM判定变体主题...")
            llm_result = self.variation_theme_service.determine_variation_theme(
                family_full_data,
                valid_themes,
                priority_themes,
            )

            variation_theme = llm_result.get("variation_theme")
            child_attributes_map = llm_result.get("child_attributes", {})

            logger.info(f"  变体主题: {variation_theme}")

        except Exception as e:
            logger.error(f"  变体主题判定失败: {e}")

        return variation_theme, child_attributes_map

    def _build_parent_row(
        self,
        first_product: Dict[str, Any],
        template_rules: Dict,
        parent_sku: str,
        variation_theme: str | None,
    ) -> Dict[str, Any]:
        parent_row = self.data_mapper.apply_mapping(
            first_product,
            template_rules,
            self.category_config,
            self.llm_service,
        )

        parent_row["SKU"] = parent_sku
        parent_row["Listing Action"] = "Create or Replace (Full Update)"
        parent_row["Relationship Type"] = "Parent"
        parent_row["Parentage Level"] = "Parent"
        parent_row["Child Relationship Type"] = "Variation"

        if variation_theme:
            parent_row["Variation Theme Name"] = variation_theme

        if "Item Name" in parent_row:
            parent_row["Item Name"] = self.variation_helper.generalize_parent_title(
                parent_row["Item Name"]
            )

        return parent_row

    def _build_child_row(
        self,
        child_product: Dict[str, Any],
        template_rules: Dict,
        parent_sku: str,
        variation_theme: str | None,
    ) -> Dict[str, Any]:
        child_row = self.data_mapper.apply_mapping(
            child_product,
            template_rules,
            self.category_config,
            self.llm_service,
        )

        child_row["Listing Action"] = "Create or Replace (Full Update)"
        child_row["Relationship Type"] = "Child"
        child_row["Parentage Level"] = "Child"
        child_row["Parent SKU"] = parent_sku
        child_row["Child Relationship Type"] = "Variation"

        if variation_theme:
            child_row["Variation Theme Name"] = variation_theme

        return child_row

    @staticmethod
    def _to_amazon_attributes(
        internal_attributes: Dict[str, Any],
        variation_mapping: Dict[str, str],
    ) -> Dict[str, Any]:
        return {
            variation_mapping.get(k, k): v
            for k, v in internal_attributes.items()
            if variation_mapping.get(k)
        }

    @staticmethod
    def extract_valid_themes(template_rules: Dict) -> List[str]:
        """Extract valid variation themes from template rules."""
        for item in template_rules.get("valid_values", []):
            if item.get("attribute") == "Variation Theme Name":
                return item.get("values", [])

        return ["Color", "Size", "Color/Size"]
