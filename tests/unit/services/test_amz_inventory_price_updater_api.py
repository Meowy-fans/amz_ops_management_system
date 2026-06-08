"""Unit tests for API-native price/inventory updates."""

from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from infrastructure.amazon.api_client import AmazonAPIException
from src.services.amazon_price_inventory_update_service import (
    AmazonPriceInventoryUpdateService,
)
from src.services.amz_inventory_price_updater_service import InventoryPriceUpdaterService
from src.services.progress_reporter import ProgressReporter


class FakeListingsClient:
    def __init__(self, responses=None):
        self.calls = []
        self.get_calls = []
        self.search_calls = []
        self.responses = responses or []
        self.search_pages = [{"headers": {}, "body": {"items": [{"sku": "SKU1"}]}}]
        self.listing_bodies = {}
        self.get_errors = {}

    def search_listings_items(
        self,
        issue_locale="en_US",
        included_data=None,
        with_issue_severity=None,
        page_size=20,
        page_token=None,
    ):
        self.search_calls.append(
            {"included_data": included_data, "page_size": page_size, "page_token": page_token}
        )
        return self.search_pages.pop(0)

    def get_listings_item(self, sku, issue_locale="en_US", included_data=None):
        self.get_calls.append({"sku": sku, "included_data": included_data})
        if sku in self.get_errors:
            raise self.get_errors[sku]
        body = self.listing_bodies.get(
            sku,
            {
                "sku": sku,
                "summaries": [{"productType": "CABINET"}],
                "issues": [],
                "offers": [{"price": {"amount": 10.00}}],
                "fulfillmentAvailability": [{"quantity": 1}],
            },
        )
        return {"headers": {"x-amzn-RequestId": "REQ-GET"}, "body": body}

    def patch_listings_item(self, sku, product_type, patches, issue_locale="en_US"):
        self.calls.append(
            {"sku": sku, "product_type": product_type, "patches": patches}
        )
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {
            "headers": {"x-amzn-RequestId": "REQ-OK"},
            "body": {"status": "ACCEPTED", "issues": []},
        }


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
        return self._price_map, self._quantity_map


class FakeCacheRepo:
    def __init__(self):
        self.items = []

    def upsert_items(self, items):
        self.items.extend(items)
        return len(items)


def _make_service(
    skus=None,
    price_map=None,
    quantity_map=None,
    listings_client=None,
    submission_repo=None,
):
    return AmazonPriceInventoryUpdateService(
        db=MagicMock(spec=Session),
        reporter=ProgressReporter(),
        listings_client=listings_client or FakeListingsClient(),
        submission_repo=submission_repo or FakeSubmissionRepo(),
        listing_data_repo=FakeListingDataRepository(
            skus=skus or [],
            price_map=price_map or {},
            quantity_map=quantity_map or {},
        ),
        cache_repo=FakeCacheRepo(),
        sync_latest_data=lambda: None,
    )


def test_build_patches_price_only():
    patches = InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=19.99, quantity=None, marketplace_id="ATVPDKIKX0DER"
    )
    assert patches[0]["path"] == "/attributes/purchasable_offer"
    assert patches[0]["value"][0]["our_price"][0]["schedule"][0]["value_with_tax"] == 19.99


def test_build_patches_quantity_only():
    patches = InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=None, quantity=5, marketplace_id="ATVPDKIKX0DER"
    )
    assert patches[0]["path"] == "/attributes/fulfillment_availability"
    assert patches[0]["value"][0]["quantity"] == 5


def test_build_patches_both_price_and_quantity():
    patches = InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=31.50, quantity=3, marketplace_id="ATVPDKIKX0DER"
    )
    assert {patch["path"] for patch in patches} == {
        "/attributes/purchasable_offer",
        "/attributes/fulfillment_availability",
    }


def test_build_patches_none():
    assert InventoryPriceUpdaterService._build_patches(
        sku="SKU1", price=None, quantity=None, marketplace_id="ATVPDKIKX0DER"
    ) == []


def test_dry_run_syncs_api_cache_and_records_patch_without_live_patch():
    client = FakeListingsClient()
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1", "product_type": "CABINET"}],
        price_map={"SKU1": 19.99},
        quantity_map={},
        listings_client=client,
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=True)

    assert results == [{"sku": "SKU1", "status": "dry_run"}]
    assert len(client.search_calls) == 1
    assert len(client.get_calls) == 1
    assert client.calls == []
    assert repo.inserts[0]["status"] == "dry_run"
    assert repo.inserts[0]["operation"] == "price"


