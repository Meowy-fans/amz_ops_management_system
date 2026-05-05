import json

import pytest

from src.repositories.amz_template_repository import AmzTemplateRepository


class FetchResult:
    def __init__(self, one_row=None, scalar_value=None):
        self.one_row = one_row
        self.scalar_value = scalar_value

    def fetchone(self):
        return self.one_row

    def scalar_one(self):
        return self.scalar_value

    def scalar_one_or_none(self):
        return self.scalar_value


class RecordingSession:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return FetchResult()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _normalized(sql):
    return " ".join(sql.split())


def test_save_parsed_data_sql_contract_serializes_json_and_commits():
    session = RecordingSession([FetchResult(scalar_value=123)])
    repository = AmzTemplateRepository(session)
    parsed_results = {
        "fields": ["sku", "title"],
        "field_definitions": {"sku": {"required": True}},
        "valid_values": [{"field": "color", "values": ["Black"]}],
        "variation_mapping": {"Color": ["Black"]},
        "priority_themes": ["Color", "Size"],
    }

    inserted_id = repository.save_parsed_data(
        "CABINET", "cabinet-template.xlsx", parsed_results
    )

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert inserted_id == 123
    assert session.commits == 1
    assert session.rollbacks == 0
    assert "INSERT INTO amazon_cat_templates" in normalized_sql
    assert "RETURNING id" in normalized_sql
    assert params["category"] == "CABINET"
    assert params["template_name"] == "cabinet-template.xlsx"
    assert json.loads(params["fields"]) == parsed_results["fields"]
    assert json.loads(params["field_defs"]) == parsed_results["field_definitions"]
    assert json.loads(params["valid_values"]) == parsed_results["valid_values"]
    assert json.loads(params["variation_mapping"]) == parsed_results[
        "variation_mapping"
    ]
    assert json.loads(params["priority_themes"]) == parsed_results["priority_themes"]


def test_save_parsed_data_rolls_back_and_returns_none_when_database_fails():
    session = RecordingSession([RuntimeError("insert failed")])
    repository = AmzTemplateRepository(session)

    inserted_id = repository.save_parsed_data("CABINET", "template.xlsx", {})

    assert inserted_id is None
    assert session.commits == 0
    assert session.rollbacks == 1


def test_find_template_by_category_sql_contract_decodes_json_strings_and_defaults_invalid_json():
    row = (
        '["sku", "title"]',
        '{"sku": {"required": true}}',
        "not-json",
        '{"Color": ["Black"]}',
        '["Color"]',
    )
    session = RecordingSession([FetchResult(one_row=row)])
    repository = AmzTemplateRepository(session)

    template = repository.find_template_by_category("CABINET")

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert template == {
        "fields": ["sku", "title"],
        "field_definitions": {"sku": {"required": True}},
        "valid_values": [],
        "variation_mapping": {"Color": ["Black"]},
        "priority_themes": ["Color"],
    }
    assert "WHERE LOWER(category) = LOWER(:category)" in normalized_sql
    assert "ORDER BY id DESC LIMIT 1" in normalized_sql
    assert params == {"category": "CABINET"}


def test_find_template_by_category_returns_none_when_missing():
    session = RecordingSession([FetchResult(one_row=None)])
    repository = AmzTemplateRepository(session)

    assert repository.find_template_by_category("CABINET") is None


def test_find_template_by_category_reraises_database_errors():
    session = RecordingSession([RuntimeError("select failed")])
    repository = AmzTemplateRepository(session)

    with pytest.raises(RuntimeError, match="select failed"):
        repository.find_template_by_category("CABINET")


def test_find_latest_template_id_and_defs_sql_contract_decodes_json_string():
    session = RecordingSession(
        [FetchResult(one_row=(42, '{"sku": {"required": true}}'))]
    )
    repository = AmzTemplateRepository(session)

    latest = repository.find_latest_template_id_and_defs("CABINET")

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert latest == (42, {"sku": {"required": True}})
    assert "SELECT id, field_definitions" in normalized_sql
    assert "WHERE LOWER(category) = LOWER(:category)" in normalized_sql
    assert "ORDER BY id DESC LIMIT 1" in normalized_sql
    assert params == {"category": "CABINET"}


def test_find_latest_template_id_and_defs_returns_dict_payload_or_none():
    definitions = {"title": {"required": False}}
    dict_session = RecordingSession([FetchResult(one_row=(43, definitions))])
    missing_session = RecordingSession([FetchResult(one_row=None)])
    null_id_session = RecordingSession([FetchResult(one_row=(None, {"x": 1}))])

    assert AmzTemplateRepository(dict_session).find_latest_template_id_and_defs(
        "CABINET"
    ) == (43, definitions)
    assert (
        AmzTemplateRepository(missing_session).find_latest_template_id_and_defs(
            "CABINET"
        )
        is None
    )
    assert (
        AmzTemplateRepository(null_id_session).find_latest_template_id_and_defs(
            "CABINET"
        )
        is None
    )


def test_find_latest_template_id_and_defs_reraises_database_errors():
    session = RecordingSession([RuntimeError("select failed")])
    repository = AmzTemplateRepository(session)

    with pytest.raises(RuntimeError, match="select failed"):
        repository.find_latest_template_id_and_defs("CABINET")


def test_update_field_definitions_by_id_sql_contract_serializes_json_without_commit():
    session = RecordingSession()
    repository = AmzTemplateRepository(session)
    new_definitions = {"sku": {"required": True, "type": "string"}}

    result = repository.update_field_definitions_by_id(42, new_definitions)

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert result is True
    assert session.commits == 0
    assert "UPDATE amazon_cat_templates SET field_definitions = :defs" in (
        normalized_sql
    )
    assert "WHERE id = :id" in normalized_sql
    assert params["id"] == 42
    assert json.loads(params["defs"]) == new_definitions


def test_update_field_definitions_by_id_returns_false_when_database_fails():
    session = RecordingSession([RuntimeError("update failed")])
    repository = AmzTemplateRepository(session)

    assert repository.update_field_definitions_by_id(42, {"sku": {}}) is False


def test_find_latest_priority_themes_by_category_sql_contract_returns_list_only():
    session = RecordingSession([FetchResult(scalar_value=["Color", "Size"])])
    repository = AmzTemplateRepository(session)

    priority_themes = repository.find_latest_priority_themes_by_category("CABINET")

    sql, params = session.calls[0]
    normalized_sql = _normalized(sql)
    assert priority_themes == ["Color", "Size"]
    assert "SELECT priority_themes" in normalized_sql
    assert "WHERE LOWER(category) = LOWER(:category)" in normalized_sql
    assert "ORDER BY created_at DESC, id DESC LIMIT 1" in normalized_sql
    assert params == {"category": "CABINET"}


@pytest.mark.parametrize("stored_value", [[], None, '["Color"]'])
def test_find_latest_priority_themes_by_category_returns_none_for_non_list_or_empty_values(
    stored_value,
):
    session = RecordingSession([FetchResult(scalar_value=stored_value)])
    repository = AmzTemplateRepository(session)

    assert repository.find_latest_priority_themes_by_category("CABINET") is None


def test_find_latest_priority_themes_by_category_reraises_database_errors():
    session = RecordingSession([RuntimeError("select failed")])
    repository = AmzTemplateRepository(session)

    with pytest.raises(RuntimeError, match="select failed"):
        repository.find_latest_priority_themes_by_category("CABINET")
