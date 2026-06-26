"""Tests for V2 schema condition evaluation."""

from src.services.schema_condition_evaluator_v2 import SchemaConditionEvaluatorV2


def test_evaluator_matches_not_required_when_attribute_absent():
    evaluator = SchemaConditionEvaluatorV2()
    schema = {"not": {"required": ["parentage_level"]}}

    result = evaluator.evaluate(schema, payload={})

    assert result.result == "true"


def test_evaluator_matches_contains_enum_in_array_payload():
    evaluator = SchemaConditionEvaluatorV2()
    schema = {
        "required": ["variation_theme"],
        "properties": {
            "variation_theme": {
                "contains": {
                    "required": ["name"],
                    "properties": {"name": {"enum": ["COLOR"]}},
                }
            }
        },
    }
    payload = {"variation_theme": [{"name": "COLOR"}]}

    result = evaluator.evaluate(schema, payload=payload)

    assert result.result == "true"
    assert "variation_theme" in result.dependent_paths


def test_evaluator_rejects_contains_enum_mismatch():
    evaluator = SchemaConditionEvaluatorV2()
    schema = {
        "required": ["variation_theme"],
        "properties": {
            "variation_theme": {
                "contains": {
                    "required": ["name"],
                    "properties": {"name": {"enum": ["COLOR"]}},
                }
            }
        },
    }
    payload = {"variation_theme": [{"name": "SIZE"}]}

    result = evaluator.evaluate(schema, payload=payload)

    assert result.result == "false"


def test_evaluator_marks_unsupported_predicate_unknown_for_builder():
    evaluator = SchemaConditionEvaluatorV2()
    schema = {"dependentRequired": {"battery": ["battery_type"]}}

    result = evaluator.evaluate(schema, payload={"battery": [{"value": "yes"}]})

    assert result.result == "unsupported"
    assert result.is_unknown
    assert "dependentRequired" in result.traces[0].reason
