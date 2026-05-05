from src.utils.data_mapping_tasks import collect_llm_tasks_from_mapping
from src.utils.data_mapping_valid_values import (
    align_to_valid_values,
    fuzzy_select,
    normalize_text,
)
from src.utils.data_field_mapper import DataFieldMapper


def test_align_to_valid_values_exact_normalized_and_fuzzy_matches():
    mapped_data = {
        "Color": "light-blue",
        "Style": "modrn",
        "Quantity": 1,
        "Tags": ["home"],
    }
    template_rules = {
        "valid_values": [
            {"attribute": "Color", "values": ["Light Blue", "Black"]},
            {"attribute": "Style", "values": ["Modern", "Classic"]},
            {"attribute": "Quantity", "values": ["1"]},
            {"attribute": "Tags", "values": ["home"]},
        ]
    }

    result = align_to_valid_values(mapped_data, template_rules)

    assert result["Color"] == "Light Blue"
    assert result["Style"] == "Modern"
    assert result["Quantity"] == 1
    assert result["Tags"] == ["home"]
    assert normalize_text(" Light_Blue ") == "light blue"
    assert fuzzy_select("modrn", ["Modern"], cutoff=0.8) == "Modern"


def test_collect_llm_tasks_from_mapping_includes_valid_options():
    mapping_config = {
        "Style": {
            "source_type": "llm_enhanced",
            "description": "Pick style",
            "output_type": "string",
        },
        "Static": {"source_type": "static", "value": "x"},
    }
    template_rules = {
        "valid_values": [{"attribute": " style ", "values": ["Modern"]}]
    }

    tasks = collect_llm_tasks_from_mapping(mapping_config, template_rules)

    assert tasks == [{
        "field_name": "Style",
        "description": "Pick style",
        "output_type": "string",
        "valid_options": ["Modern"],
    }]


def test_data_field_mapper_fallback_branches():
    mapper = DataFieldMapper()

    assert mapper.map_single_field(
        "Item Width",
        {"source_type": "item_dimension", "dimension": "assembledWidth"},
        {},
        {"assembledWidth": 12},
        {},
    ) == 12
    assert mapper.map_single_field(
        "Amazon Type",
        {"source_type": "category_lookup", "lookup_key": "amazon_type"},
        {"category_name": "cabinet"},
        {},
        None,
    ) is None
    assert mapper.map_single_field(
        "Amazon Type",
        {"source_type": "category_lookup"},
        {"category_name": "cabinet"},
        {},
        {"CABINET": {"amazon_type": "Storage Cabinet"}},
    ) is None
    assert mapper.map_single_field(
        "Unknown",
        {"source_type": "unknown"},
        {},
        {},
        {},
    ) is None


def test_data_field_mapper_json_unit_and_weight_fallbacks():
    mapper = DataFieldMapper()

    assert mapper.get_jsonb_value({}, "") is None
    assert mapper.get_jsonb_value({"attributes": "not a dict"}, "attributes.color") is None
    assert mapper.get_jsonb_value({"attributes": {"color": None}}, "attributes.color") is None
    assert mapper.map_unit("unknown", {"weightUnit": "lb", "lengthUnit": "in"}) is None
    assert mapper.calculate_weight("item", {"assembledWeight": 2.5}) == 2.5
