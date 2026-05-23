"""Keyword Research & Allocation Service.

Phase 1: LLM-powered keyword expansion and listing-field allocation.
Phase 2+: Enrich with Brand Analytics SQP data and competitor reverse-ASIN.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.models.product import StandardProduct

logger = logging.getLogger(__name__)


# ── output models ───────────────────────────────────────────────────


@dataclass
class KeywordResearchResult:
    """Complete keyword research output for a product."""

    # Keyword categories
    core_keywords: List[str] = field(default_factory=list)
    long_tail_keywords: List[str] = field(default_factory=list)
    scenario_intent_keywords: List[str] = field(default_factory=list)
    purchase_intent_keywords: List[str] = field(default_factory=list)
    alternate_language_keywords: List[str] = field(default_factory=list)

    # Listing field allocations
    title_keywords: List[str] = field(default_factory=list)
    title_recommendation: str = ""
    bullet_keywords: Dict[str, List[str]] = field(default_factory=dict)
    description_keywords: List[str] = field(default_factory=list)
    backend_search_terms: str = ""
    generic_keyword: str = ""

    # COSMO backend attributes
    target_audience: str = ""
    intended_use: str = ""
    room_type: str = ""
    style: str = ""

    # PPC signals
    negative_keywords_for_ppc: List[str] = field(default_factory=list)
    keyword_priority_order: List[str] = field(default_factory=list)

    # Metadata
    total_keyword_count: int = 0
    expansion_raw_response: str = ""
    allocation_raw_response: str = ""
    warnings: List[str] = field(default_factory=list)


# ── service ──────────────────────────────────────────────────────────


class KeywordResearchService:
    """LLM-driven keyword research and allocation for Amazon listings.

    Pipeline:
      1. keyword_expansion  →  generate 50+ candidate keywords
      2. keyword_allocation →  assign keywords to listing fields + COSMO attrs
    """

    def __init__(self, llm_service: Any = None):
        self._llm = llm_service

    # ── public API ──────────────────────────────────────────────────

    def research(
        self,
        product: StandardProduct,
        product_type: str = "",
        category: str = "",
        competitor_asins: Optional[List[str]] = None,
    ) -> KeywordResearchResult:
        """Run the full keyword research pipeline for a single product.

        Args:
            product: Standardised product data (from Giga normalizer).
            product_type: Amazon product type (e.g. "CABINET").
            category: Internal category name.
            competitor_asins: Optional list of competitor ASINs for context.

        Returns:
            KeywordResearchResult with expansion + allocation filled.
        """
        result = KeywordResearchResult()

        # Step 1 — expand keyword universe via LLM
        expansion = self._call_expansion(product)
        if expansion is None:
            result.warnings.append("Keyword expansion LLM call returned no data")
            return result
        self._apply_expansion(result, expansion)

        # Step 2 — allocate keywords to listing fields
        keyword_pool = self._build_keyword_pool(result)
        allocation = self._call_allocation(keyword_pool, product_type, category)
        if allocation is None:
            result.warnings.append("Keyword allocation LLM call returned no data")
            return result
        self._apply_allocation(result, allocation)

        result.total_keyword_count = sum(
            len(lst) for lst in [
                result.core_keywords,
                result.long_tail_keywords,
                result.scenario_intent_keywords,
                result.purchase_intent_keywords,
                result.alternate_language_keywords,
            ]
        )
        logger.info(
            "Keyword research complete: %d keywords for %s (%s)",
            result.total_keyword_count,
            product.sku,
            product.name[:60],
        )
        return result

    def research_batch(
        self,
        products: List[StandardProduct],
        product_type: str = "",
        category: str = "",
    ) -> Dict[str, KeywordResearchResult]:
        """Run keyword research for a batch of products.

        Returns a dict keyed by product SKU.
        """
        results: Dict[str, KeywordResearchResult] = {}
        for product in products:
            try:
                results[product.sku] = self.research(product, product_type, category)
            except Exception as exc:
                logger.error("Keyword research failed for %s: %s", product.sku, exc)
                results[product.sku] = KeywordResearchResult(
                    warnings=[f"Research failed: {exc}"]
                )
        return results

    # ── step 1: expansion ───────────────────────────────────────────

    def _call_expansion(self, product: StandardProduct) -> Optional[Dict]:
        prompt_template = self._get_prompt("keyword_expansion")
        product_data = self._format_product_data(product)
        user_prompt = prompt_template.format(product_data=product_data)

        return self._call_llm(
            system="You are an Amazon keyword research specialist. Return ONLY valid JSON.",
            user=user_prompt,
        )

    def _apply_expansion(
        self, result: KeywordResearchResult, data: Dict
    ) -> None:
        result.core_keywords = _as_str_list(data.get("core_keywords", []))
        result.long_tail_keywords = _as_str_list(data.get("long_tail_keywords", []))
        result.scenario_intent_keywords = _as_str_list(data.get("scenario_intent_keywords", []))
        result.purchase_intent_keywords = _as_str_list(data.get("purchase_intent_keywords", []))
        result.alternate_language_keywords = _as_str_list(data.get("alternate_language_keywords", []))
        # Pre-allocation hints from expansion phase
        if data.get("recommended_search_terms_field"):
            result.backend_search_terms = str(data["recommended_search_terms_field"]).strip()
        if data.get("recommended_generic_keyword"):
            result.generic_keyword = str(data["recommended_generic_keyword"]).strip()
        if data.get("target_audience"):
            result.target_audience = str(data["target_audience"]).strip()
        if data.get("intended_use"):
            result.intended_use = str(data["intended_use"]).strip()
        if data.get("room_type"):
            result.room_type = str(data["room_type"]).strip()
        if data.get("style"):
            result.style = str(data["style"]).strip()

    # ── step 2: allocation ──────────────────────────────────────────

    def _build_keyword_pool(self, result: KeywordResearchResult) -> str:
        sections = []
        if result.core_keywords:
            sections.append("Core: " + ", ".join(result.core_keywords))
        if result.long_tail_keywords:
            sections.append("Long-tail: " + ", ".join(result.long_tail_keywords))
        if result.scenario_intent_keywords:
            sections.append("Scenario/Intent: " + ", ".join(result.scenario_intent_keywords))
        if result.purchase_intent_keywords:
            sections.append("Purchase Intent: " + ", ".join(result.purchase_intent_keywords))
        if result.alternate_language_keywords:
            sections.append("Alt Language/Misspellings: " + ", ".join(result.alternate_language_keywords))
        return "\n".join(sections)

    def _call_allocation(
        self, keyword_pool: str, product_type: str, category: str
    ) -> Optional[Dict]:
        prompt_template = self._get_prompt("keyword_allocation")
        user_prompt = prompt_template.format(
            keyword_pool=keyword_pool,
            product_type=product_type or "Unknown",
            category=category or "Unknown",
        )
        return self._call_llm(
            system="You are an Amazon listing optimization expert. Return ONLY valid JSON.",
            user=user_prompt,
        )

    def _apply_allocation(
        self, result: KeywordResearchResult, data: Dict
    ) -> None:
        result.title_keywords = _as_str_list(data.get("title_keywords", []))
        result.title_recommendation = str(data.get("title_recommendation", ""))
        bullet_kw = data.get("bullet_keywords", {})
        if isinstance(bullet_kw, dict):
            result.bullet_keywords = {
                k: _as_str_list(v) for k, v in bullet_kw.items()
            }
        result.description_keywords = _as_str_list(data.get("description_keywords", []))
        if data.get("backend_search_terms"):
            result.backend_search_terms = str(data["backend_search_terms"]).strip()
        if data.get("generic_keyword"):
            result.generic_keyword = str(data["generic_keyword"]).strip()
        # COSMO backend attributes (allocation may refine expansion values)
        attrs = data.get("backend_attributes", {})
        if isinstance(attrs, dict):
            if attrs.get("target_audience"):
                result.target_audience = str(attrs["target_audience"]).strip()
            if attrs.get("intended_use"):
                result.intended_use = str(attrs["intended_use"]).strip()
            if attrs.get("room_type"):
                result.room_type = str(attrs["room_type"]).strip()
            if attrs.get("style"):
                result.style = str(attrs["style"]).strip()
        result.negative_keywords_for_ppc = _as_str_list(data.get("negative_keywords_for_ppc", []))
        result.keyword_priority_order = _as_str_list(data.get("keyword_priority_order", []))

    # ── helpers ─────────────────────────────────────────────────────

    def _format_product_data(self, product: StandardProduct) -> str:
        lines = [
            f"Product Name: {product.name}",
            f"Vendor SKU: {product.vendor_sku}",
            f"Category Hint: {product.category_hint}",
        ]
        if product.attributes:
            lines.append("Attributes:")
            for k, v in list(product.attributes.items())[:20]:
                lines.append(f"  {k}: {v}")
        if product.description:
            lines.append(f"Description: {product.description[:600]}")
        if product.bullet_points:
            lines.append("Supplier Bullets:")
            for bp in product.bullet_points[:5]:
                lines.append(f"  - {bp}")
        if product.dimensions:
            d = product.dimensions
            dims = []
            if d.assembled_length:
                dims.append(f'{d.assembled_length}"L')
            if d.assembled_width:
                dims.append(f'{d.assembled_width}"W')
            if d.assembled_height:
                dims.append(f'{d.assembled_height}"H')
            if dims:
                lines.append(f"Dimensions: {' x '.join(dims)}")
            if d.assembled_weight:
                lines.append(f"Weight: {d.assembled_weight} lbs")
        return "\n".join(lines)

    def _call_llm(self, system: str, user: str) -> Optional[Dict]:
        try:
            llm = self._get_llm()
            from infrastructure.llm.types import LLMRequest

            request = LLMRequest(
                task_type="keyword_research",
                system_prompt=system,
                user_prompt=user,
                json_mode=True,
                temperature=0.3,
            )
            response = llm.generate(request)
            raw = response.content if hasattr(response, "content") else response
            return self._parse_json(raw)
        except Exception as exc:
            logger.error("LLM call failed in keyword research: %s", exc)
            return None

    def _parse_json(self, raw: Any) -> Optional[Dict]:
        if isinstance(raw, dict):
            return raw
        text = str(raw).strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        logger.warning("Could not parse LLM response as JSON: %.200s", text)
        return None

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from infrastructure.llm.factory import get_llm_service

        self._llm = get_llm_service()
        return self._llm

    def _get_prompt(self, prompt_key: str) -> str:
        from src.utils.prompt_manager import PromptManager

        return PromptManager().get_prompt(prompt_key)


# ── module helpers ───────────────────────────────────────────────────


def _as_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        # Comma-separated string
        return [v.strip() for v in value.split(",") if v.strip()]
    return []
