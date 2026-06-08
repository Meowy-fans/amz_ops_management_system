from unittest.mock import MagicMock

from src.services.amazon_price_inventory_delayed_confirmation_service import (
    AmazonPriceInventoryDelayedConfirmationService,
)


class FakeListingsClient:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def get_listings_item(self, sku, issue_locale="en_US", included_data=None):
        self.calls.append({"sku": sku, "included_data": included_data})
        return {"headers": {"x-amzn-RequestId": "REQ-DELAYED"}, "body": self.body}


class FakeSubmissionRepo:
    def __init__(self, candidates):
        self.candidates = candidates
        self.inserts = []

    def get_delayed_confirmation_candidates(self, older_than_minutes=30, limit=500):
        self.request = {"older_than_minutes": older_than_minutes, "limit": limit}
        return self.candidates

    def insert_submission(self, **kwargs):
        self.inserts.append(kwargs)
        return 999


class FakeCacheRepo:
    def __init__(self):
        self.items = []

    def upsert_items(self, items):
        self.items.extend(items)
        return len(items)


def _candidate():
    return {
        "id": 1123,
        "sku": "A0004420240915",
        "operation": "both",
        "status": "confirmed_with_mismatch",
        "marketplace_id": "ATVPDKIKX0DER",
        "product_type": "HOME_MIRROR",
        "request_payload": {
            "productType": "HOME_MIRROR",
            "patches": [
                {
                    "op": "replace",
                    "path": "/attributes/purchasable_offer",
                    "value": [
                        {
                            "currency": "USD",
                            "our_price": [
                                {"schedule": [{"value_with_tax": 190.86}]}
                            ],
                            "marketplace_id": "ATVPDKIKX0DER",
                        }
                    ],
                },
                {
                    "op": "replace",
                    "path": "/attributes/fulfillment_availability",
                    "value": [
                        {
                            "fulfillment_channel_code": "DEFAULT",
                            "quantity": 0,
                        }
                    ],
                },
            ],
        },
        "response_body": {},
        "submitted_at": "2026-06-08T20:25:47+08:00",
    }


def _listing_body(price=190.86, quantity=0, issues=None):
    return {
        "sku": "A0004420240915",
        "issues": issues or [],
        "offers": [{"price": {"amount": str(price), "currency": "USD"}}],
        "fulfillmentAvailability": [{"quantity": quantity}],
        "attributes": {
            "purchasable_offer": [
                {"our_price": [{"schedule": [{"value_with_tax": price}]}]}
            ],
            "fulfillment_availability": [{"quantity": quantity}],
        },
    }


def test_confirm_pending_records_delayed_update_confirmed():
    repo = FakeSubmissionRepo([_candidate()])
    cache = FakeCacheRepo()
    service = AmazonPriceInventoryDelayedConfirmationService(
        db=MagicMock(),
        listings_client=FakeListingsClient(_listing_body()),
        submission_repo=repo,
        cache_repo=cache,
    )

    results = service.confirm_pending(older_than_minutes=30, limit=10)

    assert results == [
        {
            "sku": "A0004420240915",
            "source_id": 1123,
            "status": "delayed_update_confirmed",
        }
    ]
    assert repo.request == {"older_than_minutes": 30, "limit": 10}
    assert repo.inserts[0]["operation"] == "delayed_confirmation"
    assert repo.inserts[0]["status"] == "delayed_update_confirmed"
    assert repo.inserts[0]["response_body"]["source_submission_id"] == 1123
    assert repo.inserts[0]["response_body"]["confirmation"]["mismatches"] == {}
    assert cache.items[0]["sku"] == "A0004420240915"


def test_confirm_pending_records_issues_and_mismatch_together():
    repo = FakeSubmissionRepo([_candidate()])
    service = AmazonPriceInventoryDelayedConfirmationService(
        db=MagicMock(),
        listings_client=FakeListingsClient(
            _listing_body(
                price=134.67,
                quantity=55,
                issues=[{"severity": "WARNING", "code": "18448"}],
            )
        ),
        submission_repo=repo,
        cache_repo=FakeCacheRepo(),
    )

    results = service.confirm_pending()

    assert results[0]["status"] == "delayed_confirmed_with_issues_and_mismatch"
    confirmation = repo.inserts[0]["response_body"]["confirmation"]
    assert confirmation["issues"] == 1
    assert confirmation["mismatches"] == {
        "price": {"expected": 190.86, "actual": 134.67},
        "quantity": {"expected": 0, "actual": 55},
    }


def test_confirm_pending_records_failure():
    class FailingClient:
        def get_listings_item(self, **kwargs):
            raise RuntimeError("api down")

    repo = FakeSubmissionRepo([_candidate()])
    service = AmazonPriceInventoryDelayedConfirmationService(
        db=MagicMock(),
        listings_client=FailingClient(),
        submission_repo=repo,
        cache_repo=FakeCacheRepo(),
    )

    results = service.confirm_pending()

    assert results[0]["status"] == "delayed_confirmation_failed"
    assert repo.inserts[0]["error_message"] == "api down"


def test_confirm_pending_no_candidates_returns_empty():
    service = AmazonPriceInventoryDelayedConfirmationService(
        db=MagicMock(),
        listings_client=FakeListingsClient(_listing_body()),
        submission_repo=FakeSubmissionRepo([]),
        cache_repo=FakeCacheRepo(),
    )

    assert service.confirm_pending() == []
