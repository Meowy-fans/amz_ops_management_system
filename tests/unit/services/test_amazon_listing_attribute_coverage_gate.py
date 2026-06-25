"""Unit tests for required Amazon listing attribute coverage."""

from src.services.amazon_listing_attribute_coverage_gate import (
    AmazonListingAttributeCoverageGate,
)


class FakeSchemaService:
    def __init__(self, required=None, schema_error=None):
        self.required = required
        self.schema_error = schema_error

    def get_required_properties(self, product_type):
        if self.schema_error:
            raise self.schema_error
        return list(self.required or [])


class FakeCoverageSchemaService(FakeSchemaService):
    def get_required_properties(self, product_type):
        return ["item_name"]

    def get_coverage_required_properties(self, product_type):
        if self.schema_error:
            raise self.schema_error
        return list(self.required or [])


def _plan(attrs=None, resolutions=None):
    plan = {
        "sku": "SKU1",
        "product_type": "HOME_MIRROR",
        "attributes": {
            "item_name": [{"value": "Wall Mirror"}],
        },
    }
    if attrs:
        plan["attributes"].update(attrs)
    if resolutions is not None:
        plan["attribute_resolutions"] = resolutions
    return plan


def test_coverage_gate_passes_when_required_attributes_are_present():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeSchemaService(required=["item_name", "fabric_type"])
    )

    result = gate.evaluate(
        _plan(attrs={"fabric_type": [{"value": "Glass, Metal"}]})
    )

    assert result.blocked is False
    assert result.missing_required == []
    assert set(result.covered_required) == {"item_name", "fabric_type"}


def test_coverage_gate_blocks_missing_required_attribute():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeSchemaService(required=["item_name", "fabric_type"])
    )

    result = gate.evaluate(_plan())

    assert result.blocked is True
    assert result.missing_required == ["fabric_type"]
    assert result.blocking_codes == ["MISSING_REQUIRED_ATTRIBUTE_RULE"]
    assert result.findings[0]["attribute"] == "fabric_type"


def test_coverage_gate_warns_when_schema_is_unavailable():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeSchemaService(schema_error=RuntimeError("schema down"))
    )

    result = gate.evaluate(_plan())

    assert result.blocked is False
    assert result.warning_codes == ["ATTRIBUTE_SCHEMA_UNAVAILABLE"]
    assert result.findings[0]["blocking"] is False


def test_coverage_gate_blocks_low_confidence_required_resolution():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeSchemaService(required=["fabric_type"])
    )

    result = gate.evaluate(
        _plan(
            attrs={"fabric_type": [{"value": "Unknown"}]},
            resolutions={
                "fabric_type": {
                    "state": "resolved_low_confidence",
                    "level": "required",
                    "confidence": "low",
                    "source": "default",
                }
            },
        )
    )

    assert result.blocked is True
    assert result.low_confidence_required == ["fabric_type"]
    assert result.blocking_codes == ["LOW_CONFIDENCE_REQUIRED_ATTRIBUTE"]


def test_coverage_gate_blocks_pending_required_llm_review():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeSchemaService(required=["included_components"])
    )

    result = gate.evaluate(
        _plan(
            attrs={"included_components": [{"value": "Chair"}]},
            resolutions={
                "included_components": {
                    "state": "needs_manual_review",
                    "level": "required",
                    "confidence": "medium",
                    "source": "llm",
                    "review_status": "pending",
                }
            },
        )
    )

    assert result.blocked is True
    assert result.review_required == ["included_components"]
    assert result.blocking_codes == ["NEEDS_REVIEW_REQUIRED_ATTRIBUTE"]


def test_coverage_gate_allows_auto_approved_required_llm_review():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeSchemaService(required=["included_components"])
    )

    result = gate.evaluate(
        _plan(
            attrs={"included_components": [{"value": "Chair"}]},
            resolutions={
                "included_components": {
                    "state": "auto_approved",
                    "level": "required",
                    "confidence": "medium",
                    "source": "llm",
                    "review_status": "auto_approved",
                }
            },
        )
    )

    assert result.blocked is False
    assert result.review_required == []


def test_coverage_gate_allows_safe_evidenced_medium_confidence_default():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeSchemaService(required=["fabric_type"])
    )

    result = gate.evaluate(
        _plan(
            attrs={"fabric_type": [{"value": "Glass, Metal"}]},
            resolutions={
                "fabric_type": {
                    "state": "resolved_with_default",
                    "level": "required",
                    "confidence": "medium",
                    "source": "default",
                    "evidence": "Safe HOME_MIRROR material fallback.",
                    "safe_default": True,
                }
            },
        )
    )

    assert result.blocked is False
    assert result.defaulted_required == ["fabric_type"]


def test_coverage_gate_blocks_default_without_safe_default_marker():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeSchemaService(required=["fabric_type"])
    )

    result = gate.evaluate(
        _plan(
            attrs={"fabric_type": [{"value": "Unknown"}]},
            resolutions={
                "fabric_type": {
                    "state": "resolved_with_default",
                    "level": "required",
                    "confidence": "medium",
                    "source": "default",
                    "evidence": "Generic fallback.",
                }
            },
        )
    )

    assert result.blocked is True
    assert result.blocking_codes == ["UNSAFE_DEFAULT_REQUIRED_ATTRIBUTE"]
    assert result.findings[0]["attribute"] == "fabric_type"


def test_coverage_gate_uses_coverage_required_properties_when_available():
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeCoverageSchemaService(
            required=["item_name", "model_name", "mounting_type"]
        )
    )

    result = gate.evaluate(_plan(attrs={"model_name": [{"value": "M-1"}]}))

    assert result.blocked is True
    assert result.covered_required == ["item_name", "model_name"]
    assert result.missing_required == ["mounting_type"]


def test_coverage_gate_skips_configured_child_only_required_for_parent(monkeypatch):
    class FakeRuleLoader:
        def load(self, product_type):
            return {"coverage_ignore_when_parent": ["item_width"]}

    monkeypatch.setattr(
        "src.services.amazon_listing_attribute_coverage_gate.AttributeRuleLoader",
        lambda: FakeRuleLoader(),
    )
    gate = AmazonListingAttributeCoverageGate(
        schema_service=FakeCoverageSchemaService(required=["item_name", "item_width"])
    )

    result = gate.evaluate(
        _plan(attrs={"parentage_level": [{"value": "parent"}]})
    )

    assert result.blocked is False
    assert result.missing_required == []
