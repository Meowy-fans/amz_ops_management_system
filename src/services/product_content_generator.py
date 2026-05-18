"""Unified product content generator — category-aware LLM enrichment.

Replaces the dual-pipeline pattern (ProductDetailGenerationService +
DataMappingLLM) with a single LLM call that produces title, bullets,
description, search terms, and enriched attributes.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.models.product import StandardProduct
from src.services.content_validator import validate_content

logger = logging.getLogger(__name__)


# ── output model ──────────────────────────────────────────────────


@dataclass
class EnrichedProductContent:
    """Output of the content generation pipeline."""

    title: str = ""
    bullet_1: str = ""
    bullet_2: str = ""
    bullet_3: str = ""
    bullet_4: str = ""
    bullet_5: str = ""
    description: str = ""
    search_terms: str = ""
    generic_keyword: str = ""
    enriched_attributes: Dict[str, Any] = field(default_factory=dict)
    validation_warnings: List[str] = field(default_factory=list)
    raw_llm_response: str = ""

# ── buyer personas ────────────────────────────────────────────────

_BUYER_PERSONAS = {
    "CABINET": "Homeowners renovating bathrooms, ages 30-55, value-conscious but quality-focused, DIY-capable or working with contractors",
    "HOME_MIRROR": "Home decor enthusiasts, ages 25-50, design-conscious, looking for statement pieces that combine function and aesthetics",
    "default": "Online shoppers looking for quality home products, value durability and clear product information",
}


# ── generator ─────────────────────────────────────────────────────


class ProductContentGenerator:
    """Generates Amazon-optimized product content using LLM.

    Takes a StandardProduct and product type context, produces
    EnrichedProductContent with title, bullets, description,
    search terms, and enriched attributes.
    """

    def __init__(self, llm_service: Any = None):
        self._llm = llm_service

    def generate(
        self,
        product: StandardProduct,
        product_type: str,
        schema_service: Any = None,
        extra_context: Optional[Dict[str, str]] = None,
    ) -> EnrichedProductContent:
        """Generate enriched content for a single product.

        Args:
            product: Standardized product data.
            product_type: Amazon product type (e.g. "CABINET").
            schema_service: Optional AmazonSchemaService for requirements.
            extra_context: Optional dict with keys like buyer_persona,
                           category_description, etc.
        """
        # Build prompt parameters
        category_context = self._build_category_context(
            product_type, schema_service, extra_context
        )
        required_attrs = self._build_required_attrs(product_type, schema_service)
        valid_hints = self._build_valid_hints(product_type, schema_service)
        persona = self._build_persona(product_type, extra_context)
        product_data = self._format_product_data(product)

        # Get prompt template
        prompt_template = self._get_prompt()
        user_prompt = prompt_template.format(
            category_context=category_context,
            required_attributes=required_attrs,
            valid_values_hints=valid_hints,
            buyer_persona=persona,
            product_data=product_data,
        )

        system_prompt = (
            "You are an expert Amazon listing copywriter. "
            "Return ONLY valid JSON matching the specified format. "
            "No explanations, no markdown fences, just JSON."
        )

        # Call LLM
        try:
            llm = self._get_llm()
            request = self._make_llm_request(system_prompt, user_prompt)
            response = llm.generate(request)
            raw = response.content if hasattr(response, "content") else response
            if isinstance(raw, dict):
                raw_text = json.dumps(raw)
            else:
                raw_text = str(raw)
        except Exception as e:
            logger.error("LLM generation failed: %s", e)
            return EnrichedProductContent(
                validation_warnings=[f"LLM call failed: {e}"]
            )

        # Parse and validate
        return self._parse_and_validate(raw_text)

    # ── prompt building ───────────────────────────────────────────

    def _build_category_context(
        self, product_type: str, schema_service: Any, extra: Optional[Dict]
    ) -> str:
        parts = [f"Amazon Product Type: {product_type}"]
        if extra and extra.get("category_description"):
            parts.append(f"Category: {extra['category_description']}")
        if schema_service:
            try:
                required = schema_service.get_required_properties(product_type)
                parts.append(f"This category has {len(required)} required fields.")
            except Exception:
                pass
        return "\n".join(parts)

    def _build_required_attrs(self, product_type: str, schema_service: Any) -> str:
        if not schema_service:
            return "(unknown — include all available product details)"
        try:
            required = schema_service.get_required_properties(product_type)
            if required:
                return "These attributes MUST be covered: " + ", ".join(required[:20])
        except Exception:
            pass
        return "(unknown)"

    def _build_valid_hints(self, product_type: str, schema_service: Any) -> str:
        if not schema_service:
            return "(none provided)"
        hints = []
        for field in ["country_of_origin", "style", "color", "material"]:
            try:
                vals = schema_service.get_valid_values(product_type, field)
                if vals:
                    hints.append(f"{field}: {', '.join(vals[:15])}")
            except Exception:
                pass
        return "\n".join(hints) if hints else "(none provided)"

    def _build_persona(self, product_type: str, extra: Optional[Dict]) -> str:
        if extra and extra.get("buyer_persona"):
            return extra["buyer_persona"]
        return _BUYER_PERSONAS.get(product_type.upper(), _BUYER_PERSONAS["default"])

    def _format_product_data(self, product: StandardProduct) -> str:
        lines = [
            f"Name: {product.name}",
            f"Vendor SKU: {product.vendor_sku}",
        ]
        if product.attributes:
            lines.append("Attributes:")
            for k, v in list(product.attributes.items())[:20]:
                lines.append(f"  {k}: {v}")
        if product.description:
            desc = product.description[:500]
            lines.append(f"Description excerpt: {desc}")
        if product.bullet_points:
            lines.append("Supplier bullet points:")
            for bp in product.bullet_points:
                lines.append(f"  - {bp}")
        if product.dimensions:
            d = product.dimensions
            dims = []
            if d.assembled_length:
                dims.append(f"{d.assembled_length}\"L")
            if d.assembled_width:
                dims.append(f"{d.assembled_width}\"W")
            if d.assembled_height:
                dims.append(f"{d.assembled_height}\"H")
            if dims:
                lines.append(f"Assembled: {' x '.join(dims)}")
            if d.assembled_weight:
                lines.append(f"Weight: {d.assembled_weight} lbs")
        return "\n".join(lines)

    # ── LLM ───────────────────────────────────────────────────────

    def _make_llm_request(self, system_prompt: str, user_prompt: str):
        from infrastructure.llm.types import LLMRequest

        return LLMRequest(
            task_type="product_generation",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_mode=True,
            temperature=0.4,
        )

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from infrastructure.llm.factory import get_llm_service

        self._llm = get_llm_service()
        return self._llm

    def _get_prompt(self) -> str:
        from src.utils.prompt_manager import PromptManager

        pm = PromptManager()
        return pm.get_prompt("prod_detail_gen_v2")

    # ── parse & validate ───────────────────────────────────────────

    def _parse_and_validate(self, raw_text: str) -> EnrichedProductContent:
        result = EnrichedProductContent(raw_llm_response=raw_text)

        # Extract JSON
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if lines[0].startswith("```") else text
            if text.endswith("```"):
                text = text[:-3]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            match = re.search(r"\{[^{}]*\{.*\}[^{}]*\}", text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    result.validation_warnings.append("Could not parse LLM output as JSON")
                    return result
            else:
                result.validation_warnings.append("Could not parse LLM output as JSON")
                return result

        result.title = str(data.get("title", "")).strip()
        result.bullet_1 = str(data.get("bullet_1", "")).strip()
        result.bullet_2 = str(data.get("bullet_2", "")).strip()
        result.bullet_3 = str(data.get("bullet_3", "")).strip()
        result.bullet_4 = str(data.get("bullet_4", "")).strip()
        result.bullet_5 = str(data.get("bullet_5", "")).strip()
        result.description = str(data.get("description", "")).strip()
        result.search_terms = str(data.get("search_terms", "")).strip()
        result.generic_keyword = str(data.get("generic_keyword", "")).strip()

        # Pick up any extra enriched attributes
        known_keys = {
            "title", "bullet_1", "bullet_2", "bullet_3", "bullet_4", "bullet_5",
            "description", "search_terms", "generic_keyword",
        }
        for k, v in data.items():
            if k not in known_keys:
                result.enriched_attributes[k] = v

        # ── validate ───────────────────────────────────────────
        self._validate(result)

        return result

    def _validate(self, content: EnrichedProductContent) -> None:
        bullets = [
            content.bullet_1, content.bullet_2, content.bullet_3,
            content.bullet_4, content.bullet_5,
        ]
        w = validate_content(
            title=content.title,
            bullets=bullets,
            description=content.description,
            search_terms=content.search_terms,
        )
        content.validation_warnings.extend(w)
        if w:
            logger.warning("Content validation warnings: %s", w)
