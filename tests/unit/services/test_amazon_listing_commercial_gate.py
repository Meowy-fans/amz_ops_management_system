"""Unit tests for auditable commercial listing gate."""

from datetime import datetime, timedelta, timezone

from src.services.amazon_listing_commercial_gate import AmazonListingCommercialGate


class FakeRepo:
    def __init__(self):
        self.runs = []

    def insert_run(self, **kwargs):
        self.runs.append(kwargs)
        return len(self.runs)


def _rules(**overrides):
    data = {
        "version": "test_gate_v1",
        "defaults": {
            "allowed_currency": "USD",
            "price_max_age_hours": 24,
            "inventory_max_age_hours": 6,
            "min_margin_rate": 0.25,
            "min_price": 1,
            "max_price": 1000,
            "max_publish_quantity": 20,
            "allow_zero_inventory_listing": True,
            "quantity_source": "inventory_quantity",
            "allowed_pricing_formula_versions": [],
        },
        "categories": {
            "CABINET": {"min_margin_rate": 0.30, "max_publish_quantity": 10}
        },
    }
    data["defaults"].update(overrides)
    return data


def _product_data(**overrides):
    now = datetime.now(timezone.utc)
    data = {
        "meow_sku": "MEOW1",
        "vendor_sku": "GIGA1",
        "category_name": "CABINET",
        "final_price": 199.99,
        "price_currency": "USD",
        "cost_at_pricing": 100,
        "pricing_formula_version": "v1",
        "price_updated_at": now - timedelta(hours=1),
        "inventory_quantity": 5,
        "buyer_qty": 99,
        "seller_qty": 0,
        "inventory_last_updated": now - timedelta(hours=1),
        "total_quantity": 5,
    }
    data.update(overrides)
    return data


def test_gate_passes_and_audits_snapshot():
    repo = FakeRepo()
    gate = AmazonListingCommercialGate(audit_repo=repo, config=_rules())

    result = gate.evaluate(_product_data(), product_type="CABINET")

    assert result.blocked is False
    assert result.decision == "passed"
    assert result.audit_run_id == 1
    assert repo.runs[0]["input_snapshot"]["buyer_qty"] == 99
    assert repo.runs[0]["rule_snapshot"]["min_margin_rate"] == 0.30


def test_gate_blocks_missing_or_invalid_price():
    repo = FakeRepo()
    gate = AmazonListingCommercialGate(audit_repo=repo, config=_rules())

    result = gate.evaluate(_product_data(final_price=0), product_type="CABINET")

    assert result.blocked is True
    assert result.decision == "blocked"
    assert result.blocking_codes == ["INVALID_PRICE"]
    assert repo.runs[0]["decision"] == "blocked"


def test_gate_blocks_stale_price_and_inventory():
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    gate = AmazonListingCommercialGate(audit_repo=FakeRepo(), config=_rules())

    result = gate.evaluate(
        _product_data(price_updated_at=old, inventory_last_updated=old),
        product_type="CABINET",
    )

    assert result.blocked is True
    assert "PRICE_STALE" in result.blocking_codes
    assert "INVENTORY_STALE" in result.blocking_codes


def test_gate_blocks_price_below_min_margin():
    gate = AmazonListingCommercialGate(audit_repo=FakeRepo(), config=_rules())

    result = gate.evaluate(
        _product_data(final_price=120, cost_at_pricing=100),
        product_type="CABINET",
    )

    assert result.blocked is True
    assert result.blocking_codes == ["PRICE_BELOW_MIN_MARGIN"]


def test_gate_allows_zero_inventory_only_when_configured():
    gate = AmazonListingCommercialGate(
        audit_repo=FakeRepo(),
        config=_rules(allow_zero_inventory_listing=False),
    )

    result = gate.evaluate(_product_data(inventory_quantity=0), product_type="CABINET")

    assert result.blocked is True
    assert "ZERO_INVENTORY_NOT_ALLOWED" in result.blocking_codes


def test_gate_clamps_quantity_above_publish_cap_and_audits_warning():
    repo = FakeRepo()
    gate = AmazonListingCommercialGate(audit_repo=repo, config=_rules())

    result = gate.evaluate(_product_data(inventory_quantity=50), product_type="CABINET")

    assert result.blocked is False
    assert "PUBLISH_QUANTITY_CLAMPED" in result.warning_codes
    assert result.input_snapshot["source_publish_quantity"] == 50
    assert result.input_snapshot["publish_quantity"] == 10
    assert repo.runs[0]["input_snapshot"]["publish_quantity"] == 10
