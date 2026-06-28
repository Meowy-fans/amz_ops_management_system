"""Tests for V2 regression readiness evaluator."""

from src.services.listing_payload_v2_regression import ListingPayloadV2Regression


class FakeDiffService:
    def __init__(self, reports):
        self.reports = reports
        self.calls = []

    def report(self, product_type=None, sku=None, limit=20):
        self.calls.append({"product_type": product_type, "sku": sku, "limit": limit})
        return self.reports[product_type]


def test_live_category_go_requires_shadow_rows_and_no_blocking():
    diff_service = FakeDiffService({
        "CABINET": _report(
            count=2,
            summary={"shadow_built": 2, "shadow_failed": 0},
            diffs=[
                {"v2_blocking_codes": [], "v2_pending_review_paths": []},
                {"v2_blocking_codes": [], "v2_pending_review_paths": []},
            ],
        )
    })

    result = ListingPayloadV2Regression(
        db=object(),
        diff_service=diff_service,
    ).evaluate(product_types=["CABINET"], limit_per_category=5)

    assert result["status"] == "go"
    assert result["categories"][0]["decision"] == "go"
    assert result["categories"][0]["reasons"] == []
    assert diff_service.calls == [
        {"product_type": "CABINET", "sku": None, "limit": 5}
    ]


def test_live_category_blocks_on_v2_blocking_codes():
    diff_service = FakeDiffService({
        "HOME_MIRROR": _report(
            count=1,
            summary={"shadow_built": 1, "shadow_failed": 0},
            diffs=[{"v2_blocking_codes": ["MISSING_REQUIRED_ATTRIBUTE_RULE"]}],
        )
    })

    result = ListingPayloadV2Regression(
        db=object(),
        diff_service=diff_service,
    ).evaluate(product_types=["HOME_MIRROR"])

    assert result["status"] == "no_go"
    assert result["categories"][0]["reasons"] == ["live_category_has_v2_blocking"]
    assert result["categories"][0]["blocking_codes"] == [
        "MISSING_REQUIRED_ATTRIBUTE_RULE"
    ]


def test_live_category_uses_latest_shadow_row_per_sku():
    diff_service = FakeDiffService({
        "CABINET": _report(
            count=2,
            summary={"shadow_built": 2, "shadow_failed": 0},
            diffs=[
                {
                    "submission_id": 2,
                    "sku": "SKU1",
                    "shadow_status": "shadow_built",
                    "v2_blocking_codes": [],
                    "v2_missing_required_paths": [],
                    "v2_pending_review_paths": [],
                },
                {
                    "submission_id": 1,
                    "sku": "SKU1",
                    "shadow_status": "shadow_built",
                    "v2_blocking_codes": ["MISSING_REQUIRED_ATTRIBUTE_RULE"],
                    "v2_missing_required_paths": ["item_weight"],
                    "v2_pending_review_paths": [],
                },
            ],
        )
    })

    result = ListingPayloadV2Regression(
        db=object(),
        diff_service=diff_service,
    ).evaluate(product_types=["CABINET"])

    category = result["categories"][0]
    assert result["status"] == "go"
    assert category["shadow_rows"] == 1
    assert category["raw_shadow_rows"] == 2
    assert category["blocking_codes"] == []
    assert category["missing_required_paths"] == []


def test_exploratory_category_allows_explainable_blocking_codes():
    diff_service = FakeDiffService({
        "CHAIR": _report(
            count=1,
            summary={"shadow_built": 1, "shadow_failed": 0},
            diffs=[
                {
                    "v2_blocking_codes": ["NEEDS_REVIEW_REQUIRED_ATTRIBUTE"],
                    "v2_pending_review_paths": ["frame.color.value"],
                    "v2_missing_required_paths": [],
                }
            ],
        )
    })

    result = ListingPayloadV2Regression(
        db=object(),
        diff_service=diff_service,
    ).evaluate(product_types=["CHAIR"])

    assert result["status"] == "go"
    category = result["categories"][0]
    assert category["mode"] == "exploratory"
    assert category["pending_review_paths"] == ["frame.color.value"]


def test_missing_shadow_evidence_is_no_go():
    diff_service = FakeDiffService({
        "OTTOMAN": _report(
            count=0,
            summary={"shadow_built": 0, "shadow_failed": 0},
            diffs=[],
        )
    })

    result = ListingPayloadV2Regression(
        db=object(),
        diff_service=diff_service,
    ).evaluate(product_types=["OTTOMAN"])

    assert result["status"] == "no_go"
    assert result["categories"][0]["reasons"] == ["insufficient_shadow_evidence"]


def test_exploratory_unknown_blocking_code_is_no_go():
    diff_service = FakeDiffService({
        "SOFA": _report(
            count=1,
            summary={"shadow_built": 1, "shadow_failed": 0},
            diffs=[{"v2_blocking_codes": ["UNKNOWN_SHAPE_ERROR"]}],
        )
    })

    result = ListingPayloadV2Regression(
        db=object(),
        diff_service=diff_service,
    ).evaluate(product_types=["SOFA"])

    assert result["status"] == "no_go"
    assert result["categories"][0]["reasons"] == ["unexplained_v2_blocking_codes"]


def _report(count, summary, diffs):
    base_summary = {
        "shadow_built": 0,
        "shadow_failed": 0,
        "v2_blocking": 0,
        "with_pending_review": 0,
        "with_missing_required": 0,
    }
    base_summary.update(summary)
    return {"count": count, "summary": base_summary, "diffs": diffs}
