from infrastructure.amazon.api_client import AmazonAPIException
from infrastructure.amazon.listings_client import AmazonListingsClient


class FakeAPIClient:
    def __init__(self):
        self.calls = []
        self.responses = []

    def request(self, method, path, params=None, json=None, headers=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json": json,
                "headers": headers,
            }
        )
        return self.responses.pop(0)


def test_patch_listings_item_builds_correct_request():
    api = FakeAPIClient()
    api.responses.append({"headers": {"x-amzn-RequestId": "REQ-1"}, "body": {}})
    client = AmazonListingsClient(
        api_client=api, marketplace_id="ATVPDKIKX0DER", seller_id="SELLER1"
    )

    patches = [
        {
            "op": "replace",
            "path": "/attributes/purchasable_offer",
            "value": [{"currency": "USD", "our_price": [{"schedule": [{"value_with_tax": 19.99}]}]}],
        }
    ]
    response = client.patch_listings_item(sku="SKU1", product_type="CABINET", patches=patches)

    assert response["headers"]["x-amzn-RequestId"] == "REQ-1"
    assert len(api.calls) == 1
    call = api.calls[0]
    assert call["method"] == "PATCH"
    assert call["path"] == "/listings/2021-08-01/items/SELLER1/SKU1"
    assert call["params"] == {
        "marketplaceIds": "ATVPDKIKX0DER",
        "issueLocale": "en_US",
    }
    assert call["json"] == {
        "productType": "CABINET",
        "patches": patches,
    }


def test_get_listings_item_builds_correct_request():
    api = FakeAPIClient()
    api.responses.append({"headers": {}, "body": {"sku": "SKU1"}})
    client = AmazonListingsClient(
        api_client=api, marketplace_id="ATVPDKIKX0DER", seller_id="SELLER2"
    )

    response = client.get_listings_item(sku="SKU1")

    assert response["body"]["sku"] == "SKU1"
    call = api.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/listings/2021-08-01/items/SELLER2/SKU1"
    assert call["params"] == {
        "marketplaceIds": "ATVPDKIKX0DER",
        "issueLocale": "en_US",
    }


def test_get_listings_item_can_include_issue_data():
    api = FakeAPIClient()
    api.responses.append({"headers": {}, "body": {"sku": "SKU1", "issues": []}})
    client = AmazonListingsClient(
        api_client=api, marketplace_id="ATVPDKIKX0DER", seller_id="SELLER2"
    )

    client.get_listings_item(
        sku="SKU1",
        included_data=["summaries", "issues", "productTypes"],
    )

    assert api.calls[0]["params"]["includedData"] == "summaries,issues,productTypes"


def test_search_listings_items_builds_issue_query():
    api = FakeAPIClient()
    api.responses.append({"headers": {}, "body": {"items": []}})
    client = AmazonListingsClient(
        api_client=api, marketplace_id="ATVPDKIKX0DER", seller_id="SELLER2"
    )

    client.search_listings_items(
        included_data=["summaries", "issues"],
        with_issue_severity=["ERROR", "WARNING"],
        page_size=10,
    )

    call = api.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/listings/2021-08-01/items/SELLER2"
    assert call["params"]["includedData"] == "summaries,issues"
    assert call["params"]["withIssueSeverity"] == "ERROR,WARNING"
    assert call["params"]["pageSize"] == 10


def test_search_listings_items_page_token_uses_token_context():
    api = FakeAPIClient()
    api.responses.append({"headers": {}, "body": {"items": []}})
    client = AmazonListingsClient(
        api_client=api, marketplace_id="ATVPDKIKX0DER", seller_id="SELLER2"
    )

    client.search_listings_items(
        included_data=["summaries", "issues"],
        page_size=10,
        page_token="NEXT",
    )

    assert api.calls[0]["params"] == {
        "marketplaceIds": "ATVPDKIKX0DER",
        "issueLocale": "en_US",
        "pageSize": 10,
        "includedData": "summaries,issues",
        "pageToken": "NEXT",
    }


def test_patch_listings_item_uses_injected_ids():
    api = FakeAPIClient()
    api.responses.append({"headers": {}, "body": {}})
    client = AmazonListingsClient(
        api_client=api, marketplace_id="MARKET99", seller_id="SELLER99"
    )

    client.patch_listings_item(sku="SKU1", product_type="HOME_MIRROR", patches=[])

    call = api.calls[0]
    assert "/items/SELLER99/SKU1" in call["path"]
    assert call["params"]["marketplaceIds"] == "MARKET99"


def test_patch_listings_item_propagates_api_error():
    api = FakeAPIClient()

    def raise_error(*args, **kwargs):
        raise AmazonAPIException("test error", status_code=400)

    api.request = raise_error
    client = AmazonListingsClient(api_client=api)

    try:
        client.patch_listings_item(sku="SKU1", product_type="CABINET", patches=[])
        assert False, "should have raised"
    except AmazonAPIException as e:
        assert e.status_code == 400


def test_patch_listings_item_with_multiple_patches():
    api = FakeAPIClient()
    api.responses.append({"headers": {}, "body": {}})
    client = AmazonListingsClient(api_client=api)

    patches = [
        {"op": "replace", "path": "/attributes/purchasable_offer", "value": [{}]},
        {"op": "replace", "path": "/attributes/fulfillment_availability", "value": [{}]},
    ]
    client.patch_listings_item(sku="SKU1", product_type="CABINET", patches=patches)

    call = api.calls[0]
    assert len(call["json"]["patches"]) == 2
