import uuid
from unittest.mock import MagicMock

from src.services.product_listing_flow_helpers import (
    failure_result,
    get_pending_skus_for_category,
    success_result,
)
from src.services.product_listing_log_builder import build_listing_logs


def test_get_pending_skus_for_category_filters_case_insensitively():
    repo = MagicMock()
    repo.get_pending_listing_skus.return_value = ["SKU1", "SKU2", "SKU3"]
    repo.get_sku_to_category_mapping.return_value = [
        ("SKU1", "cabinet"),
        ("SKU2", "MIRROR"),
        ("SKU3", None),
    ]

    skus, message = get_pending_skus_for_category(repo, "CABINET")

    assert skus == ["SKU1"]
    assert message is None
    repo.get_sku_to_category_mapping.assert_called_once_with(["SKU1", "SKU2", "SKU3"])


def test_get_pending_skus_for_category_returns_message_when_empty():
    repo = MagicMock()
    repo.get_pending_listing_skus.return_value = []

    skus, message = get_pending_skus_for_category(repo, "CABINET")

    assert skus == []
    assert message == "没有待发品SKU"
    repo.get_sku_to_category_mapping.assert_not_called()


def test_result_helpers_build_existing_contract_shape():
    batch_id = uuid.uuid4()

    assert failure_result("bad") == {"success": False, "message": "bad"}
    assert success_result(batch_id, "file.xlsm", 1, 2, 3) == {
        "success": True,
        "batch_id": batch_id,
        "excel_file": "file.xlsm",
        "single_count": 1,
        "variation_count": 2,
        "total_rows": 3,
        "message": "成功生成 3 行数据",
    }


def test_build_listing_logs_adds_batch_id_to_single_and_variation_logs():
    batch_id = uuid.uuid4()
    logs = build_listing_logs(
        ["SKU1"],
        [{"meow_sku": "SKU2", "parent_sku": "PARENT"}],
        batch_id,
    )

    assert logs == [
        {
            "meow_sku": "SKU1",
            "parent_sku": "SINGLE_PRODUCT",
            "variation_attributes": {},
            "listing_batch_id": batch_id,
            "status": "GENERATED",
            "variation_theme": None,
        },
        {
            "meow_sku": "SKU2",
            "parent_sku": "PARENT",
            "listing_batch_id": batch_id,
        },
    ]
