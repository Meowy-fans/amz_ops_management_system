"""Unified product content generator — category-aware LLM enrichment.

Replaces the dual-pipeline pattern (ProductDetailGenerationService +
DataMappingLLM) with a single LLM call that produces title, bullets,
description, search terms, and enriched attributes.

Keyword research integration: optionally accepts KeywordResearchResult
to guide title/keyword placement and COSMO attribute population.
"""

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from src.models.product import StandardProduct
from src.services.compliance_claim_scanner import ComplianceClaimScanner
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
    validation_errors: List[str] = field(default_factory=list)
    compliance_hits: List[Dict[str, Any]] = field(default_factory=list)
    compliance_fixes: List[Dict[str, Any]] = field(default_factory=list)
    compliance_blocked: bool = False
    auto_sanitized: bool = False
    compliance_retried: bool = False
    review_status: str = "not_reviewed"
    review_attempts: int = 0
    review_result: Dict[str, Any] = field(default_factory=dict)
    raw_llm_response: str = ""

# ── buyer personas ────────────────────────────────────────────────

_BUYER_PERSONAS = {
    "CABINET": "Homeowners renovating bathrooms, ages 30-55, value-conscious but quality-focused, DIY-capable or working with contractors",
    "HOME_MIRROR": "Home decor enthusiasts, ages 25-50, design-conscious, looking for statement pieces that combine function and aesthetics",
    "default": "Online shoppers looking for quality home products, value durability and clear product information",
}

_COMPLIANCE_RETRY_SYSTEM = (
    "You are an Amazon listing compliance editor. "
    "Rewrite the JSON content to remove pesticide/antimicrobial claims. "
    "Return ONLY valid JSON with the same keys. No markdown."
)


# ── generator ─────────────────────────────────────────────────────


