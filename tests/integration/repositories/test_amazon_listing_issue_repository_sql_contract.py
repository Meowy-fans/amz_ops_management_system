"""SQL contract tests for AmazonListingIssueRepository."""
from src.repositories.amazon_listing_issue_repository import (
    AmazonListingIssueRepository,
)


class ScalarResult:
    def __init__(self, value):
        self.value = value
        self.rowcount = 1

    def scalar_one(self):
        return self.value

    def fetchall(self):
        return []


class RecordingSession:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.commits = 0

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if not self.results:
            return ScalarResult(0)
        return self.results.pop(0)

    def commit(self):
        self.commits += 1


def _normalized(sql):
    return " ".join(sql.split())


def test_begin_and_finish_scan_sql_contract():
    session = RecordingSession([ScalarResult(7), ScalarResult(0)])
    repo = AmazonListingIssueRepository(session)

    scan_id = repo.begin_scan("listings_items")
    repo.finish_scan(scan_id, "success", 3, 2, 1)

    assert scan_id == 7
    assert "INSERT INTO amazon_listing_issue_scan_runs" in _normalized(session.calls[0][0])
    assert "UPDATE amazon_listing_issue_scan_runs" in _normalized(session.calls[1][0])
    assert session.calls[1][1]["checked_count"] == 3
    assert session.calls[1][1]["issue_count"] == 2
    assert session.calls[1][1]["action_count"] == 1


def test_upsert_issue_sql_contract():
    session = RecordingSession([ScalarResult(11)])
    repo = AmazonListingIssueRepository(session)

    issue_id = repo.upsert_issue(
        {
            "scan_run_id": 7,
            "sku": "SKU1",
            "asin": "ASIN1",
            "marketplace_id": "ATVPDKIKX0DER",
            "product_type": "CABINET",
            "issue_key": "KEY1",
            "issue_code": "18448",
            "severity": "WARNING",
            "message": "missing attr",
            "attribute_names": ["recommended_uses_for_product"],
            "categories": ["MISSING_ATTRIBUTE"],
            "source": "listings_items",
            "raw_issue": {"code": "18448"},
        }
    )

    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert issue_id == 11
    assert "INSERT INTO amazon_listing_issues" in sql
    assert "ON CONFLICT" in sql
    assert params["sku"] == "SKU1"
    assert params["issue_code"] == "18448"
    assert "recommended_uses_for_product" in params["attribute_names"]


def test_insert_action_sql_contract():
    session = RecordingSession([ScalarResult(21)])
    repo = AmazonListingIssueRepository(session)

    action_id = repo.insert_action(
        issue_id=11,
        scan_run_id=7,
        sku="SKU1",
        marketplace_id="ATVPDKIKX0DER",
        product_type="CABINET",
        action_type="patch_listing_attribute",
        status="dry_run",
        reason="补字段",
        request_payload={"patches": []},
    )

    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert action_id == 21
    assert "INSERT INTO amazon_listing_issue_actions" in sql
    assert params["action_type"] == "patch_listing_attribute"
    assert '"patches"' in params["request_payload"]


def test_get_open_issues_can_filter_by_source():
    session = RecordingSession([ScalarResult(0)])
    repo = AmazonListingIssueRepository(session)

    repo.get_open_issues(limit=50, source="price_inventory_confirmation")

    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "FROM amazon_listing_issues" in sql
    assert "WHERE status = 'open'" in sql
    assert "AND source = :source" in sql
    assert "LIMIT :limit" in sql
    assert params == {"source": "price_inventory_confirmation", "limit": 50}


def test_mark_resolved_for_sku_source_sql_contract():
    session = RecordingSession([ScalarResult(0)])
    repo = AmazonListingIssueRepository(session)

    repo.mark_resolved_for_sku_source(
        sku="SKU1",
        marketplace_id="ATVPDKIKX0DER",
        source="price_inventory_confirmation",
        seen_issue_keys=["KEY1"],
    )

    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "UPDATE amazon_listing_issues" in sql
    assert "AND source = :source" in sql
    assert "AND issue_key NOT IN" in sql
    assert params["source"] == "price_inventory_confirmation"


def test_get_submitted_actions_for_confirmation_sql_contract():
    session = RecordingSession([ScalarResult(0)])
    repo = AmazonListingIssueRepository(session)

    repo.get_submitted_actions_for_confirmation(older_than_minutes=30, limit=100)

    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "FROM amazon_listing_issue_actions action" in sql
    assert "JOIN amazon_listing_issues issue" in sql
    assert "action.status = 'submitted'" in sql
    assert "action.executed_at <= NOW()" in sql
    assert "confirm_patch_listing_attribute" in sql
    assert params == {"older_than_minutes": 30, "limit": 100}


def test_mark_issue_resolved_sql_contract():
    session = RecordingSession([ScalarResult(0)])
    repo = AmazonListingIssueRepository(session)

    repo.mark_issue_resolved(issue_id=11)

    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "UPDATE amazon_listing_issues" in sql
    assert "SET status = 'resolved'" in sql
    assert "WHERE id = :issue_id" in sql
    assert params["issue_id"] == 11


def test_has_confirmed_repair_after_sql_contract():
    session = RecordingSession([ScalarResult(True)])
    repo = AmazonListingIssueRepository(session)

    result = repo.has_confirmed_repair_after(
        sku="SKU1",
        marketplace_id="ATVPDKIKX0DER",
        issue_code="18448",
        attribute_names=["recommended_uses_for_product"],
        submitted_at="2026-06-09T02:41:00+08:00",
    )

    assert result is True
    sql = _normalized(session.calls[0][0])
    params = session.calls[0][1]
    assert "FROM amazon_listing_issue_actions confirm_action" in sql
    assert "confirm_action.status = 'repair_confirmed'" in sql
    assert "confirm_action.executed_at > :submitted_at" in sql
    assert "issue.issue_code = :issue_code" in sql
    assert "issue.attribute_names = CAST(:attribute_names AS jsonb)" in sql
    assert params["attribute_names"] == '["recommended_uses_for_product"]'
