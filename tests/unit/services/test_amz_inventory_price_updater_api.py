"""Unit tests for submit_updates_via_api on InventoryPriceUpdaterService."""
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.services.amz_inventory_price_updater_service import InventoryPriceUpdaterService
from src.services.progress_reporter import ProgressReporter


class FakeListingsClient:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or []

    def patch_listings_item(self, sku, product_type, patches, issue_locale="en_US"):
        self.calls.append(
            {
                "sku": sku,
                "product_type": product_type,
                "patches": patches,
                "issue_locale": issue_locale,
            }
        )
        if self.responses:
            resp = self.responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp
        return {"headers": {"x-amzn-RequestId": "REQ-OK"}, "body": {}}


class FakeSubmissionRepo:
    def __init__(self):
        self.inserts = []

    def insert_submission(self, **kwargs):
        self.inserts.append(kwargs)
        return len(self.inserts)


class FakeListingDataRepository:
    def __init__(self, skus=None, price_map=None, quantity_map=None):
        self.skus = skus or []
        self._price_map = price_map or {}
        self._quantity_map = quantity_map or {}

    def get_skus_for_update(self):
        return self.skus

    def get_latest_data(self, amazon_skus, giga_skus):
        return (self._price_map, self._quantity_map)


# ── _build_patches tests ──────────────────────────────────────────

def test_build_patches_price_only():
    patches = InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=19.99, quantity=None, marketplace_id="ATVPDKIKX0DER"
    )
    assert len(patches) == 1
    assert patches[0]["path"] == "/attributes/purchasable_offer"
    assert patches[0]["value"][0]["our_price"][0]["schedule"][0]["value_with_tax"] == 19.99


def test_build_patches_quantity_only():
    patches = InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=None, quantity=5, marketplace_id="ATVPDKIKX0DER"
    )
    assert len(patches) == 1
    assert patches[0]["path"] == "/attributes/fulfillment_availability"
    assert patches[0]["value"][0]["quantity"] == 5
    assert patches[0]["value"][0]["fulfillment_channel_code"] == "DEFAULT"


def test_build_patches_both_price_and_quantity():
    patches = InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=31.50, quantity=3, marketplace_id="ATVPDKIKX0DER"
    )
    assert len(patches) == 2
    paths = [p["path"] for p in patches]
    assert "/attributes/purchasable_offer" in paths
    assert "/attributes/fulfillment_availability" in paths


def test_build_patches_none():
    patches = InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=None, quantity=None, marketplace_id="ATVPDKIKX0DER"
    )
    assert patches == []


def test_build_patches_uses_provided_marketplace_id():
    patches = InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=10.00, quantity=None, marketplace_id="MARKET99"
    )
    assert patches[0]["value"][0]["marketplace_id"] == "MARKET99"


# ── submit_updates_via_api dry-run tests ──────────────────────────

def _make_service(
    skus=None,
    price_map=None,
    quantity_map=None,
    listings_client=None,
    submission_repo=None,
):
    """Build a service with dependency injection and mock sync."""
    repo = FakeListingDataRepository(
        skus=skus or [],
        price_map=price_map or {},
        quantity_map=quantity_map or {},
    )
    svc = InventoryPriceUpdaterService.__new__(InventoryPriceUpdaterService)
    svc.db = MagicMock(spec=Session)
    svc.repository = repo
    svc.reporter = ProgressReporter()
    svc._listings_client_instance = listings_client
    svc._submission_repo_instance = submission_repo
    svc._sync_latest_data = lambda: None  # skip real sync
    svc._resolve_product_types = lambda amazon_skus: {s: "CABINET" for s in amazon_skus}
    return svc


def test_dry_run_builds_patches_and_logs_without_api_calls(capsys):
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[
            {"amazon_sku": "SKU1", "giga_sku": "GIGA1"},
            {"amazon_sku": "SKU2", "giga_sku": "GIGA2"},
        ],
        price_map={"SKU1": 19.99},
        quantity_map={"GIGA2": 5},
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=True)

    assert len(results) == 2
    assert results[0]["status"] == "dry_run"
    assert results[1]["status"] == "dry_run"
    assert len(repo.inserts) == 2
    assert repo.inserts[0]["status"] == "dry_run"
    assert repo.inserts[0]["operation"] == "price"
    assert repo.inserts[1]["operation"] == "quantity"


def test_dry_run_skips_sku_with_no_data(capsys):
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1"}],
        price_map={},
        quantity_map={},
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=True)

    assert results == []
    assert len(repo.inserts) == 0


def test_dry_run_empty_sku_list_early_return():
    svc = _make_service(skus=[])
    results = svc.submit_updates_via_api(dry_run=True)
    assert results == []


# ── submit_updates_via_api real-mode tests ────────────────────────

def test_real_mode_calls_api_and_records_success(capsys):
    fake_client = FakeListingsClient(
        responses=[{"headers": {"x-amzn-RequestId": "REQ1"}, "body": {}}]
    )
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1"}],
        price_map={"SKU1": 19.99},
        quantity_map={},
        listings_client=fake_client,
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=False)

    assert len(results) == 1
    assert results[0]["status"] == "success"
    assert results[0]["request_id"] == "REQ1"
    assert len(fake_client.calls) == 1
    assert len(repo.inserts) == 1
    assert repo.inserts[0]["status"] == "success"
    assert repo.inserts[0]["amazon_request_id"] == "REQ1"


def test_real_mode_handles_api_error_and_continues(capsys):
    fake_client = FakeListingsClient(
        responses=[
            RuntimeError("API unavailable"),
            {"headers": {"x-amzn-RequestId": "REQ2"}, "body": {}},
        ]
    )
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[
            {"amazon_sku": "SKU1", "giga_sku": "GIGA1"},
            {"amazon_sku": "SKU2", "giga_sku": "GIGA2"},
        ],
        price_map={"SKU1": 10.00, "SKU2": 20.00},
        quantity_map={},
        listings_client=fake_client,
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=False)

    assert len(results) == 2
    assert results[0]["status"] == "failed"
    assert results[1]["status"] == "success"
    assert len(repo.inserts) == 2
    assert repo.inserts[0]["status"] == "failed"
    assert repo.inserts[1]["status"] == "success"


def test_real_mode_records_product_type_in_submission(capsys):
    fake_client = FakeListingsClient()
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1"}],
        price_map={"SKU1": 19.99},
        quantity_map={},
        listings_client=fake_client,
        submission_repo=repo,
    )

    svc.submit_updates_via_api(dry_run=False)

    assert repo.inserts[0]["product_type"] == "CABINET"
    assert repo.inserts[0]["request_payload"]["productType"] == "CABINET"
