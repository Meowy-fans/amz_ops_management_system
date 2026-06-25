"""Unit tests for AmazonSchemaService."""
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.services.attribute_rule_generator import AttributeRuleGenerator
from src.services.amazon_schema_service import AmazonSchemaService


class FakeSchemaRepo:
    def __init__(self, cached=None):
        self.cached = cached
        self.upserted = []

    def get(self, product_type, marketplace_id):
        return self.cached

    def upsert(self, product_type, marketplace_id, schema, required):
        self.upserted.append((product_type, schema, required))


@pytest.fixture
def svc():
    db = MagicMock(spec=Session)
    s = AmazonSchemaService(db=db)
    s._repo_instance = FakeSchemaRepo()
    return s


# ── cache ─────────────────────────────────────────────────────────

def test_get_cached_schema_miss(svc):
    assert svc.get_cached_schema("CABINET") is None


def test_get_cached_schema_hit(svc):
    svc._repo_instance.cached = {
        "schema_json": {"type": "object"},
        "required_properties": ["item_name", "brand"],
        "retrieved_at": "2026-05-17",
    }
    cached = svc.get_cached_schema("CABINET")
    assert cached is not None
    assert cached["required_properties"] == ["item_name", "brand"]


# ── validation ────────────────────────────────────────────────────

def test_validate_attributes_all_present(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_required_properties", lambda pt: ["item_name", "brand"])
    attrs = {"item_name": [{"value": "Test"}], "brand": [{"value": "B"}]}
    assert svc.validate_attributes("CABINET", attrs) == []


def test_validate_attributes_missing(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_required_properties", lambda pt: ["item_name", "brand", "fabric_type"])
    missing = svc.validate_attributes("CABINET", {"item_name": [{"value": "Test"}]})
    assert len(missing) == 2
    names = {m["property"] for m in missing}
    assert "brand" in names
    assert "fabric_type" in names


def test_validate_attributes_empty_value(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_required_properties", lambda pt: ["brand"])
    missing = svc.validate_attributes("CABINET", {"brand": []})
    assert len(missing) == 1


# ── valid values ──────────────────────────────────────────────────

def test_get_valid_values_not_in_schema(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {"schema_json": {}, "required_properties": []})
    assert svc.get_valid_values("CABINET", "nonexistent") is None


def test_get_valid_values_with_enum(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {
        "schema_json": {
            "properties": {
                "country_of_origin": {
                    "items": {"properties": {"value": {"enum": ["CN", "US", "VN"]}}}
                }
            }
        },
        "required_properties": [],
    })
    assert svc.get_valid_values("CABINET", "country_of_origin") == ["CN", "US", "VN"]


def test_get_valid_values_no_enum(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {
        "schema_json": {
            "properties": {
                "item_name": {"items": {"properties": {"value": {"type": "string"}}}}
            }
        },
        "required_properties": [],
    })
    assert svc.get_valid_values("CABINET", "item_name") is None


# ── property descriptions ─────────────────────────────────────────

def test_get_property_descriptions(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {
        "schema_json": {
            "allOf": [{"properties": {"item_name": {"description": "The product title"}}}],
            "properties": {"brand": {"title": "Brand", "description": "The brand name"}},
        },
        "required_properties": [],
    })
    descs = svc.get_property_descriptions("CABINET")
    assert "item_name" in descs
    assert "brand" in descs
    assert descs["item_name"] == "The product title"


def test_get_property_names_merges_root_allof_and_conditional_properties(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {
        "schema_json": {
            "properties": {"item_name": {"title": "Item Name"}},
            "allOf": [
                {
                    "properties": {"brand": {"title": "Brand"}},
                    "then": {"properties": {"model_name": {"title": "Model Name"}}},
                }
            ],
        },
        "required_properties": [],
    })

    assert svc.get_property_names("HOME_MIRROR") == [
        "item_name",
        "brand",
        "model_name",
    ]


def test_merged_properties_preserves_base_properties_when_conditional_is_partial():
    schema = {
        "properties": {
            "frame": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [],
                    "properties": {
                        "color": {"type": "array"},
                        "material": {"type": "array"},
                    },
                },
            }
        },
        "allOf": [
            {
                "then": {
                    "required": ["frame"],
                    "properties": {
                        "frame": {"items": {"required": ["color"]}},
                    },
                }
            }
        ],
    }

    merged = AmazonSchemaService._merged_properties(schema)

    assert merged["frame"]["type"] == "array"
    assert merged["frame"]["items"]["type"] == "object"
    assert merged["frame"]["items"]["required"] == ["color"]
    assert set(merged["frame"]["items"]["properties"]) == {"color", "material"}


def test_merged_properties_frame_resolves_to_object_after_deep_merge():
    schema = {
        "properties": {
            "frame": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [],
                    "properties": {
                        "color": {"type": "array"},
                        "material": {"type": "array"},
                    },
                },
            }
        },
        "allOf": [
            {
                "then": {
                    "properties": {
                        "frame": {"items": {"required": ["color"]}},
                    }
                }
            }
        ],
    }

    merged = AmazonSchemaService._merged_properties(schema)
    generator = AttributeRuleGenerator.__new__(AttributeRuleGenerator)

    assert generator._shape(merged["frame"]) == "object"


