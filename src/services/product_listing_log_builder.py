"""Listing log payload helpers."""
import logging
import uuid
from typing import Dict, List

logger = logging.getLogger(__name__)


def build_listing_logs(
    single_skus: List[str],
    variation_logs: List[Dict],
    batch_id: uuid.UUID,
) -> List[Dict]:
    """Build listing-log rows for single products and variations."""
    all_logs = []

    for sku in single_skus:
        all_logs.append({
            "meow_sku": sku,
            "parent_sku": "SINGLE_PRODUCT",
            "variation_attributes": {},
            "listing_batch_id": batch_id,
            "status": "GENERATED",
            "variation_theme": None,
        })

    for log in variation_logs:
        log["listing_batch_id"] = batch_id
        all_logs.append(log)

    return all_logs
