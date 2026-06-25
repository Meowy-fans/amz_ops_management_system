"""Golden regression tests for Amazon schema property merging."""

import json
from pathlib import Path
from typing import Any, Dict

from src.services.amazon_schema_service import AmazonSchemaService
from src.services.attribute_rule_generator import AttributeRuleGenerator


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "fixtures"
    / "amazon_schemas"
    / "cached_product_type_schemas.json"
)


def _legacy_shallow_merged_properties(schema: Dict[str, Any]) -> Dict[str, Any]:
    props = dict(schema.get("properties", {}) or {})
    for part in schema.get("allOf", []) or []:
        props.update(part.get("properties", {}) or {})
        for key in ("then", "else"):
            props.update((part.get(key) or {}).get("properties", {}) or {})
    return props


def test_schema_deep_merge_only_upgrades_shape_in_cached_schema_fixtures():
    schemas = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    generator = AttributeRuleGenerator.__new__(AttributeRuleGenerator)
    rank = {
        "value": 0,
        "list_value": 1,
        "nested_object": 2,
        "object": 3,
        "measure": 3,
    }

    upgraded = []
    downgraded = []
    unchanged_count = 0
    for product_type, schema in schemas.items():
        legacy = _legacy_shallow_merged_properties(schema)
        merged = AmazonSchemaService._merged_properties(schema)
        for name in set(legacy) | set(merged):
            old_shape = generator._shape(legacy.get(name, {}))
            new_shape = generator._shape(merged.get(name, {}))
            if old_shape == new_shape:
                unchanged_count += 1
                continue
            record = (product_type, name, old_shape, new_shape)
            if rank[new_shape] > rank[old_shape]:
                upgraded.append(record)
            else:
                downgraded.append(record)

    assert len(schemas) == 17
    assert unchanged_count == 2198
    assert len(upgraded) == 224
    assert downgraded == []
    assert ("CHAIR", "frame", "value", "object") in upgraded
    assert ("CHAIR", "seat", "value", "object") in upgraded
