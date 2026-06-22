"""Required attribute coverage gate for API-native listing plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.services.attribute_rule_loader import AttributeRuleLoader


@dataclass
class AttributeCoverageResult:
    """Coverage decision for one listing plan."""

    blocked: bool = False
    covered_required: List[str] = field(default_factory=list)
    missing_required: List[str] = field(default_factory=list)
    low_confidence_required: List[str] = field(default_factory=list)
    defaulted_required: List[str] = field(default_factory=list)
    blocking_codes: List[str] = field(default_factory=list)
    warning_codes: List[str] = field(default_factory=list)
    findings: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "blocked": self.blocked,
            "covered_required": self.covered_required,
            "missing_required": self.missing_required,
            "low_confidence_required": self.low_confidence_required,
            "defaulted_required": self.defaulted_required,
            "blocking_codes": self.blocking_codes,
            "warning_codes": self.warning_codes,
            "findings": self.findings,
        }


class AmazonListingAttributeCoverageGate:
    """Checks schema required attributes before Amazon submitter receives a plan."""

    def __init__(self, schema_service: Any = None):
        self.schema_service = schema_service

    def evaluate(self, plan: Dict[str, Any]) -> AttributeCoverageResult:
        """Return required attribute coverage for one listing plan."""
        result = AttributeCoverageResult()
        product_type = plan.get("product_type")
        if self.schema_service is None or not product_type:
            return result

        try:
            if hasattr(self.schema_service, "get_coverage_required_properties"):
                required = (
                    self.schema_service.get_coverage_required_properties(product_type)
                    or []
                )
            else:
                required = self.schema_service.get_required_properties(product_type) or []
        except Exception as exc:
            result.warning_codes.append("ATTRIBUTE_SCHEMA_UNAVAILABLE")
            result.findings.append(
                self._finding(
                    code="ATTRIBUTE_SCHEMA_UNAVAILABLE",
                    attribute="",
                    severity="WARNING",
                    blocking=False,
                    message=(
                        f"Required attribute coverage skipped because schema "
                        f"is unavailable for product_type={product_type}: {exc}"
                    ),
                )
            )
            return result

        attrs = plan.get("attributes") or {}
        resolutions = plan.get("attribute_resolutions") or {}
        ignored_required = self._ignored_required_for_plan(product_type, attrs)
        for name in required:
            if name in ignored_required:
                continue
            if self._has_payload_value(attrs.get(name)):
                result.covered_required.append(name)
                resolution = self._resolution_dict(resolutions.get(name))
                if self._is_low_confidence_required(resolution):
                    result.low_confidence_required.append(name)
                    self._add_blocking(
                        result,
                        code="LOW_CONFIDENCE_REQUIRED_ATTRIBUTE",
                        attribute=name,
                        message=f"Required attribute '{name}' resolved with low confidence",
                    )
                elif self._is_evidenced_default_required(resolution):
                    result.defaulted_required.append(name)
                elif self._is_unsafe_default_required(resolution):
                    self._add_blocking(
                        result,
                        code="UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE",
                        attribute=name,
                        message=(
                            f"Required attribute '{name}' resolved with a default "
                            "that is not explicitly safe-default whitelisted"
                        ),
                    )
                continue

            result.missing_required.append(name)
            self._add_blocking(
                result,
                code="MISSING_REQUIRED_ATTRIBUTE_RULE",
                attribute=name,
                message=f"Required attribute '{name}' has no resolved payload value",
            )

        result.blocked = bool(result.blocking_codes)
        return result

    def _ignored_required_for_plan(
        self,
        product_type: str,
        attrs: Dict[str, Any],
    ) -> set[str]:
        if not self._is_parent_plan(attrs):
            return set()
        try:
            rules = AttributeRuleLoader().load(product_type)
        except Exception:
            return set()
        return {
            str(name)
            for name in (rules.get("coverage_ignore_when_parent") or [])
            if str(name or "").strip()
        }

    @classmethod
    def _is_parent_plan(cls, attrs: Dict[str, Any]) -> bool:
        value = attrs.get("parentage_level")
        if isinstance(value, list) and value:
            value = value[0]
        if isinstance(value, dict):
            value = value.get("value")
        return str(value or "").strip().lower() == "parent"

    @staticmethod
    def _has_payload_value(value: Any) -> bool:
        if value in (None, "", []):
            return False
        if isinstance(value, list):
            return any(
                AmazonListingAttributeCoverageGate._has_payload_value(item)
                for item in value
            )
        if isinstance(value, dict):
            return any(v not in (None, "", []) for v in value.values())
        return True

    @staticmethod
    def _resolution_dict(resolution: Any) -> Dict[str, Any]:
        if resolution is None:
            return {}
        if isinstance(resolution, dict):
            return resolution
        if hasattr(resolution, "as_dict"):
            return resolution.as_dict()
        return {}

    @staticmethod
    def _is_low_confidence_required(resolution: Dict[str, Any]) -> bool:
        if not resolution:
            return False
        return (
            resolution.get("level") == "required"
            and (
                resolution.get("state") == "resolved_low_confidence"
                or resolution.get("confidence") == "low"
                or bool(resolution.get("blocking"))
            )
        )

    @staticmethod
    def _is_evidenced_default_required(resolution: Dict[str, Any]) -> bool:
        if not resolution:
            return False
        return (
            resolution.get("level") == "required"
            and resolution.get("source") == "default"
            and resolution.get("confidence") in {"medium", "high"}
            and bool(resolution.get("evidence"))
            and bool(resolution.get("safe_default"))
        )

    @staticmethod
    def _is_unsafe_default_required(resolution: Dict[str, Any]) -> bool:
        if not resolution:
            return False
        return (
            resolution.get("level") == "required"
            and resolution.get("source") == "default"
            and not bool(resolution.get("safe_default"))
        )

    def _add_blocking(
        self,
        result: AttributeCoverageResult,
        code: str,
        attribute: str,
        message: str,
    ) -> None:
        if code not in result.blocking_codes:
            result.blocking_codes.append(code)
        result.findings.append(
            self._finding(
                code=code,
                attribute=attribute,
                severity="ERROR",
                blocking=True,
                message=message,
            )
        )

    @staticmethod
    def _finding(
        code: str,
        attribute: str,
        severity: str,
        blocking: bool,
        message: str,
    ) -> Dict[str, Any]:
        return {
            "code": code,
            "attribute": attribute,
            "attribute_names": [attribute] if attribute else [],
            "severity": severity,
            "blocking": blocking,
            "message": message,
        }
