"""Online variation hierarchy audit gate for append-child listing flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from src.services.amazon_variation_resolver import VariationResolutionFinding


@dataclass
class VariationHierarchyAuditResult:
    """Decision and audit details from online hierarchy comparison."""

    blocked: bool = False
    blocking_codes: List[str] = field(default_factory=list)
    warning_codes: List[str] = field(default_factory=list)
    findings: List[VariationResolutionFinding] = field(default_factory=list)
    online_signatures: List[List[str]] = field(default_factory=list)
    local_signatures: List[List[str]] = field(default_factory=list)
    probe_snapshot: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "blocked": self.blocked,
            "blocking_codes": self.blocking_codes,
            "warning_codes": self.warning_codes,
            "findings": [item.as_dict() for item in self.findings],
            "online_signatures": self.online_signatures,
            "local_signatures": self.local_signatures,
            "probe_snapshot": self.probe_snapshot,
        }


class VariationHierarchyAuditGate:
    """Compares a new child variation signature against online sibling facts."""

    def evaluate(
        self,
        parent_sku: str,
        existing_theme: str,
        selected_attrs: Dict[str, Any],
        existing_children: List[Dict[str, Any]],
        probe_result: Any,
        required_attrs: List[str] | None = None,
    ) -> VariationHierarchyAuditResult:
        required = list(required_attrs or self._theme_attributes(existing_theme))
        result = VariationHierarchyAuditResult(
            probe_snapshot=(
                probe_result.as_dict()
                if hasattr(probe_result, "as_dict")
                else dict(probe_result or {})
            )
        )
        new_signature = self._signature(selected_attrs, required)
        result.local_signatures = [
            list(self._signature(item.get("variation_attributes") or {}, required))
            for item in existing_children
            if self._complete_signature(item.get("variation_attributes") or {}, required)
        ]

        if not self._complete_signature(selected_attrs, required):
            self._add_warning(
                result,
                "ONLINE_VARIATION_AUDIT_SKIPPED",
                "New child signature is incomplete; local resolver should handle missing attributes.",
                {"parent_sku": parent_sku, "theme": existing_theme},
            )
            return result

        online_facts = list(getattr(probe_result, "online_sibling_facts", []) or [])
        if not online_facts:
            self._add_warning(
                result,
                "ONLINE_VARIATION_FACTS_UNAVAILABLE",
                "Online sibling variation facts are unavailable or cannot be mapped.",
                {
                    "parent_sku": parent_sku,
                    "theme": existing_theme,
                    "probe_status": getattr(probe_result, "probe_status", ""),
                },
            )
            return result

        for fact in online_facts:
            attrs = fact.get("variation_attributes") or {}
            if not self._complete_signature(attrs, required):
                continue
            signature = self._signature(attrs, required)
            result.online_signatures.append(list(signature))
            if signature == new_signature:
                self._add_blocking(
                    result,
                    "DUPLICATE_ONLINE_VARIATION_ATTRIBUTES",
                    "New child duplicates an online sibling variation attribute combination.",
                    {
                        "parent_sku": parent_sku,
                        "theme": existing_theme,
                        "signature": list(signature),
                        "online_sibling": {
                            "asin": fact.get("asin"),
                            "sku": fact.get("sku"),
                        },
                    },
                )

        if not result.online_signatures and not result.blocked:
            self._add_warning(
                result,
                "ONLINE_VARIATION_FACTS_UNAVAILABLE",
                "Online sibling facts did not include complete attributes for the active theme.",
                {"parent_sku": parent_sku, "theme": existing_theme},
            )
        result.blocked = bool(result.blocking_codes)
        return result

    @staticmethod
    def _theme_attributes(theme: str) -> List[str]:
        mapping = {
            "Color": ["color_name"],
            "Size": ["size_name"],
            "Color/Size": ["color_name", "size_name"],
        }
        return mapping.get(str(theme or ""), [])

    @classmethod
    def _complete_signature(cls, attrs: Dict[str, Any], required: List[str]) -> bool:
        return bool(required) and all(str(attrs.get(key) or "").strip() for key in required)

    @staticmethod
    def _signature(attrs: Dict[str, Any], required: List[str]) -> Tuple[str, ...]:
        return tuple(str(attrs.get(key) or "").strip().lower() for key in required)

    def _add_blocking(
        self,
        result: VariationHierarchyAuditResult,
        code: str,
        message: str,
        details: Dict[str, Any],
    ) -> None:
        if code not in result.blocking_codes:
            result.blocking_codes.append(code)
        result.findings.append(
            VariationResolutionFinding(
                code=code,
                message=message,
                blocking=True,
                details=details,
            )
        )

    def _add_warning(
        self,
        result: VariationHierarchyAuditResult,
        code: str,
        message: str,
        details: Dict[str, Any],
    ) -> None:
        if code not in result.warning_codes:
            result.warning_codes.append(code)
        result.findings.append(
            VariationResolutionFinding(
                code=code,
                message=message,
                blocking=False,
                details=details,
            )
        )
