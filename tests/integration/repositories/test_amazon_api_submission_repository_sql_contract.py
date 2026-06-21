"""SQL contract tests for AmazonAPISubmissionRepository."""
from src.repositories.amazon_api_submission_repository import AmazonAPISubmissionRepository


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class MappingResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self.rows


class RecordingSession:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if not self.results:
            raise AssertionError("Unexpected execute call")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def commit(self):
        pass


def _normalized(sql):
    return " ".join(sql.split())


def test_insert_submission_sql_contract():
    session = RecordingSession([ScalarResult(1)])
    repo = AmazonAPISubmissionRepository(session)

    result_id = repo.insert_submission(
        sku="SKU1",
        operation="both",
        status="success",
        amazon_request_id="REQ-1",
        marketplace_id="ATVPDKIKX0DER",
        product_type="CABINET",
    )

    assert result_id == 1
    assert len(session.calls) == 1
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "INSERT INTO amazon_api_submissions" in sql
    assert params["sku"] == "SKU1"
    assert params["operation"] == "both"
    assert params["status"] == "success"
    assert params["amazon_request_id"] == "REQ-1"


def test_insert_submission_stores_json_payloads():
    session = RecordingSession([ScalarResult(2)])
    repo = AmazonAPISubmissionRepository(session)

    repo.insert_submission(
        sku="SKU1",
        operation="price",
        status="failed",
        request_payload={"productType": "HOME_MIRROR", "patches": [{"op": "replace"}]},
        response_body={"errors": [{"message": "bad"}]},
        error_message="some error",
    )

    params = session.calls[0][1]
    assert '"productType"' in params["request_payload"]
    assert '"errors"' in params["response_body"]


def test_insert_submission_nullable_fields_default_none():
    session = RecordingSession([ScalarResult(3)])
    repo = AmazonAPISubmissionRepository(session)

    repo.insert_submission(sku="SKU1", operation="quantity", status="dry_run")

    params = session.calls[0][1]
    assert params["amazon_request_id"] is None
    assert params["response_body"] is None
    assert params["error_message"] is None


def test_get_delayed_confirmation_candidates_sql_contract():
    session = RecordingSession([
        MappingResult([
            {
                "id": 1123,
                "sku": "SKU1",
                "operation": "both",
                "status": "confirmed_with_mismatch",
            }
        ])
    ])
    repo = AmazonAPISubmissionRepository(session)

    rows = repo.get_delayed_confirmation_candidates(
        older_than_minutes=30,
        limit=25,
    )

    assert rows[0]["id"] == 1123
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "source.status IN" in sql
    assert "'confirmed_with_mismatch'" in sql
    assert "'confirmed_with_issues'" in sql
    assert "source.submitted_at <= NOW()" in sql
    assert "child.operation = 'delayed_confirmation'" in sql
    assert "child.response_body->>'source_submission_id' = source.id::text" in sql
    assert "ORDER BY source.submitted_at ASC" in sql
    assert params == {"older_than_minutes": 30, "limit": 25}


def test_get_latest_delayed_confirmation_items_sql_contract():
    session = RecordingSession([
        MappingResult([
            {
                "id": 1942,
                "sku": "SKU1",
                "status": "delayed_confirmed_with_issues",
            }
        ])
    ])
    repo = AmazonAPISubmissionRepository(session)

    rows = repo.get_latest_delayed_confirmation_items(limit=10)

    assert rows[0]["id"] == 1942
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "DISTINCT ON (sku, marketplace_id)" in sql
    assert "operation = 'delayed_confirmation'" in sql
    assert "response_body->>'source_submission_id'" in sql
    assert "ORDER BY sku, marketplace_id, submitted_at DESC" in sql
    assert params == {"limit": 10}


def test_get_learned_required_attributes_sql_contract():
    session = RecordingSession([
        MappingResult([
            {"attribute_name": "mounting_type"},
            {"attribute_name": "model_name"},
        ])
    ])
    repo = AmazonAPISubmissionRepository(session)

    attrs = repo.get_learned_required_attributes("HOME_MIRROR")

    assert attrs == ["mounting_type", "model_name"]
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "jsonb_array_elements(response_body->'issues')" in sql
    assert "issue->>'code' = '90220'" in sql
    assert "jsonb_array_elements_text(" in sql
    assert "COALESCE(issue->'attributeNames', '[]'::jsonb)" in sql
    assert "product_type = :product_type" in sql
    assert "ORDER BY attribute_name" in sql
    assert params == {"product_type": "HOME_MIRROR"}
