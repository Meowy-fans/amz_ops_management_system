"""Unit tests for AmazonListingIssueRepairService."""
from unittest.mock import MagicMock

from src.services.amazon_listing_issue_repair_service import (
    AmazonListingIssueRepairService,
)


class FakeIssueRepo:
    def __init__(self):
        self.actions = []

    def insert_action(self, **kwargs):
        self.actions.append(kwargs)
        return len(self.actions)


class FakeSchemaService:
    def __init__(self, properties=None):
        self.properties = properties or {}

    def get_cached_schema(self, product_type):
        props = self.properties.get(product_type)
        if props is None:
            return None
        return {"schema_json": {"properties": props}}


class FakeListingsClient:
    def __init__(self):
        self.calls = []

    def patch_listings_item(self, sku, product_type, patches, issue_locale="en_US"):
        self.calls.append(
            {"sku": sku, "product_type": product_type, "patches": patches}
        )
        return {"headers": {"x-amzn-RequestId": "REQ1"}, "body": {"status": "ACCEPTED"}}


def _issue(**overrides):
    data = {
        "id": 10,
        "sku": "SKU1",
        "asin": "ASIN1",
        "marketplace_id": "ATVPDKIKX0DER",
        "product_type": "CABINET",
        "issue_code": "18448",
        "severity": "WARNING",
        "message": "missing recommended_uses_for_product",
        "attribute_names": ["recommended_uses_for_product"],
        "categories": ["MISSING_ATTRIBUTE"],
    }
    data.update(overrides)
    return data


def _service(repo=None, schema=None, client=None):
    return AmazonListingIssueRepairService(
        db=MagicMock(),
        issue_repo=repo or FakeIssueRepo(),
        schema_service=schema or FakeSchemaService(
            {"CABINET": {"recommended_uses_for_product": {}}}
        ),
        listings_client=client,
    )


def test_missing_recommended_use_creates_dry_run_patch_action():
    repo = FakeIssueRepo()
    service = _service(repo=repo)

    results = service.plan_and_execute([_issue()], scan_run_id=1, dry_run=True)

    assert results[0]["status"] == "dry_run"
    action = repo.actions[0]
    assert action["action_type"] == "patch_listing_attribute"
    assert action["request_payload"]["productType"] == "CABINET"
    patch = action["request_payload"]["patches"][0]
    assert patch["path"] == "/attributes/recommended_uses_for_product"
    assert patch["value"][0]["value"] == "Bathroom"


def test_missing_attribute_without_schema_requires_schema_first():
    repo = FakeIssueRepo()
    service = _service(repo=repo, schema=FakeSchemaService())

    results = service.plan_and_execute([_issue()], scan_run_id=1, dry_run=True)

    assert results[0]["status"] == "manual_required"
    assert repo.actions[0]["action_type"] == "schema_required"


def test_image_issue_requires_manual_image_replacement():
    repo = FakeIssueRepo()
    service = _service(repo=repo)

    results = service.plan_and_execute(
        [_issue(issue_code="18027", categories=["INVALID_IMAGE"])],
        scan_run_id=1,
        dry_run=True,
    )

    assert results[0]["status"] == "manual_required"
    assert repo.actions[0]["action_type"] == "replace_main_image"


def test_qualification_issue_requires_manual_review():
    repo = FakeIssueRepo()
    service = _service(repo=repo)

    results = service.plan_and_execute(
        [_issue(issue_code="18503", categories=["QUALIFICATION_REQUIRED"])],
        scan_run_id=1,
        dry_run=True,
    )

    assert results[0]["status"] == "manual_required"
    assert repo.actions[0]["action_type"] == "qualification_or_claim_review"


def test_live_patch_calls_listings_api_and_records_submission():
    repo = FakeIssueRepo()
    client = FakeListingsClient()
    service = _service(repo=repo, client=client)

    results = service.plan_and_execute([_issue()], scan_run_id=1, dry_run=False)

    assert results[0]["status"] == "submitted"
    assert client.calls[0]["sku"] == "SKU1"
    assert repo.actions[0]["response_body"] == {"status": "ACCEPTED"}
