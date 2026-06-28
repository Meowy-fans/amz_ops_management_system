"""Path-level evidence resolver for Listing Requirement & Payload Engine V2."""

from __future__ import annotations

from difflib import get_close_matches
from typing import Any, Dict

from src.models.amazon_listing import AmazonListingDraft
from src.services.attribute_transform_helpers import (
    join_text_value,
    normalize_country_of_origin,
    parse_integer_value,
    scan_enum_token,
)
from src.services.requirement_models_v2 import RequirementNode, ResolutionNode


class EvidenceResolverV2:
    """Resolve RequirementTree paths into ResolutionTree nodes."""

    def __init__(self, schema_service: Any = None, llm_extractor: Any = None):
        self.schema_service = schema_service
        self.llm_extractor = llm_extractor

    def resolve(
        self,
        requirement_root: RequirementNode,
        draft: AmazonListingDraft,
        rules: Dict[str, Any],
        overrides: Dict[str, Any] | None = None,
        candidate_attributes: Dict[str, Any] | None = None,
    ) -> ResolutionNode:
        override_map = overrides or {}
        candidate_map = candidate_attributes or {}
        root = ResolutionNode(path_key=requirement_root.path_key)
        for requirement in requirement_root.children:
            rule = (rules.get("attributes") or {}).get(requirement.path_key) or {}
            root.children.append(
                self._resolve_node(
                    requirement,
                    draft,
                    rule,
                    override_map,
                    candidate_map,
                    str(rules.get("version") or ""),
                )
            )
        return root

    def _resolve_node(
        self,
        requirement: RequirementNode,
        draft: AmazonListingDraft,
        rule: Dict[str, Any],
        overrides: Dict[str, Any],
        candidate_attributes: Dict[str, Any],
        rule_version: str,
    ) -> ResolutionNode:
        if requirement.path_key in overrides:
            node = self._override_node(requirement, overrides[requirement.path_key])
        else:
            node = self._rule_node(
                requirement,
                draft,
                rule,
                rule_version,
                candidate_attributes,
            )
        for child in requirement.children:
            child_rule = ((rule.get("children") or {}).get(child.name) or {})
            if child.path_key in overrides:
                node.children.append(
                    self._override_node(child, overrides[child.path_key])
                )
                continue
            inherited = self._inherited_child_node(child, node, child_rule)
            if inherited is not None:
                node.children.append(inherited)
            else:
                node.children.append(
                    self._resolve_node(
                        child,
                        draft,
                        child_rule,
                        overrides,
                        candidate_attributes,
                        rule_version,
                    )
                )
        self._resolve_rule_only_children(
            node=node,
            requirement=requirement,
            rule=rule,
            draft=draft,
            overrides=overrides,
            candidate_attributes=candidate_attributes,
            rule_version=rule_version,
        )
        return node

    def _resolve_rule_only_children(
        self,
        node: ResolutionNode,
        requirement: RequirementNode,
        rule: Dict[str, Any],
        draft: AmazonListingDraft,
        overrides: Dict[str, Any],
        candidate_attributes: Dict[str, Any],
        rule_version: str,
    ) -> None:
        """Resolve YAML children that are not present on the RequirementTree.

        Required array_object parents such as TABLE.frame only declare optional
        schema children, but category rules still map nested fields like
        frame.material. Without this pass the parent stays blocking even when
        OptionalRuleChildrenEnricher later renders a valid payload.
        """
        schema_child_names = {child.name for child in requirement.children}
        from src.services.optional_rule_children_enricher_v2 import (
            OptionalRuleChildrenEnricherV2,
        )

        enricher = OptionalRuleChildrenEnricherV2()
        for child_name, child_rule in (rule.get("children") or {}).items():
            if child_name in schema_child_names:
                continue
            child_requirement = enricher._requirement_from_rule(
                requirement.name,
                str(child_name),
                child_rule,
            )
            if child_requirement.path_key in overrides:
                node.children.append(
                    self._override_node(child_requirement, overrides[child_requirement.path_key])
                )
                continue
            node.children.append(
                self._resolve_node(
                    child_requirement,
                    draft,
                    child_rule,
                    overrides,
                    candidate_attributes,
                    rule_version,
                )
            )

    def _rule_node(
        self,
        requirement: RequirementNode,
        draft: AmazonListingDraft,
        rule: Dict[str, Any],
        rule_version: str,
        candidate_attributes: Dict[str, Any],
    ) -> ResolutionNode:
        transform = str(rule.get("transform") or "text")
        for source in rule.get("sources") or []:
            raw_value, source_name, confidence, evidence, safe_default = self._read_source(
                draft,
                source,
                requirement,
            )
            if raw_value in (None, ""):
                continue
            value = self._transform(draft.product_type, requirement, raw_value, transform)
            if value in (None, ""):
                continue
            return self._finish(
                ResolutionNode(
                    path_key=requirement.path_key,
                    value=value,
                    source=source_name,
                    evidence=evidence or rule_version,
                    confidence=confidence,
                    safe_default=safe_default,
                ),
                requirement,
            )
        candidate_value = self._candidate_value(candidate_attributes, requirement)
        if candidate_value not in (None, "", []):
            return self._finish(
                ResolutionNode(
                    path_key=requirement.path_key,
                    value=candidate_value,
                    source=f"candidate_attributes.{requirement.path_key}",
                    evidence=f"candidate_attributes.{requirement.path_key}",
                    confidence="high",
                ),
                requirement,
            )
        return self._finish(ResolutionNode(path_key=requirement.path_key), requirement)

    def _override_node(self, requirement: RequirementNode, override: Any) -> ResolutionNode:
        metadata = override if isinstance(override, dict) else {"value": override}
        return ResolutionNode(
            path_key=requirement.path_key,
            value=metadata.get("value"),
            source=metadata.get("source", "review_override"),
            evidence=metadata.get("evidence", "Reviewed path override"),
            confidence=metadata.get("confidence", "high"),
            confidence_score=metadata.get("confidence_score"),
            review_status=metadata.get("review_status", "completed"),
            review_route=metadata.get("review_route", "human"),
            safe_default=bool(metadata.get("safe_default", False)),
            blocking=False,
        )

    def _inherited_child_node(
        self,
        requirement: RequirementNode,
        parent: ResolutionNode,
        child_rule: Dict[str, Any],
    ) -> ResolutionNode | None:
        if child_rule or parent.value in (None, ""):
            return None
        value = None
        if isinstance(parent.value, dict):
            value = parent.value.get(requirement.name)
        elif isinstance(parent.value, list):
            values = []
            for item in parent.value:
                if isinstance(item, dict) and requirement.name in item:
                    values.append(item.get(requirement.name))
                elif requirement.name == "value":
                    values.append(item)
            value = [item for item in values if item not in (None, "", [])]
        elif requirement.name == "value":
            value = parent.value
        if value in (None, ""):
            return None
        return self._finish(
            ResolutionNode(
                path_key=requirement.path_key,
                value=value,
                source=parent.source,
                evidence=parent.evidence,
                confidence=parent.confidence,
                confidence_score=parent.confidence_score,
                review_status=parent.review_status,
                review_route=parent.review_route,
                safe_default=parent.safe_default,
            ),
            requirement,
        )

    def _read_source(
        self,
        draft: AmazonListingDraft,
        source: Dict[str, Any],
        requirement: RequirementNode,
    ) -> tuple[Any, str, str, str, bool]:
        if "default" in source:
            return (
                source.get("default"),
                "default",
                source.get("confidence", "medium"),
                source.get("evidence", ""),
                bool(source.get("safe_default", False)),
            )
        if "llm" in source:
            return self._read_llm_source(draft, requirement)
        path = source.get("path")
        if not path:
            return None, "", "low", "", False
        return (
            self._path_value(draft, str(path)),
            str(path),
            source.get("confidence", "high"),
            source.get("evidence", str(path)),
            False,
        )

    @staticmethod
    def _candidate_value(
        candidate_attributes: Dict[str, Any],
        requirement: RequirementNode,
    ) -> Any:
        for key in (requirement.path_key, requirement.name):
            value = candidate_attributes.get(key)
            if value not in (None, "", []):
                return value
        return None

    def _read_llm_source(
        self,
        draft: AmazonListingDraft,
        requirement: RequirementNode,
    ) -> tuple[Any, str, str, str, bool]:
        if self.llm_extractor is None:
            return None, "llm", "low", "", False
        extraction = self.llm_extractor.extract(draft, requirement)
        if extraction.value in (None, ""):
            return None, "llm", "low", "", False
        return extraction.value, "llm", extraction.confidence, extraction.evidence, False

    def _transform(
        self,
        product_type: str,
        requirement: RequirementNode,
        value: Any,
        transform: str,
    ) -> Any:
        if transform == "integer":
            return parse_integer_value(value)
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
            return self._valid_value(product_type, requirement, value)
        if transform == "enum_scan":
            return self._scan_enum_value(product_type, requirement, value)
        if transform == "text_join":
            return join_text_value(value)
        if transform in {"passthrough", "raw"}:
            return value
        return str(value).strip() if value is not None else None

    def _valid_value(
        self,
        product_type: str,
        requirement: RequirementNode,
        value: Any,
    ) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text and value is not False:
            return text
        if self._is_country_of_origin(requirement):
            text = normalize_country_of_origin(text)
        candidates = requirement.enum_values
        if not candidates and self.schema_service is not None:
            try:
                candidates = (
                    self.schema_service.get_cached_valid_values(
                        product_type,
                        requirement.name,
                    )
                    or []
                )
            except Exception:
                candidates = []
        if not candidates:
            return text
        exact = {str(item).lower(): str(item) for item in candidates}
        if text.lower() in exact:
            return exact[text.lower()]
        match = get_close_matches(text.lower(), list(exact.keys()), n=1, cutoff=0.75)
        return exact[match[0]] if match else text

    def _scan_enum_value(
        self,
        product_type: str,
        requirement: RequirementNode,
        value: Any,
    ) -> str | None:
        candidates = list(requirement.enum_values or [])
        if not candidates and self.schema_service is not None:
            try:
                candidates = (
                    self.schema_service.get_cached_valid_values(
                        product_type,
                        requirement.name,
                    )
                    or []
                )
            except Exception:
                candidates = []
        if not candidates:
            return None
        return scan_enum_token(value, candidates)

    @staticmethod
    def _is_country_of_origin(requirement: RequirementNode) -> bool:
        if requirement.name == "country_of_origin":
            return True
        return "country_of_origin" in str(requirement.path_key or "")

    def _finish(
        self,
        node: ResolutionNode,
        requirement: RequirementNode,
    ) -> ResolutionNode:
        if node.value in (None, ""):
            if requirement.required and not requirement.children:
                node.blocking = True
                node.blocking_codes.append("MISSING_REQUIRED_ATTRIBUTE_RULE")
            return node
        if node.confidence == "low":
            if requirement.required:
                node.blocking = True
                node.blocking_codes.append("LOW_CONFIDENCE_REQUIRED_ATTRIBUTE")
            return node
        if node.source == "default" and not node.safe_default and requirement.required:
            node.blocking = True
            node.blocking_codes.append("UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE")
        return node

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
