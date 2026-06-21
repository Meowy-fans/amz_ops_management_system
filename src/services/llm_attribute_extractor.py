"""Constrained LLM extraction for Amazon listing attributes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.models.amazon_listing import AmazonListingDraft


@dataclass
class LLMAttributeExtraction:
    """Evidence-bound candidate value extracted from product text."""

    value: Any = None
    evidence: str = ""
    confidence: str = "low"
    warnings: List[str] = field(default_factory=list)
    raw_response: Any = None


class LLMAttributeExtractor:
    """Extracts attribute candidates without allowing unsupported invention."""

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
        attribute: str,
        config: Dict[str, Any] | None = None,
        schema_service: Any = None,
    ) -> LLMAttributeExtraction:
        """Return a validated extraction or a null result."""
        config = config or {}
        if self._is_sensitive(attribute):
            return LLMAttributeExtraction(warnings=["sensitive"])
        llm_client = self.llm_client or self._default_client()
        if llm_client is None:
            return LLMAttributeExtraction(warnings=["llm_unavailable"])

        valid_values = self._valid_values(
            draft.product_type,
            attribute,
            schema_service,
        )
        context = self._context(draft, attribute, config, valid_values)
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
        if config.get("enum_locked") and valid_values:
            value = self._canonical_enum(value, valid_values)
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
    def _is_sensitive(cls, attribute: str) -> bool:
        name = str(attribute or "").strip().lower()
        if name in cls._SENSITIVE_EXACT:
            return True
        return any(marker in name for marker in cls._SENSITIVE_MARKERS)

    @staticmethod
    def _valid_values(
        product_type: str,
        attribute: str,
        schema_service: Any,
    ) -> List[str]:
        if schema_service is None:
            return []
        try:
            values = schema_service.get_cached_valid_values(product_type, attribute)
        except Exception:
            return []
        return [str(value) for value in (values or [])]

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
        attribute: str,
        config: Dict[str, Any],
        valid_values: List[str],
    ) -> Dict[str, Any]:
        content = draft.content
        product = draft.standard_product
        raw = getattr(product, "raw_source_data", {}) or {}
        return {
            "sku": draft.sku,
            "product_type": draft.product_type,
            "attribute": attribute,
            "hint": config.get("hint", ""),
            "enum_locked": bool(config.get("enum_locked")),
            "valid_values": valid_values,
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
