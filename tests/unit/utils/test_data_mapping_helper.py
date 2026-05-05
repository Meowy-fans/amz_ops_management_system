import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from infrastructure.llm.types import LLMResponse
from src.utils.data_mapping_helper import DataMappingHelper

# Subclass to bypass file loading logic safely
class MockDataMappingHelper(DataMappingHelper):
    def _load_mapping_config(self):
        # Return empty dict initially, we will inject real config manually
        return {}

@pytest.fixture
def sample_mapping_config():
    return {
        "StaticField": {"source_type": "static", "value": "StaticValue"},
        "DirectField": {"source_type": "direct", "value": "product_name"},
        "DBField": {"source_type": "db_field", "field": "vendor_sku"},
        "JsonbField": {"source_type": "jsonb", "json_path": "attributes.color"},
        "UnitField": {"source_type": "unit_mapper", "unit_type": "weight"},
    }

@pytest.fixture
def helper(sample_mapping_config):
    # Pass dummy path since subclass overrides loading
    helper = MockDataMappingHelper(config_path=Path("dummy"))
    # Manually inject the config we want to test
    helper.mapping_config = sample_mapping_config
    return helper

class TestDataMappingHelper:
    def test_load_mapping_config_from_file(self, tmp_path):
        config_path = tmp_path / "amz_mapping.json"
        config_path.write_text(
            json.dumps({"mappings": {"Brand": {"source_type": "direct", "value": "brand"}}}),
            encoding="utf-8",
        )

        helper = DataMappingHelper(config_path=config_path)

        assert helper.mapping_config == {
            "Brand": {"source_type": "direct", "value": "brand"}
        }

    def test_load_mapping_config_raises_for_invalid_json(self, tmp_path):
        config_path = tmp_path / "amz_mapping.json"
        config_path.write_text("{bad json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            DataMappingHelper(config_path=config_path)

    def test_apply_mapping_returns_empty_for_empty_product(self, helper):
        assert helper.apply_mapping({}, {}) == {}

    def test_static_mapping(self, helper):
        product_data = {"dummy": "data"}
        result = helper.apply_mapping(product_data, {})
        assert result.get("StaticField") == "StaticValue"

    def test_direct_mapping(self, helper):
        product_data = {"product_name": "My Product"}
        result = helper.apply_mapping(product_data, {})
        assert result.get("DirectField") == "My Product"

    def test_db_field_mapping(self, helper):
        product_data = {"vendor_sku": "V-123"}
        result = helper.apply_mapping(product_data, {})
        assert result.get("DBField") == "V-123"

    def test_jsonb_mapping(self, helper):
        product_data = {
            "raw_data": {
                "attributes": {"color": "Red"}
            }
        }
        result = helper.apply_mapping(product_data, {})
        assert result.get("JsonbField") == "Red"

    def test_unit_mapping(self, helper):
        product_data = {
            "raw_data": {"weightUnit": "lb"}
        }
        result = helper.apply_mapping(product_data, {})
        assert result.get("UnitField") == "Pounds"

    def test_field_reference_and_valid_value_alignment(self, helper):
        helper.mapping_config = {
            "Color": {"source_type": "direct", "value": "color"},
            "CopiedColor": {"source_type": "field_reference", "field": "Color"}
        }
        product_data = {"color": "light-blue"}
        template_rules = {
            "valid_values": [
                {"attribute": "Color", "values": ["Light Blue", "Black"]}
            ]
        }

        result = helper.apply_mapping(product_data, template_rules)

        assert result["Color"] == "Light Blue"
        assert result["CopiedColor"] == "light-blue"

    def test_map_single_field_extended_source_types(self, helper):
        raw_data = {
            "attributes": {"material": "Not Applicable"},
            "tags": ["home", "decor"],
            "comboInfo": [
                {"assembledLength": 12, "weight": 2.5},
                {"weight": 1.5}
            ],
            "assembledWidth": "Not Applicable",
            "weightUnit": "kg",
            "lengthUnit": "in",
            "comboFlag": True
        }
        product_data = {
            "category_name": "CABINET",
            "name": "Product",
            "subtitle": "Subtitle"
        }
        category_map = {"CABINET": {"amazon_type": "Storage Cabinet"}}

        assert helper._map_single_field(
            "Product Type",
            {"source_type": "direct", "value": "category_name"},
            product_data,
            raw_data,
            category_map
        ) == "CABINET"
        assert helper._map_single_field(
            "Bullets",
            {"source_type": "db_field_multiple", "fields": ["name", "subtitle", "missing"]},
            product_data,
            raw_data,
            category_map
        ) == ["Product", "Subtitle"]
        assert helper._map_single_field(
            "Material",
            {"source_type": "jsonb", "json_path": "attributes.material", "fallback": "Wood"},
            product_data,
            raw_data,
            category_map
        ) == "Wood"
        assert helper._map_single_field(
            "Tags",
            {"source_type": "jsonb_array", "json_path": "tags"},
            product_data,
            raw_data,
            category_map
        ) == ["home", "decor"]
        assert helper._map_single_field(
            "Package Quantity",
            {"source_type": "jsonb_computed", "json_path": "comboInfo"},
            product_data,
            raw_data,
            category_map
        ) == 2
        assert helper._map_single_field(
            "Package Length",
            {"source_type": "package_dimension", "dimension": "assembledLength"},
            product_data,
            raw_data,
            category_map
        ) == 12
        assert helper._map_single_field(
            "Item Width",
            {"source_type": "item_dimension", "dimension": "assembledWidth"},
            product_data,
            raw_data,
            category_map
        ) is None
        assert helper._map_single_field(
            "Dimension Unit",
            {"source_type": "unit_mapper", "unit_type": "dimension"},
            product_data,
            raw_data,
            category_map
        ) == "Inches"
        assert helper._map_single_field(
            "Weight",
            {"source_type": "summed_weight", "weight_type": "package"},
            product_data,
            raw_data,
            category_map
        ) == 4.0
        assert helper._map_single_field(
            "Amazon Type",
            {"source_type": "category_lookup", "lookup_key": "amazon_type"},
            product_data,
            raw_data,
            category_map
        ) == "Storage Cabinet"

    def test_enrich_with_llm_adds_valid_options_and_strips_html(self, helper):
        llm_service = MagicMock()
        llm_service.generate.return_value = LLMResponse(content={"Style": "Modern"})
        product_data = {
            "product_name": "Cabinet",
            "product_description": "<p>Modern cabinet</p>",
            "raw_data": {
                "attributes": {"color": "white"},
                "characteristics": ["storage"],
                "assembledLength": 12
            }
        }
        template_rules = {
            "valid_values": [{"attribute": "Style", "values": ["Modern", "Classic"]}]
        }

        with patch('src.utils.prompt_manager.PromptManager') as MockPromptManager:
            MockPromptManager.return_value.get_prompt.return_value = "system prompt"
            result = helper._enrich_with_llm(
                product_data,
                [{"field_name": "Style", "description": "Pick style"}],
                template_rules,
                llm_service
            )

        assert result == {"Style": "Modern"}
        request = llm_service.generate.call_args[0][0]
        assert request.json_mode is True
        assert "<p>" not in request.user_prompt
        assert "Modern" in request.user_prompt

    def test_enrich_with_llm_returns_empty_when_prompt_missing_or_llm_fails(self, helper):
        llm_service = MagicMock()

        with patch('src.utils.prompt_manager.PromptManager') as MockPromptManager:
            MockPromptManager.return_value.get_prompt.return_value = None
            assert helper._enrich_with_llm({}, [{"field_name": "Style"}], {}, llm_service) == {}
            llm_service.generate.assert_not_called()

        llm_service.generate.side_effect = RuntimeError("llm failed")
        with patch('src.utils.prompt_manager.PromptManager') as MockPromptManager:
            MockPromptManager.return_value.get_prompt.return_value = "system prompt"
            assert helper._enrich_with_llm({}, [{"field_name": "Style"}], {}, llm_service) == {}

    def test_get_llm_tasks_includes_valid_options(self, helper):
        helper.mapping_config = {
            "Style": {
                "source_type": "llm_enhanced",
                "description": "Pick style",
                "output_type": "string"
            },
            "Static": {"source_type": "static", "value": "x"}
        }

        tasks = helper.get_llm_tasks({
            "valid_values": [{"attribute": " style ", "values": ["Modern"]}]
        })

        assert tasks == [{
            "field_name": "Style",
            "description": "Pick style",
            "output_type": "string",
            "valid_options": ["Modern"]
        }]

    def test_apply_mapping_merges_llm_enrichment(self, helper, monkeypatch):
        helper.mapping_config = {
            "StaticField": {"source_type": "static", "value": "StaticValue"},
            "Style": {
                "source_type": "llm_enhanced",
                "description": "Pick style",
                "output_type": "string",
            },
        }
        llm_service = object()
        seen = []

        def enrich(product_data, llm_tasks, template_rules, service):
            seen.append((product_data, llm_tasks, template_rules, service))
            return {"Style": "Modern"}

        monkeypatch.setattr(helper, "_enrich_with_llm", enrich)

        result = helper.apply_mapping(
            {"product_name": "Cabinet"},
            {"valid_values": [{"attribute": "Style", "values": ["Modern"]}]},
            llm_service=llm_service,
        )

        assert result == {"StaticField": "StaticValue", "Style": "Modern"}
        assert seen[0][1] == [{
            "field_name": "Style",
            "description": "Pick style",
            "output_type": "string",
        }]
        assert seen[0][3] is llm_service

    def test_apply_mapping_keeps_non_llm_data_when_llm_enrichment_fails(self, helper, monkeypatch):
        helper.mapping_config = {
            "StaticField": {"source_type": "static", "value": "StaticValue"},
            "Style": {"source_type": "llm_enhanced", "description": "Pick style"},
        }

        def fail_enrich(*args, **kwargs):
            raise RuntimeError("llm failed")

        monkeypatch.setattr(helper, "_enrich_with_llm", fail_enrich)

        result = helper.apply_mapping({"product_name": "Cabinet"}, {}, llm_service=object())

        assert result == {"StaticField": "StaticValue"}

    def test_wrapper_helpers_delegate_to_extracted_mapping_logic(self, helper):
        raw_data = {
            "attributes": {"color": "Red"},
            "weightUnit": "oz",
            "lengthUnit": "cm",
            "assembledWeight": 2.5,
        }

        assert helper._strip_html(None) == ""
        assert helper._strip_html("<p>Hello<br> world</p>") == "Hello world"
        assert helper._get_jsonb_value(raw_data, "attributes.color") == "Red"
        assert helper._normalize_text(" Light_Blue ") == "light blue"
        assert helper._fuzzy_select("modrn", ["Modern"], cutoff=0.8) == "Modern"
        assert helper._map_unit("weight", raw_data) == "Ounces"
        assert helper._map_unit("dimension", raw_data) == "Centimeters"
        assert helper._calculate_weight("item", raw_data) == 2.5
