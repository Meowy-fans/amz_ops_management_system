"""Unit tests for schema-driven attribute rule draft generation."""

from src.services.attribute_rule_generator import AttributeRuleGenerator


class FakeSchemaService:
    def get_or_fetch_schema(self, product_type):
        assert product_type == "SOFA"
        return {
            "schema_json": {
                "properties": {
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
                    "frame": {
                        "items": {
                            "properties": {
                                "material": {"type": "array"},
                            }
                        }
                    },
                },
                "required": [
                    "fabric_type",
                    "mounting_type",
                    "externally_assigned_product_identifier",
                    "frame",
                ],
            },
            "required_properties": [
                "fabric_type",
                "mounting_type",
                "externally_assigned_product_identifier",
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
    assert result.rules["attributes"]["mounting_type"]["transform"] == "enum"
    assert result.rules["attributes"]["fabric_type"]["manual_review"] is False
    assert (
        result.rules["attributes"]["externally_assigned_product_identifier"]["manual_review"]
        is True
    )
    assert result.rules["attributes"]["frame"]["manual_review"] is True
    assert result.path.exists()


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
