"""Tests for V2 shadow diff reporting."""

import json

from src.services.listing_payload_shadow_diff_v2 import ListingPayloadShadowDiffV2


class FakeSubmissionRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def list_listing_payload_v2_shadow_submissions(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


def test_shadow_diff_report_compares_v1_and_v2_attributes():
    repo = FakeSubmissionRepo([
        {
            "id": 1,
            "sku": "SKU1",
            "status": "shadow_built",
            "product_type": "CHAIR",
            "request_payload": {
                "v1_status": "plan_generated",
                "v1_attribute_names": ["item_name", "brand"],
                "v1_attributes": {"item_name": [{"value": "Chair"}]},
            },
            "response_body": {
                "summary": {
                    "missing_required_paths": ["frame"],
                    "pending_review_paths": ["seat.material.value"],
                    "blocking_codes": ["MISSING_REQUIRED_ATTRIBUTE_RULE"],
                    "condition_trace_count": 3,
                },
                "v2_attribute_names": ["item_name", "frame"],
                "v2_attributes": {"frame": [{"color": [{"value": "Black"}]}]},
                "v2_required_paths": ["item_name", "frame"],
                "v2_findings": [{"code": "MISSING_REQUIRED_ATTRIBUTE_RULE"}],
            },
        }
    ])

    report = ListingPayloadShadowDiffV2(db=object(), submission_repo=repo).report(
        product_type="chair",
        sku="sku1",
        limit=7,
    )

    assert repo.calls == [{"product_type": "CHAIR", "sku": "SKU1", "limit": 7}]
    assert report["summary"] == {
        "shadow_built": 1,
        "shadow_failed": 0,
        "v2_blocking": 1,
        "with_pending_review": 1,
        "with_missing_required": 1,
    }
    diff = report["diffs"][0]
    assert diff["attributes_only_in_v1"] == ["brand"]
    assert diff["attributes_only_in_v2"] == ["frame"]
    assert diff["attributes_in_both"] == ["item_name"]
    assert diff["v2_missing_required_paths"] == ["frame"]
    assert diff["v2_pending_review_paths"] == ["seat.material.value"]
    assert diff["v2_blocking_codes"] == ["MISSING_REQUIRED_ATTRIBUTE_RULE"]
    assert diff["v2_condition_trace_count"] == 3


def test_shadow_diff_accepts_json_string_payloads_and_failed_rows():
    repo = FakeSubmissionRepo([
        {
            "id": 2,
            "sku": "SKU2",
            "status": "shadow_failed",
            "product_type": "CHAIR",
            "request_payload": json.dumps({"v1_status": "blocked"}),
            "response_body": json.dumps({"engine": "v2"}),
            "error_message": "boom",
        }
    ])

    report = ListingPayloadShadowDiffV2(db=object(), submission_repo=repo).report()

    assert report["summary"]["shadow_failed"] == 1
    assert report["summary"]["v2_blocking"] == 0
    assert report["diffs"][0]["error_message"] == "boom"
    assert report["diffs"][0]["v1_status"] == "blocked"
