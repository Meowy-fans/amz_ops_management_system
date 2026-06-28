"""Tests for optional YAML rule child enrichment."""

from types import SimpleNamespace

from src.services.evidence_resolver_v2 import EvidenceResolverV2
from src.services.optional_rule_children_enricher_v2 import OptionalRuleChildrenEnricherV2
from src.services.requirement_models_v2 import RequirementNode


def test_enricher_adds_optional_frame_material_and_seat_depth():
    requirement_root = RequirementNode(
        path_key="CHAIR",
        schema_path="$",
        name="CHAIR",
        shape="root",
        required=True,
        children=[
            RequirementNode(
                path_key="frame",
                schema_path="$.frame",
                name="frame",
                shape="object",
                required=True,
                children=[
                    RequirementNode(
                        path_key="frame.color",
                        schema_path="$.frame.color",
                        name="color",
                        shape="list_value",
                        required=True,
                        children=[
                            RequirementNode(
                                path_key="frame.color.value",
                                schema_path="$.x",
                                name="value",
                                shape="scalar",
                                required=True,
                            )
                        ],
                    )
                ],
            ),
            RequirementNode(
                path_key="seat",
                schema_path="$.seat",
                name="seat",
                shape="object",
                required=True,
                children=[
                    RequirementNode(
                        path_key="seat.height",
                        schema_path="$.seat.height",
                        name="height",
                        shape="measure",
                        required=True,
                        children=[
                            RequirementNode(
                                path_key="seat.height.value",
                                schema_path="$.x",
                                name="value",
                                shape="scalar",
                                required=True,
                            ),
                            RequirementNode(
                                path_key="seat.height.unit",
                                schema_path="$.x",
                                name="unit",
                                shape="scalar",
                                required=True,
                            ),
                        ],
                    )
                ],
            ),
        ],
    )
    rules = {
        "version": "test",
        "attributes": {
            "frame": {
                "shape": "object",
                "children": {
                    "color": {
                        "shape": "list_value",
                        "children": {
                            "value": {
                                "sources": [{"default": "Brown", "safe_default": True}]
                            }
                        },
                    },
                    "material": {
                        "shape": "list_value",
                        "children": {
                            "value": {
                                "sources": [{"default": "Wood", "safe_default": True}]
                            }
                        },
                    },
                },
            },
            "seat": {
                "shape": "object",
                "children": {
                    "depth": {
                        "shape": "measure",
                        "children": {
                            "value": {"sources": [{"default": 20.0, "safe_default": True}]},
                            "unit": {"sources": [{"default": "inches", "safe_default": True}]},
                        },
                    },
                },
            },
        },
    }
    draft = SimpleNamespace(
        sku="SKU1",
        product_type="CHAIR",
        content=SimpleNamespace(title="", description="", bullets=[]),
        standard_product=SimpleNamespace(attributes={}, dimensions=None, images=[]),
        offer=SimpleNamespace(price=1.0, currency="USD", quantity=1, condition_type="new_new"),
        variation=SimpleNamespace(
            parentage_level="",
            variation_theme="",
            parent_sku="",
            child_relationship_type="",
            theme_attributes={},
        ),
        vendor_sku="SKU1",
    )
    attributes = {
        "frame": [{"color": [{"value": "Brown", "language_tag": "en_US"}]}],
        "seat": [{"height": [{"value": 18.0, "unit": "inches"}]}],
    }
    resolver = EvidenceResolverV2()

    enriched = OptionalRuleChildrenEnricherV2().enrich(
        attributes=attributes,
        rules=rules,
        requirement_root=requirement_root,
        draft=draft,
        resolver=resolver,
    )

    assert enriched["frame"][0]["material"] == [{"value": "Wood", "language_tag": "en_US"}]
    depth = enriched["seat"][0]["depth"][0]
    assert depth["unit"] == "inches"
    assert float(depth["value"]) == 20.0


