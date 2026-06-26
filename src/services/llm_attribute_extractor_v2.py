"""Path-level LLM extraction for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from src.models.amazon_listing import AmazonListingDraft
from src.services.llm_attribute_extractor import LLMAttributeExtraction
from src.services.requirement_models_v2 import RequirementNode


class LLMAttributeExtractorV2:
    """Extract path-level candidate values with evidence and enum/type lock."""

    _SENSITIVE_EXACT = {
        "brand",
        "manufacturer",
        "externally_assigned_product_identifier",
        "supplier_declared_has_product_identifier_exemption",
    }
    _SENSITIVE_MARKERS = (
        "gtin",
        "identifier",
        "certification",
        "compliance",
        "regulation",
        "supplier_declared",
    )

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def extract(
        self,
        draft: AmazonListingDraft,
        requirement: RequirementNode,
    ) -> LLMAttributeExtraction:
        """Return a validated path-level extraction or a null result."""
        if self._is_sensitive(requirement.path_key):
            return LLMAttributeExtraction(warnings=["sensitive"])
        llm_client = self.llm_client or self._default_client()
        if llm_client is None:
            return LLMAttributeExtraction(warnings=["llm_unavailable"])

        context = self._context(draft, requirement)
        response = self._call_client(llm_client, context)
        value = response.get("value")
        evidence = str(response.get("evidence") or "").strip()
        if value in (None, ""):
            return LLMAttributeExtraction(
                raw_response=response,
                warnings=["not_found"],
            )
        if not evidence:
            return LLMAttributeExtraction(
                raw_response=response,
                warnings=["missing_evidence"],
            )
        if requirement.enum_values:
            value = self._canonical_enum(value, requirement.enum_values)
            if value is None:
                return LLMAttributeExtraction(
                    raw_response=response,
                    warnings=["invalid_enum"],
                )
        return LLMAttributeExtraction(
            value=value,
            evidence=evidence,
            confidence=self._cap_confidence(response.get("confidence", "medium")),
            raw_response=response,
        )

    @classmethod
    def _is_sensitive(cls, path_key: str) -> bool:
        root = str(path_key or "").split(".")[0].strip().lower()
        if root in cls._SENSITIVE_EXACT:
            return True
        return any(marker in root for marker in cls._SENSITIVE_MARKERS)

    @staticmethod
    def _canonical_enum(value: Any, valid_values: List[str]) -> str | None:
        text = str(value or "").strip().lower()
        exact = {item.lower(): item for item in valid_values}
        return exact.get(text)

    @staticmethod
    def _cap_confidence(confidence: Any) -> str:
        text = str(confidence or "medium").strip().lower()
        if text == "low":
            return "low"
        return "medium"

    @staticmethod
    def _context(
        draft: AmazonListingDraft,
        requirement: RequirementNode,
    ) -> Dict[str, Any]:
        content = draft.content
        product = draft.standard_product
        raw = getattr(product, "raw_source_data", {}) or {}
        return {
            "sku": draft.sku,
            "product_type": draft.product_type,
            "path_key": requirement.path_key,
            "attribute": requirement.path_key,
            "shape": requirement.shape,
            "enum_locked": bool(requirement.enum_values),
            "valid_values": list(requirement.enum_values),
            "unit_values": list(requirement.unit_values),
            "hint": "",
            "title": content.title,
            "bullets": list(content.bullets or []),
            "description": content.description,
            "product_attributes": dict(product.attributes or {}),
            "raw_name": raw.get("name", ""),
            "raw_description": raw.get("description", ""),
            "raw_characteristics": list(raw.get("characteristics") or []),
        }

    @staticmethod
    def _default_client() -> Any:
        enabled = os.getenv("ATTRIBUTE_LLM_EXTRACTION_ENABLED", "false").lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return None
        try:
            from src.services.attribute_extraction_llm_client import (
                AttributeExtractionLLMClient,
            )

            return AttributeExtractionLLMClient()
        except Exception:
            return None

    def _call_client(self, llm_client: Any, context: Dict[str, Any]) -> Dict[str, Any]:
        if hasattr(llm_client, "extract_attribute"):
            try:
                response = llm_client.extract_attribute(context)
            except Exception:
                return {}
            return response if isinstance(response, dict) else {}
        return {}
