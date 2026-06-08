"""Export the latest price/inventory API update audit records to CSV."""

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import text

from infrastructure.db_pool import SessionLocal


def _json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        return json.loads(value)
    return {}


def _amount(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_patch_targets(payload: Dict[str, Any]) -> tuple[Optional[float], Optional[int]]:
    price = None
    quantity = None
    for patch in payload.get("patches") or []:
        path = patch.get("path")
        value = patch.get("value") or []
        if path == "/attributes/purchasable_offer":
            try:
                schedule = value[0]["our_price"][0]["schedule"][0]
                price = _amount(schedule.get("value_with_tax"))
            except (KeyError, IndexError, TypeError):
                pass
        if path == "/attributes/fulfillment_availability":
            try:
                quantity = int(value[0]["quantity"])
            except (KeyError, IndexError, TypeError, ValueError):
                pass
    return price, quantity


def _extract_listing_price(body: Dict[str, Any]) -> Optional[float]:
    for offer in body.get("offers") or []:
        for key in ("price", "listingPrice"):
            value = offer.get(key)
            if isinstance(value, dict):
                amount = value.get("amount") or value.get("value")
                if amount is not None:
                    return _amount(amount)
    try:
        schedule = body["attributes"]["purchasable_offer"][0]["our_price"][0]["schedule"][0]
        return _amount(schedule.get("value_with_tax"))
    except (KeyError, IndexError, TypeError):
        return None


def _extract_listing_quantity(body: Dict[str, Any]) -> Optional[int]:
    for item in body.get("fulfillmentAvailability") or []:
        if item.get("quantity") is not None:
            return int(item["quantity"])
    try:
        return int(body["attributes"]["fulfillment_availability"][0]["quantity"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _issue_summary(body: Dict[str, Any]) -> str:
    issues = body.get("issues") or []
    parts = []
    for issue in issues[:5]:
        code = issue.get("code") or issue.get("issueCode") or ""
        severity = issue.get("severity") or ""
        message = issue.get("message") or ""
        parts.append(f"{severity}:{code}:{message}".strip(":"))
    return " | ".join(parts)


def _operation_basis(status: str, response_body: Dict[str, Any]) -> str:
    if status == "skipped_no_change":
        return "Amazon current price/quantity already matched local targets before PATCH"
    if status == "blocked_listing_issue":
        return "Pre-PATCH getListingsItem returned ERROR issue; update blocked"
    confirmation = response_body.get("confirmation") or {}
    if status == "confirmed_with_mismatch":
        return f"PATCH accepted, post-PATCH GET still mismatched: {json.dumps(confirmation.get('mismatches') or {}, ensure_ascii=False)}"
    if status == "confirmed_with_issues":
        return "PATCH accepted, post-PATCH GET returned listing issues"
    if status == "update_confirmed":
        return "PATCH accepted and post-PATCH GET matched target price/quantity"
    if status == "issues_found":
        return "PATCH response contained issues"
    if status == "not_accepted":
        return "PATCH response status was not ACCEPTED"
    return status


def export(limit: int, output_path: Path) -> None:
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                WITH latest AS (
                    SELECT *
                    FROM amazon_api_submissions
                    ORDER BY id DESC
                    LIMIT :limit
                )
                SELECT
                    latest.id,
                    latest.sku,
                    msm.vendor_sku AS giga_sku,
                    latest.operation,
                    latest.status,
                    latest.product_type,
                    latest.marketplace_id,
                    latest.amazon_request_id,
                    latest.request_payload,
                    latest.response_body,
                    latest.error_message,
                    latest.submitted_at,
                    pfp.final_price AS local_target_price,
                    gi.quantity AS local_target_quantity,
                    gp.updated_at AS giga_price_updated_at,
                    gi.last_updated AS giga_inventory_updated_at
                FROM latest
                LEFT JOIN meow_sku_map msm ON latest.sku = msm.meow_sku
                LEFT JOIN product_final_prices pfp ON latest.sku = pfp.meow_sku
                LEFT JOIN giga_inventory gi ON msm.vendor_sku = gi.giga_sku
                LEFT JOIN giga_product_base_prices gp ON msm.vendor_sku = gp.giga_sku
                ORDER BY latest.id ASC
                """
            ),
            {"limit": limit},
        ).mappings().all()

        fieldnames = [
            "submission_id",
            "submitted_at",
            "amazon_sku",
            "giga_sku",
            "operation",
            "status",
            "product_type",
            "marketplace_id",
            "amazon_request_id",
            "local_target_price",
            "local_target_quantity",
            "giga_price_updated_at",
            "giga_inventory_updated_at",
            "patch_target_price",
            "patch_target_quantity",
            "confirmed_price",
            "confirmed_quantity",
            "mismatches_json",
            "issue_count",
            "issue_summary",
            "operation_basis",
            "request_payload_json",
            "response_body_json",
            "error_message",
        ]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8-sig") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                request_payload = _json(row["request_payload"])
                response_body = _json(row["response_body"])
                confirmation = response_body.get("confirmation") or {}
                confirm_body = _json(confirmation.get("body"))
                patch_price, patch_quantity = _extract_patch_targets(request_payload)
                issues = confirm_body.get("issues") or response_body.get("issues") or []
                writer.writerow(
                    {
                        "submission_id": row["id"],
                        "submitted_at": row["submitted_at"],
                        "amazon_sku": row["sku"],
                        "giga_sku": row["giga_sku"],
                        "operation": row["operation"],
                        "status": row["status"],
                        "product_type": row["product_type"],
                        "marketplace_id": row["marketplace_id"],
                        "amazon_request_id": row["amazon_request_id"],
                        "local_target_price": row["local_target_price"],
                        "local_target_quantity": row["local_target_quantity"],
                        "giga_price_updated_at": row["giga_price_updated_at"],
                        "giga_inventory_updated_at": row["giga_inventory_updated_at"],
                        "patch_target_price": patch_price,
                        "patch_target_quantity": patch_quantity,
                        "confirmed_price": _extract_listing_price(confirm_body),
                        "confirmed_quantity": _extract_listing_quantity(confirm_body),
                        "mismatches_json": json.dumps(
                            confirmation.get("mismatches") or {}, ensure_ascii=False
                        ),
                        "issue_count": len(issues),
                        "issue_summary": _issue_summary(confirm_body or response_body),
                        "operation_basis": _operation_basis(row["status"], response_body),
                        "request_payload_json": json.dumps(
                            request_payload, ensure_ascii=False
                        ),
                        "response_body_json": json.dumps(
                            response_body, ensure_ascii=False
                        ),
                        "error_message": row["error_message"],
                    }
                )
    finally:
        db.close()


if __name__ == "__main__":
    limit_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 273
    output_arg = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
        "output/audit_exports/latest_price_inventory_update_audit.csv"
    )
    export(limit_arg, output_arg)
    print(output_arg)
