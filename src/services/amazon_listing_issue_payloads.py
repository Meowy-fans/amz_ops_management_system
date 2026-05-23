"""Helpers for normalizing Amazon listing issue payloads."""
import csv
import hashlib
import io
from typing import Any, Dict, List, Optional


def normalize_issue(
    sku: str,
    asin: Optional[str],
    marketplace_id: str,
    product_type: Optional[str],
    item_name: Optional[str],
    raw_issue: Dict[str, Any],
    source: str,
) -> Dict[str, Any]:
    """Build the canonical issue row persisted by the sync service."""
    attrs = raw_issue.get("attributeNames")
    categories = raw_issue.get("categories")
    message = raw_issue.get("message") or ""
    code = str(raw_issue.get("code") or "UNKNOWN")
    severity = str(raw_issue.get("severity") or "UNKNOWN")
    return {
        "sku": sku,
        "asin": asin,
        "marketplace_id": marketplace_id,
        "product_type": product_type,
        "item_name": item_name,
        "issue_key": issue_key(code, severity, attrs, categories, message, source),
        "issue_code": code,
        "severity": severity,
        "message": message,
        "attribute_names": attrs,
        "categories": categories,
        "enforcements": raw_issue.get("enforcements") or raw_issue.get("enforcementActions"),
        "raw_issue": raw_issue,
        "source": source,
    }


def parse_suppressed_report(
    report_text: str,
    marketplace_id: str,
    source: str,
) -> List[Dict[str, Any]]:
    """Parse GET_MERCHANTS_LISTINGS_FYP_REPORT TSV rows into issue dicts."""
    issues: List[Dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(report_text), delimiter="\t"):
        sku = (row.get("SKU") or "").strip()
        if not sku:
            continue
        raw_issue = {
            "code": "FYP_SUPPRESSED",
            "severity": "ERROR",
            "message": row.get("Issue Description") or row.get("Reason") or "",
            "categories": suppressed_categories(row),
            "report_row": row,
        }
        issues.append(
            normalize_issue(
                sku=sku,
                asin=row.get("ASIN"),
                marketplace_id=marketplace_id,
                product_type=None,
                item_name=row.get("Product name"),
                raw_issue=raw_issue,
                source=source,
            )
        )
    return issues


def suppressed_categories(row: Dict[str, str]) -> List[str]:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("Reason", "Issue Description", "Status")
    ).lower()
    categories = ["SEARCH_SUPPRESSED"]
    if "image" in text:
        categories.append("INVALID_IMAGE")
    if "invalid" in text:
        categories.append("INVALID_ATTRIBUTE")
    return categories


def issue_key(
    code: str,
    severity: str,
    attrs: Any,
    categories: Any,
    message: str,
    source: str,
) -> str:
    raw = "|".join(
        [
            source,
            code,
            severity,
            repr(attrs or []),
            repr(categories or []),
            message,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
