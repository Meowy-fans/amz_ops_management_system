"""Unit tests for AmazonPackageDimensionsService."""
from unittest.mock import MagicMock

from src.services.amazon_package_dimensions_service import (
    AmazonPackageDimensionsService,
)


def _combo_info(*boxes):
    """Build a comboInfo list from (length, width, height, weight) tuples."""
    return [
        {"length": l, "width": w, "height": h, "weight": wt, "sku": f"SKU{i}", "qty": 1}
        for i, (l, w, h, wt) in enumerate(boxes, 1)
    ]


def test_builds_patches_for_missing_all_fields():
    patches = AmazonPackageDimensionsService._build_patches(
        combo_info=_combo_info(
            (50.4, 24.4, 6.7, 65.04),
            (52.36, 23.62, 14.17, 102.51),
        ),
        item={
            "need_pkg_dims": True,
            "need_pkg_wt": True,
            "need_pkg_qty": True,
            "need_num_items": True,
        },
    )
    assert len(patches) == 4

    pkg_dims = next(p for p in patches if p["path"] == "/attributes/item_package_dimensions")
    dims = pkg_dims["value"][0]
    assert dims["length"]["value"] == 52.36  # largest box by volume
    assert dims["length"]["unit"] == "inches"

    pkg_wt = next(p for p in patches if p["path"] == "/attributes/item_package_weight")
    assert pkg_wt["value"][0]["value"] == 167.55  # sum of both

    pkg_qty = next(p for p in patches if p["path"] == "/attributes/item_package_quantity")
    assert pkg_qty["value"][0]["value"] == 2

    num_items = next(p for p in patches if p["path"] == "/attributes/number_of_items")
    assert num_items["value"][0]["value"] == 1


def test_builds_only_missing_fields():
    patches = AmazonPackageDimensionsService._build_patches(
        combo_info=_combo_info((50.0, 20.0, 10.0, 50.0)),
        item={
            "need_pkg_dims": True,
            "need_pkg_wt": False,
            "need_pkg_qty": False,
            "need_num_items": False,
        },
    )
    assert len(patches) == 1
    assert patches[0]["path"] == "/attributes/item_package_dimensions"


def test_single_box_uses_itself():
    patches = AmazonPackageDimensionsService._build_patches(
        combo_info=_combo_info((30.0, 20.0, 10.0, 40.0)),
        item={
            "need_pkg_dims": True,
            "need_pkg_wt": True,
            "need_pkg_qty": True,
            "need_num_items": True,
        },
    )
    pkg_dims = next(p for p in patches if p["path"] == "/attributes/item_package_dimensions")
    assert pkg_dims["value"][0]["length"]["value"] == 30.0

    pkg_qty = next(p for p in patches if p["path"] == "/attributes/item_package_quantity")
    assert pkg_qty["value"][0]["value"] == 1


def test_three_boxes_picks_largest_volume():
    patches = AmazonPackageDimensionsService._build_patches(
        combo_info=_combo_info(
            (10.0, 10.0, 10.0, 5.0),  # vol=1000
            (20.0, 20.0, 20.0, 10.0),  # vol=8000 ← largest
            (15.0, 10.0, 5.0, 3.0),  # vol=750
        ),
        item={
            "need_pkg_dims": True,
            "need_pkg_wt": True,
            "need_pkg_qty": True,
            "need_num_items": True,
        },
    )
    pkg_dims = next(p for p in patches if p["path"] == "/attributes/item_package_dimensions")
    assert pkg_dims["value"][0]["length"]["value"] == 20.0
    assert pkg_dims["value"][0]["width"]["value"] == 20.0

    pkg_qty = next(p for p in patches if p["path"] == "/attributes/item_package_quantity")
    assert pkg_qty["value"][0]["value"] == 3


def test_dry_run_records_submission():
    repo = MagicMock()
    repo.insert_submission = MagicMock(return_value=1)
    service = AmazonPackageDimensionsService(
        db=MagicMock(),
        submission_repo=repo,
        listings_client=MagicMock(),
    )
    service._get_combo_candidates = MagicMock(return_value=[
        {
            "meow_sku": "SKU1",
            "combo_info": [{"length": 30, "width": 20, "height": 10, "weight": 40, "sku": "S1", "qty": 1}],
            "product_type": "CABINET",
            "need_pkg_dims": True,
            "need_pkg_wt": True,
            "need_pkg_qty": True,
            "need_num_items": True,
        }
    ])

    results = service.submit_package_dimensions(dry_run=True)
    assert len(results) == 1
    assert results[0]["status"] == "dry_run"
    repo.insert_submission.assert_called_once()
    call_args = repo.insert_submission.call_args[1]
    assert call_args["status"] == "dry_run"
    assert call_args["operation"] == "package_dimensions"
