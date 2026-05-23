"""Inventory Planner.

Monitors inventory health, computes replenishment triggers,
and flags excess inventory for liquidation.

Data sources:
  - giga_inventory: current stock from GigaCloud
  - amz_all_listing_report: active listing status
  - (Phase 3+) SP-API FBA Inventory API: FBA stock levels, inbound shipments
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class InventoryItem:
    """Single SKU inventory status."""

    sku: str = ""
    asin: str = ""
    product_name: str = ""
    current_stock: int = 0
    fba_stock: int = 0
    reserved_stock: int = 0
    available_stock: int = 0

    # Sales velocity
    units_sold_7d: int = 0
    units_sold_30d: int = 0
    daily_velocity: float = 0.0

    # Health indicators
    days_of_stock: float = 0.0  # current_stock / daily_velocity
    stock_status: str = "HEALTHY"  # HEALTHY, LOW, CRITICAL, EXCESS, STALE
    needs_replenishment: bool = False
    recommended_order_qty: int = 0
    days_until_stockout: float = 0.0


@dataclass
class InventoryReport:
    """Aggregated inventory health report."""

    report_date: str = ""
    total_skus: int = 0
    healthy_skus: int = 0
    low_stock_skus: int = 0
    critical_stock_skus: int = 0
    excess_stock_skus: int = 0
    stale_stock_skus: int = 0

    items_needing_action: List[InventoryItem] = field(default_factory=list)
    replenishment_plan: List[Dict[str, Any]] = field(default_factory=list)
    liquidation_suggestions: List[str] = field(default_factory=list)


class InventoryPlanner:
    """Analyzes inventory health and generates replenishment plans."""

    # Thresholds
    DAYS_LOW = 14  # days of stock below this = LOW
    DAYS_CRITICAL = 7  # days of stock below this = CRITICAL
    DAYS_EXCESS = 120  # days of stock above this = EXCESS
    DAYS_STALE = 180  # days of stock above this = STALE (risk long-term storage fee)
    TARGET_DAYS = 45  # target days of inventory

    def __init__(self):
        pass

    def analyze(
        self,
        inventory_items: List[Dict[str, Any]],
    ) -> InventoryReport:
        """Analyze inventory health for a set of products.

        Args:
            inventory_items: List of dicts with keys:
                sku, asin, product_name, current_stock, fba_stock,
                units_sold_7d, units_sold_30d
        """
        report = InventoryReport(
            report_date=datetime.now().strftime("%Y-%m-%d"),
            total_skus=len(inventory_items),
        )

        items = []
        for item_data in inventory_items:
            item = self._analyze_item(item_data)
            items.append(item)

            if item.stock_status == "LOW":
                report.low_stock_skus += 1
            elif item.stock_status == "CRITICAL":
                report.critical_stock_skus += 1
            elif item.stock_status == "EXCESS":
                report.excess_stock_skus += 1
            elif item.stock_status == "STALE":
                report.stale_stock_skus += 1
                report.liquidation_suggestions.append(
                    f"{item.sku} ({item.product_name[:40]}): "
                    f"{item.days_of_stock:.0f} 天库存, "
                    f"建议创建 Coupon 促销或移除订单"
                )
            else:
                report.healthy_skus += 1

            if item.needs_replenishment:
                report.items_needing_action.append(item)
                report.replenishment_plan.append({
                    "sku": item.sku,
                    "asin": item.asin,
                    "product_name": item.product_name,
                    "current_stock": item.current_stock,
                    "daily_velocity": round(item.daily_velocity, 1),
                    "days_until_stockout": round(item.days_until_stockout, 1),
                    "recommended_order_qty": item.recommended_order_qty,
                    "urgency": item.stock_status,
                })

        # Sort replenishment by urgency (CRITICAL first)
        report.replenishment_plan.sort(key=lambda x: x["days_until_stockout"])

        logger.info(
            "Inventory report: %d total, %d healthy, %d low, %d critical, %d excess",
            report.total_skus,
            report.healthy_skus,
            report.low_stock_skus,
            report.critical_stock_skus,
            report.excess_stock_skus,
        )

        return report

    def _analyze_item(self, data: Dict[str, Any]) -> InventoryItem:
        """Analyze a single inventory item."""
        item = InventoryItem(
            sku=data.get("sku", ""),
            asin=data.get("asin", ""),
            product_name=data.get("product_name", ""),
            current_stock=int(data.get("current_stock", 0)),
            fba_stock=int(data.get("fba_stock", 0)),
            reserved_stock=int(data.get("reserved_stock", 0)),
            units_sold_7d=int(data.get("units_sold_7d", 0)),
            units_sold_30d=int(data.get("units_sold_30d", 0)),
        )

        item.available_stock = item.current_stock + item.fba_stock - item.reserved_stock

        # Daily velocity (use 30d for stability, fall back to 7d)
        if item.units_sold_30d > 0:
            item.daily_velocity = item.units_sold_30d / 30.0
        elif item.units_sold_7d > 0:
            item.daily_velocity = item.units_sold_7d / 7.0
        else:
            item.daily_velocity = 0.05  # assume very slow-moving

        # Days of stock
        if item.daily_velocity > 0:
            item.days_of_stock = item.available_stock / item.daily_velocity
            item.days_until_stockout = item.days_of_stock
        else:
            item.days_of_stock = 999
            item.days_until_stockout = 999

        # Classification
        if item.days_of_stock <= self.DAYS_CRITICAL:
            item.stock_status = "CRITICAL"
            item.needs_replenishment = True
        elif item.days_of_stock <= self.DAYS_LOW:
            item.stock_status = "LOW"
            item.needs_replenishment = True
        elif item.days_of_stock >= self.DAYS_STALE:
            item.stock_status = "STALE"
        elif item.days_of_stock >= self.DAYS_EXCESS:
            item.stock_status = "EXCESS"
        else:
            item.stock_status = "HEALTHY"

        # Replenishment recommendation
        if item.needs_replenishment and item.daily_velocity > 0:
            target_stock = item.daily_velocity * self.TARGET_DAYS
            item.recommended_order_qty = max(1, int(target_stock - item.available_stock))

        return item

    def generate_liquidation_strategy(
        self,
        report: InventoryReport,
    ) -> List[Dict[str, str]]:
        """Generate liquidation strategies for stale/excess inventory."""
        strategies = []
        for suggestion in report.liquidation_suggestions:
            strategies.append({
                "action": "CREATE_COUPON",
                "description": suggestion,
                "priority": "HIGH" if "STALE" in suggestion else "MEDIUM",
            })
        return strategies
