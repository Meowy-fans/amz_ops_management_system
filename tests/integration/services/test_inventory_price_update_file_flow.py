import csv
from pathlib import Path

from src.services.amz_inventory_price_updater_service import InventoryPriceUpdaterService


class FakeReporter:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class FakeListingDataRepository:
    def __init__(self):
        self.latest_data_args = None

    def get_skus_for_update(self):
        return [
            {"amazon_sku": "AMZ-1", "giga_sku": "GIGA-1"},
            {"amazon_sku": "AMZ-2", "giga_sku": "GIGA-2"},
            {"amazon_sku": "AMZ-3", "giga_sku": "GIGA-3"},
        ]

    def get_latest_data(self, amazon_skus, giga_skus):
        self.latest_data_args = (amazon_skus, giga_skus)
        return (
            {
                "AMZ-1": "19.99",
                "AMZ-2": None,
                "AMZ-3": "31.50",
            },
            {
                "GIGA-1": 8,
                "GIGA-2": None,
            },
        )


def _build_service(repository, reporter):
    service = InventoryPriceUpdaterService.__new__(InventoryPriceUpdaterService)
    service.db = object()
    service.repository = repository
    service.reporter = reporter
    service.sync_called = False

    def sync_latest_data():
        service.sync_called = True

    service._sync_latest_data = sync_latest_data
    return service


def test_generate_update_file_writes_tab_separated_amazon_update_file(tmp_path, monkeypatch):
    fake_service_dir = tmp_path / "src" / "services"
    fake_service_dir.mkdir(parents=True)
    output_dir = tmp_path / "output"
    repository = FakeListingDataRepository()
    reporter = FakeReporter()
    service = _build_service(repository, reporter)

    monkeypatch.setattr(
        "src.services.amz_inventory_price_updater_service.os.path.dirname",
        lambda _: str(fake_service_dir),
    )

    result = service.generate_update_file()

    assert result is None
    assert service.sync_called is True
    amazon_skus, giga_skus = repository.latest_data_args
    assert set(amazon_skus) == {"AMZ-1", "AMZ-2", "AMZ-3"}
    assert set(giga_skus) == {"GIGA-1", "GIGA-2", "GIGA-3"}

    output_files = list(output_dir.glob("AmazonPriceQuantityUpdate_*.txt"))
    assert len(output_files) == 1

    with output_files[0].open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file, delimiter="\t"))

    assert rows == [
        {
            "sku": "AMZ-1",
            "price": "19.99",
            "minimum-seller-allowed-price": "",
            "maximum-seller-allowed-price": "",
            "quantity": "8",
            "handling-time": "",
            "fulfillment-channel": "",
        },
        {
            "sku": "AMZ-2",
            "price": "",
            "minimum-seller-allowed-price": "",
            "maximum-seller-allowed-price": "",
            "quantity": "0",
            "handling-time": "",
            "fulfillment-channel": "",
        },
        {
            "sku": "AMZ-3",
            "price": "31.50",
            "minimum-seller-allowed-price": "",
            "maximum-seller-allowed-price": "",
            "quantity": "0",
            "handling-time": "",
            "fulfillment-channel": "",
        },
    ]
    assert list(rows[0].keys()) == [
        "sku",
        "price",
        "minimum-seller-allowed-price",
        "maximum-seller-allowed-price",
        "quantity",
        "handling-time",
        "fulfillment-channel",
    ]
    assert any("更新文件已成功保存至" in message for message in reporter.messages)
    assert any("共处理 3 个商品" in message for message in reporter.messages)
