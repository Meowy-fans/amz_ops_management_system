"""Unit tests for attribute payload rendering."""

from src.services.attribute_payload_renderer import AttributePayloadRenderer
from src.services.attribute_resolver import AttributeResolution


def test_renderer_passthrough_list_value_for_bullet_points():
    attrs = AttributePayloadRenderer().render(
        {
            "bullet_point": AttributeResolution(
                attribute="bullet_point",
                value=["Soft close doors", "Water resistant finish"],
                confidence="high",
                evidence="content.bullets",
                blocking=False,
                shape="list_value",
            )
        }
    )

    assert attrs["bullet_point"] == [
        {"value": "Soft close doors"},
        {"value": "Water resistant finish"},
    ]


def test_renderer_renders_object_default_shape():
    attrs = AttributePayloadRenderer().render(
        {
            "externally_assigned_product_identifier": AttributeResolution(
                attribute="externally_assigned_product_identifier",
                value={
                    "type": "GTIN_EXEMPTION",
                    "value": "product_does_not_have_gtin",
                },
                confidence="medium",
                evidence="preset",
                blocking=False,
                shape="object",
            )
        }
    )

    assert attrs["externally_assigned_product_identifier"] == [
        {"type": "GTIN_EXEMPTION", "value": "product_does_not_have_gtin"}
    ]
