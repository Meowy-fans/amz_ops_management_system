"""Coordinates online hierarchy audit for append-child variation plans."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class VariationHierarchyAuditCoordinator:
    """Runs probe, gate evaluation, and audit persistence for one append child."""

    def __init__(self, service: Any):
        self.service = service

    def apply(
        self,
        result: Any,
        parent_sku: str,
        existing_theme: str,
        existing_children: List[Dict[str, Any]],
    ) -> None:
        try:
            _sku, selected_attrs = next(iter(result.child_attributes.items()))
        except Exception:
            return
        try:
            probe_result = self._get_probe().probe_parent(parent_sku)
            audit_result = self._get_gate().evaluate(
                parent_sku=parent_sku,
                existing_theme=existing_theme,
                selected_attrs=selected_attrs,
                existing_children=existing_children,
                probe_result=probe_result,
            )
        except Exception as exc:
            logger.warning(
                "Online variation hierarchy audit skipped for parent=%s: %s",
                parent_sku,
                exc,
            )
            return

        self._attach_result(result, audit_result)
        self._update_run(result)

    def _attach_result(self, result: Any, audit_result: Any) -> None:
        if audit_result.warning_codes:
            for code in audit_result.warning_codes:
                if code not in result.warning_codes:
                    result.warning_codes.append(code)
        if audit_result.findings:
            result.findings.extend(audit_result.findings)
        result.existing_family_snapshot = {
            **(result.existing_family_snapshot or {}),
            "online_hierarchy_audit": audit_result.as_dict(),
        }
        if not audit_result.blocked:
            return
        result.decision = "blocked"
        result.child_attributes = {}
        for code in audit_result.blocking_codes:
            if code not in result.blocking_codes:
                result.blocking_codes.append(code)

    def _get_probe(self):
        if hasattr(self.service, "_variation_hierarchy_probe_instance"):
            return self.service._variation_hierarchy_probe_instance
        from infrastructure.amazon.catalog_client import AmazonCatalogClient
        from infrastructure.amazon.listings_client import AmazonListingsClient
        from src.services.variation_hierarchy_probe import VariationHierarchyProbe

        self.service._variation_hierarchy_probe_instance = VariationHierarchyProbe(
            listings_client=AmazonListingsClient(),
            catalog_client=AmazonCatalogClient(),
        )
        return self.service._variation_hierarchy_probe_instance

    def _get_gate(self):
        if hasattr(self.service, "_variation_hierarchy_audit_gate_instance"):
            return self.service._variation_hierarchy_audit_gate_instance
        from src.services.variation_hierarchy_audit_gate import (
            VariationHierarchyAuditGate,
        )

        self.service._variation_hierarchy_audit_gate_instance = (
            VariationHierarchyAuditGate()
        )
        return self.service._variation_hierarchy_audit_gate_instance

    def _update_run(self, result: Any) -> None:
        run_id = getattr(result, "audit_run_id", None)
        if not run_id:
            return
        try:
            self._get_repo().update_run_audit(
                run_id=run_id,
                existing_family_snapshot=result.existing_family_snapshot,
                finding_snapshot=[item.as_dict() for item in result.findings],
                decision=result.decision,
            )
        except Exception as exc:
            logger.warning(
                "Failed to update variation hierarchy audit run_id=%s: %s",
                run_id,
                exc,
            )

    def _get_repo(self):
        if hasattr(self.service, "_variation_resolution_repo_instance"):
            return self.service._variation_resolution_repo_instance
        from src.repositories.amazon_variation_resolution_repository import (
            AmazonVariationResolutionRepository,
        )

        self.service._variation_resolution_repo_instance = (
            AmazonVariationResolutionRepository(self.service.db)
        )
        return self.service._variation_resolution_repo_instance
