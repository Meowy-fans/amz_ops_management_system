from infrastructure.amazon.orders_client import AmazonOrdersClient


class FakeAPIClient:
    def __init__(self):
        self.calls = []

    def request(self, method, path, params=None, json=None, headers=None):
        self.calls.append(
            {"method": method, "path": path, "params": params, "json": json}
        )
        return {"body": {"payload": {"Orders": []}}}


def test_get_orders_builds_expected_query_params():
    client = AmazonOrdersClient(
        api_client=FakeAPIClient(),
        marketplace_id="ATVPDKIKX0DER",
    )

    client.get_orders(
        created_after="2026-06-01T00:00:00Z",
        order_statuses=["Unshipped"],
        fulfillment_channels=["MFN"],
        max_results=50,
        next_token="abc",
    )

    call = client.api_client.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/orders/v0/orders"
    assert call["params"] == {
        "MarketplaceIds": "ATVPDKIKX0DER",
        "CreatedAfter": "2026-06-01T00:00:00Z",
        "MaxResultsPerPage": 50,
        "OrderStatuses": ["Unshipped"],
        "FulfillmentChannels": ["MFN"],
        "NextToken": "abc",
    }


def test_get_order_detail_endpoints():
    api_client = FakeAPIClient()
    client = AmazonOrdersClient(api_client=api_client)

    client.get_order("111-123-456")
    client.get_order_items("111-123-456")
    client.get_order_address("111-123-456")

    assert [call["path"] for call in api_client.calls] == [
        "/orders/v0/orders/111-123-456",
        "/orders/v0/orders/111-123-456/orderItems",
        "/orders/v0/orders/111-123-456/address",
    ]