def test_enricher_skips_coverage_ignore_required_roots():
    requirement_root = RequirementNode(
        path_key="BED_FRAME",
        schema_path="$",
        name="BED_FRAME",
        shape="root",
        required=True,
        children=[
            RequirementNode(
                path_key="merchant_suggested_asin",
                schema_path="$.merchant_suggested_asin",
                name="merchant_suggested_asin",
                shape="array_object",
                required=True,
                children=[],
            ),
        ],
    )
    rules = {
        "coverage_ignore_required": ["merchant_suggested_asin"],
        "attributes": {
            "merchant_suggested_asin": {
                "shape": "array_object",
                "children": {
                    "value": {"sources": [{"default": "B000000000", "safe_default": True}]},
                },
            },
        },
    }
    draft = SimpleNamespace(
        sku="SKU1",
        product_type="BED_FRAME",
        content=SimpleNamespace(title="", description="", bullets=[]),
        standard_product=SimpleNamespace(attributes={}, dimensions=None, images=[]),
        offer=SimpleNamespace(price=1.0, currency="USD", quantity=1, condition_type="new_new"),
        variation=SimpleNamespace(
            parentage_level="",
            variation_theme="",
            parent_sku="",
            child_relationship_type="",
            theme_attributes={},
        ),
        vendor_sku="SKU1",
    )

    enriched = OptionalRuleChildrenEnricherV2().enrich(
        attributes={},
        rules=rules,
        requirement_root=requirement_root,
        draft=draft,
        resolver=EvidenceResolverV2(),
    )

    assert "merchant_suggested_asin" not in enriched


def test_strip_incomplete_ignored_attributes_drops_partial_msa_shell():
    attributes = {
        "merchant_suggested_asin": [{"marketplace_id": "ATVPDKIKX0DER"}],
        "brand": [{"value": "Generic", "language_tag": "en_US"}],
    }
    stripped = OptionalRuleChildrenEnricherV2.strip_incomplete_ignored_attributes(
        attributes,
        ["merchant_suggested_asin"],
    )
    assert "merchant_suggested_asin" not in stripped
    assert "brand" in stripped


def test_enricher_bootstraps_missing_array_object_parent_from_rule_children():
    requirement_root = RequirementNode(
        path_key="TABLE",
        schema_path="$",
        name="TABLE",
        shape="root",
        required=True,
        children=[
            RequirementNode(
                path_key="frame",
                schema_path="$.frame",
                name="frame",
                shape="array_object",
                required=True,
                children=[],
            ),
            RequirementNode(
                path_key="top",
                schema_path="$.top",
                name="top",
                shape="array_object",
                required=True,
                children=[
                    RequirementNode(
                        path_key="top.color",
                        schema_path="$.top.color",
                        name="color",
                        shape="list_value",
                        required=True,
                    ),
                ],
            ),
        ],
    )
    rules = {
        "version": "table_v2",
        "attributes": {
            "frame": {
                "shape": "array_object",
                "children": {
                    "material": {
                        "shape": "list_value",
                        "children": {
                            "value": {"sources": [{"default": "Wood", "safe_default": True}]},
                        },
                    },
                },
            },
        },
    }
    draft = SimpleNamespace(
        sku="SKU1",
        product_type="TABLE",
        content=SimpleNamespace(title="", description="", bullets=[]),
        standard_product=SimpleNamespace(attributes={}, dimensions=None, images=[]),
        offer=SimpleNamespace(price=1.0, currency="USD", quantity=1, condition_type="new_new"),
        variation=SimpleNamespace(
            parentage_level="",
            variation_theme="",
            parent_sku="",
            child_relationship_type="",
            theme_attributes={},
        ),
        vendor_sku="SKU1",
    )

    enriched = OptionalRuleChildrenEnricherV2().enrich(
        attributes={"top": [{"color": [{"value": "Brown", "language_tag": "en_US"}]}]},
        rules=rules,
        requirement_root=requirement_root,
        draft=draft,
        resolver=EvidenceResolverV2(),
    )

    assert enriched["frame"][0]["material"] == [{"value": "Wood", "language_tag": "en_US"}]
    assert enriched["frame"][0]["marketplace_id"]
