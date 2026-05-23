"""Unit tests for AmazonListingIssueSyncService."""
from unittest.mock import MagicMock

from src.services.amazon_listing_issue_sync_service import (
    AmazonListingIssueSyncService,
)


class FakeIssueRepo:
    def __init__(self):
        self.scan_id = 101
        self.upserts = []
        self.resolved_skus = []
        self.resolved_sources = []
        self.finished = []

    def begin_scan(self, source):
        self.source = source
        return self.scan_id

    def get_report_skus(self, limit=None):
        return [{"sku": "SKU1", "asin": "ASIN1"}]

    def upsert_issue(self, issue):
        self.upserts.append(issue)
        return len(self.upserts)

    def mark_resolved_for_sku(self, sku, marketplace_id, seen_issue_keys):
        self.resolved_skus.append((sku, marketplace_id, list(seen_issue_keys)))
        return 0

    def mark_resolved_for_source(self, source, marketplace_id, seen_issue_keys):
        self.resolved_sources.append((source, marketplace_id, list(seen_issue_keys)))
        return 0

    def get_open_issues(self, limit=None):
        return list(self.upserts)

    def finish_scan(self, **kwargs):
        self.finished.append(kwargs)


class FakeListingsClient:
    def get_listings_item(self, sku, issue_locale="en_US", included_data=None):
        assert included_data == ["summaries", "issues", "productTypes"]
        return {
            "body": {
                "summaries": [
                    {
                        "asin": "ASIN1",
                        "itemName": "Bathroom Cabinet",
                    }
                ],
                "productTypes": [{"productType": "CABINET"}],
                "issues": [
                    {
                        "code": "18448",
                        "severity": "WARNING",
                        "message": "missing recommended_uses_for_product",
                        "attributeNames": ["recommended_uses_for_product"],
                        "categories": ["MISSING_ATTRIBUTE"],
                    }
                ],
            }
        }


class FakeReportsClient:
    def create_suppressed_listings_report(self):
        return "R1"

    def wait_for_report(self, report_id):
        return "D1"

    def get_report_document(self, document_id):
        return {"url": "https://example/report.txt"}

    def download_report_document(self, document):
        return (
            "Status\tReason\tSKU\tASIN\tProduct name\tIssue Description\n"
            "Search Suppressed\tInvalid information\tSKU2\tASIN2\tMirror\tmain image has watermark\n"
        )


class FakeRepairService:
    def __init__(self):
        self.calls = []

    def plan_and_execute(self, issues, scan_run_id=None, dry_run=True):
        self.calls.append(
            {"issues": issues, "scan_run_id": scan_run_id, "dry_run": dry_run}
        )
        return [{"sku": issue["sku"], "status": "dry_run"} for issue in issues]


def test_sync_and_repair_persists_listing_and_suppressed_issues():
    repo = FakeIssueRepo()
    repair = FakeRepairService()
    service = AmazonListingIssueSyncService(
        db=MagicMock(),
        listings_client=FakeListingsClient(),
        reports_client=FakeReportsClient(),
        issue_repo=repo,
        repair_service=repair,
    )

    result = service.sync_and_repair(limit=1, dry_run=True)

    assert result["scan_run_id"] == 101
    assert result["checked_count"] == 1
    assert result["issue_count"] == 2
    assert len(repo.upserts) == 2
    assert repo.upserts[0]["sku"] == "SKU1"
    assert repo.upserts[0]["product_type"] == "CABINET"
    assert repo.upserts[1]["sku"] == "SKU2"
    assert "INVALID_IMAGE" in repo.upserts[1]["categories"]
    assert repo.resolved_skus[0][0] == "SKU1"
    assert repo.resolved_sources[0][0] == "suppressed_report"
    assert repair.calls[0]["scan_run_id"] == 101
    assert repair.calls[0]["dry_run"] is True
    assert repo.finished[0]["status"] == "success"


def test_sync_marks_partial_success_when_one_sku_fails():
    class BrokenListingsClient:
        def get_listings_item(self, *args, **kwargs):
            raise RuntimeError("api down")

    repo = FakeIssueRepo()
    service = AmazonListingIssueSyncService(
        db=MagicMock(),
        listings_client=BrokenListingsClient(),
        reports_client=FakeReportsClient(),
        issue_repo=repo,
        repair_service=FakeRepairService(),
    )

    result = service.sync_and_repair(
        limit=1,
        dry_run=True,
        include_suppressed_report=False,
    )

    assert result["error_count"] == 1
    assert repo.finished[0]["status"] == "partial_success"
    assert "api down" in repo.finished[0]["error_message"]
