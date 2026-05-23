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


class NullQualityGate:
    def prepare_plans(self, plans):
        return [
            {
                "plan": plan,
                "blocked": False,
                "findings": [],
            }
            for plan in plans
        ]


def _valid_attrs(**overrides):
    attrs = {
        "item_name": [{"value": "Bathroom Cabinet"}],
        "product_description": [{"value": "Modern bathroom cabinet."}],
        "main_product_image_locator": [{"media_location": "https://img.example/main.jpg"}],
    }
    attrs.update(overrides)
    return attrs


def test_dry_run_does_not_call_api():
    repo = FakeSubmissionRepo()
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

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
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

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
        quality_gate=NullQualityGate(),
    )
    plans = [
        {"sku": "A", "product_type": "CABINET", "attributes": _valid_attrs()},
        {"sku": "B", "product_type": "CABINET", "attributes": _valid_attrs()},
    ]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "failed"
    assert results[1]["status"] == "ACCEPTED"
    assert len(repo.inserts) == 2


def test_quality_gate_blocks_high_risk_payload_before_api_call():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
    )
    plans = [
        {
            "sku": "SKU1",
            "product_type": "CABINET",
            "attributes": _valid_attrs(
                product_description=[
                    {"value": "This cabinet resists bacteria buildup."}
                ]
            ),
        }
    ]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "blocked"
    assert len(client.calls) == 0
    assert repo.inserts[0]["status"] == "blocked_quality_gate"
    assert any(
        item["code"] == "PESTICIDE_CLAIM_RISK"
        for item in repo.inserts[0]["request_payload"]["qualityFindings"]
    )


def test_empty_plans_returns_empty():
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
    )
    assert submitter.submit([], dry_run=True) == []
