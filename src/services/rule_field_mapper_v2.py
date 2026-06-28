"""Map Giga sample data fields onto V2 YAML rule leaf source chains."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any, Dict, List, Optional

from src.services.amazon_listing_draft_builder import AmazonListingDraftBuilder
from src.services.attribute_rule_generator import AttributeRuleGenerator
from src.services.listing_payload_engine_v2 import ListingPayloadEngineV2
from src.services.rule_tree_utils_v2 import (
    has_placeholder_source,
    iter_leaf_rules,
    replace_placeholder_sources,
)


@dataclass
class RuleFieldMappingResult:
    product_type: str
    sample_sku_count: int
    leaf_count: int
    mapped_leaf_count: int
    mapped_paths: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rules: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "product_type": self.product_type,
            "sample_sku_count": self.sample_sku_count,
            "leaf_count": self.leaf_count,
            "mapped_leaf_count": self.mapped_leaf_count,
            "mapped_paths": self.mapped_paths,
            "warnings": self.warnings,
        }


class RuleFieldMapperV2:
    """Fill leaf path sources using bootstrap tables and Giga field heuristics."""

    DIMENSION_VALUE_PATHS: Dict[str, List[str]] = {
        "seat.depth.value": [
            "product.dimensions.assembled_width",
            "product.dimensions.width",
        ],
        "seat.height.value": [
            "product.dimensions.assembled_height",
            "product.dimensions.height",
        ],
        "item_depth_width_height.depth.value": [
            "product.dimensions.assembled_width",
            "product.dimensions.width",
        ],
        "item_depth_width_height.width.value": [
            "product.dimensions.assembled_length",
            "product.dimensions.length",
        ],
        "item_depth_width_height.height.value": [
            "product.dimensions.assembled_height",
            "product.dimensions.height",
        ],
        "item_length_width_height.length.value": [
            "product.dimensions.assembled_length",
            "product.dimensions.length",
        ],
        "item_length_width_height.width.value": [
            "product.dimensions.assembled_width",
            "product.dimensions.width",
        ],
        "item_length_width_height.height.value": [
            "product.dimensions.assembled_height",
            "product.dimensions.height",
        ],
        "item_package_dimensions.length.value": [
            "product.dimensions.length",
        ],
        "item_package_dimensions.width.value": [
            "product.dimensions.width",
        ],
        "item_package_dimensions.height.value": [
            "product.dimensions.height",
        ],
        "item_package_weight.value": [
            "product.dimensions.weight",
            "product.dimensions.assembled_weight",
        ],
        "maximum_weight_recommendation.value": [
            "product.dimensions.assembled_weight",
            "product.dimensions.weight",
        ],
    }
    DIMENSION_UNIT_PATHS: Dict[str, str] = {
        "seat.depth.unit": "inches",
        "seat.height.unit": "inches",
        "item_depth_width_height.depth.unit": "inches",
        "item_depth_width_height.width.unit": "inches",
        "item_depth_width_height.height.unit": "inches",
        "item_length_width_height.length.unit": "inches",
        "item_length_width_height.width.unit": "inches",
        "item_length_width_height.height.unit": "inches",
        "item_package_dimensions.length.unit": "inches",
        "item_package_dimensions.width.unit": "inches",
        "item_package_dimensions.height.unit": "inches",
        "item_package_weight.unit": "pounds",
        "maximum_weight_recommendation.unit": "pounds",
    }

    def __init__(
        self,
        db: Any = None,
        product_repo: Any = None,
        draft_builder: AmazonListingDraftBuilder | None = None,
    ):
        self.db = db
        self.product_repo = product_repo
        self.draft_builder = draft_builder or AmazonListingDraftBuilder()

    def map_rules(
        self,
        product_type: str,
        rules: Dict[str, Any],
        sample_skus: List[str] | None = None,
        min_hit_rate: float = 0.5,
    ) -> RuleFieldMappingResult:
        normalized = str(product_type or "").strip().upper()
        attributes = dict((rules.get("attributes") or {}))
        skus = list(sample_skus or [])
        warnings: List[str] = []
        if not skus and self.product_repo is not None:
            skus = self._default_sample_skus(normalized, limit=5)
        if not skus:
            warnings.append("No sample SKUs available; only bootstrap paths applied")

        attribute_keys = self._collect_attribute_keys(skus, normalized)
        mapped_paths: List[str] = []
        leaf_count = 0
        product_repo = self._get_product_repo()

        for path_key, rule in iter_leaf_rules(attributes):
            if not has_placeholder_source(rule):
                continue
            leaf_count += 1
            proposals = self._propose_sources(
                path_key,
                attribute_keys,
                skus,
                normalized,
                min_hit_rate,
            )
            if not proposals:
                continue
            replace_placeholder_sources(rule, proposals)
            mapped_paths.append(path_key)

        merged = dict(rules)
        merged["attributes"] = attributes
        return RuleFieldMappingResult(
            product_type=normalized,
            sample_sku_count=len(skus),
            leaf_count=leaf_count,
            mapped_leaf_count=len(mapped_paths),
            mapped_paths=mapped_paths,
            warnings=warnings,
            rules=merged,
        )

    def _get_product_repo(self):
        if self.product_repo is not None:
            return self.product_repo
        if self.db is None:
            return None
        from src.repositories.product_data_repository import ProductDataRepository

        self.product_repo = ProductDataRepository(self.db)
        return self.product_repo

    def _default_sample_skus(self, product_type: str, limit: int) -> List[str]:
        if self.db is None:
            return []
        from src.repositories.product_listing_repository import ProductListingRepository

        repo = ProductListingRepository(self.db)
        all_skus = repo.get_pending_listing_skus()
        mapping = dict(repo.get_sku_to_category_mapping(all_skus))
        return [sku for sku in all_skus if mapping.get(sku) == product_type][:limit]

    def _collect_attribute_keys(
        self,
        skus: List[str],
        product_type: str,
    ) -> List[str]:
        keys: List[str] = []
        product_repo = self._get_product_repo()
        if product_repo is None:
            return keys
        engine = ListingPayloadEngineV2(db=self.db, product_repo=product_repo)
        for sku in skus:
            product_data = product_repo.get_full_product_data(sku)
            if not product_data:
                continue
            draft = self.draft_builder.build(product_data, product_type=product_type)
            keys.extend(draft.standard_product.attributes.keys())
            candidate_attrs = engine._candidate_attributes_from_draft(draft, {})
            keys.extend(candidate_attrs.keys())
        return sorted({str(key) for key in keys if str(key).strip()})

    def _propose_sources(
        self,
        path_key: str,
        attribute_keys: List[str],
        skus: List[str],
        product_type: str,
        min_hit_rate: float,
    ) -> List[Dict[str, Any]]:
        if path_key in self.DIMENSION_UNIT_PATHS:
            return [
                {
                    "default": self.DIMENSION_UNIT_PATHS[path_key],
                    "confidence": "high",
                    "evidence": f"Bootstrap unit for {path_key}",
                }
            ]
        if path_key in self.DIMENSION_VALUE_PATHS:
            return [
                {
                    "path": path,
                    "confidence": "high" if idx == 0 else "medium",
                    "evidence": f"Bootstrap dimension mapping for {path_key}",
                }
                for idx, path in enumerate(self.DIMENSION_VALUE_PATHS[path_key])
            ]

        bootstrap = self._bootstrap_paths(path_key)
        if bootstrap:
            return [
                {
                    "path": path,
                    "confidence": "high",
                    "evidence": f"Bootstrap mapping for {path_key}",
                }
                for path in bootstrap
            ]

        giga_field = self._match_giga_field(path_key, attribute_keys)
        if not giga_field:
            return []
        hit_rate = self._field_presence_rate(giga_field, skus, product_type)
        if hit_rate < min_hit_rate and skus:
            return []
        return [
            {
                "path": f"product.attributes.{giga_field}",
                "confidence": "high" if hit_rate >= 0.8 else "medium",
                "evidence": f"Heuristic Giga field match for {path_key}",
            }
        ]

    @classmethod
    def _bootstrap_paths(cls, path_key: str) -> List[str]:
        leaf = path_key.split(".")[-1]
        root = path_key.split(".")[0]
        candidates = AttributeRuleGenerator._DEFAULT_SOURCE_CANDIDATES.get(root) or []
        paths: List[str] = []
        for candidate in candidates:
            if isinstance(candidate, str):
                paths.append(candidate)
            elif isinstance(candidate, dict) and candidate.get("path"):
                paths.append(str(candidate["path"]))
        if paths:
            return paths

        if leaf in {"value", "unit"}:
            parent = ".".join(path_key.split(".")[:-1])
            parent_root = parent.split(".")[0]
            parent_candidates = AttributeRuleGenerator._DEFAULT_SOURCE_CANDIDATES.get(
                parent_root
            ) or []
            for candidate in parent_candidates:
                if isinstance(candidate, dict) and candidate.get("path"):
                    paths.append(str(candidate["path"]))
        return paths

    @staticmethod
    def _normalize_token(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())

    def _match_giga_field(self, path_key: str, attribute_keys: List[str]) -> str | None:
        leaf = path_key.split(".")[-1]
        if leaf in {"value", "unit"}:
            leaf = path_key.split(".")[-2] if "." in path_key else leaf
        target = self._normalize_token(leaf)
        if not target or not attribute_keys:
            return None

        normalized = {
            self._normalize_token(key): key
            for key in attribute_keys
        }
        if target in normalized:
            return normalized[target]

        spaced = leaf.replace("_", " ").title()
        if spaced in attribute_keys:
            return spaced

        aliases = {
            "materialtype": ["main material", "material", "fabric type"],
            "fillmaterial": ["fill material", "filler"],
            "itemshape": ["item shape"],
            "includedcomponents": ["included components"],
            "framematerial": ["main material", "material", "frame material"],
        }
        for alias in aliases.get(target, []):
            norm_alias = self._normalize_token(alias)
            if norm_alias in normalized:
                return normalized[norm_alias]
            for key in attribute_keys:
                if self._normalize_token(key) == norm_alias:
                    return key

        close = get_close_matches(
            target,
            list(normalized.keys()),
            n=1,
            cutoff=0.82,
        )
        if close:
            return normalized[close[0]]
        return None

    def _field_presence_rate(
        self,
        field_name: str,
        skus: List[str],
        product_type: str,
    ) -> float:
        if not skus:
            return 0.0
        product_repo = self._get_product_repo()
        if product_repo is None:
            return 0.0
        hits = 0
        for sku in skus:
            product_data = product_repo.get_full_product_data(sku)
            if not product_data:
                continue
            draft = self.draft_builder.build(product_data, product_type=product_type)
            if field_name in draft.standard_product.attributes:
                hits += 1
        return hits / len(skus)
