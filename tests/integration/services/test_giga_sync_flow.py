from infrastructure.giga.api_client import GigaAPIException
from src.services.giga_sync_service import GigaSyncService


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


class FakeProductSyncRepository:
    def __init__(self, saved_counts, stats=None):
        self.saved_counts = list(saved_counts)
        self.stats = stats or {"total": 0, "oversize": 0}
        self.saved_batches = []

    def batch_upsert_products(self, products):
        self.saved_batches.append(products)
        if not self.saved_counts:
            raise AssertionError("Unexpected repository save")
        return self.saved_counts.pop(0)

    def get_statistics(self):
        return self.stats


def _build_service(api_client, repository, reporter=None):
    db = FakeDbSession()
    service = GigaSyncService.__new__(GigaSyncService)
    service.db = db
    service.api_client = api_client
    service.repository = repository
    service.reporter = reporter or FakeReporter()
    return service, db


def test_get_full_sku_list_paginates_when_page_is_full(monkeypatch):
    monkeypatch.setattr("src.services.giga_sync_service.time.sleep", lambda *_: None)
    api_client = FakeGigaApiClient([
        {
            "body": {
                "pageMeta": {"total": 3, "next": True},
                "data": [{"sku": "SKU-1"}, {"sku": "SKU-2"}],
            },
            "headers": {"X-RateLimit-Remaining": "10"},
        },
        {
            "body": {
                "pageMeta": {"total": 3, "next": False},
                "data": [{"sku": "SKU-3"}],
            },
            "headers": {"X-RateLimit-Remaining": "10"},
        },
    ])
    service, _ = _build_service(api_client, FakeProductSyncRepository(saved_counts=[]))

    assert service.get_full_sku_list(limit_per_page=2) == ["SKU-1", "SKU-2", "SKU-3"]
    assert api_client.calls == [
        {
            "endpoint_name": "product_list",
            "payload": {"limit": 2, "page": 1, "sort": 4},
            "method": "GET",
        },
        {
            "endpoint_name": "product_list",
            "payload": {"limit": 2, "page": 2, "sort": 4},
            "method": "GET",
        },
    ]


def test_sync_full_products_batches_details_and_reports(monkeypatch):
    monkeypatch.setattr("src.services.giga_sync_service.time.sleep", lambda *_: None)
    api_client = FakeGigaApiClient([
        {
            "body": {
                "pageMeta": {"total": 3, "next": False},
                "data": [{"sku": "SKU-1"}, {"sku": "SKU-2"}, {"sku": "SKU-3"}],
            },
            "headers": {"X-RateLimit-Remaining": "10"},
        },
        {
            "body": {
                "data": [
                    {"sku": "SKU-1", "name": "Product 1"},
                    {"sku": "SKU-2", "name": "Product 2"},
                    {"sku": "SKU-3", "name": "Product 3"},
                ]
            }
        },
    ])
    reporter = FakeReporter()
    repository = FakeProductSyncRepository(
        saved_counts=[3],
        stats={"total": 42, "oversize": 5},
    )
    service, db = _build_service(api_client, repository, reporter)

    result = service.sync_full_products()

    assert result == {"total": 3, "success": 3, "failed": 0}
    assert db.commits == 1
    assert db.rollbacks == 0
    assert repository.saved_batches == [[
        {"sku": "SKU-1", "name": "Product 1"},
        {"sku": "SKU-2", "name": "Product 2"},
        {"sku": "SKU-3", "name": "Product 3"},
    ]]
    assert api_client.calls == [
        {
            "endpoint_name": "product_list",
            "payload": {"limit": 100, "page": 1, "sort": 4},
            "method": "GET",
        },
        {
            "endpoint_name": "product_details",
            "payload": {"skus": ["SKU-1", "SKU-2", "SKU-3"]},
            "method": "POST",
        },
    ]
    assert any("成功获取3个SKU" in message for message in reporter.messages)
    assert any("本次同步: 总计3，成功3，失败0" in message for message in reporter.messages)
    assert any("数据库统计: 总记录42，超大件5" in message for message in reporter.messages)


def test_sync_product_details_rolls_back_failed_batch_and_continues(monkeypatch):
    monkeypatch.setattr("src.services.giga_sync_service.time.sleep", lambda *_: None)
    api_client = FakeGigaApiClient([
        {
            "body": {
                "data": [
                    {"sku": "SKU-1", "name": "Product 1"},
                    {"sku": "SKU-2", "name": "Product 2"},
                ]
            }
        },
        GigaAPIException("temporary outage"),
    ])
    repository = FakeProductSyncRepository(saved_counts=[1])
    service, db = _build_service(api_client, repository)

    result = service.sync_product_details(["SKU-1", "SKU-2", "SKU-3"], batch_size=2)

    assert result == {"total": 3, "success": 1, "failed": 2}
    assert db.commits == 1
    assert db.rollbacks == 1
    assert repository.saved_batches == [[
        {"sku": "SKU-1", "name": "Product 1"},
        {"sku": "SKU-2", "name": "Product 2"},
    ]]
    assert api_client.calls == [
        {
            "endpoint_name": "product_details",
            "payload": {"skus": ["SKU-1", "SKU-2"]},
            "method": "POST",
        },
        {
            "endpoint_name": "product_details",
            "payload": {"skus": ["SKU-3"]},
            "method": "POST",
        },
    ]
