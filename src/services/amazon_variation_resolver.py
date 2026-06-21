"""Deterministic-first resolver for Amazon variation family structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class VariationResolutionFinding:
    """A machine-readable variation resolution finding."""

    code: str
    message: str
    blocking: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
            "details": self.details,
        }


@dataclass
class VariationResolutionResult:
    """Resolved variation structure plus audit metadata."""

    mode: str
    decision: str
    variation_theme: Optional[str] = None
    child_attributes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    parent_sku: Optional[str] = None
    blocking_codes: List[str] = field(default_factory=list)
    warning_codes: List[str] = field(default_factory=list)
    findings: List[VariationResolutionFinding] = field(default_factory=list)
    audit_run_id: Optional[int] = None
    candidate_snapshot: Dict[str, Any] = field(default_factory=dict)
    score_snapshot: Dict[str, Any] = field(default_factory=dict)
    existing_family_snapshot: Dict[str, Any] = field(default_factory=dict)


class AmazonVariationResolver:
    """Chooses Amazon variation themes and validates child attribute uniqueness."""

    _THEME_ATTRIBUTES = {
        "Color": ["color_name"],
        "Size": ["size_name"],
        "Color/Size": ["color_name", "size_name"],
    }

    def __init__(
        self,
        audit_repo: Any,
        config: Optional[Dict[str, Any]] = None,
        config_path: Optional[Path] = None,
    ):
        self.audit_repo = audit_repo
        self.config = config or self._load_config(config_path)
        self.version = self.config.get("version", "variation_theme_strategy_v1")

    def resolve_new_family(
        self,
        family_data: List[Dict[str, Any]],
        product_type: str,
    ) -> VariationResolutionResult:
        """Choose a theme for a newly-created parent family."""
        child_skus = [str(item.get("meow_sku") or "") for item in family_data]
        category_config = self._category_config(product_type)
        allowed_themes = category_config.get("allowed_themes") or list(
            self._THEME_ATTRIBUTES
        )
        candidates: Dict[str, Any] = {}
        scores: Dict[str, Any] = {}
        findings: List[VariationResolutionFinding] = []

        for theme in allowed_themes:
            required_attrs = self._theme_attributes(theme)
            child_attrs, extraction = self._extract_child_attributes(
                family_data,
                product_type,
                required_attrs,
            )
            candidates[theme] = extraction
            scores[theme] = self._score_theme(
                theme,
                child_attrs,
                required_attrs,
                category_config,
            )

        eligible = [
            (theme, score)
            for theme, score in scores.items()
            if score["eligible"]
        ]
        if not eligible:
            findings.append(
                VariationResolutionFinding(
                    code="NO_ELIGIBLE_VARIATION_THEME",
                    message="No configured variation theme has complete and unique child attributes.",
                    details={"scores": scores},
                )
            )
            return self._finish(
                VariationResolutionResult(
                    mode="new_family",
                    decision="blocked",
                    blocking_codes=[item.code for item in findings if item.blocking],
                    findings=findings,
                    candidate_snapshot=candidates,
                    score_snapshot=scores,
                ),
                product_type,
                child_skus,
            )

        selected_theme = sorted(
            eligible,
            key=lambda item: (
                item[1]["score"],
                -len(self._theme_attributes(item[0])),
            ),
            reverse=True,
        )[0][0]
        selected_attrs, _snapshot = self._extract_child_attributes(
            family_data,
            product_type,
            self._theme_attributes(selected_theme),
        )
        return self._finish(
            VariationResolutionResult(
                mode="new_family",
                decision="passed",
                variation_theme=selected_theme,
                child_attributes=selected_attrs,
                candidate_snapshot=candidates,
                score_snapshot=scores,
            ),
            product_type,
            child_skus,
        )

    def resolve_append_child(
        self,
        new_child_data: Dict[str, Any],
        product_type: str,
        parent_sku: str,
        existing_theme: str,
        existing_children: List[Dict[str, Any]],
    ) -> VariationResolutionResult:
        """Inherit an existing parent theme and validate the new child."""
        sku = str(new_child_data.get("meow_sku") or "")
        required_attrs = self._theme_attributes(existing_theme)
        child_attrs, candidate_snapshot = self._extract_child_attributes(
            [new_child_data],
            product_type,
            required_attrs,
        )
        selected_attrs = child_attrs.get(sku, {})
        findings: List[VariationResolutionFinding] = []

        missing = [key for key in required_attrs if not selected_attrs.get(key)]
        if missing:
            findings.append(
                VariationResolutionFinding(
                    code="MISSING_VARIATION_ATTRIBUTE",
                    message="New child is missing attributes required by the existing parent theme.",
                    details={"missing_attributes": missing},
                )
            )

        existing_signatures = {
            self._signature(
                (item.get("variation_attributes") or {}),
                required_attrs,
            )
            for item in existing_children
        }
        new_signature = self._signature(selected_attrs, required_attrs)
        if new_signature in existing_signatures:
            findings.append(
                VariationResolutionFinding(
                    code="DUPLICATE_VARIATION_ATTRIBUTES",
                    message="New child duplicates an existing variation attribute combination.",
                    details={"signature": list(new_signature)},
                )
            )

        decision = "blocked" if any(item.blocking for item in findings) else "passed"
        return self._finish(
            VariationResolutionResult(
                mode="append_child",
                decision=decision,
                variation_theme=existing_theme,
                parent_sku=parent_sku,
                child_attributes={sku: selected_attrs} if decision == "passed" else {},
                blocking_codes=[item.code for item in findings if item.blocking],
                findings=findings,
                candidate_snapshot={existing_theme: candidate_snapshot},
                existing_family_snapshot={
                    "parent_sku": parent_sku,
                    "variation_theme": existing_theme,
                    "children": existing_children,
                },
            ),
            product_type,
            [sku],
        )

    def _finish(
        self,
        result: VariationResolutionResult,
        product_type: str,
        child_skus: List[str],
    ) -> VariationResolutionResult:
        result.audit_run_id = self.audit_repo.insert_run(
            mode=result.mode,
            parent_sku=result.parent_sku,
            product_type=product_type,
            selected_theme=result.variation_theme,
            decision=result.decision,
            child_skus=child_skus,
            candidate_snapshot=result.candidate_snapshot,
            score_snapshot=result.score_snapshot,
            existing_family_snapshot=result.existing_family_snapshot,
            finding_snapshot=[item.as_dict() for item in result.findings],
            resolver_version=self.version,
        )
        return result

    def _score_theme(
        self,
        theme: str,
        child_attrs: Dict[str, Dict[str, Any]],
        required_attrs: List[str],
        category_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        weights = self.config.get("defaults", {}).get("weights", {})
        minimum = self.config.get("defaults", {}).get("minimum_auto_pass_score", 70)
        child_count = len(child_attrs)
        complete_count = sum(
            1
            for attrs in child_attrs.values()
            if all(attrs.get(key) for key in required_attrs)
        )
        coverage = complete_count / child_count if child_count else 0
        signatures = [
            self._signature(attrs, required_attrs)
            for attrs in child_attrs.values()
            if all(attrs.get(key) for key in required_attrs)
        ]
        unique = len(signatures) == child_count and len(set(signatures)) == child_count
        buyer_relevance = category_config.get("buyer_theme_priority", {}).get(theme, 0)
        data_confidence = 100 if coverage == 1 else round(coverage * 100, 2)
        simplicity = 100 if len(required_attrs) == 1 else 70
        metric = {
            "uniqueness": 100 if unique else 0,
            "buyer_relevance": buyer_relevance,
            "data_confidence": data_confidence,
            "simplicity": simplicity,
            "coverage": round(coverage * 100, 2),
        }
        score = round(
            sum((metric.get(key, 0) / 100) * float(weight) for key, weight in weights.items()),
            2,
        )
        return {
            **metric,
            "score": score,
            "unique": unique,
            "eligible": unique and coverage == 1 and score >= minimum,
            "required_attributes": required_attrs,
        }

    def _extract_child_attributes(
        self,
        family_data: List[Dict[str, Any]],
        product_type: str,
        required_attrs: List[str],
    ) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        category_config = self._category_config(product_type)
        sources = category_config.get("attribute_sources", {})
        child_attrs: Dict[str, Dict[str, Any]] = {}
        snapshot: Dict[str, Any] = {}
        for product in family_data:
            sku = str(product.get("meow_sku") or "")
            child_attrs[sku] = {}
            snapshot[sku] = {}
            for attr_name in required_attrs:
                value, source = self._first_value(
                    product,
                    sources.get(attr_name, []),
                    attr_name,
                )
                normalized = self._normalize_value(value, attr_name)
                if normalized:
                    child_attrs[sku][attr_name] = normalized
                snapshot[sku][attr_name] = {
                    "value": normalized,
                    "source": source,
                    "confidence": 0.95 if normalized else 0,
                }
        return child_attrs, snapshot

    def _category_config(self, product_type: str) -> Dict[str, Any]:
        categories = self.config.get("categories", {})
        return categories.get(str(product_type or "").upper(), {})

    def _theme_attributes(self, theme: str) -> List[str]:
        return list(self._THEME_ATTRIBUTES.get(theme, []))

    @staticmethod
    def _signature(attrs: Dict[str, Any], required_attrs: List[str]) -> tuple:
        return tuple(str(attrs.get(key) or "").strip().lower() for key in required_attrs)

    @staticmethod
    def _first_value(
        product: Dict[str, Any],
        paths: List[str],
        attr_name: str,
    ) -> tuple[Any, Optional[str]]:
        for path in paths:
            value = AmazonVariationResolver._value_at_path(product, path)
            if not AmazonVariationResolver._is_missing_value(value):
                if attr_name == "size_name":
                    value = AmazonVariationResolver._size_value(value)
                if not AmazonVariationResolver._is_missing_value(value):
                    return value, path
        return None, None

    @staticmethod
    def _is_missing_value(value: Any) -> bool:
        if value is None or value == "":
            return True
        text = str(value).strip().lower()
        return text in {"n/a", "na", "not applicable", "none", "null", "-"}

    @staticmethod
    def _size_value(value: Any) -> Any:
        if AmazonVariationResolver._is_missing_value(value):
            return None
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        try:
            return float(text)
        except ValueError:
            pass
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:inches|inch|in|\"|”)", text, re.I)
        return match.group(1) if match else None

    @staticmethod
    def _value_at_path(product: Dict[str, Any], path: str) -> Any:
        if path.startswith("raw."):
            current: Any = product.get("raw_data") or {}
            parts = path.split(".")[1:]
        else:
            current = product
            parts = path.split(".")
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    @staticmethod
    def _normalize_value(value: Any, attr_name: str = "") -> str:
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, int):
            return str(value)
        text = str(value).strip()
        if AmazonVariationResolver._is_missing_value(text):
            return ""
        if attr_name == "size_name":
            text = str(AmazonVariationResolver._size_value(text) or "").strip()
        if text.endswith(".0"):
            return text[:-2]
        return text

    @staticmethod
    def _load_config(config_path: Optional[Path]) -> Dict[str, Any]:
        path = config_path or (
            Path(__file__).resolve().parents[2]
            / "config"
            / "listing_gates"
            / "variation_theme_strategy.yaml"
        )
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
