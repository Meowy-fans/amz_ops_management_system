"""Unit tests for AmazonListingIssueRepairService."""
from unittest.mock import MagicMock

from src.services.amazon_listing_issue_repair_service import (
    AmazonListingIssueRepairService,
)


class FakeIssueRepo:
    def __init__(self):
        self.actions = []
        self.open_issues = []
        self.marked_resolved = []

    def insert_action(self, **kwargs):
        self.actions.append(kwargs)
        return len(self.actions)

    def get_open_issues(self, limit=None, source=None):
        issues = list(self.open_issues)
        if source:
            issues = [issue for issue in issues if issue.get("source") == source]
        return issues[:limit] if limit else issues

    def get_submitted_actions_for_confirmation(self, older_than_minutes=30, limit=100):
        return [
            {
                "id": index + 1,
                "issue_code": "18448",
                "attribute_names": ["recommended_uses_for_product"],
                "categories": ["MISSING_ATTRIBUTE"],
                "raw_issue": {"code": "18448"},
                **action,
            }
            for index, action in enumerate(self.actions)
            if action["status"] == "submitted"
        ][:limit]

    def mark_issue_resolved(self, issue_id):
        self.marked_resolved.append(issue_id)
        return 1


class FakeSchemaService:
    def __init__(self, properties=None):
        self.properties = properties or {}

    def get_cached_schema(self, product_type):
        props = self.properties.get(product_type)
        if props is None:
            return None
        return {"schema_json": {"properties": props}}

    def get_or_fetch_schema(self, product_type):
        return self.get_cached_schema(product_type)


class FakeListingsClient:
    def __init__(self):
        self.calls = []
        self.confirm_body = {"issues": []}

    def patch_listings_item(self, sku, product_type, patches, issue_locale="en_US"):
        self.calls.append(
            {"sku": sku, "product_type": product_type, "patches": patches}
        )
        return {"headers": {"x-amzn-RequestId": "REQ1"}, "body": {"status": "ACCEPTED"}}

    def get_listings_item(self, sku, issue_locale="en_US", included_data=None):
        self.calls.append({"sku": sku, "included_data": included_data})
        return {"headers": {"x-amzn-RequestId": "REQ2"}, "body": self.confirm_body}


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
        "item_name": "Bathroom Vanity Cabinet",
        "source": "price_inventory_confirmation",
    }
    data.update(overrides)
    return data


