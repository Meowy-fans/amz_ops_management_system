from src.services.giga_inventory_sync_service import GigaInventorySyncService


class FakeRepository:
    def __init__(self, skus):
        self.skus = skus

    def get_all_skus(self):
        return self.skus


class FakeReporter:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


def _build_service(skus, reporter=None):
    service = GigaInventorySyncService.__new__(GigaInventorySyncService)
    service.db = object()
    service.repository = FakeRepository(skus)
    service.api_client = object()
    service.reporter = reporter or FakeReporter()
    service.batch_size = 2
    service.max_retries = 1
    service.max_threads = 3
    service.api_rate_limit = 2
    service.wait_time = 9
    service.save_api_response = False
    return service


def test_sync_all_inventory_aggregates_success_and_failed_batches(monkeypatch):
    sleeps = []
    monkeypatch.setattr("src.services.giga_inventory_sync_service.time.sleep", sleeps.append)
    reporter = FakeReporter()
    service = _build_service(
        ["SKU-1", "SKU-2", "SKU-3", "SKU-4", "SKU-5"],
        reporter,
    )
    processed_batches = []

    def process_batch(batch_idx, skus):
        processed_batches.append((batch_idx, list(skus)))
        if batch_idx == 2:
            raise RuntimeError("inventory api outage")
        return len(skus), len(skus)

    service.process_batch = process_batch

    stats = service.sync_all_inventory()

    assert stats == {
        "total_skus": 5,
        "batches": 3,
        "processed": 3,
        "upserted": 3,
        "success_batches": 2,
        "failed_batches": 1,
    }
    assert sorted(processed_batches) == [
        (1, ["SKU-1", "SKU-2"]),
        (2, ["SKU-3", "SKU-4"]),
        (3, ["SKU-5"]),
    ]
    assert sleeps == [9]
    assert any("待同步SKU总数: 5" in message for message in reporter.messages)
    assert any("成功批次: 2" in message for message in reporter.messages)
    assert any("失败批次: 1" in message for message in reporter.messages)
    assert any("更新记录: 3/3" in message for message in reporter.messages)


def test_sync_all_inventory_returns_zero_stats_when_repository_fails():
    reporter = FakeReporter()
    service = _build_service([], reporter)

    def raise_from_get_all_skus():
        raise RuntimeError("database unavailable")

    service.repository.get_all_skus = raise_from_get_all_skus

    stats = service.sync_all_inventory()

    assert stats == {
        "total_skus": 0,
        "batches": 0,
        "processed": 0,
        "upserted": 0,
        "success_batches": 0,
        "failed_batches": 0,
    }
    assert any("SKU总数: 0" in message for message in reporter.messages)
    assert any("更新记录: 0/0" in message for message in reporter.messages)
