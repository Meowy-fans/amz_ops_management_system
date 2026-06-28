"""Unit tests for V2 cross-category rule pattern reuse."""

from src.services.rule_pattern_reuse_v2 import RulePatternReuseV2


def test_reuse_patterns_copies_matching_leaf_sources():
    reference_rules = {
        "attributes": {
            "seat": {
                "children": {
                    "height": {
                        "children": {
                            "value": {
                                "sources": [
                                    {
                                        "path": "product.dimensions.assembled_height",
                                        "confidence": "high",
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
    }
    target_rules = {
        "attributes": {
            "seat": {
                "children": {
                    "height": {
                        "children": {
                            "value": {
                                "sources": [
                                    {
                                        "default": None,
                                        "evidence": "TODO: review source mapping for seat.height.value",
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
    }

    result = RulePatternReuseV2().reuse_patterns(
        product_type="CHAIR",
        rules=target_rules,
        reference_rules=reference_rules,
        reference_product_type="SOFA",
    )

    copied = result.rules["attributes"]["seat"]["children"]["height"]["children"]["value"]
    assert copied["sources"][0]["path"] == "product.dimensions.assembled_height"
    assert copied["sources"][0]["inherited_from"] == "SOFA"
    assert result.reused_paths == ["seat.height.value"]
