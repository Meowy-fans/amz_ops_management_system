"""Unit tests for ComplianceClaimScanner."""
from src.services.compliance_claim_scanner import ComplianceClaimScanner


def test_scan_detects_bacteria_and_mold():
    scanner = ComplianceClaimScanner()
    hits = scanner.scan_fields({
        "description": "Resists stains and bacteria buildup in humid bathrooms.",
        "bullet_1": "Crafted to resist moisture and mold.",
    })
    matched = {hit.matched_text.lower() for hit in hits}
    assert "bacteria buildup" in matched or "bacteria" in matched
    assert "mold" in matched


def test_sanitize_replaces_risky_claims():
    scanner = ComplianceClaimScanner()
    sanitized, fixes = scanner.sanitize_fields({
        "description": (
            "Non-porous surface inhibits mold and mildew growth and resists bacteria buildup."
        ),
        "bullet_4": "Easy Maintenance: ceramic sink resists stains and bacteria",
    })
    combined = " ".join(sanitized.values()).lower()
    assert "bacteria" not in combined
    assert "mildew" not in combined
    assert "mold" not in combined
    assert fixes


def test_scan_and_sanitize_returns_clean_result():
    scanner = ComplianceClaimScanner()
    result = scanner.scan_and_sanitize({
        "title": "Bathroom Vanity",
        "description": "Resists moisture and mold in humid bathrooms.",
    })
    assert result.clean
    assert "mold" not in result.sanitized_fields["description"].lower()
