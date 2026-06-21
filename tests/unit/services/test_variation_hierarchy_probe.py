"""Unit tests for read-only variation hierarchy probe."""

from src.services.variation_hierarchy_probe import VariationHierarchyProbe


class FakeListingsClient:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def get_listings_item(self, sku, included_data=None):
        self.calls.append((sku, included_data))
        return {"body": self.body}


class FakeCatalogClient:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def get_catalog_item(self, asin, included_data=None):
        self.calls.append((asin, included_data))
        return {"body": self.body}


def test_probe_parent_fetches_catalog_relationships():
    listings = FakeListingsClient({"summaries": [{"asin": "B012345678"}]})
    catalog = FakeCatalogClient(
        {
            "relationships": [
                {
                    "variationChildren": [
                        {"asin": "B000000001"},
                        {"asin": "B000000002"},
                    ]
                }
            ]
        }
    )
    probe = VariationHierarchyProbe(
        listings_client=listings,
        catalog_client=catalog,
    )

    result = probe.probe_parent("PARENT-SKU")

    assert result.parent_asin == "B012345678"
    assert result.child_asins == ["B000000001", "B000000002"]
    assert listings.calls == [
        ("PARENT-SKU", ["summaries", "attributes", "productTypes"])
    ]
    assert catalog.calls == [("B012345678", ["relationships"])]


def test_probe_parent_warns_when_parent_asin_missing():
    probe = VariationHierarchyProbe(
        listings_client=FakeListingsClient({"summaries": []}),
        catalog_client=FakeCatalogClient({}),
    )

    result = probe.probe_parent("PARENT-SKU")

    assert result.parent_asin is None
    assert "parent_asin_not_found" in result.warnings
