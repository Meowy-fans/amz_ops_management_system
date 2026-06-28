"""Tests for V2 Amazon VALIDATION_PREVIEW integration."""

from src.services.requirement_models_v2 import PayloadBuildPlan, RequirementTree
from src.services.requirement_models_v2 import RequirementNode
from src.services.validation_preview_v2 import (
    ValidationPreviewComparison,
    ValidationPreviewResult,
    ValidationPreviewV2,
)


class FakeListingsClient:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.calls = []

    def get_listings_item(self, sku):
        self.calls.append(("get", sku))
        if self._raises:
            raise self._raises
        return {"body": {"sku": sku}}

    def validation_preview(self, sku, product_type, attributes, issue_locale="en_US"):
        self.calls.append(("preview", sku, product_type, attributes))
        if self._raises:
            raise self._raises
        return self._response


class FakeSubmissionRepo:
    def __init__(self):
        self.inserts = []
        self._next_id = 100

    def insert_submission(self, **kwargs):
        self.inserts.append(kwargs)
        self._next_id += 1
        return self._next_id


def _plan(sku="SKU1", product_type="CHAIR", attributes=None, findings=None):
    root = RequirementNode(
        path_key=product_type,
        schema_path="$",
        name=product_type,
        shape="root",
    )
    tree = RequirementTree(
        product_type=product_type,
        root=root,
        required_paths=[],
    )
    return PayloadBuildPlan(
        sku=sku,
        product_type=product_type,
        attributes=attributes or {"item_name": [{"value": "Walnut Chair"}]},
        requirement_tree=tree,
        findings=findings or [],
    )


def test_preview_calls_amazon_validation_preview_and_persists_result():
    amazon_response = {
        "headers": {"x-amzn-RequestId": "req-123"},
        "body": {
            "status": "VALID",
            "issues": [],
            "submissionId": "amzn-sub-1",
        },
    }
    client = FakeListingsClient(response=amazon_response)
    repo = FakeSubmissionRepo()
    adapter = ValidationPreviewV2(db=None, listings_client=client, submission_repo=repo)

    result = adapter.preview(_plan())

    assert result.sku == "SKU1"
    assert result.product_type == "CHAIR"
    assert result.status == "validation_preview_passed"
    assert result.amazon_request_id == "req-123"
    assert result.issues == []
    assert result.submission_id is not None
    assert len(repo.inserts) == 1
    insert = repo.inserts[0]
    assert insert["sku"] == "SKU1"
    assert insert["status"] == "validation_preview_passed"
    assert insert["amazon_request_id"] == "req-123"
    assert insert["product_type"] == "CHAIR"
    assert "item_name" in insert["request_payload"]["attributes"]


def test_preview_classifies_issues_status_when_amazon_returns_issues():
    amazon_response = {
        "headers": {"x-amzn-RequestId": "req-456"},
        "body": {
            "status": "INVALID",
            "issues": [
                {
                    "code": "90220",
                    "severity": "ERROR",
                    "message": "Required attribute missing",
                    "attributeNames": ["frame_material"],
                }
            ],
        },
    }
    client = FakeListingsClient(response=amazon_response)
    repo = FakeSubmissionRepo()
    adapter = ValidationPreviewV2(db=None, listings_client=client, submission_repo=repo)

    result = adapter.preview(_plan())

    assert result.status == "validation_preview_issues"
    assert len(result.issues) == 1
    assert result.issues[0]["code"] == "90220"
    assert result.issues[0]["attributeNames"] == ["frame_material"]


def test_preview_records_failed_status_when_amazon_call_raises():
    client = FakeListingsClient(raises=RuntimeError("network timeout"))
    repo = FakeSubmissionRepo()
    adapter = ValidationPreviewV2(db=None, listings_client=client, submission_repo=repo)

    result = adapter.preview(_plan())

    assert result.status == "validation_preview_failed"
    assert result.error_message == "network timeout"
    assert result.issues == []
    assert len(repo.inserts) == 1
    assert repo.inserts[0]["status"] == "validation_preview_failed"
    assert "network timeout" in repo.inserts[0]["error_message"]


