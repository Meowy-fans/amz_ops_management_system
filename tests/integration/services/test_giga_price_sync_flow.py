from infrastructure.giga.api_client import GigaAPIException
from src.services.giga_price_sync_service import GigaPriceSyncService


class FakeDbSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakeReporter:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class FakeGigaApiClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute(self, endpoint_name, payload, method):
        self.calls.append({
            "endpoint_name": endpoint_name,
            "payload": payload,
            "method": method,
        })
        if not self.responses:
            raise AssertionError("Unexpected API call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakePriceRepository:
    def __init__(self, skus, save_results):
        self.skus = skus
        self.save_results = list(save_results)
        self.saved_batches = []

    def get_all_skus(self):
        return self.skus

    def batch_upsert_prices(self, prices):
        self.saved_batches.append(prices)
        if not self.save_results:
            raise AssertionError("Unexpected save call")
        result = self.save_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _build_service(api_client, repository, reporter=None, **kwargs):
    db = FakeDbSession()
    service = GigaPriceSyncService.__new__(GigaPriceSyncService)
    service.db = db
    service.api_client = api_client
    service.repository = repository
    service.reporter = reporter or FakeReporter()
    service.batch_size = kwargs.get("batch_size", 2)
    service.max_retries = kwargs.get("max_retries", 2)
    service.api_rate_limit = kwargs.get("api_rate_limit", 1)
    service.wait_time = kwargs.get("wait_time", 7)
    return service, db


def test_sync_all_prices_batches_api_results_saves_and_rate_limits(monkeypatch):
    sleeps = []
    monkeypatch.setattr("src.services.giga_price_sync_service.time.sleep", sleeps.append)
    api_client = FakeGigaApiClient([
        {
            "body": {
                "success": True,
                "data": [
                    {"sku": "SKU-1", "basePrice": 10},
                    {"sku": "SKU-2", "basePrice": 20},
                ],
            }
        },
        {
            "body": {
                "success": True,
                "data": [
                    {"sku": "SKU-3", "basePrice": 30},
                ],
            }
        },
    ])
    repository = FakePriceRepository(
        skus=["SKU-1", "SKU-2", "SKU-3"],
        save_results=[(2, 0), (1, 0)],
    )
    reporter = FakeReporter()
    service, db = _build_service(api_client, repository, reporter)

    result = service.sync_all_prices()

    assert result == {"total": 3, "success": 3, "failed": 0}
    assert db.commits == 2
    assert db.rollbacks == 0
    assert sleeps == [7]
    assert api_client.calls == [
        {
            "endpoint_name": "product_price",
            "payload": {"skus": ["SKU-1", "SKU-2"]},
            "method": "POST",
        },
        {
            "endpoint_name": "product_price",
            "payload": {"skus": ["SKU-3"]},
            "method": "POST",
        },
    ]
    assert repository.saved_batches == [
        [
            {"sku": "SKU-1", "basePrice": 10},
            {"sku": "SKU-2", "basePrice": 20},
        ],
        [
            {"sku": "SKU-3", "basePrice": 30},
        ],
    ]
    assert any("待同步SKU总数: 3" in message for message in reporter.messages)
    assert any("总计: 3" in message for message in reporter.messages)
    assert any("成功: 3" in message for message in reporter.messages)


def test_sync_all_prices_rolls_back_failed_batch_and_continues(monkeypatch):
    monkeypatch.setattr("src.services.giga_price_sync_service.time.sleep", lambda *_: None)
    api_client = FakeGigaApiClient([
        {
            "body": {
                "success": True,
                "data": [
                    {"sku": "SKU-1", "basePrice": 10},
                    {"sku": "SKU-2", "basePrice": 20},
                ],
            }
        },
        GigaAPIException("price api unavailable"),
    ])
    repository = FakePriceRepository(
        skus=["SKU-1", "SKU-2", "SKU-3"],
        save_results=[(1, 1)],
    )
    service, db = _build_service(api_client, repository, max_retries=1)

    result = service.sync_all_prices()

    assert result == {"total": 3, "success": 1, "failed": 2}
    assert db.commits == 1
    assert db.rollbacks == 1
    assert repository.saved_batches == [[
        {"sku": "SKU-1", "basePrice": 10},
        {"sku": "SKU-2", "basePrice": 20},
    ]]
    assert api_client.calls == [
        {
            "endpoint_name": "product_price",
            "payload": {"skus": ["SKU-1", "SKU-2"]},
            "method": "POST",
        },
        {
            "endpoint_name": "product_price",
            "payload": {"skus": ["SKU-3"]},
            "method": "POST",
        },
    ]


def test_fetch_batch_prices_retries_api_error_then_returns_data(monkeypatch):
    sleeps = []
    monkeypatch.setattr("src.services.giga_price_sync_service.time.sleep", sleeps.append)
    api_client = FakeGigaApiClient([
        GigaAPIException("temporary"),
        {
            "body": {
                "success": True,
                "data": [{"sku": "SKU-1", "basePrice": 10}],
            }
        },
    ])
    service, _ = _build_service(
        api_client,
        FakePriceRepository(skus=[], save_results=[]),
        max_retries=2,
    )

    assert service.fetch_batch_prices(["SKU-1"]) == [{"sku": "SKU-1", "basePrice": 10}]
    assert sleeps == [1]
    assert len(api_client.calls) == 2
