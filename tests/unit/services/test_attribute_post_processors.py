"""Unit tests for config-driven attribute post processors."""

from src.services.attribute_post_processors import apply_attribute_post_processors


def test_apply_cabinet_attribute_shapes_normalizes_door_and_removes_inapplicable_fields():
    attrs = {
        "door": [{"value": "slab"}],
        "item_type_name": [{"value": "Cabinet"}],
        "target_audience_base": [{"value": "Homeowners"}],
    }

    apply_attribute_post_processors(
        ["cabinet_attribute_shapes"],
        attrs,
        marketplace_id="MARKET1",
    )

    assert "item_type_name" not in attrs
    assert "target_audience_base" not in attrs
    assert attrs["door"] == [
        {
            "style": [
                {
                    "value": "Slab",
                    "language_tag": "en_US",
                    "marketplace_id": "MARKET1",
                }
            ],
            "marketplace_id": "MARKET1",
        }
    ]


def test_unknown_post_processor_is_ignored():
    attrs = {"item_name": [{"value": "Mirror"}]}

    apply_attribute_post_processors(["unknown"], attrs, marketplace_id="MARKET1")

    assert attrs == {"item_name": [{"value": "Mirror"}]}
