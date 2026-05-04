from src.utils.data_mapping_tasks import collect_llm_tasks_from_mapping
from src.utils.data_mapping_valid_values import (
    align_to_valid_values,
    fuzzy_select,
    normalize_text,
)


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
