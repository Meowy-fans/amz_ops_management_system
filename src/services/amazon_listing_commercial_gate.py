"""Auditable commercial gate for API-native listing creation."""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class CommercialGateFinding:
    severity: str
    code: str
    message: str
    blocking: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
            "details": self.details,
        }


@dataclass
class CommercialGateResult:
    blocked: bool
    decision: str
    findings: List[CommercialGateFinding]
    blocking_codes: List[str]
    warning_codes: List[str]
    input_snapshot: Dict[str, Any]
    rule_snapshot: Dict[str, Any]
    audit_run_id: Optional[int] = None


class CommercialGateConfigLoader:
    """Loads category-aware commercial gate rules from YAML."""

    _config: Optional[Dict[str, Any]] = None
    _config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "config",
        "listing_gates",
        "commercial_gate.yaml",
    )

    @classmethod
    def load(cls) -> Dict[str, Any]:
        if cls._config is None:
            with open(cls._config_path, "r", encoding="utf-8") as f:
                cls._config = yaml.safe_load(f) or {}
        return cls._config


class AmazonListingCommercialGate:
    """Evaluates price/inventory safety and persists every decision."""

    def __init__(
        self,
        audit_repo: Any,
        config: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ):
        self.audit_repo = audit_repo
        self.config = config or CommercialGateConfigLoader.load()
        self.now = now

    def evaluate(
        self,
        product_data: Dict[str, Any],
        product_type: str,
    ) -> CommercialGateResult:
        sku = str(product_data.get("meow_sku") or "")
        vendor_sku = str(product_data.get("vendor_sku") or "")
        rule_snapshot = self._rules_for(product_type)
        input_snapshot = self._input_snapshot(product_data, rule_snapshot)

        findings: List[CommercialGateFinding] = []
        self._validate_price(input_snapshot, rule_snapshot, findings)
        self._validate_inventory(input_snapshot, rule_snapshot, findings)

        blocking_codes = [item.code for item in findings if item.blocking]
        warning_codes = [item.code for item in findings if not item.blocking]
        blocked = bool(blocking_codes)
        decision = "blocked" if blocked else "passed"

        result = CommercialGateResult(
            blocked=blocked,
            decision=decision,
            findings=findings,
            blocking_codes=blocking_codes,
            warning_codes=warning_codes,
            input_snapshot=input_snapshot,
            rule_snapshot=rule_snapshot,
        )

        result.audit_run_id = self.audit_repo.insert_run(
            sku=sku,
            vendor_sku=vendor_sku,
            product_type=product_type.upper(),
            gate_version=self.config.get("version", "commercial_gate_unknown"),
            decision=decision,
            blocking_codes=blocking_codes,
            warning_codes=warning_codes,
            input_snapshot=input_snapshot,
            rule_snapshot=rule_snapshot,
            finding_snapshot=[item.as_dict() for item in findings],
        )
        return result

    def _rules_for(self, product_type: str) -> Dict[str, Any]:
        defaults = dict(self.config.get("defaults") or {})
        categories = self.config.get("categories") or {}
        category_rules = categories.get(product_type.upper()) or categories.get(
            product_type.lower(), {}
        )
        rules = {**defaults, **category_rules}
        rules["gate_version"] = self.config.get("version", "commercial_gate_unknown")
        return rules

    def _input_snapshot(
        self,
        product_data: Dict[str, Any],
        rules: Dict[str, Any],
    ) -> Dict[str, Any]:
        quantity_source = rules.get("quantity_source", "inventory_quantity")
        return {
            "sku": product_data.get("meow_sku"),
            "vendor_sku": product_data.get("vendor_sku"),
            "final_price": self._to_float(product_data.get("final_price")),
            "currency": product_data.get("price_currency"),
            "cost_at_pricing": self._to_float(product_data.get("cost_at_pricing")),
            "pricing_formula_version": product_data.get("pricing_formula_version"),
            "price_updated_at": self._to_iso(product_data.get("price_updated_at")),
            "inventory_quantity": self._to_int(product_data.get("inventory_quantity")),
            "buyer_qty": self._to_float(product_data.get("buyer_qty")),
            "seller_qty": self._to_float(product_data.get("seller_qty")),
            "inventory_last_updated": self._to_iso(
                product_data.get("inventory_last_updated")
            ),
            "source_publish_quantity": self._to_int(product_data.get(quantity_source)),
            "publish_quantity": self._to_int(product_data.get(quantity_source)),
            "quantity_source": quantity_source,
        }

    def _validate_price(
        self,
        data: Dict[str, Any],
        rules: Dict[str, Any],
        findings: List[CommercialGateFinding],
    ) -> None:
        price = self._decimal(data.get("final_price"))
        if price is None:
            findings.append(self._finding("MISSING_PRICE", "Final price is missing"))
            return
        if price <= 0:
            findings.append(self._finding("INVALID_PRICE", "Final price must be > 0"))
            return

        min_price = self._decimal(rules.get("min_price"))
        max_price = self._decimal(rules.get("max_price"))
        if min_price is not None and price < min_price:
            findings.append(
                self._finding(
                    "PRICE_BELOW_CATEGORY_MIN",
                    f"Final price {price} is below min_price {min_price}",
                )
            )
        if max_price is not None and price > max_price:
            findings.append(
                self._finding(
                    "PRICE_ABOVE_CATEGORY_MAX",
                    f"Final price {price} exceeds max_price {max_price}",
                )
            )

        expected_currency = rules.get("allowed_currency", "USD")
        if data.get("currency") != expected_currency:
            findings.append(
                self._finding(
                    "UNSUPPORTED_CURRENCY",
                    f"Currency {data.get('currency')} is not {expected_currency}",
                )
            )

        allowed_versions = rules.get("allowed_pricing_formula_versions") or []
        version = data.get("pricing_formula_version")
        if allowed_versions and version not in allowed_versions:
            findings.append(
                self._finding(
                    "PRICING_FORMULA_VERSION_NOT_ALLOWED",
                    f"Pricing formula version {version} is not allowed",
                )
            )

        self._validate_age(
            value=data.get("price_updated_at"),
            max_age_hours=rules.get("price_max_age_hours"),
            code="PRICE_STALE",
            label="Price",
            findings=findings,
        )

        cost = self._decimal(data.get("cost_at_pricing"))
        min_margin = self._decimal(rules.get("min_margin_rate"))
        if cost is not None and min_margin is not None:
            minimum_allowed = cost * (Decimal("1") + min_margin)
            if price < minimum_allowed:
                findings.append(
                    self._finding(
                        "PRICE_BELOW_MIN_MARGIN",
                        (
                            f"Final price {price} is below cost {cost} "
                            f"with min margin {min_margin}"
                        ),
                        {"minimum_allowed_price": float(minimum_allowed)},
                    )
                )

    def _validate_inventory(
        self,
        data: Dict[str, Any],
        rules: Dict[str, Any],
        findings: List[CommercialGateFinding],
    ) -> None:
        quantity = data.get("publish_quantity")
        if quantity is None:
            findings.append(
                self._finding(
                    "MISSING_INVENTORY",
                    f"Inventory source {data.get('quantity_source')} is missing",
                )
            )
            return
        if quantity < 0:
            findings.append(self._finding("NEGATIVE_INVENTORY", "Inventory is negative"))
        if quantity == 0 and not rules.get("allow_zero_inventory_listing", False):
            findings.append(
                self._finding(
                    "ZERO_INVENTORY_NOT_ALLOWED",
                    "Zero-inventory listing is disabled by rule config",
                )
            )

        max_qty = self._to_int(rules.get("max_publish_quantity"))
        if max_qty is not None and quantity > max_qty:
            data["publish_quantity"] = max_qty
            findings.append(
                self._warning(
                    "PUBLISH_QUANTITY_CLAMPED",
                    (
                        f"Publish quantity {quantity} exceeds max {max_qty}; "
                        f"listing quantity will be published as {max_qty}"
                    ),
                    {
                        "source_publish_quantity": quantity,
                        "publish_quantity": max_qty,
                        "max_publish_quantity": max_qty,
                    },
                )
            )

        self._validate_age(
            value=data.get("inventory_last_updated"),
            max_age_hours=rules.get("inventory_max_age_hours"),
            code="INVENTORY_STALE",
            label="Inventory",
            findings=findings,
        )

    def _validate_age(
        self,
        value: Any,
        max_age_hours: Any,
        code: str,
        label: str,
        findings: List[CommercialGateFinding],
    ) -> None:
        if not max_age_hours:
            return
        timestamp = self._parse_datetime(value)
        if timestamp is None:
            findings.append(self._finding(code, f"{label} timestamp is missing"))
            return
        now = self.now or datetime.now(timezone.utc)
        age_hours = (now - timestamp).total_seconds() / 3600
        if age_hours > float(max_age_hours):
            findings.append(
                self._finding(
                    code,
                    f"{label} age {age_hours:.1f}h exceeds {max_age_hours}h",
                    {"age_hours": round(age_hours, 2)},
                )
            )

    @staticmethod
    def _finding(
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> CommercialGateFinding:
        return CommercialGateFinding(
            severity="ERROR",
            code=code,
            message=message,
            blocking=True,
            details=details or {},
        )

    @staticmethod
    def _warning(
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> CommercialGateFinding:
        return CommercialGateFinding(
            severity="WARNING",
            code=code,
            message=message,
            blocking=False,
            details=details or {},
        )

    @staticmethod
    def _decimal(value: Any) -> Optional[Decimal]:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _to_iso(cls, value: Any) -> Optional[str]:
        dt = cls._parse_datetime(value)
        return dt.isoformat() if dt else None

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value)
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
