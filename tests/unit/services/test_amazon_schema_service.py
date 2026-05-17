"""Unit tests for AmazonSchemaService."""
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.services.amazon_schema_service import AmazonSchemaService


class FakeSchemaRepo:
    def __init__(self, cached=None):
        self.cached = cached
        self.upserted = []

    def get(self, product_type, marketplace_id):
        return self.cached

    def upsert(self, product_type, marketplace_id, schema, required):
        self.upserted.append((product_type, schema, required))


@pytest.fixture
def svc():
    db = MagicMock(spec=Session)
    s = AmazonSchemaService(db=db)
    s._repo_instance = FakeSchemaRepo()
    return s


# ── cache ─────────────────────────────────────────────────────────

def test_get_cached_schema_miss(svc):
    assert svc.get_cached_schema("CABINET") is None


def test_get_cached_schema_hit(svc):
    svc._repo_instance.cached = {
        "schema_json": {"type": "object"},
        "required_properties": ["item_name", "brand"],
        "retrieved_at": "2026-05-17",
    }
    cached = svc.get_cached_schema("CABINET")
    assert cached is not None
    assert cached["required_properties"] == ["item_name", "brand"]


# ── validation ────────────────────────────────────────────────────

def test_validate_attributes_all_present(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_required_properties", lambda pt: ["item_name", "brand"])
    attrs = {"item_name": [{"value": "Test"}], "brand": [{"value": "B"}]}
    assert svc.validate_attributes("CABINET", attrs) == []


def test_validate_attributes_missing(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_required_properties", lambda pt: ["item_name", "brand", "fabric_type"])
    missing = svc.validate_attributes("CABINET", {"item_name": [{"value": "Test"}]})
    assert len(missing) == 2
    names = {m["property"] for m in missing}
    assert "brand" in names
    assert "fabric_type" in names


def test_validate_attributes_empty_value(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_required_properties", lambda pt: ["brand"])
    missing = svc.validate_attributes("CABINET", {"brand": []})
    assert len(missing) == 1


# ── valid values ──────────────────────────────────────────────────

def test_get_valid_values_not_in_schema(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {"schema_json": {}, "required_properties": []})
    assert svc.get_valid_values("CABINET", "nonexistent") is None


def test_get_valid_values_with_enum(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {
        "schema_json": {
            "properties": {
                "country_of_origin": {
                    "items": {"properties": {"value": {"enum": ["CN", "US", "VN"]}}}
                }
            }
        },
        "required_properties": [],
    })
    assert svc.get_valid_values("CABINET", "country_of_origin") == ["CN", "US", "VN"]


def test_get_valid_values_no_enum(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {
        "schema_json": {
            "properties": {
                "item_name": {"items": {"properties": {"value": {"type": "string"}}}}
            }
        },
        "required_properties": [],
    })
    assert svc.get_valid_values("CABINET", "item_name") is None


# ── property descriptions ─────────────────────────────────────────

def test_get_property_descriptions(monkeypatch, svc):
    monkeypatch.setattr(svc, "get_or_fetch_schema", lambda pt: {
        "schema_json": {
            "allOf": [{"properties": {"item_name": {"description": "The product title"}}}],
            "properties": {"brand": {"title": "Brand", "description": "The brand name"}},
        },
        "required_properties": [],
    })
    descs = svc.get_property_descriptions("CABINET")
    assert "item_name" in descs
    assert "brand" in descs
    assert descs["item_name"] == "The product title"