class ProductContentGenerator:
    """Generates Amazon-optimized product content using LLM."""

    def __init__(
        self,
        llm_service: Any = None,
        max_compliance_retries: int = 1,
        reviewer: Any = None,
        max_review_revisions: int = 1,
    ):
        self._llm = llm_service
        self.max_compliance_retries = max_compliance_retries
        self._scanner = ComplianceClaimScanner()
        self._reviewer = reviewer
        self.max_review_revisions = max_review_revisions

    def generate(
        self,
        product: StandardProduct,
        product_type: str,
        schema_service: Any = None,
        extra_context: Optional[Dict[str, str]] = None,
        keyword_result: Any = None,
    ) -> EnrichedProductContent:
        """Generate enriched content for a single product."""
        category_context = self._build_category_context(
            product_type, schema_service, extra_context
        )
        required_attrs = self._build_required_attrs(product_type, schema_service)
        valid_hints = self._build_valid_hints(product_type, schema_service)
        persona = self._build_persona(product_type, extra_context)
        product_data = self._format_product_data(product, keyword_result)

        keyword_guidance = self._build_keyword_guidance(keyword_result)
        if keyword_guidance:
            product_data = keyword_guidance + "\n\n" + product_data

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

        revision_feedback = ""
        attempts = self.max_review_revisions + 1
        last_result = EnrichedProductContent()
        for attempt in range(attempts):
            prompt = user_prompt
            if revision_feedback:
                prompt = (
                    f"{user_prompt}\n\n"
                    "▼ REVIEWER REVISION FEEDBACK\n"
                    f"{revision_feedback}\n"
                    "Regenerate the same JSON fields and fix the review issues. "
                    "Do not add unsupported product facts."
                )
            result = self._generate_once(system_prompt, prompt)
            last_result = result
            if not result.title and not result.description:
                return result

            self._apply_compliance_pipeline(result, product, product_type)
            if result.compliance_blocked:
                return result

            review = self._get_reviewer().review(product, product_type, result)
            result.review_attempts = attempt + 1
            result.review_result = review.as_dict()
            result.review_status = review.verdict
            if review.verdict == "pass":
                return result
            if review.verdict == "revise" and attempt < self.max_review_revisions:
                revision_feedback = review.revision_instructions or "; ".join(
                    issue.get("message", "") for issue in review.issues
                )
                continue
            result.compliance_blocked = True
            result.validation_errors.append(
                f"Content review failed with verdict={review.verdict}"
            )
            for issue in review.issues:
                message = issue.get("message")
                if message:
                    result.validation_errors.append(str(message))
            return result

        return last_result

    def _generate_once(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> EnrichedProductContent:
        try:
            llm = self._get_llm()
            request = self._make_llm_request(system_prompt, user_prompt)
            response = llm.generate(request)
            raw = response.content if hasattr(response, "content") else response
            raw_text = json.dumps(raw) if isinstance(raw, dict) else str(raw)
        except Exception as e:
            logger.error("LLM generation failed: %s", e)
            return EnrichedProductContent(
                validation_warnings=[f"LLM call failed: {e}"]
            )
        return self._parse_content(raw_text)

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
        for field_name in ["country_of_origin", "style", "color", "material"]:
            try:
                vals = schema_service.get_valid_values(product_type, field_name)
                if vals:
                    hints.append(f"{field_name}: {', '.join(vals[:15])}")
            except Exception:
                pass
        return "\n".join(hints) if hints else "(none provided)"

    def _build_persona(self, product_type: str, extra: Optional[Dict]) -> str:
        if extra and extra.get("buyer_persona"):
            return extra["buyer_persona"]
        return _BUYER_PERSONAS.get(product_type.upper(), _BUYER_PERSONAS["default"])

    def _build_keyword_guidance(self, keyword_result: Any) -> str:
        if keyword_result is None:
            return ""

        parts = ["▼ KEYWORD RESEARCH GUIDANCE (use these keywords in your output):"]
        if keyword_result.core_keywords:
            parts.append(f"Core Keywords: {', '.join(keyword_result.core_keywords[:10])}")
        if keyword_result.long_tail_keywords:
            parts.append(f"Long-Tail Keywords: {', '.join(keyword_result.long_tail_keywords[:10])}")
        if keyword_result.scenario_intent_keywords:
            parts.append(f"Scenario/Intent Keywords: {', '.join(keyword_result.scenario_intent_keywords[:10])}")
        if keyword_result.title_recommendation:
            parts.append(f"Suggested Title Structure: {keyword_result.title_recommendation}")
        if keyword_result.backend_search_terms:
            parts.append(
                "Backend Search Terms (for reference, avoid repeating these): "
                f"{keyword_result.backend_search_terms}"
            )
        if keyword_result.target_audience:
            parts.append(f"Target Audience: {keyword_result.target_audience}")
        if keyword_result.intended_use:
            parts.append(f"Intended Use: {keyword_result.intended_use}")
        return "\n".join(parts)

    def _format_product_data(
        self, product: StandardProduct, keyword_result: Any = None
    ) -> str:
        lines = [
            f"Name: {product.name}",
            f"Vendor SKU: {product.vendor_sku}",
        ]
        if product.attributes:
            lines.append("Attributes:")
            for k, v in list(product.attributes.items())[:20]:
                lines.append(f"  {k}: {v}")
        if product.description:
            desc = self._scanner.sanitize_supplier_text(product.description[:500])
            lines.append(f"Description excerpt: {desc}")
        if product.bullet_points:
            lines.append("Supplier bullet points:")
            for bp in product.bullet_points:
                lines.append(f"  - {self._scanner.sanitize_supplier_text(str(bp))}")
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

    def _get_reviewer(self):
        if self._reviewer is not None:
            return self._reviewer
        from src.services.product_content_reviewer import ProductContentReviewer

        self._reviewer = ProductContentReviewer(llm_service=self._get_llm())
        return self._reviewer

    def _get_prompt(self) -> str:
        from src.utils.prompt_manager import PromptManager

        pm = PromptManager()
        return pm.get_prompt("prod_detail_gen_v2")

    # ── parse & validate ───────────────────────────────────────────

    def _parse_content(self, raw_text: str) -> EnrichedProductContent:
        result = EnrichedProductContent(raw_llm_response=raw_text)

        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if lines[0].startswith("```") else text
            if text.endswith("```"):
                text = text[:-3]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
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

        known_keys = {
            "title", "bullet_1", "bullet_2", "bullet_3", "bullet_4", "bullet_5",
            "description", "search_terms", "generic_keyword",
        }
        for k, v in data.items():
            if k not in known_keys:
                result.enriched_attributes[k] = v

        return result

    def _apply_compliance_pipeline(
        self,
        result: EnrichedProductContent,
        product: StandardProduct,
        product_type: str,
    ) -> None:
        fields = self._scanner.content_fields_from_enriched(result)
        hits = self._scanner.scan_fields(fields)
        result.compliance_hits = [asdict(hit) for hit in hits]

        if hits:
            sanitized, fixes = self._scanner.sanitize_fields(fields)
            if fixes:
                result.auto_sanitized = True
                result.compliance_fixes.extend(
                    [asdict(fix) for fix in fixes]
                )
                self._scanner.apply_fields_to_enriched(result, sanitized)

        remaining = self._scanner.scan_fields(
            self._scanner.content_fields_from_enriched(result)
        )
        retries = 0
        while remaining and retries < self.max_compliance_retries:
            retries += 1
            result.compliance_retried = True
            rewritten = self._retry_compliance_rewrite(result, remaining)
            if not rewritten:
                break
            remaining = self._scanner.scan_fields(
                self._scanner.content_fields_from_enriched(result)
            )
            if remaining:
                sanitized, fixes = self._scanner.sanitize_fields(
                    self._scanner.content_fields_from_enriched(result)
                )
                if fixes:
                    result.auto_sanitized = True
                    result.compliance_fixes.extend([asdict(fix) for fix in fixes])
                    self._scanner.apply_fields_to_enriched(result, sanitized)
                remaining = self._scanner.scan_fields(
                    self._scanner.content_fields_from_enriched(result)
                )

        if remaining:
            result.compliance_blocked = True
            result.compliance_hits = [asdict(hit) for hit in remaining]
            for hit in remaining:
                result.validation_errors.append(
                    "Compliance claim could not be removed: "
                    f"'{hit.matched_text}' in {hit.field}"
                )
            return

        self._validate(result)

    def _retry_compliance_rewrite(
        self,
        result: EnrichedProductContent,
        hits: List[Any],
    ) -> bool:
        forbidden = sorted({hit.matched_text for hit in hits})
        user_prompt = (
            "Rewrite this Amazon listing JSON and remove all pesticide/antimicrobial "
            "or mold/mildew/bacteria claims.\n"
            f"Forbidden terms found: {', '.join(forbidden)}\n"
            "Use safe alternatives such as moisture-resistant, stain-resistant, "
            "easy to clean, non-porous surface, resists water spots.\n"
            "Keep the same JSON keys and factual product details.\n\n"
            f"{json.dumps(self._scanner.content_fields_from_enriched(result), ensure_ascii=False)}"
        )
        try:
            llm = self._get_llm()
            request = self._make_llm_request(_COMPLIANCE_RETRY_SYSTEM, user_prompt)
            response = llm.generate(request)
            raw = response.content if hasattr(response, "content") else response
            raw_text = json.dumps(raw) if isinstance(raw, dict) else str(raw)
            rewritten = self._parse_content(raw_text)
            if not rewritten.title and not rewritten.description:
                return False
            self._scanner.apply_fields_to_enriched(
                result,
                self._scanner.content_fields_from_enriched(rewritten),
            )
            return True
        except Exception as exc:
            logger.warning("Compliance retry rewrite failed: %s", exc)
            return False

    def _validate(self, content: EnrichedProductContent) -> None:
        bullets = [
            content.bullet_1, content.bullet_2, content.bullet_3,
            content.bullet_4, content.bullet_5,
        ]
        validation = validate_content(
            title=content.title,
            bullets=bullets,
            description=content.description,
            search_terms=content.search_terms,
        )
        content.validation_errors.extend(validation.errors)
        content.validation_warnings.extend(validation.warnings)
        if validation.errors:
            content.compliance_blocked = True
        if validation.all_messages:
            logger.warning(
                "Content validation messages: errors=%s warnings=%s",
                validation.errors,
                validation.warnings,
            )
