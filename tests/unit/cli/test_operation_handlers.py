from types import SimpleNamespace
from unittest.mock import MagicMock

from src.cli import operation_handlers


def test_handle_sync_products_returns_when_no_skus(monkeypatch, capsys):
    service = MagicMock()
    service.get_full_sku_list.return_value = []
    monkeypatch.setattr(operation_handlers, "GigaSyncService", lambda db: service)

    operation_handlers.handle_sync_products(db=object())

    service.sync_product_details.assert_not_called()
    assert "没有收藏商品需要同步" in capsys.readouterr().out


def test_handle_sync_products_requires_auto_confirm_for_non_tty(monkeypatch, capsys):
    service = MagicMock()
    service.get_full_sku_list.return_value = ["SKU1"]
    monkeypatch.setattr(operation_handlers, "GigaSyncService", lambda db: service)
    monkeypatch.setattr(
        operation_handlers.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: False),
    )

    operation_handlers.handle_sync_products(db=object(), auto_confirm=False)

    service.sync_product_details.assert_not_called()
    assert "请务必勾选 '自动确认 (Auto Confirm)'" in capsys.readouterr().out


def test_handle_sync_products_cancels_when_tty_user_declines(monkeypatch, capsys):
    service = MagicMock()
    service.get_full_sku_list.return_value = ["SKU1"]
    monkeypatch.setattr(operation_handlers, "GigaSyncService", lambda db: service)
    monkeypatch.setattr(
        operation_handlers.sys,
        "stdin",
        SimpleNamespace(isatty=lambda: True),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    operation_handlers.handle_sync_products(db=object(), auto_confirm=False)

    service.sync_product_details.assert_not_called()
    assert "操作已取消" in capsys.readouterr().out


def test_handle_sync_products_runs_with_auto_confirm(monkeypatch, capsys):
    service = MagicMock()
    service.get_full_sku_list.return_value = ["SKU1", "SKU2"]
    service.sync_product_details.return_value = (2, 1, 1)
    monkeypatch.setattr(operation_handlers, "GigaSyncService", lambda db: service)

    operation_handlers.handle_sync_products(db=object(), auto_confirm=True)

    service.sync_product_details.assert_called_once_with(["SKU1", "SKU2"])
    output = capsys.readouterr().out
    assert "商品同步完成" in output
    assert "总计: 2" in output
    assert "成功: 1" in output
    assert "失败: 1" in output


def test_handle_import_amazon_report_rejects_missing_file(monkeypatch, capsys):
    monkeypatch.setattr(operation_handlers.os.path, "exists", lambda path: False)

    operation_handlers.handle_import_amazon_report(db=object(), file_path="/tmp/missing.txt")

    assert "文件不存在: /tmp/missing.txt" in capsys.readouterr().out


def test_handle_import_amazon_report_prompts_and_imports_existing_file(
    monkeypatch,
):
    service = MagicMock()
    monkeypatch.setattr("builtins.input", lambda prompt: '"/tmp/report.txt"')
    monkeypatch.setattr(operation_handlers.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        operation_handlers,
        "AmzFullListImporterService",
        lambda db: service,
    )

    operation_handlers.handle_import_amazon_report(db=object())

    service.import_report_from_file.assert_called_once_with("/tmp/report.txt")


def test_handle_sync_amazon_report_api_runs_service(monkeypatch, capsys):
    service = MagicMock()
    monkeypatch.setattr(
        operation_handlers,
        "AmzFullListImporterService",
        lambda db: service,
    )

    operation_handlers.handle_sync_amazon_report_api(db=object())

    service.sync_report_from_api.assert_called_once()
    assert "API 同步亚马逊全量 listing 数据" in capsys.readouterr().out


def test_handle_update_listing_status_runs_manager(monkeypatch, capsys):
    manager = MagicMock()
    monkeypatch.setattr(
        operation_handlers,
        "ListingStatusManager",
        lambda db: manager,
    )

    operation_handlers.handle_update_listing_status(db=object())

    manager.update_statuses_to_listed.assert_called_once()
    assert "更新亚马逊父品发品状态" in capsys.readouterr().out


def test_handle_update_listing_status_prints_errors(monkeypatch, capsys):
    manager = MagicMock()
    manager.update_statuses_to_listed.side_effect = RuntimeError("boom")
    monkeypatch.setattr(
        operation_handlers,
        "ListingStatusManager",
        lambda db: manager,
    )

    operation_handlers.handle_update_listing_status(db=object())

    assert "执行发品状态更新时发生错误: boom" in capsys.readouterr().out


def test_handle_generate_details_runs_generation_and_sku_mapping(monkeypatch, capsys):
    detail_service = MagicMock()
    mapping_service = MagicMock()
    mapping_service.sync_mappings_from_llm_details.return_value = (5, 2)
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setattr(
        operation_handlers,
        "ProductDetailGenerationService",
        lambda db: detail_service,
    )
    monkeypatch.setattr(
        operation_handlers,
        "SkuMappingService",
        lambda db: mapping_service,
    )

    operation_handlers.handle_generate_details(db=object())

    detail_service.process_all_skus.assert_called_once()
    mapping_service.sync_mappings_from_llm_details.assert_called_once()
    output = capsys.readouterr().out
    assert "使用 QWEN 模型" in output
    assert "SKU映射完成。检查: 5, 新建: 2" in output


def test_handle_sync_prices_and_inventory_call_services(monkeypatch):
    price_service = MagicMock()
    inventory_service = MagicMock()
    monkeypatch.setattr(
        operation_handlers,
        "GigaPriceSyncService",
        lambda db: price_service,
    )
    monkeypatch.setattr(
        operation_handlers,
        "GigaInventorySyncService",
        lambda db: inventory_service,
    )

    operation_handlers.handle_sync_prices(db=object())
    operation_handlers.handle_sync_inventory(db=object())

    price_service.sync_all_prices.assert_called_once()
    inventory_service.sync_all_inventory.assert_called_once()


def test_handle_update_prices_prints_first_five_report_rows(monkeypatch, capsys):
    service = MagicMock()
    report_rows = [
        {
            "meow_sku": f"SKU{i}",
            "category": "CABINET",
            "total_cost": 10 + i,
            "final_price": 20 + i,
            "margin": "50%",
        }
        for i in range(6)
    ]
    service.update_prices.return_value = (6, 6, report_rows)
    monkeypatch.setattr(operation_handlers, "PricingService", lambda db: service)

    operation_handlers.handle_update_prices(db=object())

    output = capsys.readouterr().out
    assert "价格更新样例" in output
    assert "SKU0" in output
    assert "SKU4" in output
    assert "还有 1 条记录" in output


def test_handle_update_prices_does_not_print_samples_when_report_empty(
    monkeypatch,
    capsys,
):
    service = MagicMock()
    service.update_prices.return_value = (0, 0, [])
    monkeypatch.setattr(operation_handlers, "PricingService", lambda db: service)

    operation_handlers.handle_update_prices(db=object())

    assert capsys.readouterr().out == ""


def test_handle_sku_sync_from_csv_prints_not_implemented(capsys):
    operation_handlers.handle_sku_sync_from_csv(db=object())

    assert "此功能暂未实现" in capsys.readouterr().out


def test_handle_generate_update_file_runs_service(monkeypatch, capsys):
    service = MagicMock()
    monkeypatch.setattr(
        "src.services.amz_inventory_price_updater_service.InventoryPriceUpdaterService",
        lambda db: service,
    )

    operation_handlers.handle_generate_update_file(db=object())

    service.generate_update_file.assert_called_once()
    assert "生成亚马逊价格与库存更新文件" in capsys.readouterr().out


def test_handle_generate_update_file_prints_errors(monkeypatch, capsys):
    service = MagicMock()
    service.generate_update_file.side_effect = RuntimeError("boom")
    monkeypatch.setattr(
        "src.services.amz_inventory_price_updater_service.InventoryPriceUpdaterService",
        lambda db: service,
    )

    operation_handlers.handle_generate_update_file(db=object())

    assert "生成更新文件时发生错误: boom" in capsys.readouterr().out


def test_handle_update_price_inventory_api_runs_under_lock(monkeypatch, capsys):
    service = MagicMock()
    service.submit_updates_via_api.return_value = [{"sku": "SKU1"}]
    lock = MagicMock()
    lock.acquire.return_value = True
    monkeypatch.setattr(operation_handlers, "PostgresAdvisoryLock", lambda db, name: lock)
    monkeypatch.setattr(
        "src.services.amz_inventory_price_updater_service.InventoryPriceUpdaterService",
        lambda db: service,
    )

    operation_handlers.handle_update_price_inventory_api(db=object(), dry_run=False)

    service.submit_updates_via_api.assert_called_once_with(dry_run=False)
    lock.release.assert_called_once()
    assert "Processed 1 SKUs" in capsys.readouterr().out


def test_handle_update_price_inventory_api_skips_when_lock_is_held(
    monkeypatch,
    capsys,
):
    service = MagicMock()
    lock = MagicMock()
    lock.acquire.return_value = False
    monkeypatch.setattr(operation_handlers, "PostgresAdvisoryLock", lambda db, name: lock)
    monkeypatch.setattr(
        "src.services.amz_inventory_price_updater_service.InventoryPriceUpdaterService",
        lambda db: service,
    )

    operation_handlers.handle_update_price_inventory_api(db=object(), dry_run=False)

    service.submit_updates_via_api.assert_not_called()
    lock.release.assert_not_called()
    assert "already running" in capsys.readouterr().out


def test_handle_update_price_inventory_api_reraises_and_releases_lock(
    monkeypatch,
    capsys,
):
    service = MagicMock()
    service.submit_updates_via_api.side_effect = RuntimeError("boom")
    lock = MagicMock()
    lock.acquire.return_value = True
    monkeypatch.setattr(operation_handlers, "PostgresAdvisoryLock", lambda db, name: lock)
    monkeypatch.setattr(
        "src.services.amz_inventory_price_updater_service.InventoryPriceUpdaterService",
        lambda db: service,
    )

    try:
        operation_handlers.handle_update_price_inventory_api(db=object(), dry_run=False)
        raised = False
    except RuntimeError:
        raised = True

    assert raised is True
    lock.release.assert_called_once()
    assert "Price/inventory API update failed: boom" in capsys.readouterr().out


def test_handle_confirm_price_inventory_api_runs_under_lock(monkeypatch, capsys):
    service = MagicMock()
    service.confirm_pending.return_value = [{"sku": "SKU1"}]
    lock = MagicMock()
    lock.acquire.return_value = True
    monkeypatch.setenv("PRICE_INVENTORY_CONFIRM_AFTER_MINUTES", "30")
    monkeypatch.setenv("PRICE_INVENTORY_CONFIRM_LIMIT", "20")
    monkeypatch.setattr(operation_handlers, "PostgresAdvisoryLock", lambda db, name: lock)
    monkeypatch.setattr(
        "src.services.amazon_price_inventory_delayed_confirmation_service.AmazonPriceInventoryDelayedConfirmationService",
        lambda db: service,
    )

    operation_handlers.handle_confirm_price_inventory_api(db=object())

    service.confirm_pending.assert_called_once_with(older_than_minutes=30, limit=20)
    lock.release.assert_called_once()
    assert "Confirmed 1 prior submissions" in capsys.readouterr().out


def test_handle_confirm_price_inventory_api_skips_when_lock_is_held(
    monkeypatch,
    capsys,
):
    service = MagicMock()
    lock = MagicMock()
    lock.acquire.return_value = False
    monkeypatch.setattr(operation_handlers, "PostgresAdvisoryLock", lambda db, name: lock)
    monkeypatch.setattr(
        "src.services.amazon_price_inventory_delayed_confirmation_service.AmazonPriceInventoryDelayedConfirmationService",
        lambda db: service,
    )

    operation_handlers.handle_confirm_price_inventory_api(db=object())

    service.confirm_pending.assert_not_called()
    lock.release.assert_not_called()
    assert "already running" in capsys.readouterr().out