def test_compare_matches_amazon_issues_to_v2_findings_by_attribute_root():
    plan = _plan(
        findings=[
            {"path_key": "frame_material", "code": "MISSING_REQUIRED_ATTRIBUTE_RULE", "severity": "ERROR"},
            {"path_key": "item_name", "code": "LOW_CONFIDENCE_REQUIRED_ATTRIBUTE", "severity": "WARN"},
        ]
    )
    result = ValidationPreviewResult(
        sku="SKU1",
        product_type="CHAIR",
        status="validation_preview_issues",
        amazon_request_id="req-1",
        issues=[
            {
                "code": "90220",
                "severity": "ERROR",
                "message": "Missing required",
                "attributeNames": ["frame_material"],
            },
            {
                "code": "90220",
                "severity": "ERROR",
                "message": "Missing required",
                "attributeNames": ["seat_material_type"],
            },
        ],
        submission_id=1,
        error_message=None,
    )
    adapter = ValidationPreviewV2(db=None, listings_client=FakeListingsClient(), submission_repo=FakeSubmissionRepo())

    comparison = adapter.compare(plan, result)

    assert comparison.amazon_issue_count == 2
    assert comparison.v2_finding_count == 2
    assert len(comparison.matched) == 1
    assert comparison.matched[0]["attribute"] == "frame_material"
    assert len(comparison.amazon_only) == 1
    assert comparison.amazon_only[0]["attributeNames"] == ["seat_material_type"]
    assert len(comparison.v2_only) == 1
    assert comparison.v2_only[0]["path_key"] == "item_name"


def test_compare_returns_empty_lists_when_both_sides_clean():
    plan = _plan(findings=[])
    result = ValidationPreviewResult(
        sku="SKU1",
        product_type="CHAIR",
        status="validation_preview_passed",
        amazon_request_id="req-1",
        issues=[],
        submission_id=1,
        error_message=None,
    )
    adapter = ValidationPreviewV2(db=None, listings_client=FakeListingsClient(), submission_repo=FakeSubmissionRepo())

    comparison = adapter.compare(plan, result)

    assert comparison.amazon_issue_count == 0
    assert comparison.v2_finding_count == 0
    assert comparison.matched == []
    assert comparison.amazon_only == []
    assert comparison.v2_only == []


def test_unexplained_amazon_only_ignores_warnings_and_allowlisted_codes():
    comparison = ValidationPreviewComparison(
        sku="SKU1",
        amazon_issue_count=2,
        v2_finding_count=0,
        amazon_only=[
            {
                "code": "90000900",
                "severity": "WARNING",
                "message": "Width warning",
                "attributeNames": ["item_depth_width_height"],
            },
            {
                "code": "18448",
                "severity": "ERROR",
                "message": "Recommended attribute",
                "attributeNames": ["recommended_uses_for_product"],
            },
            {
                "code": "90220",
                "severity": "ERROR",
                "message": "Missing required",
                "attributeNames": ["frame_material"],
            },
        ],
    )

    unexplained = ValidationPreviewV2.unexplained_amazon_only(comparison)

    assert len(unexplained) == 1
    assert unexplained[0]["attributeNames"] == ["frame_material"]
    assert ValidationPreviewV2.comparison_is_clean(comparison) is False


def test_unexplained_amazon_only_ignores_coverage_ignore_required_roots():
    comparison = ValidationPreviewComparison(
        sku="SKU1",
        amazon_issue_count=1,
        v2_finding_count=0,
        amazon_only=[
            {
                "code": "90220",
                "severity": "ERROR",
                "message": "Missing required",
                "attributeNames": ["merchant_suggested_asin"],
            }
        ],
    )

    unexplained = ValidationPreviewV2.unexplained_amazon_only(
        comparison,
        ignored_attribute_roots=["merchant_suggested_asin"],
    )

    assert unexplained == []
    assert ValidationPreviewV2.comparison_is_clean(
        comparison,
        ignored_attribute_roots=["merchant_suggested_asin"],
    )


def test_compare_is_dataclass_with_expected_fields():
    comparison = ValidationPreviewComparison(
        sku="SKU1",
        amazon_issue_count=0,
        v2_finding_count=0,
        matched=[],
        amazon_only=[],
        v2_only=[],
    )
    assert comparison.sku == "SKU1"
