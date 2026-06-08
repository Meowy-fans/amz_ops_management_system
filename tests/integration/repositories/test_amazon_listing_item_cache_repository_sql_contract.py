"""SQL contract tests for Amazon listing item API cache repository."""

from src.repositories.amazon_listing_item_cache_repository import (
    AmazonListingItemCacheRepository,
)


class RecordingSession:
    def __init__(self):
        self.calls = []
        self.commits = 0

    def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))

    def commit(self):
        self.commits += 1


def _normalized(sql):
    return " ".join(sql.split())


def test_upsert_items_sql_contract_stores_api_listing_facts():
    session = RecordingSession()
    repo = AmazonListingItemCacheRepository(session)

    count = repo.upsert_items([
        {
            "sku": "MEOW-1",
            "summaries": [
                {
                    "asin": "B001",
                    "productType": "CABINET",
                    "status": ["BUYABLE"],
                    "lastUpdatedDate": "2026-06-08T00:00:00Z",
                }
            ],
            "attributes": {"condition_type": [{"value": "new_new"}]},
            "issues": [],
            "offers": [{"price": {"amount": 99.99}}],
            "fulfillmentAvailability": [{"quantity": 5}],
        }
    ])

    assert count == 1
    sql = _normalized(session.calls[0][0])
    rows = session.calls[0][1]
    assert "INSERT INTO amazon_listing_items_cache" in sql
    assert "ON CONFLICT (sku) DO UPDATE SET" in sql
    assert rows[0]["sku"] == "MEOW-1"
    assert rows[0]["asin"] == "B001"
    assert rows[0]["product_type"] == "CABINET"
    assert '"BUYABLE"' in rows[0]["listing_status"]
    assert '"quantity": 5' in rows[0]["fulfillment_availability"]
    assert session.commits == 1


def test_upsert_items_empty_input_does_not_hit_database():
    session = RecordingSession()
    repo = AmazonListingItemCacheRepository(session)

    assert repo.upsert_items([]) == 0
    assert session.calls == []
    assert session.commits == 0