def _service(repo=None, schema=None, client=None, db=None):
    return AmazonListingIssueRepairService(
        db=db or MagicMock(),
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
    assert action["status"] == "dry_run"
    assert action["request_payload"]["productType"] == "CABINET"
    assert action["request_payload"]["confidence"] == "high"
    assert "Bathroom Vanity" in action["request_payload"]["evidence"][0][0]
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


def _mock_db_with_regenerated_content():
    db = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = (
        "W2615S00095",
        "Modern Bathroom Vanity Cabinet with Storage",
        "Spacious storage for bathroom essentials",
        "Durable engineered wood construction",
        "Easy assembly with included hardware",
        "Sleek design complements modern decor",
        "Adjustable shelves for flexible organization",
        "This vanity cabinet offers practical bathroom storage with a clean contemporary look.",
        '{"search_terms": "bathroom vanity cabinet storage", "generic_keyword": "bathroom vanity"}',
    )
    db.execute.return_value = result
    return db


def test_qualification_issue_requires_manual_review_without_regenerated_content():
    repo = FakeIssueRepo()
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = None
    service = _service(repo=repo, db=db)

    results = service.plan_and_execute(
        [_issue(issue_code="18503", categories=["QUALIFICATION_REQUIRED"])],
        scan_run_id=1,
        dry_run=True,
    )

    assert results[0]["status"] == "manual_required"
    assert repo.actions[0]["action_type"] == "qualification_or_claim_review"


def test_qualification_issue_with_regenerated_content_creates_compliance_patch():
    repo = FakeIssueRepo()
    service = _service(repo=repo, db=_mock_db_with_regenerated_content())

    results = service.plan_and_execute(
        [_issue(issue_code="18503", categories=["QUALIFICATION_REQUIRED"])],
        scan_run_id=1,
        dry_run=True,
    )

    assert results[0]["status"] == "dry_run"
    action = repo.actions[0]
    assert action["action_type"] == "patch_compliance_content"
    assert action["request_payload"]["productType"] == "CABINET"
    assert action["request_payload"]["confidence"] == "high"
    patch_paths = {patch["path"] for patch in action["request_payload"]["patches"]}
    assert "/attributes/item_name" in patch_paths
    assert "/attributes/product_description" in patch_paths
    assert "/attributes/bullet_point" in patch_paths


def test_live_patch_calls_listings_api_and_records_submission():
    repo = FakeIssueRepo()
    client = FakeListingsClient()
    service = _service(repo=repo, client=client)

    results = service.plan_and_execute([_issue()], scan_run_id=1, dry_run=False)

    assert results[0]["status"] == "submitted"
    assert client.calls[0]["sku"] == "SKU1"
    assert repo.actions[0]["response_body"] == {"status": "ACCEPTED"}


def test_repair_open_issues_filters_confirmation_source_and_dry_runs():
    repo = FakeIssueRepo()
    repo.open_issues = [
        _issue(source="price_inventory_confirmation"),
        _issue(sku="SKU2", source="suppressed_report"),
    ]
    service = _service(repo=repo)

    results = service.repair_open_issues(
        source="price_inventory_confirmation",
        dry_run=True,
    )

    assert len(results) == 1
    assert results[0]["sku"] == "SKU1"
    assert repo.actions[0]["status"] == "dry_run"


def test_confirmation_marks_submitted_repair_confirmed_when_issue_disappears():
    repo = FakeIssueRepo()
    client = FakeListingsClient()
    service = _service(repo=repo, client=client)
    service.plan_and_execute([_issue()], scan_run_id=1, dry_run=False)

    results = service.confirm_submitted_repairs(older_than_minutes=30)

    assert results[0]["status"] == "repair_confirmed"
    assert repo.actions[-1]["action_type"] == "confirm_patch_listing_attribute"
    assert repo.actions[-1]["status"] == "repair_confirmed"
    assert repo.marked_resolved == [10]


def test_confirmation_records_failed_when_same_issue_remains():
    repo = FakeIssueRepo()
    client = FakeListingsClient()
    client.confirm_body = {
        "issues": [
            {
                "code": "18448",
                "severity": "WARNING",
                "attributeNames": ["recommended_uses_for_product"],
                "categories": ["MISSING_ATTRIBUTE"],
                "message": "missing recommended_uses_for_product",
            }
        ]
    }
    service = _service(repo=repo, client=client)
    service.plan_and_execute([_issue()], scan_run_id=1, dry_run=False)

    results = service.confirm_submitted_repairs(older_than_minutes=30)

    assert results[0]["status"] == "repair_failed"
    assert repo.actions[-1]["status"] == "repair_failed"
    assert repo.marked_resolved == []


def test_missing_installation_type_vessel_sink_creates_patch():
    repo = FakeIssueRepo()
    service = _service(repo=repo, schema=FakeSchemaService(
        {"SINK": {"installation_type": {"type": "array"}}}
    ))

    results = service.plan_and_execute(
        [_issue(
            sku="SKU-SINK-1",
            product_type="SINK",
            attribute_names=["installation_type"],
            item_name="White Ceramic Vessel Sink - Above Counter Bathroom Basin",
        )],
        scan_run_id=1,
        dry_run=True,
    )

    assert results[0]["status"] == "dry_run"
    action = repo.actions[0]
    assert action["action_type"] == "patch_listing_attribute"
    assert action["request_payload"]["productType"] == "SINK"
    assert action["request_payload"]["target_values"]["installation_type"] == "Countertop"


def test_missing_style_modern_sink_creates_patch():
    repo = FakeIssueRepo()
    service = _service(repo=repo, schema=FakeSchemaService(
        {"SINK": {"style": {"type": "array"}}}
    ))

    results = service.plan_and_execute(
        [_issue(
            sku="SKU-SINK-2",
            product_type="SINK",
            attribute_names=["style"],
            item_name="Modern White Ceramic Vessel Sink",
        )],
        scan_run_id=1,
        dry_run=True,
    )

    assert results[0]["status"] == "dry_run"
    action = repo.actions[0]
    assert action["request_payload"]["target_values"]["style"] == "Contemporary"


def test_missing_style_marble_sink_auto_fills_classic():
    repo = FakeIssueRepo()
    service = _service(repo=repo, schema=FakeSchemaService(
        {"SINK": {"style": {"type": "array"}}}
    ))

    results = service.plan_and_execute(
        [_issue(
            sku="SKU-SINK-2b",
            product_type="SINK",
            attribute_names=["style"],
            item_name="Green Natural Marble Bathroom Sink",
        )],
        scan_run_id=1,
        dry_run=True,
    )

    assert results[0]["status"] == "dry_run"
    assert repo.actions[0]["request_payload"]["target_values"]["style"] == "Classic"


def test_missing_both_installation_type_and_style_creates_multi_patch():
    repo = FakeIssueRepo()
    service = _service(repo=repo, schema=FakeSchemaService(
        {"SINK": {"installation_type": {"type": "array"}, "style": {"type": "array"}}}
    ))

    results = service.plan_and_execute(
        [_issue(
            sku="SKU-SINK-3",
            product_type="SINK",
            attribute_names=["installation_type", "style"],
            item_name="Matte Black Modern Vessel Sink",
        )],
        scan_run_id=1,
        dry_run=True,
    )

    assert results[0]["status"] == "dry_run"
    action = repo.actions[0]
    assert action["action_type"] == "patch_listing_attribute"
    assert len(action["request_payload"]["patches"]) == 2
    assert action["request_payload"]["target_values"]["installation_type"] == "Countertop"
    assert action["request_payload"]["target_values"]["style"] == "Contemporary"