def test_merged_properties_measure_shape_is_unaffected_by_unrelated_condition():
    schema = {
        "properties": {
            "maximum_weight_recommendation": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["unit", "value"],
                    "properties": {
                        "unit": {"enum": ["pounds", "kilograms"]},
                        "value": {"type": "number"},
                    },
                },
            }
        },
        "allOf": [
            {"then": {"properties": {"other_attribute": {"title": "Other"}}}}
        ],
    }

    merged = AmazonSchemaService._merged_properties(schema)
    generator = AttributeRuleGenerator.__new__(AttributeRuleGenerator)

    assert generator._shape(merged["maximum_weight_recommendation"]) == "measure"


def test_merged_properties_required_lists_are_union_without_duplicates():
    schema = {
        "properties": {
            "seat": {
                "items": {
                    "required": ["depth"],
                    "properties": {"depth": {"type": "array"}},
                }
            }
        },
        "allOf": [
            {
                "then": {
                    "properties": {
                        "seat": {"items": {"required": ["depth", "height"]}},
                    }
                }
            }
        ],
    }

    merged = AmazonSchemaService._merged_properties(schema)

    assert merged["seat"]["items"]["required"] == ["depth", "height"]


def test_merged_properties_does_not_union_enum_lists():
    schema = {
        "properties": {
            "item_shape": {
                "items": {
                    "properties": {
                        "value": {"enum": ["Square", "Round"]},
                    }
                }
            }
        },
        "allOf": [
            {
                "then": {
                    "properties": {
                        "item_shape": {
                            "items": {
                                "properties": {
                                    "value": {"enum": ["Rectangular"]},
                                }
                            }
                        }
                    }
                }
            }
        ],
    }

    merged = AmazonSchemaService._merged_properties(schema)

    assert merged["item_shape"]["items"]["properties"]["value"]["enum"] == [
        "Rectangular"
    ]


def test_get_expanded_required_properties_merges_top_allof_and_nested_attribute(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {
        "schema_json": {
            "required": ["item_name"],
            "properties": {
                "item_name": {"title": "Item Name"},
                "frame": {
                    "items": {
                        "type": "object",
                        "properties": {"material": {"type": "string"}},
                        "required": ["material"],
                    }
                },
            },
            "allOf": [
                {
                    "required": ["model_name"],
                    "properties": {"model_name": {"title": "Model Name"}},
                }
            ],
        },
        "required_properties": ["brand"],
    })

    required = svc.get_expanded_required_properties("HOME_MIRROR")

    assert required == ["brand", "item_name", "model_name"]


def test_get_coverage_required_properties_merges_schema_and_preview_learned(monkeypatch, svc):
    monkeypatch.setattr(
        svc,
        "get_expanded_required_properties",
        lambda pt: ["item_name", "brand"],
    )
    monkeypatch.setattr(
        svc,
        "get_learned_required_properties",
        lambda pt: ["brand", "mounting_type"],
    )

    required = svc.get_coverage_required_properties("HOME_MIRROR")

    assert required == ["item_name", "brand", "mounting_type"]
