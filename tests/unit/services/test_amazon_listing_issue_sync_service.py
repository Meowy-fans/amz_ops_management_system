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
        self.resolved_sku_sources = []
        self.finished = []
        self.repaired_after = set()

    def begin_scan(self, source):
        self.source = source
        return self.scan_id

    def get_report_skus(self, limit=None):
        return [{"sku": "SKU1", "asin": "ASIN1"}]

    def upsert_issue(self, issue):
        self.upserts.append(issue)
        return len(self.upserts)

    def has_confirmed_repair_after(
        self,
        sku,
        marketplace_id,
        issue_code,
        attribute_names,
        submitted_at,
    ):
        return (
            sku,
            marketplace_id,
            issue_code,
            tuple(attribute_names or []),
        ) in self.repaired_after

    def mark_resolved_for_sku(self, sku, marketplace_id, seen_issue_keys):
        self.resolved_skus.append((sku, marketplace_id, list(seen_issue_keys)))
        return 0

    def mark_resolved_for_source(self, source, marketplace_id, seen_issue_keys):
        self.resolved_sources.append((source, marketplace_id, list(seen_issue_keys)))
        return 0

    def mark_resolved_for_sku_source(self, sku, marketplace_id, source, seen_issue_keys):
        self.resolved_sku_sources.append(
            (sku, marketplace_id, source, list(seen_issue_keys))
        )
        return 0

    def get_open_issues(self, limit=None, source=None):
        issues = list(self.upserts)
        if source:
            issues = [issue for issue in issues if issue.get("source") == source]
        return issues[:limit] if limit else issues

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


class FakeSubmissionRepo:
    def get_latest_delayed_confirmation_items(self, limit=None):
        return [
            {
                "id": 201,
                "sku": "SKU1",
                "marketplace_id": "ATVPDKIKX0DER",
                "product_type": "CABINET",
                "response_body": {
                    "confirmation": {
                        "body": {
                            "summaries": [
                                {
                                    "asin": "ASIN1",
                                    "itemName": "Bathroom Vanity Cabinet",
                                }
                            ],
                            "productTypes": [{"productType": "CABINET"}],
                            "issues": [
                                {
                                    "code": "18448",
                                    "severity": "WARNING",
                                    "message": (
                                        "Your submission is missing few key attributes: "
                                        "recommended_uses_for_product."
                                    ),
                                    "attributeNames": ["recommended_uses_for_product"],
                                    "categories": ["MISSING_ATTRIBUTE"],
                                }
                            ],
                        }
                    }
                },
            },
            {
                "id": 202,
                "sku": "SKU2",
                "marketplace_id": "ATVPDKIKX0DER",
                "product_type": "CABINET",
                "response_body": {"confirmation": {"body": {"issues": []}}},
            },
        ]


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


def test_sync_confirmation_issues_persists_latest_delayed_confirmation_issues():
    repo = FakeIssueRepo()
    repair = FakeRepairService()
    service = AmazonListingIssueSyncService(
        db=MagicMock(),
        issue_repo=repo,
        repair_service=repair,
        submission_repo=FakeSubmissionRepo(),
    )

    result = service.sync_confirmation_issues(limit=10, dry_run=True)

    assert result["checked_count"] == 2
    assert result["issue_count"] == 1
    assert result["action_count"] == 1
    assert repo.source == "price_inventory_confirmation"
    assert repo.upserts[0]["source"] == "price_inventory_confirmation"
    assert repo.upserts[0]["sku"] == "SKU1"
    assert repo.upserts[0]["item_name"] == "Bathroom Vanity Cabinet"
    assert repo.resolved_sku_sources[0][0] == "SKU1"
    assert repo.resolved_sku_sources[0][2] == "price_inventory_confirmation"
    assert repo.resolved_sku_sources[1][0] == "SKU2"
    assert repo.resolved_sku_sources[1][3] == []
    assert repair.calls[0]["dry_run"] is True


def test_sync_confirmation_issues_does_not_reopen_confirmed_repairs():
    repo = FakeIssueRepo()
    repo.repaired_after.add(
        (
            "SKU1",
            "ATVPDKIKX0DER",
            "18448",
            ("recommended_uses_for_product",),
        )
    )
    service = AmazonListingIssueSyncService(
        db=MagicMock(),
        issue_repo=repo,
        repair_service=FakeRepairService(),
        submission_repo=FakeSubmissionRepo(),
    )

    result = service.sync_confirmation_issues(limit=10, dry_run=True)

    assert result["checked_count"] == 2
    assert result["issue_count"] == 0
    assert repo.upserts == []
    assert repo.resolved_sku_sources[0][3] == []
