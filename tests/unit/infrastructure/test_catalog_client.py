from infrastructure.amazon.catalog_client import AmazonCatalogClient


class FakeAPIClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, path, params=None):
        self.calls.append((method, path, params))
        return self.response


def test_batch_get_summaries_extracts_product_type_from_product_types_payload():
    api_client = FakeAPIClient(
        {
            "body": {
                "items": [
                    {
                        "asin": "B0001",
                        "summaries": [{"itemName": "Modern Sofa", "brand": "Brand"}],
                        "productTypes": [{"productType": "SOFA"}],
                    }
                ]
            }
        }
    )

    result = AmazonCatalogClient(api_client=api_client).batch_get_summaries(["B0001"])

    assert result["B0001"]["product_type"] == "SOFA"
    assert api_client.calls[0][2]["identifiers"] == "B0001"
    assert api_client.calls[0][2]["includedData"] == "summaries,salesRanks,productTypes"


def test_search_catalog_items_serializes_multiple_identifiers_as_comma_string():
    api_client = FakeAPIClient({"body": {"items": []}})

    AmazonCatalogClient(api_client=api_client).search_catalog_items(
        identifiers=["B0001", "B0002"],
        identifiers_type="ASIN",
    )

    assert api_client.calls[0][2]["identifiers"] == "B0001,B0002"
