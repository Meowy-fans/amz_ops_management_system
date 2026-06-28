"""Unit tests for V2 rule field mapping."""

from src.services.rule_field_mapper_v2 import RuleFieldMapperV2


class FakeProductRepo:
    def __init__(self, products):
        self.products = products

    def get_full_product_data(self, sku):
        return self.products.get(sku)


def test_map_rules_applies_bootstrap_dimension_paths():
    rules = {
        "attributes": {
            "seat": {
                "children": {
                    "depth": {
                        "children": {
                            "value": {
                                "sources": [
                                    {
                                        "default": None,
                                        "evidence": "TODO: review source mapping for seat.depth.value",
                                    }
                                ]
                            },
                            "unit": {
                                "sources": [
                                    {
                                        "default": None,
                                        "evidence": "TODO: review source mapping for seat.depth.unit",
                                    }
                                ]
                            },
                        }
                    }
                }
            }
        }
    }
    mapper = RuleFieldMapperV2()

    result = mapper.map_rules("CHAIR", rules, sample_skus=[])

    depth_rule = result.rules["attributes"]["seat"]["children"]["depth"]["children"]["value"]
    unit_rule = result.rules["attributes"]["seat"]["children"]["depth"]["children"]["unit"]
    assert depth_rule["sources"][0]["path"] == "product.dimensions.assembled_width"
    assert unit_rule["sources"][0]["default"] == "inches"
    assert "seat.depth.value" in result.mapped_paths


def test_map_rules_matches_giga_attribute_name_from_samples():
    rules = {
        "attributes": {
            "room_type": {
                "sources": [
                    {
                        "default": None,
                        "evidence": "TODO: review source mapping for room_type",
                    }
                ]
            }
        }
    }
    repo = FakeProductRepo(
        {
            "SKU1": {
                "meow_sku": "SKU1",
                "vendor_sku": "VSKU1",
                "product": {
                    "attributes": {"Room Type": "Dining Room"},
                    "dimensions": {},
                },
                "content": {"title": "Chair", "description": "", "bullets": []},
                "offer": {"price": 10, "currency": "USD", "quantity": 1},
            }
        }
    )
    mapper = RuleFieldMapperV2(product_repo=repo)

    result = mapper.map_rules("CHAIR", rules, sample_skus=["SKU1"])

    room_rule = result.rules["attributes"]["room_type"]
    assert room_rule["sources"][0]["path"] == "product.attributes.Room Type"
    assert "room_type" in result.mapped_paths
