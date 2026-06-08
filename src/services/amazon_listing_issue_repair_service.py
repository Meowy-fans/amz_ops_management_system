"""Repair planning and execution for Amazon listing issues."""
import logging
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class AmazonListingIssueRepairService:
    """Creates repair actions for synced Amazon listing issues."""

    AUTO_PATCH_ATTRIBUTES = {"recommended_uses_for_product"}
    PESTICIDE_CODES = {"18503"}
    IMAGE_CODES = {"18027", "100581"}

    def __init__(
        self,
        db: Session,
        reporter: Optional[ProgressReporter] = None,
        listings_client: Any = None,
        issue_repo: Any = None,
        schema_service: Any = None,
    ):
        self.db = db
        self.reporter = reporter or ProgressReporter()
        self._listings_client_instance = listings_client
        self._issue_repo_instance = issue_repo
        self._schema_service_instance = schema_service

    def plan_and_execute(
        self,
        issues: List[Dict[str, Any]],
        scan_run_id: Optional[int] = None,
        dry_run: bool = True,
    ) -> List[Dict[str, Any]]:
        """Plan repair actions and optionally submit safe automatic patches."""
        results: List[Dict[str, Any]] = []
        for issue in issues:
            action = self._plan_action(issue)
            result = self._record_or_execute(action, scan_run_id, dry_run)
            results.append(result)
        return results

    def repair_open_issues(
        self,
        source: Optional[str] = None,
        limit: Optional[int] = None,
        dry_run: bool = True,
    ) -> List[Dict[str, Any]]:
        """Plan and optionally repair currently open listing issues."""
        issues = self._issue_repo().get_open_issues(limit=limit, source=source)
        results = self.plan_and_execute(issues, dry_run=dry_run)
        self._emit_summary(results, dry_run=dry_run, label="Listing issue repair")
        return results

    def confirm_submitted_repairs(
        self,
        older_than_minutes: int = 30,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Re-check submitted repair actions after Amazon propagation delay."""
        actions = self._issue_repo().get_submitted_actions_for_confirmation(
            older_than_minutes=older_than_minutes,
            limit=limit,
        )
        results = []
        for action in actions:
            results.append(self._confirm_action(action, older_than_minutes))
        self._emit_summary(results, dry_run=False, label="Listing issue repair confirmation")
        return results

    def _plan_action(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        code = str(issue.get("issue_code") or "")
        attrs = self._as_list(issue.get("attribute_names"))
        categories = set(self._as_list(issue.get("categories")))
        message = issue.get("message") or ""

        if code in self.IMAGE_CODES or "INVALID_IMAGE" in categories:
            return self._manual_action(
                issue,
                "replace_main_image",
                "主图违规需要人工提供无文字、无 logo、无水印的合规图片 URL。",
            )

        if code in self.PESTICIDE_CODES or "QUALIFICATION_REQUIRED" in categories:
            return self._manual_action(
                issue,
                "qualification_or_claim_review",
                "需要 Seller Central 审批或人工复核并移除 pesticide/antimicrobial 相关宣称。",
            )

        if (
            "MISSING_ATTRIBUTE" in categories
            and any(attr in self.AUTO_PATCH_ATTRIBUTES for attr in attrs)
        ):
            return self._missing_attribute_action(issue)

        return self._manual_action(
            issue,
            "manual_review",
            f"暂未定义自动修复策略: code={code} message={message[:160]}",
        )

    def _missing_attribute_action(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        product_type = issue.get("product_type")
        marketplace_id = issue["marketplace_id"]
        attr_name = "recommended_uses_for_product"
        if not product_type:
            return self._manual_action(
                issue,
                "manual_review",
                "缺少 product_type，无法生成属性修复 payload。",
            )
        if not self._schema_has_property(product_type, attr_name):
            return self._manual_action(
                issue,
                "schema_required",
                f"未缓存 {product_type} schema 或 schema 中未确认 {attr_name}，先补 schema 再自动修复。",
            )

        proposal = self._recommended_use_value(issue)
        if proposal["confidence"] != "high":
            return self._manual_action(
                issue,
                "manual_review",
                f"缺少高置信度 {attr_name} 补全依据。",
            )
        patches = [
            {
                "op": "replace",
                "path": f"/attributes/{attr_name}",
                "value": [
                    {
                        "value": proposal["value"],
                        "language_tag": "en_US",
                        "marketplace_id": marketplace_id,
                    }
                ],
            }
        ]
        return {
            "issue": issue,
            "action_type": "patch_listing_attribute",
            "status": "planned",
            "reason": f"补充缺失属性 {attr_name}={proposal['value']}",
            "request_payload": {
                "productType": product_type,
                "patches": patches,
                "target_attribute": attr_name,
                "target_value": proposal["value"],
                "confidence": proposal["confidence"],
                "evidence": proposal["evidence"],
            },
        }

    def _record_or_execute(
        self,
        action: Dict[str, Any],
        scan_run_id: Optional[int],
        dry_run: bool,
    ) -> Dict[str, Any]:
        issue = action["issue"]
        repo = self._issue_repo()

        status = action["status"]
        response_body = None
        error_message = None
        if action["action_type"] == "patch_listing_attribute":
            if dry_run:
                status = "dry_run"
            else:
                try:
                    payload = action["request_payload"]
                    response = self._listings_client().patch_listings_item(
                        sku=issue["sku"],
                        product_type=payload["productType"],
                        patches=payload["patches"],
                    )
                    response_body = response.get("body")
                    patch_issues = (response_body or {}).get("issues") or []
                    patch_status = (response_body or {}).get("status", "ACCEPTED")
                    if patch_issues:
                        status = "patch_issues_found"
                    elif patch_status != "ACCEPTED":
                        status = "not_accepted"
                    else:
                        status = "submitted"
                except Exception as exc:
                    logger.error("Listing issue repair failed for %s: %s", issue["sku"], exc)
                    status = "failed"
                    error_message = str(exc)
        elif status == "planned":
            status = "manual_required"

        action_id = repo.insert_action(
            issue_id=issue.get("id"),
            scan_run_id=scan_run_id,
            sku=issue["sku"],
            marketplace_id=issue["marketplace_id"],
            product_type=issue.get("product_type"),
            action_type=action["action_type"],
            status=status,
            reason=action["reason"],
            request_payload=action.get("request_payload"),
            response_body=response_body,
            error_message=error_message,
        )
        return {
            "action_id": action_id,
            "sku": issue["sku"],
            "issue_code": issue.get("issue_code"),
            "action_type": action["action_type"],
            "status": status,
            "reason": action["reason"],
        }

    def _confirm_action(
        self,
        action: Dict[str, Any],
        older_than_minutes: int,
    ) -> Dict[str, Any]:
        repo = self._issue_repo()
        request_payload = self._as_dict(action.get("request_payload"))
        target_attribute = request_payload.get("target_attribute")
        try:
            response = self._listings_client().get_listings_item(
                sku=action["sku"],
                included_data=["summaries", "issues", "attributes", "productTypes"],
            )
            body = response.get("body") or {}
            remaining = self._matching_issues(body.get("issues") or [], action)
            status = "repair_failed" if remaining else "repair_confirmed"
            response_body = {
                "source_action_id": action["id"],
                "target_attribute": target_attribute,
                "remaining_matching_issues": remaining,
                "body": body,
            }
            error_message = None
            if status == "repair_confirmed" and action.get("issue_id"):
                repo.mark_issue_resolved(action["issue_id"])
        except Exception as exc:
            status = "repair_confirmation_failed"
            response_body = {
                "source_action_id": action["id"],
                "target_attribute": target_attribute,
            }
            error_message = str(exc)

        action_id = repo.insert_action(
            issue_id=action.get("issue_id"),
            scan_run_id=action.get("scan_run_id"),
            sku=action["sku"],
            marketplace_id=action["marketplace_id"],
            product_type=action.get("product_type"),
            action_type="confirm_patch_listing_attribute",
            status=status,
            reason=f"确认 {target_attribute or 'listing attribute'} 修复结果",
            request_payload={
                "source_action_id": action["id"],
                "older_than_minutes": older_than_minutes,
                "target_attribute": target_attribute,
            },
            response_body=response_body,
            error_message=error_message,
        )
        return {
            "action_id": action_id,
            "source_action_id": action["id"],
            "sku": action["sku"],
            "issue_code": action.get("issue_code"),
            "action_type": "confirm_patch_listing_attribute",
            "status": status,
        }

    @staticmethod
    def _matching_issues(
        raw_issues: List[Dict[str, Any]],
        action: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        issue_code = str(action.get("issue_code") or "")
        target_attrs = set(AmazonListingIssueRepairService._as_list(action.get("attribute_names")))
        matches = []
        for raw_issue in raw_issues:
            attrs = set(
                AmazonListingIssueRepairService._as_list(raw_issue.get("attributeNames"))
            )
            if str(raw_issue.get("code") or "") != issue_code:
                continue
            if target_attrs and attrs and not target_attrs.intersection(attrs):
                continue
            matches.append(raw_issue)
        return matches

    def _manual_action(
        self,
        issue: Dict[str, Any],
        action_type: str,
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "issue": issue,
            "action_type": action_type,
            "status": "planned",
            "reason": reason,
            "request_payload": None,
        }

    def _schema_has_property(self, product_type: str, property_name: str) -> bool:
        try:
            schema_service = self._schema_service()
            data = schema_service.get_cached_schema(product_type)
        except Exception:
            return False
        if not data:
            return False
        schema = data.get("schema_json") or {}
        props = dict(schema.get("properties", {}))
        for part in schema.get("allOf", []):
            props.update(part.get("properties", {}))
        return property_name in props

    @staticmethod
    def _recommended_use_value(issue: Dict[str, Any]) -> Dict[str, Any]:
        product_type = (issue.get("product_type") or "").upper()
        text = " ".join(
            str(issue.get(key) or "")
            for key in ("sku", "asin", "message", "item_name")
        ).lower()
        evidence = []
        item_name = issue.get("item_name")
        if item_name:
            evidence.append(str(item_name))
        if product_type:
            evidence.append(f"product_type={product_type}")
        if "bathroom" in text or product_type in {"CABINET", "HOME_MIRROR"}:
            return {
                "value": "Bathroom",
                "confidence": "high",
                "evidence": evidence or ["bathroom/category rule"],
            }
        return {
            "value": "Home",
            "confidence": "medium",
            "evidence": evidence or ["default home rule"],
        }

    @staticmethod
    def _as_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]

    def _listings_client(self):
        if self._listings_client_instance is not None:
            return self._listings_client_instance
        from infrastructure.amazon.listings_client import AmazonListingsClient

        self._listings_client_instance = AmazonListingsClient()
        return self._listings_client_instance

    def _issue_repo(self):
        if self._issue_repo_instance is not None:
            return self._issue_repo_instance
        from src.repositories.amazon_listing_issue_repository import (
            AmazonListingIssueRepository,
        )

        self._issue_repo_instance = AmazonListingIssueRepository(self.db)
        return self._issue_repo_instance

    def _schema_service(self):
        if self._schema_service_instance is not None:
            return self._schema_service_instance
        from src.services.amazon_schema_service import AmazonSchemaService

        self._schema_service_instance = AmazonSchemaService(self.db)
        return self._schema_service_instance

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            return json.loads(value)
        return {}

    def _emit_summary(
        self,
        results: List[Dict[str, Any]],
        dry_run: bool,
        label: str,
    ) -> None:
        counts: Dict[str, int] = {}
        for result in results:
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        mode = "DRY RUN" if dry_run else "LIVE"
        self.reporter.emit(f"{label} complete - {mode}: {len(results)} action(s)")
        for status, count in sorted(counts.items()):
            self.reporter.emit(f"  {status}: {count}")
