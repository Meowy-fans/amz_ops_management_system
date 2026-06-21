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

    assert result.probe_status == "insufficient_online_facts"
    assert result.parent_asin == "B012345678"
    assert result.child_asins == ["B000000001", "B000000002"]
    assert result.parent_listing_snapshot == {"summaries": [{"asin": "B012345678"}]}
    assert result.catalog_relationship_snapshot == {
        "relationships": [
            {
                "variationChildren": [
                    {"asin": "B000000001"},
                    {"asin": "B000000002"},
                ]
            }
        ]
    }
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
    assert result.probe_status == "parent_asin_not_found"
    assert "parent_asin_not_found" in result.warnings


def test_probe_parent_extracts_online_sibling_facts():
    listings = FakeListingsClient({"summaries": [{"asin": "B012345678"}]})
    catalog = FakeCatalogClient(
        {
            "relationships": [
                {
                    "variationChildren": [
                        {
                            "asin": "B000000001",
                            "sellerSku": "CHILD-1",
                            "variation_attributes": {"color_name": "White"},
                        },
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

    assert result.probe_status == "facts_collected"
    assert result.online_sibling_facts == [
        {
            "asin": "B000000001",
            "sku": "CHILD-1",
            "variation_attributes": {"color_name": "White"},
            "raw": {
                "asin": "B000000001",
                "sellerSku": "CHILD-1",
                "variation_attributes": {"color_name": "White"},
            },
        }
    ]


def test_probe_parent_limits_deep_relationship_recursion():
    relationships = [{"variationChildren": [{"asin": "B000000001"}]}]
    probe = VariationHierarchyProbe(
        listings_client=FakeListingsClient({"summaries": [{"asin": "B012345678"}]}),
        catalog_client=FakeCatalogClient({"relationships": relationships}),
        max_depth=1,
    )

    result = probe.probe_parent("PARENT-SKU")

    assert result.child_asins == []
    assert result.probe_status == "child_asins_not_found"
