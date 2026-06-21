"""Automatically infer Amazon product types for unmapped supplier categories."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class AutoCategoryMappingResult:
    category_code: str
    category_name: str = ""
    status: str = "needs_review"
    selected_product_type: Optional[str] = None
    confidence: float = 0.0
    vote_counts: Dict[str, int] = field(default_factory=dict)
    fallback_candidates: List[str] = field(default_factory=list)
    samples: List[Dict[str, Any]] = field(default_factory=list)
    keywords_by_sample: List[List[str]] = field(default_factory=list)
    asins: List[str] = field(default_factory=list)
    summaries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    dry_run: bool = True
    written: bool = False
    schema_cached: bool = False


class AutoCategoryMapper:
    """Infers product type mappings from Amazon Catalog search results."""

    _STOPWORDS = {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "by",
        "set",
        "pack",
        "new",
    }

    def __init__(
        self,
        db: Session,
        repository: Any = None,
        catalog_client: Any = None,
        product_type_client: Any = None,
        schema_service: Any = None,
    ):
        self.db = db
        if repository is None:
            from src.repositories.category_repository import CategoryRepository

            repository = CategoryRepository(db)
        if catalog_client is None:
            from infrastructure.amazon.catalog_client import AmazonCatalogClient

            catalog_client = AmazonCatalogClient()
        if product_type_client is None:
            from infrastructure.amazon.product_type_client import AmazonProductTypeClient

            product_type_client = AmazonProductTypeClient()
        if schema_service is None:
            from src.services.amazon_schema_service import AmazonSchemaService

            schema_service = AmazonSchemaService(db)
        self.repository = repository
        self.catalog_client = catalog_client
        self.product_type_client = product_type_client
        self.schema_service = schema_service

    def discover_category(
        self,
        category_code: str,
        dry_run: bool = True,
        sample_limit: int = 5,
        asin_limit_per_sample: int = 5,
        min_product_type_votes: int = 3,
        min_winner_votes: int = 2,
        min_winner_share: float = 0.6,
    ) -> AutoCategoryMappingResult:
        """Infer and optionally persist one Giga category mapping."""
        samples = self.repository.get_category_sample_products(
            category_code,
            limit=sample_limit,
        )
        category_name = self._category_name(category_code, samples)
        result = AutoCategoryMappingResult(
            category_code=str(category_code),
            category_name=category_name,
            samples=samples,
            dry_run=dry_run,
        )
        if not samples:
            result.status = "no_samples"
            result.warnings.append("No listing-eligible sample products found")
            result.fallback_candidates = self._fallback_candidates(category_name)
            return result

        asins: List[str] = []
        for sample in samples:
            keywords = self._extract_keywords(
                str(sample.get("name") or ""),
                str(sample.get("category_name") or category_name),
            )
            result.keywords_by_sample.append(keywords)
            asins.extend(
                self._search_asins(keywords, limit=asin_limit_per_sample)
            )
        result.asins = self._dedupe(asins)
        if result.asins:
            result.summaries = self.catalog_client.batch_get_summaries(result.asins)

        votes = Counter(
            self._normalize_product_type(summary.get("product_type"))
            for summary in result.summaries.values()
            if self._normalize_product_type(summary.get("product_type"))
        )
        result.vote_counts = dict(votes)
        selected, confidence = self._vote_winner(
            votes,
            min_product_type_votes=min_product_type_votes,
            min_winner_votes=min_winner_votes,
            min_winner_share=min_winner_share,
        )
        result.selected_product_type = selected
        result.confidence = confidence
        result.fallback_candidates = self._fallback_candidates(
            self._fallback_keywords(samples, category_name)
        )

        if not selected:
            result.status = "needs_review"
            if votes:
                result.warnings.append("Catalog vote confidence below threshold")
            else:
                result.warnings.append(
                    "Catalog search returned no usable product types"
                )
            return result

        if self._fallback_conflicts(selected, result.fallback_candidates):
            result.status = "needs_review"
            result.warnings.append(
                "Catalog winner conflicts with Product Type Definitions fallback"
            )
            return result

        if dry_run:
            result.status = "dry_run_selected"
            return result

        if hasattr(self.repository, "update_category_mapping_if_unmapped"):
            written_count = self.repository.update_category_mapping_if_unmapped(
                supplier_platform="giga",
                supplier_category_code=str(category_code),
                standard_category_name=selected,
            )
        else:
            written_count = self.repository.batch_update_category_mappings(
                [
                    {
                        "supplier_platform": "giga",
                        "supplier_category_code": str(category_code),
                        "standard_category_name": selected,
                    }
                ]
            )
        result.written = written_count > 0
        result.status = "mapped" if result.written else "not_updated"
        self._cache_schema(selected, result)
        return result

    def discover_unmapped(
        self,
        dry_run: bool = True,
        limit: Optional[int] = None,
    ) -> List[AutoCategoryMappingResult]:
        categories = self.repository.get_unmapped_categories_with_product_count(
            platform="giga"
        )
        if limit is not None:
            categories = categories[: int(limit)]
        return [
            self.discover_category(
                str(category.get("category_code")),
                dry_run=dry_run,
            )
            for category in categories
            if category.get("category_code")
        ]

    def _search_asins(self, keywords: List[str], limit: int) -> List[str]:
        if not keywords:
            return []
        try:
            response = self.catalog_client.search_catalog_items(keywords=keywords)
        except Exception as exc:
            logger.warning("Catalog search failed for %s: %s", keywords, exc)
            return []
        body = response.get("body") if isinstance(response, dict) else response
        items = (body or {}).get("items") or []
        return [
            str(item.get("asin"))
            for item in items[:limit]
            if isinstance(item, dict) and item.get("asin")
        ]

    def _fallback_candidates(self, keywords: str) -> List[str]:
        text = str(keywords or "").strip()
        if not text:
            return []
        try:
            return [
                self._normalize_product_type(candidate)
                for candidate in self.product_type_client.search_product_types(text)
                if self._normalize_product_type(candidate)
            ]
        except Exception as exc:
            logger.warning("Product type fallback search failed for %s: %s", text, exc)
            return []

    def _cache_schema(
        self,
        product_type: str,
        result: AutoCategoryMappingResult,
    ) -> None:
        try:
            self.schema_service.fetch_and_cache(product_type)
            result.schema_cached = True
        except Exception as exc:
            result.warnings.append(f"Schema cache failed: {exc}")
            logger.warning("Schema cache failed for %s: %s", product_type, exc)

    @classmethod
    def _extract_keywords(cls, name: str, category_name: str = "") -> List[str]:
        text = f"{category_name} {name}".lower()
        tokens = re.findall(r"[a-z][a-z0-9]+", text)
        cleaned: List[str] = []
        for token in tokens:
            if token in cls._STOPWORDS:
                continue
            if token.isdigit():
                continue
            if token not in cleaned:
                cleaned.append(token)
            if len(cleaned) >= 6:
                break
        return cleaned

    @staticmethod
    def _dedupe(values: List[str]) -> List[str]:
        seen = set()
        result = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    @staticmethod
    def _normalize_product_type(value: Any) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _category_name(category_code: str, samples: List[Dict[str, Any]]) -> str:
        for sample in samples:
            if sample.get("category_name"):
                return str(sample["category_name"])
        return str(category_code)

    @staticmethod
    def _fallback_keywords(samples: List[Dict[str, Any]], category_name: str) -> str:
        if samples:
            return " ".join(
                str(samples[0].get("name") or category_name).split()[:6]
            )
        return category_name

    @staticmethod
    def _vote_winner(
        votes: Counter,
        min_product_type_votes: int,
        min_winner_votes: int,
        min_winner_share: float,
    ) -> tuple[Optional[str], float]:
        total = sum(votes.values())
        if total < min_product_type_votes:
            return None, 0.0
        product_type, count = votes.most_common(1)[0]
        share = count / total if total else 0.0
        if count < min_winner_votes or share < min_winner_share:
            return None, share
        return product_type, share

    @staticmethod
    def _fallback_conflicts(product_type: str, fallback_candidates: List[str]) -> bool:
        if not fallback_candidates:
            return False
        return product_type not in fallback_candidates[:5]
