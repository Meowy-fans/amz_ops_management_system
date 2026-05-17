"""Unit tests for AmazonListingSubmitter."""
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from src.services.amazon_listing_submitter import AmazonListingSubmitter
from src.services.progress_reporter import ProgressReporter


class FakeListingsClient:
    def __init__(self):
        self.calls = []

    def put_listings_item(self, sku, product_type, attributes, issue_locale="en_US"):
        self.calls.append(
            {"sku": sku, "product_type": product_type, "attributes": attributes}
        )
        return {
            "headers": {"x-amzn-RequestId": "REQ-OK"},
            "body": {"status": "ACCEPTED", "issues": []},
        }


class FakeSubmissionRepo:
    def __init__(self):
        self.inserts = []

    def insert_submission(self, **kwargs):
        self.inserts.append(kwargs)
        return len(self.inserts)


def test_dry_run_does_not_call_api():
    repo = FakeSubmissionRepo()
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        submission_repo=repo,
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": {}}]

    results = submitter.submit(plans, dry_run=True)

    assert results[0]["status"] == "dry_run"
    assert len(repo.inserts) == 1
    assert repo.inserts[0]["status"] == "dry_run"


def test_real_mode_calls_api():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": {"item_name": [{"value": "X"}]}}]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "ACCEPTED"
    assert len(client.calls) == 1
    assert repo.inserts[0]["status"] == "success"


def test_real_mode_per_sku_isolation():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    original_put = client.put_listings_item

    call_count = [0]

    def fail_one_then_ok(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("fail")
        return original_put(*args, **kwargs)

    client.put_listings_item = fail_one_then_ok
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
    )
    plans = [
        {"sku": "A", "product_type": "CABINET", "attributes": {}},
        {"sku": "B", "product_type": "CABINET", "attributes": {}},
    ]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "failed"
    assert results[1]["status"] == "ACCEPTED"
    assert len(repo.inserts) == 2


def test_empty_plans_returns_empty():
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
    )
    assert submitter.submit([], dry_run=True) == []
