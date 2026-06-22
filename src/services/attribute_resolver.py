"""Resolve API-native Amazon attributes from draft data and rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any, Dict, List

from src.models.amazon_listing import AmazonListingDraft
from src.services.attribute_rule_loader import AttributeRuleLoader


@dataclass
class AttributeResolution:
    """Resolved Amazon attribute with evidence and confidence."""

    attribute: str
    value: Any = None
    level: str = "optional"
    shape: str = "value"
    source: str = ""
    evidence: str = ""
    confidence: str = "low"
    state: str = "unresolved"
    blocking: bool = False
    rule_version: str = ""
    safe_default: bool = False
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "attribute": self.attribute,
            "value": self.value,
            "level": self.level,
            "shape": self.shape,
            "source": self.source,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "state": self.state,
            "blocking": self.blocking,
            "rule_version": self.rule_version,
            "safe_default": self.safe_default,
            "warnings": self.warnings,
        }


class AttributeResolver:
    """Resolves configured Amazon attributes for one listing draft."""

    def __init__(
        self,
        rule_loader: AttributeRuleLoader | None = None,
        schema_service: Any = None,
        llm_extractor: Any = None,
    ):
        self.rule_loader = rule_loader or AttributeRuleLoader()
        self.schema_service = schema_service
        self.llm_extractor = llm_extractor

    def resolve(self, draft: AmazonListingDraft) -> Dict[str, AttributeResolution]:
        rules = self.rule_loader.load(draft.product_type)
        version = rules.get("version", "attribute_rules_unknown")
        resolved: Dict[str, AttributeResolution] = {}
        for attribute, rule in (rules.get("attributes") or {}).items():
            result = self._resolve_one(draft, attribute, rule, version)
            resolved[attribute] = result
        return resolved

    def _resolve_one(
        self,
        draft: AmazonListingDraft,
        attribute: str,
        rule: Dict[str, Any],
        version: str,
    ) -> AttributeResolution:
        level = rule.get("level", "optional")
        shape = rule.get("shape", "value")
        transform = rule.get("transform", "text")
        for source in rule.get("sources") or []:
            raw_value, source_name, confidence, evidence, safe_default = self._read_source(
                draft,
                attribute,
                source,
            )
            if raw_value in (None, ""):
                continue
            value = self._transform(draft.product_type, attribute, raw_value, transform)
            if value in (None, ""):
                continue
            return self._finish(
                AttributeResolution(
                    attribute=attribute,
                    value=value,
                    level=level,
                    shape=shape,
                    source=source_name,
                    evidence=evidence,
                    confidence=confidence,
                    rule_version=version,
                    safe_default=safe_default,
                )
            )
        return self._finish(
            AttributeResolution(
                attribute=attribute,
                level=level,
                shape=shape,
                rule_version=version,
                blocking=level == "required",
            )
        )

    def _read_source(
        self,
        draft: AmazonListingDraft,
        attribute: str,
        source: Dict[str, Any],
    ) -> tuple[Any, str, str, str, bool]:
        if "default" in source:
            return (
                source.get("default"),
                "default",
                source.get("confidence", "medium"),
                source.get("evidence", ""),
                bool(source.get("safe_default")),
            )
        if "llm" in source:
            return self._read_llm_source(draft, attribute, source)
        path = source.get("path")
        if not path:
            return None, "", "low", "", False
        return (
            self._path_value(draft, path),
            path,
            source.get("confidence", "high"),
            source.get("evidence", path),
            False,
        )

    def _read_llm_source(
        self,
        draft: AmazonListingDraft,
        attribute: str,
        source: Dict[str, Any],
    ) -> tuple[Any, str, str, str, bool]:
        extractor = self.llm_extractor
        if extractor is None:
            try:
                from src.services.llm_attribute_extractor import LLMAttributeExtractor

                extractor = LLMAttributeExtractor()
            except Exception:
                return None, "llm", "low", "", False
        config = source.get("llm") or {}
        extraction = extractor.extract(
            draft,
            attribute,
            config,
            schema_service=self.schema_service,
        )
        return (
            getattr(extraction, "value", None),
            "llm",
            self._llm_confidence(getattr(extraction, "confidence", "medium")),
            getattr(extraction, "evidence", ""),
            False,
        )

    def _path_value(self, draft: AmazonListingDraft, path: str) -> Any:
        parts = path.split(".")
        root = parts[0]
        if root == "content":
            current: Any = draft.content
        elif root == "product":
            current = draft.standard_product
        elif root == "offer":
            current = draft.offer
        elif root == "variation":
            current = draft.variation
        else:
            return None
        for part in parts[1:]:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
        return current

    def _transform(
        self,
        product_type: str,
        attribute: str,
        value: Any,
        transform: str,
    ) -> Any:
        if transform == "integer":
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None
        if transform == "boolean_yes_no":
            text = str(value).strip().lower()
            if text in {"true", "yes", "y", "1", "required"}:
                return "Yes"
            if text in {"false", "no", "n", "0", "not required"}:
                return "No"
            return str(value).strip()
        if transform == "boolean":
            text = str(value).strip().lower()
            if text in {"true", "yes", "y", "1", "required"}:
                return True
            if text in {"false", "no", "n", "0", "not required"}:
                return False
            return value if isinstance(value, bool) else None
        if transform == "enum":
            return self._valid_value(product_type, attribute, value)
        if transform in {"passthrough", "raw"}:
            return value
        return str(value).strip() if value is not None else None

    @staticmethod
    def _llm_confidence(confidence: Any) -> str:
        text = str(confidence or "medium").strip().lower()
        if text == "low":
            return "low"
        return "medium"

    def _valid_value(self, product_type: str, attribute: str, value: Any) -> str:
        text = str(value or "").strip()
        if not text or self.schema_service is None:
            return text
        if attribute == "country_of_origin":
            text = self._country_code(text)
        try:
            candidates = self.schema_service.get_cached_valid_values(
                product_type, attribute
            )
        except Exception:
            return text
        if not candidates:
            return text
        exact = {str(item).lower(): str(item) for item in candidates}
        if text.lower() in exact:
            return exact[text.lower()]
        match = get_close_matches(text.lower(), list(exact.keys()), n=1, cutoff=0.75)
        return exact[match[0]] if match else text

    @staticmethod
    def _country_code(value: str) -> str:
        aliases = {
            "china": "CN",
            "cn": "CN",
            "prc": "CN",
            "malaysia": "MY",
            "my": "MY",
            "united states": "US",
            "usa": "US",
            "us": "US",
            "vietnam": "VN",
            "viet nam": "VN",
            "vn": "VN",
        }
        return aliases.get(str(value or "").strip().lower(), str(value or "").strip())

    @staticmethod
    def _finish(result: AttributeResolution) -> AttributeResolution:
        if result.value in (None, ""):
            result.state = "unresolved"
            result.blocking = result.level == "required"
            return result
        if result.confidence == "low":
            result.state = "resolved_low_confidence"
            result.blocking = result.level == "required"
            return result
        if result.source == "llm" and result.level == "required":
            result.state = "needs_manual_review"
            result.blocking = True
            return result
        if result.source == "default":
            result.state = "resolved_with_default"
            result.blocking = False
            return result
        result.state = "resolved_high_confidence"
        result.blocking = False
        return result
