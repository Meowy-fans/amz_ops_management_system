"""Pre-submit quality gate for Amazon listing payloads."""
import copy
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from infrastructure.amazon.config import AmazonConfig


class AmazonListingQualityGate:
    """Applies issue-derived checks before Listings Items API submission."""

    _PESTICIDE_PATTERNS = [
        r"\banti[-\s]?bacterial\b",
        r"\banti[-\s]?microbial\b",
        r"\bantimicrobial\b",
        r"\bbacteria(?:l)?\b",
        r"\bgerms?\b",
        r"\bdisinfect\w*\b",
        r"\bsanitiz\w*\b",
        r"\bvirus(?:es)?\b",
        r"\banti[-\s]?mold\b",
        r"\bmildew\b",
        r"\bpesticid\w*\b",
        r"\binsect(?:s)?\b",
    ]

    def __init__(
        self,
        schema_service: Any = None,
        marketplace_id: Optional[str] = None,
        require_reviewed_images: Optional[bool] = None,
    ):
        self.schema_service = schema_service
        self.marketplace_id = marketplace_id or AmazonConfig.MARKETPLACE_ID
        if require_reviewed_images is None:
            value = os.getenv("LISTING_QUALITY_REQUIRE_IMAGE_REVIEW", "false").lower()
            require_reviewed_images = value in {"1", "true", "yes"}
        self.require_reviewed_images = require_reviewed_images

    def prepare_plans(self, plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return copied plans with quality findings and blocking status."""
        return [self.prepare_plan(plan) for plan in plans]

    def prepare_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        prepared = copy.deepcopy(plan)
        prepared.setdefault("attributes", {})
        findings: List[Dict[str, Any]] = []

        self._auto_fill_recommended_use(prepared, findings)
        self._validate_cached_required_fields(prepared, findings)
        self._validate_cosmo_attributes(prepared, findings)
        self._scan_compliance_claims(prepared, findings)
        self._validate_issue_derived_ranges(prepared, findings)
        self._validate_images(prepared, findings)

        return {
            "plan": prepared,
            "blocked": any(item["blocking"] for item in findings),
            "findings": findings,
        }

    def _auto_fill_recommended_use(
        self,
        plan: Dict[str, Any],
        findings: List[Dict[str, Any]],
    ) -> None:
        product_type = (plan.get("product_type") or "").upper()
        attrs = plan["attributes"]
        if attrs.get("recommended_uses_for_product"):
            return
        value = self._recommended_use_value(product_type, attrs)
        if not value:
            return
        attrs["recommended_uses_for_product"] = [
            {
                "value": value,
                "language_tag": "en_US",
                "marketplace_id": self.marketplace_id,
            }
        ]
        findings.append(
            self._finding(
                "INFO",
                "AUTO_FILLED_RECOMMENDED_USE",
                f"Auto-filled recommended_uses_for_product={value}",
                ["recommended_uses_for_product"],
                blocking=False,
            )
        )

    def _validate_cached_required_fields(
        self,
        plan: Dict[str, Any],
        findings: List[Dict[str, Any]],
    ) -> None:
        if self.schema_service is None:
            return
        product_type = plan.get("product_type")
        if not product_type:
            return
        try:
            schema_data = self.schema_service.get_cached_schema(product_type)
        except Exception:
            return
        if not schema_data:
            findings.append(
                self._finding(
                    "WARNING",
                    "SCHEMA_NOT_CACHED",
                    f"No cached schema for product_type={product_type}",
                    [],
                    blocking=False,
                )
            )
            return
        required = schema_data.get("required_properties") or []
        attrs = plan.get("attributes") or {}
        missing = [name for name in required if not attrs.get(name)]
        for name in missing:
            findings.append(
                self._finding(
                    "ERROR",
                    "MISSING_REQUIRED_ATTRIBUTE",
                    f"Required property '{name}' is missing",
                    [name],
                    blocking=True,
                )
            )

    def _validate_cosmo_attributes(
        self,
        plan: Dict[str, Any],
        findings: List[Dict[str, Any]],
    ) -> None:
        """Check COSMO-critical backend attributes for completeness.

        These fields directly feed Amazon's COSMO knowledge graph and
        Rufus shopping assistant.  Missing fields = COSMO has less
        signal to recommend this product for intent-based queries.
        """
        attrs = plan.get("attributes") or {}
        cosmo_fields = [
            ("target_audience_base", "Target audience (e.g., 'Homeowners', 'DIYers')"),
            ("recommended_uses_for_product", "Intended use / what problem it solves"),
            ("item_type_name", "Product type classification"),
        ]
        missing = []
        for field_name, description in cosmo_fields:
            value = attrs.get(field_name)
            if not value or (isinstance(value, (list, str)) and not value):
                missing.append(f"  • {field_name}: {description}")

        if missing:
            findings.append(
                self._finding(
                    "WARNING",
                    "COSMO_ATTRIBUTE_INCOMPLETE",
                    "COSMO backend attributes missing (Rufus may not recommend):\n"
                    + "\n".join(missing),
                    [f.split(":")[0].strip(" •") for f in missing],
                    blocking=False,
                )
            )
    def _scan_compliance_claims(
        self,
        plan: Dict[str, Any],
        findings: List[Dict[str, Any]],
    ) -> None:
        text = " ".join(self._content_values(plan.get("attributes") or {}))
        for pattern in self._PESTICIDE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                findings.append(
                    self._finding(
                        "ERROR",
                        "PESTICIDE_CLAIM_RISK",
                        f"Potential pesticide/device claim found: '{match.group()}'",
                        ["item_name", "bullet_point", "product_description"],
                        blocking=True,
                    )
                )
                return

    def _validate_issue_derived_ranges(
        self,
        plan: Dict[str, Any],
        findings: List[Dict[str, Any]],
    ) -> None:
        product_type = (plan.get("product_type") or "").upper()
        if product_type != "CABINET":
            return
        dims = (plan.get("attributes") or {}).get("item_depth_width_height") or []
        first = dims[0] if isinstance(dims, list) and dims else {}
        width = ((first.get("width") or {}).get("value") if isinstance(first, dict) else None)
        try:
            width_value = float(width)
        except (TypeError, ValueError):
            return
        if width_value > 42:
            findings.append(
                self._finding(
                    "ERROR",
                    "ISSUE_DERIVED_DIMENSION_RANGE",
                    (
                        "CABINET item_depth_width_height.width exceeds observed "
                        f"Amazon max 42 inches: {width_value}"
                    ),
                    ["item_depth_width_height"],
                    blocking=True,
                )
            )

    def _validate_images(
        self,
        plan: Dict[str, Any],
        findings: List[Dict[str, Any]],
    ) -> None:
        attrs = plan.get("attributes") or {}
        main_images = attrs.get("main_product_image_locator") or []
        first = main_images[0] if isinstance(main_images, list) and main_images else {}
        url = first.get("media_location") if isinstance(first, dict) else None
        if not url:
            findings.append(
                self._finding(
                    "ERROR",
                    "MISSING_MAIN_IMAGE",
                    "main_product_image_locator is required before SP-API listing submission",
                    ["main_product_image_locator"],
                    blocking=True,
                )
            )
            return
        parsed = urlparse(str(url))
        if parsed.scheme != "https" or not parsed.netloc:
            findings.append(
                self._finding(
                    "ERROR",
                    "INVALID_MAIN_IMAGE_URL",
                    "Main image URL must be an absolute HTTPS URL",
                    ["main_product_image_locator"],
                    blocking=True,
                )
            )
            return
        if "gigab2b" in parsed.netloc or "b2bfiles" in parsed.netloc:
            findings.append(
                self._finding(
                    "WARNING",
                    "SUPPLIER_IMAGE_REVIEW_RECOMMENDED",
                    "Supplier-hosted main image should be reviewed for text/logo/watermark",
                    ["main_product_image_locator"],
                    blocking=self.require_reviewed_images,
                )
            )

    @staticmethod
    def _recommended_use_value(product_type: str, attrs: Dict[str, Any]) -> Optional[str]:
        text = " ".join(AmazonListingQualityGate._content_values(attrs)).lower()
        if product_type == "CABINET":
            return "Bathroom"
        if product_type == "HOME_MIRROR" and any(word in text for word in ("bathroom", "vanity")):
            return "Bathroom"
        return None

    @staticmethod
    def _content_values(attrs: Dict[str, Any]) -> List[str]:
        values: List[str] = []
        for key in ("item_name", "bullet_point", "product_description", "generic_keyword"):
            raw = attrs.get(key)
            if not raw:
                continue
            items = raw if isinstance(raw, list) else [raw]
            for item in items:
                if isinstance(item, dict) and item.get("value"):
                    values.append(str(item["value"]))
                elif isinstance(item, str):
                    values.append(item)
        return values

    @staticmethod
    def _finding(
        severity: str,
        code: str,
        message: str,
        attribute_names: List[str],
        blocking: bool,
    ) -> Dict[str, Any]:
        return {
            "severity": severity,
            "code": code,
            "message": message,
            "attribute_names": attribute_names,
            "blocking": blocking,
        }
