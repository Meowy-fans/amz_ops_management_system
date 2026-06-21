"""LLM review gate for generated Amazon listing content."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.models.product import StandardProduct

logger = logging.getLogger(__name__)

_ALLOWED_VERDICTS = {"pass", "revise", "manual_review", "reject"}


@dataclass
class ContentReviewResult:
    """Structured verdict returned by the content reviewer."""

    verdict: str = "manual_review"
    accuracy_score: float = 0.0
    compliance_score: float = 0.0
    amazon_readiness_score: float = 0.0
    issues: List[Dict[str, Any]] = field(default_factory=list)
    revision_instructions: str = ""
    manual_review_fields: List[str] = field(default_factory=list)
    reviewed_fields: List[str] = field(default_factory=list)
    unsupported_claims: List[str] = field(default_factory=list)
    raw_llm_response: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "accuracy_score": self.accuracy_score,
            "compliance_score": self.compliance_score,
            "amazon_readiness_score": self.amazon_readiness_score,
            "issues": self.issues,
            "revision_instructions": self.revision_instructions,
            "manual_review_fields": self.manual_review_fields,
            "reviewed_fields": self.reviewed_fields,
            "unsupported_claims": self.unsupported_claims,
            "raw_llm_response": self.raw_llm_response,
        }


class ProductContentReviewer:
    """Reviews generated listing content for accuracy and Amazon readiness."""

    def __init__(self, llm_service: Any = None):
        self._llm = llm_service

    def review(
        self,
        product: StandardProduct,
        product_type: str,
        content: Any,
    ) -> ContentReviewResult:
        """Return a structured review verdict for generated content."""
        try:
            llm = self._get_llm()
            request = self._make_request(product, product_type, content)
            response = llm.generate(request)
            raw = response.content if hasattr(response, "content") else response
            raw_text = json.dumps(raw) if isinstance(raw, dict) else str(raw)
            return self._parse_result(raw_text)
        except Exception as exc:
            logger.warning("Product content review failed: %s", exc)
            return ContentReviewResult(
                verdict="manual_review",
                issues=[
                    {
                        "severity": "error",
                        "code": "REVIEW_LLM_FAILED",
                        "field": "",
                        "message": str(exc),
                    }
                ],
            )

    def _make_request(
        self,
        product: StandardProduct,
        product_type: str,
        content: Any,
    ):
        from infrastructure.llm.types import LLMRequest

        return LLMRequest(
            task_type="product_content_review",
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(product, product_type, content),
            json_mode=True,
            temperature=0.1,
        )

    @staticmethod
    def _system_prompt() -> str:
        try:
            from src.utils.prompt_manager import PromptManager

            prompt = PromptManager().get_prompt("product_content_review")
            if prompt:
                return prompt
        except Exception:
            pass
        return (
            "You are a conservative Amazon listing content reviewer. "
            "Review generated listing content for factual accuracy against source data, "
            "Amazon listing readiness, unsupported claims, and policy risks. "
            "Do not rewrite the content. Return only valid JSON."
        )

    def _user_prompt(
        self,
        product: StandardProduct,
        product_type: str,
        content: Any,
    ) -> str:
        product_payload = {
            "sku": product.sku,
            "vendor_sku": product.vendor_sku,
            "product_type": product_type,
            "source_name": product.name,
            "source_description": product.description,
            "source_bullets": product.bullet_points,
            "source_attributes": product.attributes,
            "source_dimensions": (
                product.dimensions.__dict__ if product.dimensions else None
            ),
        }
        content_payload = {
            "title": getattr(content, "title", ""),
            "bullet_1": getattr(content, "bullet_1", ""),
            "bullet_2": getattr(content, "bullet_2", ""),
            "bullet_3": getattr(content, "bullet_3", ""),
            "bullet_4": getattr(content, "bullet_4", ""),
            "bullet_5": getattr(content, "bullet_5", ""),
            "description": getattr(content, "description", ""),
            "search_terms": getattr(content, "search_terms", ""),
            "generic_keyword": getattr(content, "generic_keyword", ""),
            "enriched_attributes": getattr(content, "enriched_attributes", {}),
        }
        output_contract = {
            "verdict": "pass | revise | manual_review | reject",
            "accuracy_score": "0.0-1.0",
            "compliance_score": "0.0-1.0",
            "amazon_readiness_score": "0.0-1.0",
            "issues": [
                {
                    "severity": "info | warning | error",
                    "code": "string",
                    "field": "string",
                    "message": "string",
                }
            ],
            "revision_instructions": "string",
            "manual_review_fields": ["field_name"],
            "reviewed_fields": ["field_name"],
            "unsupported_claims": ["claim"],
        }
        return (
            "Use a conservative policy:\n"
            "- If required factual claims are uncertain, use manual_review.\n"
            "- If copy can be fixed, use revise and provide concise instructions.\n"
            "- If the content invents unsupported facts, certifications, medical, "
            "pesticide, antimicrobial, anti-mold, bacteria, disinfecting, or insect "
            "claims, use reject or revise depending on severity.\n"
            "- Use pass only when content is accurate, policy-safe, and Amazon-ready.\n\n"
            f"SOURCE_PRODUCT:\n{json.dumps(product_payload, ensure_ascii=False)}\n\n"
            f"GENERATED_CONTENT:\n{json.dumps(content_payload, ensure_ascii=False)}\n\n"
            f"OUTPUT_CONTRACT:\n{json.dumps(output_contract, ensure_ascii=False)}"
        )

    def _parse_result(self, raw_text: str) -> ContentReviewResult:
        data = self._load_json(raw_text)
        if data is None:
            return ContentReviewResult(
                verdict="manual_review",
                raw_llm_response=raw_text,
                issues=[
                    {
                        "severity": "error",
                        "code": "REVIEW_PARSE_FAILED",
                        "field": "",
                        "message": "Could not parse reviewer output as JSON",
                    }
                ],
            )
        verdict = str(data.get("verdict") or "manual_review").strip().lower()
        issues = list(data.get("issues") or [])
        if verdict not in _ALLOWED_VERDICTS:
            issues.append(
                {
                    "severity": "error",
                    "code": "INVALID_REVIEW_VERDICT",
                    "field": "verdict",
                    "message": f"Unsupported reviewer verdict: {verdict}",
                }
            )
            verdict = "manual_review"
        return ContentReviewResult(
            verdict=verdict,
            accuracy_score=self._to_float(data.get("accuracy_score")),
            compliance_score=self._to_float(data.get("compliance_score")),
            amazon_readiness_score=self._to_float(data.get("amazon_readiness_score")),
            issues=issues,
            revision_instructions=str(data.get("revision_instructions") or ""),
            manual_review_fields=list(data.get("manual_review_fields") or []),
            reviewed_fields=list(data.get("reviewed_fields") or []),
            unsupported_claims=list(data.get("unsupported_claims") or []),
            raw_llm_response=raw_text,
        )

    @staticmethod
    def _load_json(raw_text: str) -> Dict[str, Any] | None:
        text = str(raw_text or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from infrastructure.llm.factory import get_llm_service

        self._llm = get_llm_service()
        return self._llm
