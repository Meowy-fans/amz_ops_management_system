"""Unit tests for schema-driven attribute rule draft generation."""

from src.services.attribute_rule_generator import AttributeRuleGenerator


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
    assert result.rules["attributes"]["fabric_type"]["manual_review"] is False
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
    assert rule["sources"] == [{"path": "content.bullets"}]
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
