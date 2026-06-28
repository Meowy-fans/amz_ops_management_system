"""Tests for V2 listing payload shadow audit adapter."""

from src.services.listing_payload_shadow_adapter_v2 import ListingPayloadShadowAdapterV2
from src.services.requirement_models_v2 import (
    ConditionTrace,
    PayloadBuildPlan,
    RequirementNode,
    RequirementTree,
)


class FakeEngine:
    def __init__(self, plan=None, error=None):
        self.plan = plan
        self.error = error
        self.calls = []

    def build_read_only_plan(self, product_type, sku, rules):
        self.calls.append((product_type, sku, rules))
        if self.error:
            raise self.error
        return self.plan


class FakeRuleLoader:
    def load(self, product_type):
        return {
            "product_type": product_type,
            "attributes": {"item_name": {"sources": [{"path": "content.title"}]}},
        }


class FakeSubmissionRepo:
    def __init__(self):
        self.rows = []

    def insert_submission(self, **kwargs):
        self.rows.append(kwargs)
        return 101


def test_shadow_adapter_persists_success_audit_row():
    plan = _payload_plan()
    engine = FakeEngine(plan=plan)
    repo = FakeSubmissionRepo()
    adapter = ListingPayloadShadowAdapterV2(
        db=object(),
        engine=engine,
        rule_loader=FakeRuleLoader(),
        submission_repo=repo,
    )

    result = adapter.run(
        product_type="chair",
        sku="SKU1",
        v1_plan={"attributes": {"item_name": [{"value": "V1 Chair"}]}},
        v1_status="plan_generated",
    )

    assert result == {
        "sku": "SKU1",
        "status": "shadow_built",
        "submission_id": 101,
        "v2_blocking": True,
        "v2_findings": 1,
    }
    assert engine.calls == [
        (
            "CHAIR",
            "SKU1",
            {
                "product_type": "CHAIR",
                "attributes": {
                    "item_name": {"sources": [{"path": "content.title"}]}
                },
            },
        )
    ]
    row = repo.rows[0]
    assert row["operation"] == "listing_payload_v2_shadow"
    assert row["status"] == "shadow_built"
    assert row["product_type"] == "CHAIR"
    assert row["request_payload"]["v1_status"] == "plan_generated"
    assert row["request_payload"]["v1_attribute_names"] == ["item_name"]
    assert row["response_body"]["summary"]["missing_required_paths"] == ["frame"]
    assert row["response_body"]["summary"]["blocking_codes"] == [
        "MISSING_REQUIRED_ATTRIBUTE_RULE"
    ]
    assert row["response_body"]["v2_attribute_names"] == ["item_name"]
    assert row["response_body"]["v2_condition_traces"][0]["schema_path"] == "$.allOf[0]"


def test_shadow_adapter_persists_failure_audit_row():
    repo = FakeSubmissionRepo()
    adapter = ListingPayloadShadowAdapterV2(
        db=object(),
        engine=FakeEngine(error=RuntimeError("boom")),
        rule_loader=FakeRuleLoader(),
        submission_repo=repo,
    )

    result = adapter.run(product_type="CHAIR", sku="SKU1", v1_status="blocked")

    assert result == {
        "sku": "SKU1",
        "status": "shadow_failed",
        "submission_id": 101,
        "error_message": "boom",
    }
    row = repo.rows[0]
    assert row["status"] == "shadow_failed"
    assert row["error_message"] == "boom"
    assert row["request_payload"]["v1_status"] == "blocked"


def _payload_plan():
    trace = ConditionTrace(
        schema_path="$.allOf[0]",
        operator="if/then",
        result="matched",
        introduced_required_paths=["frame"],
    )
    root = RequirementNode(
        path_key="$",
        schema_path="$",
        name="$",
        shape="root",
        children=[
            RequirementNode(
                path_key="item_name",
                schema_path="$.properties.item_name",
                name="item_name",
                shape="list_value",
                required=True,
            )
        ],
    )
    tree = RequirementTree(
        product_type="CHAIR",
        root=root,
        required_paths=["item_name", "frame"],
        condition_traces=[trace],
    )
    return PayloadBuildPlan(
        sku="SKU1",
        product_type="CHAIR",
        attributes={"item_name": [{"value": "V2 Chair"}]},
        requirement_tree=tree,
        covered_required_paths=["item_name"],
        missing_required_paths=["frame"],
        findings=[
            {
                "code": "MISSING_REQUIRED_ATTRIBUTE_RULE",
                "path_key": "frame",
                "blocking": True,
            }
        ],
    )