def test_dry_run_skips_no_change():
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1", "product_type": "CABINET"}],
        price_map={"SKU1": 10.00},
        quantity_map={"GIGA1": 1},
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=True)

    assert results == [{"sku": "SKU1", "status": "skipped_no_change"}]
    assert repo.inserts[0]["status"] == "skipped_no_change"


def test_real_mode_patch_accepted_and_confirmed():
    client = FakeListingsClient()
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1", "product_type": "CABINET"}],
        price_map={"SKU1": 19.99},
        quantity_map={},
        listings_client=client,
        submission_repo=repo,
    )

    def confirm_new_price(sku, issue_locale="en_US", included_data=None):
        client.get_calls.append({"sku": sku, "included_data": included_data})
        if len(client.get_calls) == 1:
            return {
                "headers": {},
                "body": {
                    "sku": sku,
                    "summaries": [{"productType": "CABINET"}],
                    "issues": [],
                    "offers": [{"price": {"amount": 10.00}}],
                    "fulfillmentAvailability": [{"quantity": 1}],
                },
            }
        return {
            "headers": {},
            "body": {
                "sku": sku,
                "summaries": [{"productType": "CABINET"}],
                "issues": [],
                "offers": [{"price": {"amount": 19.99}}],
                "fulfillmentAvailability": [{"quantity": 1}],
            },
        }

    client.get_listings_item = confirm_new_price

    results = svc.submit_updates_via_api(dry_run=False)

    assert results[0]["status"] == "update_confirmed"
    assert repo.inserts[0]["status"] == "update_confirmed"
    assert repo.inserts[0]["response_body"]["patch_response"]["status"] == "ACCEPTED"


def test_real_mode_records_confirmed_with_mismatch():
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1", "product_type": "CABINET"}],
        price_map={"SKU1": 19.99},
        quantity_map={},
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=False)

    assert results[0]["status"] == "confirmed_with_mismatch"
    assert repo.inserts[0]["status"] == "confirmed_with_mismatch"
    assert repo.inserts[0]["response_body"]["confirmation"]["mismatches"] == {
        "price": {"expected": 19.99, "actual": 10.0}
    }


def test_real_mode_handles_patch_issues_and_non_accepted():
    client = FakeListingsClient(
        responses=[
            {"headers": {"x-amzn-RequestId": "REQ1"}, "body": {"status": "ACCEPTED", "issues": [{"code": "X"}]}},
            {"headers": {"x-amzn-RequestId": "REQ2"}, "body": {"status": "INVALID", "issues": []}},
        ]
    )
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[
            {"amazon_sku": "SKU1", "giga_sku": "GIGA1", "product_type": "CABINET"},
            {"amazon_sku": "SKU2", "giga_sku": "GIGA2", "product_type": "CABINET"},
        ],
        price_map={"SKU1": 19.99, "SKU2": 29.99},
        quantity_map={},
        listings_client=client,
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=False)

    assert [item["status"] for item in results] == ["issues_found", "not_accepted"]
    assert [item["status"] for item in repo.inserts] == ["issues_found", "not_accepted"]


def test_real_mode_skips_not_found_before_patch():
    client = FakeListingsClient()
    client.get_errors["SKU1"] = AmazonAPIException("not found", status_code=404)
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1", "product_type": "CABINET"}],
        price_map={"SKU1": 19.99},
        quantity_map={},
        listings_client=client,
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=False)

    assert results[0]["status"] == "skipped_not_found"
    assert client.calls == []
    assert repo.inserts[0]["status"] == "skipped_not_found"


def test_real_mode_blocks_listing_with_error_issue():
    client = FakeListingsClient()
    client.listing_bodies["SKU1"] = {
        "sku": "SKU1",
        "summaries": [{"productType": "CABINET"}],
        "issues": [{"severity": "ERROR", "code": "BAD"}],
        "offers": [{"price": {"amount": 10.00}}],
        "fulfillmentAvailability": [{"quantity": 1}],
    }
    repo = FakeSubmissionRepo()
    svc = _make_service(
        skus=[{"amazon_sku": "SKU1", "giga_sku": "GIGA1", "product_type": "CABINET"}],
        price_map={"SKU1": 19.99},
        quantity_map={},
        listings_client=client,
        submission_repo=repo,
    )

    results = svc.submit_updates_via_api(dry_run=False)

    assert results[0]["status"] == "blocked_listing_issue"
    assert client.calls == []
    assert repo.inserts[0]["status"] == "blocked_listing_issue"
