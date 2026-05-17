"""Unit tests for putListingsItem and validation_preview."""
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


def test_put_listings_item_builds_correct_request():
    api = FakeAPIClient()
    api.responses.append({"headers": {"x-amzn-RequestId": "REQ-1"}, "body": {}})
    client = AmazonListingsClient(
        api_client=api, marketplace_id="ATVPDKIKX0DER", seller_id="SELLER1"
    )

    attrs = {
        "item_name": [{"value": "Test Cabinet"}],
        "brand": [{"value": "TestBrand"}],
    }
    response = client.put_listings_item(
        sku="SKU1", product_type="CABINET", attributes=attrs
    )

    assert response["headers"]["x-amzn-RequestId"] == "REQ-1"
    call = api.calls[0]
    assert call["method"] == "PUT"
    assert call["path"] == "/listings/2021-08-01/items/SELLER1/SKU1"
    assert call["params"]["marketplaceIds"] == "ATVPDKIKX0DER"
    assert call["json"]["productType"] == "CABINET"
    assert call["json"]["attributes"] == attrs


def test_validation_preview_adds_mode_param():
    api = FakeAPIClient()
    api.responses.append({"headers": {}, "body": {"status": "VALID"}})
    client = AmazonListingsClient(
        api_client=api, marketplace_id="MARKET1", seller_id="SELLER2"
    )

    response = client.validation_preview(
        sku="SKU2",
        product_type="HOME_MIRROR",
        attributes={"item_name": [{"value": "Mirror"}]},
    )

    assert response["body"]["status"] == "VALID"
    assert api.calls[0]["params"]["mode"] == "VALIDATION_PREVIEW"


def test_put_listings_item_propagates_error():
    api = FakeAPIClient()

    def raise_error(*args, **kwargs):
        from infrastructure.amazon.api_client import AmazonAPIException
        raise AmazonAPIException("bad request", status_code=400)

    api.request = raise_error
    client = AmazonListingsClient(api_client=api)

    try:
        client.put_listings_item(sku="X", product_type="CABINET", attributes={})
        assert False, "should have raised"
    except Exception as e:
        assert "bad request" in str(e)
