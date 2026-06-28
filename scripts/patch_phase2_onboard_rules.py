#!/usr/bin/env python3
"""Patch Phase 2 onboard skeleton YAML files toward live_eligible readiness."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from src.services.attribute_rule_loader import AttributeRuleLoader
from src.services.rule_tree_utils_v2 import get_rule_at_path, has_placeholder_source, iter_leaf_rules
from src.services.rule_yaml_write_guard import write_rule_yaml

PHASE2_CATEGORIES = [
    "PLANTER",
    "SUITCASE",
    "ARTIFICIAL_TREE",
    "CLIMBING_PLANT_SUPPORT_STRUCTURE",
    "LADDER",
    "FURNITURE",
    "DESK",
    "BICYCLE",
    "MAKEUP_VANITY",
    "RIDE_ON_TOY",
    "SAUNA",
    "FIRE_PIT",
    "OUTDOOR_LIVING",
]

INDOOR_OUTDOOR_DEFAULT: Dict[str, str] = {
    "PLANTER": "outdoor",
    "ARTIFICIAL_TREE": "indoor",
    "CLIMBING_PLANT_SUPPORT_STRUCTURE": "outdoor",
}

COVERAGE_IGNORE = ["merchant_shipping_group", "merchant_suggested_asin"]


def _sources(*entries: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [copy.deepcopy(entry) for entry in entries]


def _set_leaf_sources(attributes: Dict[str, Any], path_key: str, sources: List[Dict[str, Any]]) -> None:
    rule = get_rule_at_path(attributes, path_key)
    if rule is None:
        raise KeyError(path_key)
    rule["sources"] = sources
    rule["manual_review"] = False
    parent_path = path_key.rsplit(".", 1)[0]
    if parent_path != path_key:
        parent = get_rule_at_path(attributes, parent_path)
        if parent is not None:
            parent["manual_review"] = False


def _patch_commercial(attributes: Dict[str, Any]) -> None:
    patches: List[Tuple[str, List[Dict[str, Any]]]] = [
        (
            "fulfillment_availability.fulfillment_channel_code",
            _sources(
                {
                    "default": "DEFAULT",
                    "confidence": "high",
                    "evidence": "Merchant-fulfilled default channel.",
                    "safe_default": True,
                }
            ),
        ),
        (
            "condition_type.value",
            _sources(
                {"path": "offer.condition_type", "confidence": "high"},
                {
                    "default": "new_new",
                    "confidence": "high",
                    "evidence": "New product default condition.",
                    "safe_default": True,
                },
            ),
        ),
        (
            "list_price.currency",
            _sources(
                {
                    "default": "USD",
                    "confidence": "high",
                    "evidence": "US marketplace list price currency.",
                    "safe_default": True,
                }
            ),
        ),
        (
            "list_price.value",
            _sources({"path": "offer.price", "confidence": "high"}),
        ),
        (
            "batteries_required.value",
            _sources(
                {
                    "default": "False",
                    "confidence": "high",
                    "evidence": "Non-battery product default.",
                    "safe_default": True,
                }
            ),
        ),
    ]
    for path_key, sources in patches:
        if get_rule_at_path(attributes, path_key) is not None:
            _set_leaf_sources(attributes, path_key, sources)


def _patch_category_placeholders(product_type: str, attributes: Dict[str, Any]) -> None:
    pt = product_type.upper()
    if get_rule_at_path(attributes, "generic_keyword.value") is not None:
        _set_leaf_sources(
            attributes,
            "generic_keyword.value",
            _sources(
                {"path": "content.title", "confidence": "medium"},
                {
                    "default": pt.replace("_", " ").title(),
                    "confidence": "medium",
                    "evidence": "Category fallback generic keyword.",
                    "safe_default": True,
                },
            ),
        )
    if get_rule_at_path(attributes, "indoor_outdoor_usage.value") is not None:
        usage = INDOOR_OUTDOOR_DEFAULT.get(pt, "outdoor")
        _set_leaf_sources(
            attributes,
            "indoor_outdoor_usage.value",
            _sources(
                {
                    "default": usage,
                    "confidence": "high",
                    "evidence": f"Default indoor/outdoor usage for {pt}.",
                    "safe_default": True,
                }
            ),
        )
    if get_rule_at_path(attributes, "required_product_compliance_certificate.value") is not None:
        _set_leaf_sources(
            attributes,
            "required_product_compliance_certificate.value",
            _sources(
                {
                    "default": "Not Applicable",
                    "confidence": "high",
                    "evidence": "No compliance certificate required for this listing.",
                    "safe_default": True,
                }
            ),
        )
    if get_rule_at_path(attributes, "style.value") is not None:
        _set_leaf_sources(
            attributes,
            "style.value",
            _sources(
                {"path": "product.attributes.style", "confidence": "high"},
                {"path": "product.attributes.Style", "confidence": "high"},
                {
                    "default": "Modern",
                    "confidence": "medium",
                    "evidence": "Fallback style when supplier style is missing.",
                    "safe_default": True,
                },
            ),
        )
    if get_rule_at_path(attributes, "special_feature.value") is not None:
        _set_leaf_sources(
            attributes,
            "special_feature.value",
            _sources(
                {"path": "product.attributes.Special Feature", "confidence": "high"},
                {"path": "content.bullets", "confidence": "medium"},
                {
                    "default": "Durable",
                    "confidence": "medium",
                    "evidence": "Fallback special feature for supplier listings.",
                    "safe_default": True,
                },
            ),
        )
    if pt == "RIDE_ON_TOY":
        if get_rule_at_path(attributes, "target_gender.value") is not None:
            _set_leaf_sources(
                attributes,
                "target_gender.value",
                _sources(
                    {
                        "default": "unisex",
                        "confidence": "high",
                        "evidence": "Kids ride-on toys default target gender.",
                        "safe_default": True,
                    }
                ),
            )
        if get_rule_at_path(attributes, "manufacturer_minimum_age.value") is not None:
            _set_leaf_sources(
                attributes,
                "manufacturer_minimum_age.value",
                _sources(
                    {
                        "default": 36,
                        "confidence": "high",
                        "evidence": "Minimum age 36 months for ride-on toys.",
                        "safe_default": True,
                    }
                ),
            )
    if get_rule_at_path(attributes, "contains_liquid_contents.value") is not None and has_placeholder_source(
        get_rule_at_path(attributes, "contains_liquid_contents.value") or {}
    ):
        _set_leaf_sources(
            attributes,
            "contains_liquid_contents.value",
            _sources(
                {
                    "default": "False",
                    "confidence": "high",
                    "evidence": "Non-liquid product default.",
                    "safe_default": True,
                }
            ),
        )
    if get_rule_at_path(attributes, "mounting_type.value") is not None:
        default = "Freestanding"
        if pt == "CLIMBING_PLANT_SUPPORT_STRUCTURE":
            default = "Wall Mount"
        _set_leaf_sources(
            attributes,
            "mounting_type.value",
            _sources(
                {"path": "product.attributes.Mounting Type", "confidence": "high"},
                {
                    "default": default,
                    "confidence": "medium",
                    "evidence": f"Fallback mounting type for {pt}.",
                    "safe_default": True,
                },
            ),
        )


def _patch_dimension_placeholders(attributes: Dict[str, Any]) -> None:
    inch_unit = _sources(
        {
            "default": "inches",
            "confidence": "high",
            "evidence": "Product dimensions normalized to inches.",
            "safe_default": True,
        }
    )
    value_map = {
        "item_width_height.height.value": [
            "product.dimensions.assembled_height",
            "product.dimensions.height",
        ],
        "item_width_height.width.value": [
            "product.dimensions.assembled_width",
            "product.dimensions.width",
        ],
        "item_dimensions.height.value": [
            "product.dimensions.assembled_height",
            "product.dimensions.height",
        ],
        "item_dimensions.length.value": [
            "product.dimensions.assembled_length",
            "product.dimensions.length",
        ],
        "item_dimensions.width.value": [
            "product.dimensions.assembled_width",
            "product.dimensions.width",
        ],
        "maximum_height.value": [
            "product.dimensions.assembled_height",
            "product.dimensions.height",
        ],
        "load_capacity.value": [
            "product.dimensions.assembled_weight",
            "product.dimensions.weight",
        ],
    }
    for path_key, rule in list(iter_leaf_rules(attributes)):
        if not has_placeholder_source(rule):
            continue
        if path_key.endswith(".unit"):
            _set_leaf_sources(attributes, path_key, inch_unit)
            continue
        if path_key in value_map:
            sources = [{"path": p, "confidence": "high"} for p in value_map[path_key]]
            sources.append(
                {
                    "default": 1,
                    "confidence": "medium",
                    "evidence": f"Bootstrap numeric fallback for {path_key}.",
                    "safe_default": True,
                }
            )
            _set_leaf_sources(attributes, path_key, sources)


def _patch_known_defaults(product_type: str, attributes: Dict[str, Any]) -> None:
    pt = product_type.upper()
    known: Dict[str, List[Dict[str, Any]]] = {
        "department.value": _sources(
            {
                "default": "unisex-adult",
                "confidence": "medium",
                "evidence": "Default luggage department.",
                "safe_default": True,
            }
        ),
        "shell_type.value": _sources(
            {"path": "product.attributes.Shell Type", "confidence": "high"},
            {
                "default": "Hard",
                "confidence": "medium",
                "evidence": "Fallback shell type.",
                "safe_default": True,
            },
        ),
        "occasion_type.value": _sources(
            {"path": "content.title", "confidence": "medium"},
            {
                "default": "Christmas",
                "confidence": "medium",
                "evidence": "Fallback occasion for artificial tree listings.",
                "safe_default": True,
            },
        ),
        "recommended_uses_for_product.value": _sources(
            {"path": "content.bullets", "confidence": "medium"},
            {
                "default": "Home Decor",
                "confidence": "medium",
                "evidence": "Fallback recommended use.",
                "safe_default": True,
            },
        ),
        "desk_design.value": _sources(
            {"path": "product.attributes.Desk Design", "confidence": "high"},
            {
                "default": "Computer Desk",
                "confidence": "medium",
                "evidence": "Fallback desk design.",
                "safe_default": True,
            },
        ),
        "finish_type.value": _sources(
            {"path": "product.attributes.Finish Type", "confidence": "high"},
            {"path": "product.attributes.Main Material", "confidence": "medium"},
            {
                "default": "Laminated",
                "confidence": "medium",
                "evidence": "Fallback finish type.",
                "safe_default": True,
            },
        ),
        "base.color.value": _sources(
            {"path": "product.attributes.Main Color", "confidence": "high"},
            {"path": "product.attributes.color", "confidence": "high"},
            {
                "default": "Black",
                "confidence": "medium",
                "evidence": "Fallback base color.",
                "safe_default": True,
            },
        ),
        "number_of_boxes.value": _sources(
            {"path": "product.attributes.Number of Boxes", "confidence": "high"},
            {
                "default": 1,
                "confidence": "high",
                "evidence": "Single-carton default.",
                "safe_default": True,
            },
        ),
        "age_range_description.value": _sources(
            {
                "default": "Adult",
                "confidence": "medium",
                "evidence": "Fallback age range for bicycle listings.",
                "safe_default": True,
            }
        ),
        "import_designation.value": _sources(
            {
                "default": "Imported",
                "confidence": "medium",
                "evidence": "Fallback import designation.",
                "safe_default": True,
            }
        ),
        "warranty_description.value": _sources(
            {
                "default": "1 Year Manufacturer",
                "confidence": "medium",
                "evidence": "Fallback warranty description.",
                "safe_default": True,
            }
        ),
        "size.value": _sources(
            {"path": "content.title", "confidence": "medium"},
            {
                "default": "Standard",
                "confidence": "medium",
                "evidence": "Fallback size.",
                "safe_default": True,
            },
        ),
        "frame.size.value": _sources(
            {"path": "content.title", "confidence": "medium"},
            {
                "default": "Medium",
                "confidence": "medium",
                "evidence": "Fallback frame size.",
                "safe_default": True,
            },
        ),
        "frame.type.value": _sources(
            {
                "default": "Rigid",
                "confidence": "medium",
                "evidence": "Fallback frame type.",
                "safe_default": True,
            }
        ),
        "tire.tire_type.value": _sources(
            {
                "default": "Tube",
                "confidence": "medium",
                "evidence": "Fallback tire type.",
                "safe_default": True,
            }
        ),
        "bike_type.value": _sources(
            {"path": "content.title", "confidence": "medium"},
            {
                "default": "Mountain Bike",
                "confidence": "medium",
                "evidence": "Fallback bike type.",
                "safe_default": True,
            },
        ),
        "suspension_type.value": _sources(
            {
                "default": "Rigid",
                "confidence": "medium",
                "evidence": "Fallback suspension type.",
                "safe_default": True,
            }
        ),
        "number_of_speeds.value": _sources(
            {
                "default": 1,
                "confidence": "medium",
                "evidence": "Fallback number of speeds.",
                "safe_default": True,
            }
        ),
        "brake_style.value": _sources(
            {
                "default": "Coaster",
                "confidence": "medium",
                "evidence": "Fallback brake style.",
                "safe_default": True,
            }
        ),
    }
    for path_key, sources in known.items():
        if get_rule_at_path(attributes, path_key) is not None and has_placeholder_source(
            get_rule_at_path(attributes, path_key) or {}
        ):
            _set_leaf_sources(attributes, path_key, sources)


def _patch_remaining_placeholders(product_type: str, attributes: Dict[str, Any]) -> None:
    for path_key, rule in list(iter_leaf_rules(attributes)):
        if not has_placeholder_source(rule):
            continue
        fallback = "Standard"
        if path_key.endswith(".unit"):
            fallback = "inches"
        elif "number_of" in path_key or path_key.endswith(".value") and "speed" in path_key:
            fallback = 1
        _set_leaf_sources(
            attributes,
            path_key,
            _sources(
                {
                    "default": fallback,
                    "confidence": "medium",
                    "evidence": f"Phase 2 bootstrap default for {product_type} {path_key}.",
                    "safe_default": True,
                }
            ),
        )


def patch_rules(rules: Dict[str, Any], product_type: str) -> Dict[str, Any]:
    patched = copy.deepcopy(rules)
    attributes = patched.setdefault("attributes", {})

    ignored = list(patched.get("coverage_ignore_required") or [])
    for name in COVERAGE_IGNORE:
        if name not in ignored:
            ignored.append(name)
    patched["coverage_ignore_required"] = ignored
    for name in COVERAGE_IGNORE:
        attributes.pop(name, None)

    _patch_commercial(attributes)
    _patch_category_placeholders(product_type, attributes)
    _patch_dimension_placeholders(attributes)
    _patch_known_defaults(product_type, attributes)
    _patch_remaining_placeholders(product_type, attributes)

    for path_key, rule in iter_leaf_rules(attributes):
        if has_placeholder_source(rule):
            raise RuntimeError(
                f"{product_type}: unresolved placeholder at {path_key}"
            )
    return patched


def main() -> None:
    loader = AttributeRuleLoader()
    for product_type in PHASE2_CATEGORIES:
        if product_type == "PLANTER":
            # already patched in a prior partial run; re-patch idempotently
            pass
        rules = loader.load(product_type)
        patched = patch_rules(rules, product_type)
        target = Path(loader.config_dir) / f"{product_type.lower()}.yaml"
        write_rule_yaml(
            target,
            patched,
            product_type=product_type,
            written_by="patch_phase2_onboard_rules",
        )
        print(f"Patched {product_type} -> {target}")


if __name__ == "__main__":
    main()
