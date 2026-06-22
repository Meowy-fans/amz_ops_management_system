"""Unit tests for schema-driven attribute rule draft generation."""

from src.services.attribute_rule_generator import AttributeRuleGenerator
from src.services.attribute_rule_loader import AttributeRuleLoader


class FakeSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "SOFA"
        return {
            "schema_json": {
                "properties": {
                    "brand": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "bullet_point": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "country_of_origin": {
                        "items": {"properties": {"value": {"enum": ["CN", "US"]}}}
                    },
                    "item_name": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "product_description": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "supplier_declared_dg_hz_regulation": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "fabric_type": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "mounting_type": {
                        "items": {
                            "properties": {
                                "value": {"enum": ["Floor Mount", "Wall Mount"]}
                            }
                        }
                    },
                    "number_of_items": {
                        "items": {"properties": {"value": {"type": "integer"}}}
                    },
                    "is_fragile": {
                        "items": {"properties": {"value": {"type": "boolean"}}}
                    },
                    "externally_assigned_product_identifier": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "safety_compliance_certification": {
                        "items": {"properties": {"value": {"type": "string"}}}
                    },
                    "frame": {
                        "items": {
                            "properties": {
                                "material": {"type": "array"},
                            }
                        }
                    },
                },
                "required": [
                    "brand",
                    "bullet_point",
                    "country_of_origin",
                    "item_name",
                    "product_description",
                    "supplier_declared_dg_hz_regulation",
                    "fabric_type",
                    "mounting_type",
                    "number_of_items",
                    "is_fragile",
                    "externally_assigned_product_identifier",
                    "safety_compliance_certification",
                    "frame",
                ],
            },
            "required_properties": [
                "brand",
                "bullet_point",
                "country_of_origin",
                "item_name",
                "product_description",
                "supplier_declared_dg_hz_regulation",
                "fabric_type",
                "mounting_type",
                "number_of_items",
                "is_fragile",
                "externally_assigned_product_identifier",
                "safety_compliance_certification",
                "frame",
            ],
        }


def test_generator_writes_dry_run_rule_draft(tmp_path):
    generator = AttributeRuleGenerator(
        schema_service=FakeSchemaService(),
        output_dir=tmp_path,
    )

    result = generator.generate("SOFA")

    assert result.written is True
    assert result.path == tmp_path / "sofa.yaml"
    assert result.rules["mode"] == "dry_run"
    assert result.rules["presets"] == ["amazon_universal_required_v1"]
    assert "brand" not in result.rules["attributes"]
    assert "item_name" not in result.rules["attributes"]
    assert result.rules["attributes"]["mounting_type"]["transform"] == "enum"
    assert {"llm": {"hint": "Extract mounting type from the product title, description, bullet points, and supplier characteristics. Return null if the information is not found."}} in result.rules["attributes"]["mounting_type"]["sources"]
    assert result.rules["attributes"]["fabric_type"]["manual_review"] is False
    assert result.rules["attributes"]["number_of_items"]["sources"][-1] == {
        "default": 1,
        "confidence": "medium",
        "evidence": "Single-item listing fallback when supplier data lacks package count.",
        "safe_default": True,
    }
    assert result.rules["attributes"]["number_of_items"]["manual_review"] is False
    assert result.rules["attributes"]["is_fragile"]["sources"][-1] == {
        "default": None,
        "confidence": "low",
        "evidence": "TODO: review safe default for is_fragile",
    }
    assert result.rules["attributes"]["is_fragile"]["manual_review"] is True
    assert "externally_assigned_product_identifier" not in result.rules["attributes"]
    assert (
        result.rules["attributes"]["safety_compliance_certification"]["manual_review"]
        is True
    )
    assert result.rules["attributes"]["safety_compliance_certification"]["sources"] == [
        {
            "default": None,
            "confidence": "low",
            "evidence": "TODO: review source mapping for safety_compliance_certification",
        }
    ]
    assert result.rules["attributes"]["frame"]["manual_review"] is True
    assert result.path.exists()


def test_generator_supports_dict_candidates_and_passthrough_transform(tmp_path):
    generator = AttributeRuleGenerator(
        schema_service=FakeSchemaService(),
        output_dir=tmp_path,
    )

    rule = generator._rule_for_attribute(
        "bullet_point",
        {"items": {"properties": {"value": {"type": "string"}}}},
        ["bullet_point"],
    )

    assert rule["transform"] == "passthrough"
    assert rule["sources"][0] == {"path": "content.bullets"}
    assert "llm" in rule["sources"][1]
    assert rule["sources"][2] == {
        "default": None,
        "confidence": "low",
        "evidence": "TODO: review safe default for bullet_point",
    }
    assert rule["manual_review"] is False


def test_generator_uses_injected_safe_default_preset(tmp_path):
    loader = AttributeRuleLoader(
        config_dir=tmp_path,
        preset_by_name={
            "amazon_required_safe_defaults_v1": {
                "attributes": {
                    "is_fragile": {
                        "sources": [
                            {
                                "default": "No",
                                "confidence": "medium",
                                "evidence": "Only for tested furniture categories.",
                                "safe_default": True,
                            }
                        ]
                    }
                }
            }
        },
    )
    generator = AttributeRuleGenerator(
        schema_service=FakeSchemaService(),
        output_dir=tmp_path,
        rule_loader=loader,
    )

    rule = generator._rule_for_attribute(
        "is_fragile",
        {"items": {"properties": {"value": {"type": "boolean"}}}},
        ["is_fragile"],
    )

    assert rule["sources"][-1] == {
        "default": "No",
        "confidence": "medium",
        "evidence": "Only for tested furniture categories.",
        "safe_default": True,
    }
    assert rule["manual_review"] is False


def test_generator_does_not_overwrite_existing_file_without_flag(tmp_path):
    existing = tmp_path / "sofa.yaml"
    existing.write_text("product_type: SOFA\n", encoding="utf-8")
    generator = AttributeRuleGenerator(
        schema_service=FakeSchemaService(),
        output_dir=tmp_path,
    )

    result = generator.generate("SOFA", overwrite=False)

    assert result.written is False
    assert result.existed is True
    assert "not overwritten" in result.warnings[0]
    assert existing.read_text(encoding="utf-8") == "product_type: SOFA\n"
