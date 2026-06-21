"""Unit tests for AmazonListingSubmitter."""
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from infrastructure.amazon.api_client import AmazonAPIException
from src.services.amazon_listing_submitter import AmazonListingSubmitter
from src.services.progress_reporter import ProgressReporter


class FakeListingsClient:
    def __init__(self):
        self.calls = []
        self.get_calls = []
        self.existing_skus = set()
        self.submitted_skus = set()
        self.lookup_error = None
        self.confirm_error = None
        self.confirm_issues = []
        self.confirm_not_found = False
        self.validation_calls = []
        self.put_body = {"status": "ACCEPTED", "issues": []}
        self.validation_body = {"status": "ACCEPTED", "issues": []}

    def get_listings_item(self, sku, issue_locale="en_US", included_data=None):
        self.get_calls.append(
            {
                "sku": sku,
                "issue_locale": issue_locale,
                "included_data": included_data,
            }
        )
        if self.lookup_error:
            raise self.lookup_error
        if sku in self.existing_skus:
            return {"headers": {"x-amzn-RequestId": "REQ-GET"}, "body": {"sku": sku}}
        if sku in self.submitted_skus:
            if self.confirm_error:
                raise self.confirm_error
            if self.confirm_not_found:
                raise AmazonAPIException("not found", status_code=404)
            return {
                "headers": {"x-amzn-RequestId": "REQ-GET"},
                "body": {"sku": sku, "issues": self.confirm_issues},
            }
        raise AmazonAPIException("not found", status_code=404)

    def put_listings_item(self, sku, product_type, attributes, issue_locale="en_US"):
        self.calls.append(
            {"sku": sku, "product_type": product_type, "attributes": attributes}
        )
        self.submitted_skus.add(sku)
        return {
            "headers": {"x-amzn-RequestId": "REQ-OK"},
            "body": self.put_body,
        }

    def validation_preview(self, sku, product_type, attributes, issue_locale="en_US"):
        self.validation_calls.append(
            {"sku": sku, "product_type": product_type, "attributes": attributes}
        )
        return {
            "headers": {"x-amzn-RequestId": "REQ-VALID"},
            "body": self.validation_body,
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


class LiveBlockingQualityGate:
    def prepare_plans(self, plans):
        return [
            {
                "plan": plan,
                "blocked": False,
                "findings": [
                    {
                        "severity": "WARNING",
                        "code": "ISSUE_DERIVED_DIMENSION_RANGE",
                        "message": "CABINET width warning",
                        "attribute_names": ["item_depth_width_height"],
                        "blocking": False,
                        "live_blocking": True,
                    }
                ],
            }
            for plan in plans
        ]


class FakeRuleLoader:
    LIVE_ELIGIBLE_MODE = "live_eligible"

    def __init__(self, modes):
        self.modes = modes

    def mode(self, product_type):
        return self.modes.get(product_type, "dry_run")


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


def test_strict_dry_run_calls_validation_preview_without_put():
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

    results = submitter.submit(plans, dry_run=True, validation_only=True)

    assert results[0]["status"] == "validation_preview_passed"
    assert len(client.get_calls) == 1
    assert len(client.validation_calls) == 1
    assert len(client.calls) == 0
    assert repo.inserts[0]["status"] == "validation_preview_passed"
    assert repo.inserts[0]["response_body"] == {"status": "ACCEPTED", "issues": []}


def test_strict_dry_run_records_validation_preview_issues():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    client.validation_body = {
        "status": "INVALID",
        "issues": [{"code": "90220", "message": "Required attribute missing"}],
    }
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=True, validation_only=True)

    assert results[0]["status"] == "validation_preview_issues"
    assert results[0]["issues"] == 1
    assert len(client.calls) == 0
    assert repo.inserts[0]["status"] == "validation_preview_issues"


def test_strict_dry_run_skips_existing_before_validation_preview():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    client.existing_skus.add("SKU1")
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=True, validation_only=True)

    assert results[0]["status"] == "skipped_existing"
    assert len(client.validation_calls) == 0
    assert len(client.calls) == 0
    assert repo.inserts[0]["status"] == "skipped_existing"


def test_real_mode_confirms_listing_after_put():
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

    assert results[0]["status"] == "listing_confirmed"
    assert results[0]["issues"] == 0
    assert client.get_calls == [
        {
            "sku": "SKU1",
            "issue_locale": "en_US",
            "included_data": ["summaries", "issues", "attributes", "productTypes"],
        },
        {
            "sku": "SKU1",
            "issue_locale": "en_US",
            "included_data": ["summaries", "issues", "attributes", "productTypes"],
        },
    ]
    assert len(client.calls) == 1
    assert repo.inserts[0]["status"] == "listing_confirmed"
    assert repo.inserts[0]["response_body"]["put_response"] == {
        "status": "ACCEPTED",
        "issues": [],
    }
    assert repo.inserts[0]["response_body"]["confirm_response"] == {
        "sku": "SKU1",
        "issues": [],
    }


