"""Repair planning and execution for Amazon listing issues."""
import logging
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

        value = self._recommended_use_value(issue)
        patches = [
            {
                "op": "replace",
                "path": f"/attributes/{attr_name}",
                "value": [
                    {
                        "value": value,
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
            "reason": f"补充缺失属性 {attr_name}={value}",
            "request_payload": {
                "productType": product_type,
                "patches": patches,
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
                    status = "submitted"
                    response_body = response.get("body")
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
    def _recommended_use_value(issue: Dict[str, Any]) -> str:
        product_type = (issue.get("product_type") or "").upper()
        text = " ".join(
            str(issue.get(key) or "")
            for key in ("sku", "asin", "message", "item_name")
        ).lower()
        if product_type in {"CABINET", "HOME_MIRROR"} or "bathroom" in text:
            return "Bathroom"
        return "Home"

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
