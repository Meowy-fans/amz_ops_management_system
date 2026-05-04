"""Flow helpers for product listing generation."""
import logging
import uuid
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def failure_result(message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "message": message,
    }


def success_result(
    batch_id: uuid.UUID,
    excel_file: str,
    single_count: int,
    variation_count: int,
    total_rows: int,
) -> Dict[str, Any]:
    return {
        "success": True,
        "batch_id": batch_id,
        "excel_file": excel_file,
        "single_count": single_count,
        "variation_count": variation_count,
        "total_rows": total_rows,
        "message": f"成功生成 {total_rows} 行数据",
    }


def get_pending_skus_for_category(
    product_listing_repo,
    category_name: str,
) -> Tuple[List[str], str | None]:
    """Fetch pending SKUs and filter them by target category."""
    logger.info("步骤1: 获取所有待发品SKU...")
    all_pending_skus = product_listing_repo.get_pending_listing_skus()

    if not all_pending_skus:
        return [], "没有待发品SKU"

    logger.info(f"  找到 {len(all_pending_skus)} 个待发品SKU")

    logger.info("步骤2: 获取SKU品类映射...")
    sku_category_mapping = product_listing_repo.get_sku_to_category_mapping(
        all_pending_skus
    )

    logger.info(f"步骤3: 过滤品类 '{category_name}'...")
    pending_skus = [
        sku for sku, category in sku_category_mapping
        if category and category.upper() == category_name.upper()
    ]

    if not pending_skus:
        return [], f"品类 '{category_name}' 没有待发品SKU"

    logger.info(f"  品类 '{category_name}' 有 {len(pending_skus)} 个待发品SKU")
    return pending_skus, None