def test_real_mode_blocks_product_type_without_live_eligible_rule_mode():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
        rule_loader=FakeRuleLoader({"SOFA": "dry_run"}),
    )
    plans = [{"sku": "SKU1", "product_type": "SOFA", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "blocked_by_rule_mode"
    assert results[0]["rule_mode"] == "dry_run"
    assert len(client.get_calls) == 0
    assert len(client.calls) == 0
    assert repo.inserts[0]["status"] == "blocked_by_rule_mode"
    assert repo.inserts[0]["request_payload"]["ruleMode"] == "dry_run"


def test_rule_mode_does_not_block_strict_dry_run_validation_preview():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
        rule_loader=FakeRuleLoader({"SOFA": "dry_run"}),
    )
    plans = [{"sku": "SKU1", "product_type": "SOFA", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=True, validation_only=True)

    assert results[0]["status"] == "validation_preview_passed"
    assert len(client.validation_calls) == 1
    assert repo.inserts[0]["status"] == "validation_preview_passed"


def test_real_mode_allows_live_eligible_rule_mode():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
        rule_loader=FakeRuleLoader({"CABINET": "live_eligible"}),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "listing_confirmed"
    assert len(client.calls) == 1


def test_real_mode_skips_existing_amazon_sku_before_put():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    client.existing_skus.add("SKU1")
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=False)

    assert results == [
        {
            "sku": "SKU1",
            "status": "skipped_existing",
            "issues": 0,
            "quality_findings": [],
        }
    ]
    assert len(client.calls) == 0
    assert repo.inserts[0]["status"] == "skipped_existing"
    assert repo.inserts[0]["response_body"] == {"sku": "SKU1"}


def test_real_mode_blocks_when_existing_check_fails():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    client.lookup_error = AmazonAPIException("rate limited", status_code=429)
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "failed"
    assert "rate limited" in results[0]["error"]
    assert len(client.calls) == 0
    assert repo.inserts[0]["status"] == "failed_existing_check"


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
    assert results[1]["status"] == "listing_confirmed"
    assert len(repo.inserts) == 2


def test_real_mode_records_confirmed_with_issues_after_put():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    client.confirm_issues = [{"code": "MISSING_ATTRIBUTE"}]
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "confirmed_with_issues"
    assert results[0]["issues"] == 1
    assert repo.inserts[0]["status"] == "confirmed_with_issues"
    assert repo.inserts[0]["response_body"]["confirm_response"]["issues"] == [
        {"code": "MISSING_ATTRIBUTE"}
    ]


def test_real_mode_does_not_confirm_when_put_is_not_accepted():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    client.put_body = {"status": "INVALID", "issues": []}
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "INVALID"
    assert len(client.get_calls) == 1
    assert repo.inserts[0]["status"] == "not_accepted"


def test_real_mode_records_pending_confirmation_when_get_still_404():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    client.confirm_not_found = True
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "accepted_pending_confirmation"
    assert repo.inserts[0]["status"] == "accepted_pending_confirmation"
    assert repo.inserts[0]["response_body"]["put_response"]["status"] == "ACCEPTED"
    assert repo.inserts[0]["response_body"]["confirm_response"] is None


def test_real_mode_records_confirmation_failed_without_reclassifying_put_failure():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    client.confirm_error = AmazonAPIException("rate limited", status_code=429)
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=NullQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    results = submitter.submit(plans, dry_run=False)

    assert results[0]["status"] == "confirmation_failed"
    assert repo.inserts[0]["status"] == "confirmation_failed"
    assert repo.inserts[0]["error_message"] == "rate limited"
    assert repo.inserts[0]["response_body"]["put_response"]["status"] == "ACCEPTED"


def test_validation_only_does_not_run_post_submit_confirmation():
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

    results = submitter.submit(plans, dry_run=False, validation_only=True)

    assert results[0]["status"] == "ACCEPTED"
    assert len(client.validation_calls) == 1
    assert len(client.calls) == 0
    assert len(client.get_calls) == 1
    assert repo.inserts[0]["status"] == "success"


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


def test_live_blocking_quality_finding_blocks_put_but_preserves_dry_run():
    repo = FakeSubmissionRepo()
    client = FakeListingsClient()
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=client,
        submission_repo=repo,
        quality_gate=LiveBlockingQualityGate(),
    )
    plans = [{"sku": "SKU1", "product_type": "CABINET", "attributes": _valid_attrs()}]

    live_results = submitter.submit(plans, dry_run=False)
    dry_results = submitter.submit(plans, dry_run=True)

    assert live_results[0]["status"] == "blocked"
    assert dry_results[0]["status"] == "dry_run"
    assert len(client.calls) == 0
    assert repo.inserts[0]["status"] == "blocked_quality_gate"
    assert repo.inserts[1]["status"] == "dry_run"


def test_empty_plans_returns_empty():
    submitter = AmazonListingSubmitter(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
    )
    assert submitter.submit([], dry_run=True) == []
