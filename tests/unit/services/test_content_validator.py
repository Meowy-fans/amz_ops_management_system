"""Unit tests for generated listing content validation."""
from src.services.content_validator import validate_content


def test_validate_content_errors_on_pesticide_device_claims():
    result = validate_content(
        title="Bathroom Cabinet",
        bullets=[],
        description="Ceramic sink resists bacteria buildup in humid spaces.",
        search_terms="",
    )

    assert any("pesticide/device claim" in error for error in result.errors)


def test_validate_content_errors_on_claims_in_bullets():
    result = validate_content(
        title="Bathroom Cabinet",
        bullets=["Durable finish helps prevent mildew in humid rooms."],
        description="Modern storage cabinet.",
        search_terms="",
    )

    assert any("pesticide/device claim" in error for error in result.errors)
