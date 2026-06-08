"""Unit tests for deterministic-first Amazon variation resolver."""

from src.services.amazon_variation_resolver import AmazonVariationResolver


class FakeAuditRepo:
    def __init__(self):
        self.runs = []

    def insert_run(self, **kwargs):
        self.runs.append(kwargs)
        return len(self.runs)


def _config():
    return {
        "version": "variation_strategy_test",
        "defaults": {
            "weights": {
                "uniqueness": 40,
                "buyer_relevance": 25,
                "data_confidence": 20,
                "simplicity": 10,
                "coverage": 5,
            },
            "minimum_auto_pass_score": 70,
        },
        "categories": {
            "CABINET": {
                "allowed_themes": ["Color", "Size", "Color/Size"],
                "buyer_theme_priority": {
                    "Size": 100,
                    "Color": 90,
                    "Color/Size": 85,
                },
                "attribute_sources": {
                    "color_name": ["raw.attributes.Main Color"],
                    "size_name": ["raw.assembledLength"],
                },
            }
        },
    }


def _product(sku, color, size):
    return {
        "meow_sku": sku,
        "vendor_sku": f"GIGA-{sku}",
        "raw_data": {
            "attributes": {"Main Color": color},
            "assembledLength": size,
        },
    }


def test_new_family_selects_simplest_buyer_relevant_unique_theme():
    audit = FakeAuditRepo()
    resolver = AmazonVariationResolver(audit_repo=audit, config=_config())

    result = resolver.resolve_new_family(
        [_product("A", "White", 24), _product("B", "Black", 24)],
        product_type="CABINET",
    )

    assert result.decision == "passed"
    assert result.variation_theme == "Color"
    assert result.child_attributes == {
        "A": {"color_name": "White"},
        "B": {"color_name": "Black"},
    }
    assert result.audit_run_id == 1
    assert audit.runs[0]["selected_theme"] == "Color"
    assert audit.runs[0]["score_snapshot"]["Color"]["unique"] is True


def test_new_family_uses_combo_theme_when_single_dimensions_are_not_unique():
    resolver = AmazonVariationResolver(audit_repo=FakeAuditRepo(), config=_config())

    result = resolver.resolve_new_family(
        [
            _product("A", "White", 24),
            _product("B", "Black", 24),
            _product("C", "White", 30),
            _product("D", "Black", 30),
        ],
        product_type="CABINET",
    )

    assert result.decision == "passed"
    assert result.variation_theme == "Color/Size"
    assert result.child_attributes["A"] == {"color_name": "White", "size_name": "24"}


def test_append_child_inherits_existing_theme_and_checks_uniqueness():
    resolver = AmazonVariationResolver(audit_repo=FakeAuditRepo(), config=_config())

    result = resolver.resolve_append_child(
        new_child_data=_product("E", "Blue", 24),
        product_type="CABINET",
        parent_sku="PARENT-1",
        existing_theme="Color",
        existing_children=[
            {"meow_sku": "A", "variation_attributes": {"color_name": "White"}},
            {"meow_sku": "B", "variation_attributes": {"color_name": "Black"}},
        ],
    )

    assert result.decision == "passed"
    assert result.parent_sku == "PARENT-1"
    assert result.variation_theme == "Color"
    assert result.child_attributes == {"E": {"color_name": "Blue"}}


def test_append_child_blocks_duplicate_existing_attribute_combination():
    resolver = AmazonVariationResolver(audit_repo=FakeAuditRepo(), config=_config())

    result = resolver.resolve_append_child(
        new_child_data=_product("E", "White", 24),
        product_type="CABINET",
        parent_sku="PARENT-1",
        existing_theme="Color",
        existing_children=[
            {"meow_sku": "A", "variation_attributes": {"color_name": "White"}},
        ],
    )

    assert result.decision == "blocked"
    assert result.blocking_codes == ["DUPLICATE_VARIATION_ATTRIBUTES"]
