"""Unit tests for online variation hierarchy audit gate."""

from src.services.variation_hierarchy_audit_gate import VariationHierarchyAuditGate
from src.services.variation_hierarchy_probe import VariationHierarchyProbeResult


def _probe(facts=None, status="facts_collected"):
    return VariationHierarchyProbeResult(
        parent_sku="PARENT-1",
        probe_status=status,
        parent_asin="B012345678",
        child_asins=["B000000001"],
        online_sibling_facts=facts or [],
    )


def test_audit_gate_blocks_duplicate_online_signature():
    gate = VariationHierarchyAuditGate()

    result = gate.evaluate(
        parent_sku="PARENT-1",
        existing_theme="Color",
        selected_attrs={"color_name": "White"},
        existing_children=[],
        probe_result=_probe([
            {
                "asin": "B000000001",
                "sku": "CHILD-1",
                "variation_attributes": {"color_name": "White"},
            }
        ]),
    )

    assert result.blocked is True
    assert result.blocking_codes == ["DUPLICATE_ONLINE_VARIATION_ATTRIBUTES"]
    assert result.online_signatures == [["white"]]
    assert result.findings[0].blocking is True


def test_audit_gate_allows_distinct_online_signature():
    gate = VariationHierarchyAuditGate()

    result = gate.evaluate(
        parent_sku="PARENT-1",
        existing_theme="Color",
        selected_attrs={"color_name": "Blue"},
        existing_children=[],
        probe_result=_probe([
            {
                "asin": "B000000001",
                "variation_attributes": {"color_name": "White"},
            }
        ]),
    )

    assert result.blocked is False
    assert result.blocking_codes == []
    assert result.warning_codes == []
    assert result.online_signatures == [["white"]]


def test_audit_gate_warns_when_online_facts_unavailable():
    gate = VariationHierarchyAuditGate()

    result = gate.evaluate(
        parent_sku="PARENT-1",
        existing_theme="Color",
        selected_attrs={"color_name": "Blue"},
        existing_children=[],
        probe_result=_probe([], status="insufficient_online_facts"),
    )

    assert result.blocked is False
    assert result.warning_codes == ["ONLINE_VARIATION_FACTS_UNAVAILABLE"]
    assert result.findings[0].blocking is False
