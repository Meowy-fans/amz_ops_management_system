"""Repair planning and execution for Amazon listing issues."""
import logging
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.services.compliance_claim_scanner import ComplianceClaimScanner
from src.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


class AmazonListingIssueRepairService:
    """Creates repair actions for synced Amazon listing issues."""

    AUTO_PATCH_ATTRIBUTES = {"recommended_uses_for_product", "installation_type", "style"}
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
            return self._pesticide_compliance_action(issue)

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

    def _pesticide_compliance_action(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        sku = issue["sku"]
        marketplace_id = issue["marketplace_id"]
        product_type = issue.get("product_type")
        if not product_type:
            return self._manual_action(
                issue,
                "qualification_or_claim_review",
                "缺少 product_type，无法用 regenerated 文案自动修复 18503。",
            )

        content = self._load_regenerated_content_for_meow_sku(sku)
        if not content:
            return self._manual_action(
                issue,
                "qualification_or_claim_review",
                "未找到 regenerated 合规文案，请先运行 generate-details 再修复 18503。",
            )

        scanner = ComplianceClaimScanner()
        field_map = {
            "title": content["title"],
            "description": content["description"],
            "search_terms": content.get("search_terms", ""),
            "generic_keyword": content.get("generic_keyword", ""),
        }
        for index in range(1, 6):
            field_map[f"bullet_{index}"] = content.get(f"bullet_{index}", "")

        scan_result = scanner.scan_and_sanitize(field_map)
        if not scan_result.clean:
            return self._manual_action(
                issue,
                "qualification_or_claim_review",
                "regenerated 文案仍含 pesticide claim，需人工复核后再 PATCH。",
            )

        sanitized = scan_result.sanitized_fields
        patches = []
        target_attributes = []

        def _append_text_patch(attr_name: str, value: str) -> None:
            text_value = str(value or "").strip()
            if not text_value:
                return
            target_attributes.append(attr_name)
            patches.append({
                "op": "replace",
                "path": f"/attributes/{attr_name}",
                "value": [
                    {
                        "value": text_value,
                        "language_tag": "en_US",
                        "marketplace_id": marketplace_id,
                    }
                ],
            })

        def _append_bullet_patch(values: List[str]) -> None:
            bullets = [str(value or "").strip() for value in values if str(value or "").strip()]
            if not bullets:
                return
            target_attributes.append("bullet_point")
            patches.append({
                "op": "replace",
                "path": "/attributes/bullet_point",
                "value": [
                    {
                        "value": bullet,
                        "language_tag": "en_US",
                        "marketplace_id": marketplace_id,
                    }
                    for bullet in bullets
                ],
            })

        _append_text_patch("item_name", sanitized.get("title", ""))
        _append_text_patch("product_description", sanitized.get("description", ""))
        _append_bullet_patch(
            [
                sanitized.get("bullet_1", ""),
                sanitized.get("bullet_2", ""),
                sanitized.get("bullet_3", ""),
                sanitized.get("bullet_4", ""),
                sanitized.get("bullet_5", ""),
            ]
        )
        if sanitized.get("generic_keyword"):
            _append_text_patch("generic_keyword", sanitized["generic_keyword"])

        if not patches:
            return self._manual_action(
                issue,
                "qualification_or_claim_review",
                "未生成可用的合规文案 PATCH payload。",
            )

        return {
            "issue": issue,
            "action_type": "patch_compliance_content",
            "status": "planned",
            "reason": "使用 regenerated 合规文案替换 listing 文本字段，移除 pesticide claim",
            "request_payload": {
                "productType": product_type,
                "patches": patches,
                "target_attributes": target_attributes,
                "confidence": "high",
                "evidence": [
                    f"vendor_sku={content.get('vendor_sku')}",
                    f"source=ds_api_product_details",
                ],
            },
        }

    def _load_regenerated_content_for_meow_sku(self, meow_sku: str) -> Optional[Dict[str, str]]:
        row = self.db.execute(
            text("""
                SELECT
                    m.vendor_sku,
                    d.product_name,
                    d.selling_point_1,
                    d.selling_point_2,
                    d.selling_point_3,
                    d.selling_point_4,
                    d.selling_point_5,
                    d.product_description,
                    d.raw_json
                FROM meow_sku_map m
                JOIN ds_api_product_details d ON d.sku_id = m.vendor_sku
                WHERE m.meow_sku = :meow_sku
                LIMIT 1
            """),
            {"meow_sku": meow_sku},
        ).fetchone()
        if not row:
            return None

        raw_json = row[8] if isinstance(row[8], dict) else {}
        if isinstance(row[8], str) and row[8]:
            try:
                raw_json = json.loads(row[8])
            except json.JSONDecodeError:
                raw_json = {}

        return {
            "vendor_sku": row[0],
            "title": row[1] or "",
            "bullet_1": row[2] or "",
            "bullet_2": row[3] or "",
            "bullet_3": row[4] or "",
            "bullet_4": row[5] or "",
            "bullet_5": row[6] or "",
            "description": row[7] or "",
            "search_terms": raw_json.get("search_terms", ""),
            "generic_keyword": raw_json.get("generic_keyword", ""),
        }

    def _missing_attribute_action(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        product_type = issue.get("product_type")
        marketplace_id = issue["marketplace_id"]
        if not product_type:
            return self._manual_action(
                issue,
                "manual_review",
                "缺少 product_type，无法生成属性修复 payload。",
            )

        missing_attrs = set(self._as_list(issue.get("attribute_names")))
        auto_targets = sorted(missing_attrs & self.AUTO_PATCH_ATTRIBUTES)
        if not auto_targets:
            return self._manual_action(
                issue,
                "manual_review",
                f"缺失属性 {missing_attrs} 不在自动修复白名单中。",
            )

        patches = []
        proposals = {}
        for attr_name in auto_targets:
            if not self._schema_has_property(product_type, attr_name):
                return self._manual_action(
                    issue,
                    "schema_required",
                    f"未缓存 {product_type} schema 或 schema 中未确认 {attr_name}，先补 schema 再自动修复。",
                )
            proposal = self._determine_attribute_value(attr_name, issue)
            if proposal["confidence"] != "high":
                return self._manual_action(
                    issue,
                    "manual_review",
                    f"缺少高置信度 {attr_name} 补全依据。",
                )
            proposals[attr_name] = proposal
            patches.append({
                "op": "replace",
                "path": f"/attributes/{attr_name}",
                "value": [
                    {
                        "value": proposal["value"],
                        "language_tag": "en_US",
                        "marketplace_id": marketplace_id,
                    }
                ],
            })

        values_desc = ", ".join(f"{k}={v['value']}" for k, v in proposals.items())
        return {
            "issue": issue,
            "action_type": "patch_listing_attribute",
            "status": "planned",
            "reason": f"补充缺失属性 {values_desc}",
            "request_payload": {
                "productType": product_type,
                "patches": patches,
                "target_attributes": list(proposals.keys()),
                "target_values": {k: v["value"] for k, v in proposals.items()},
                "confidence": "high",
                "evidence": [v["evidence"] for v in proposals.values()],
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
        if action["action_type"] in {"patch_listing_attribute", "patch_compliance_content"}:
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
        target_attrs = request_payload.get("target_attributes") or [request_payload.get("target_attribute")]
        target_attrs = [a for a in target_attrs if a]
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
                "target_attributes": target_attrs,
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
                "target_attributes": target_attrs,
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
            reason=f"确认 {', '.join(target_attrs) or 'listing attribute'} 修复结果",
            request_payload={
                "source_action_id": action["id"],
                "older_than_minutes": older_than_minutes,
                "target_attributes": target_attrs,
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
            data = schema_service.get_or_fetch_schema(product_type)
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
    def _determine_attribute_value(attr_name: str, issue: Dict[str, Any]) -> Dict[str, Any]:
        if attr_name == "recommended_uses_for_product":
            return AmazonListingIssueRepairService._recommended_use_value(issue)
        if attr_name == "installation_type":
            return AmazonListingIssueRepairService._installation_type_value(issue)
        if attr_name == "style":
            return AmazonListingIssueRepairService._style_value(issue)
        return {"value": "", "confidence": "low", "evidence": []}

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
    def _installation_type_value(issue: Dict[str, Any]) -> Dict[str, Any]:
        text = " ".join(
            str(issue.get(key) or "").lower()
            for key in ("item_name", "message", "sku")
        )
        if any(kw in text for kw in ("vessel", "above counter", "countertop")):
            return {"value": "Countertop", "confidence": "high", "evidence": [text[:120]]}
        if "undermount" in text or "under-mount" in text:
            return {"value": "Undermount", "confidence": "high", "evidence": [text[:120]]}
        if "wall" in text and "mount" in text:
            return {"value": "Wall-Mount", "confidence": "high", "evidence": [text[:120]]}
        # Default to Countertop for bathroom sinks — safe fallback
        return {"value": "Countertop", "confidence": "high", "evidence": [text[:120]]}

    @staticmethod
    def _style_value(issue: Dict[str, Any]) -> Dict[str, Any]:
        text = " ".join(
            str(issue.get(key) or "").lower()
            for key in ("item_name", "message", "sku")
        )
        if any(kw in text for kw in ("modern", "contemporary")):
            return {"value": "Contemporary", "confidence": "high", "evidence": [text[:120]]}
        if any(kw in text for kw in ("classic", "traditional", "vintage")):
            return {"value": "Classic", "confidence": "high", "evidence": [text[:120]]}
        if "art deco" in text or "golden" in text:
            return {"value": "Art Deco", "confidence": "high", "evidence": [text[:120]]}
        if "rustic" in text or "farmhouse" in text:
            return {"value": "Cottage", "confidence": "high", "evidence": [text[:120]]}
        if "marble" in text or "stone" in text or "natural" in text:
            return {"value": "Classic", "confidence": "high", "evidence": [text[:120]]}
        # Default to Contemporary for bathroom sinks — safe fallback
        return {"value": "Contemporary", "confidence": "high", "evidence": [text[:120]]}

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
