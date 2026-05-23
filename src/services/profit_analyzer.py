"""Profit Analyzer.

Calculates per-unit profitability by combining:
  - Selling price (from Listings API / internal records)
  - COGS + shipping (from Giga pricing data)
  - FBA fees (from SP-API fee estimates or internal model)
  - Ad spend attribution (from Ads API search term report)
  - Refunds (from Finances API / Orders API)

Output: per-SKU profit snapshot with drill-down.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProfitBreakdown:
    """Detailed profit breakdown for a single SKU."""

    sku: str = ""
    asin: str = ""
    period_start: str = ""
    period_end: str = ""

    # Revenue
    selling_price: Decimal = Decimal("0")
    units_sold: int = 0
    total_revenue: Decimal = Decimal("0")

    # Costs
    landed_cost: Decimal = Decimal("0")  # COGS + shipping
    fba_fees: Decimal = Decimal("0")  # Pick&pack + weight handling
    fba_storage_fees: Decimal = Decimal("0")
    referral_fee: Decimal = Decimal("0")  # Amazon commission
    ad_spend: Decimal = Decimal("0")
    refund_cost: Decimal = Decimal("0")

    # Totals
    total_cost: Decimal = Decimal("0")
    gross_profit: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")
    margin: Decimal = Decimal("0")  # net profit / total revenue
    roi: Decimal = Decimal("0")  # (revenue - total_cost) / total_cost

    # Comparisons
    target_margin: Decimal = Decimal("0")
    margin_gap: Decimal = Decimal("0")  # actual - target


@dataclass
class ProfitReport:
    """Aggregated profit report for multiple SKUs."""

    period_start: str = ""
    period_end: str = ""
    sku_breakdowns: List[ProfitBreakdown] = field(default_factory=list)

    total_revenue: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    total_profit: Decimal = Decimal("0")
    overall_margin: Decimal = Decimal("0")

    top_profitable: List[ProfitBreakdown] = field(default_factory=list)
    bottom_profitable: List[ProfitBreakdown] = field(default_factory=list)


class ProfitAnalyzer:
    """Calculates per-unit and aggregate profitability."""

    # Amazon referral fee rate by category (simplified)
    _REFERRAL_RATES = {
        "CABINET": Decimal("0.15"),
        "HOME_MIRROR": Decimal("0.15"),
        "BATHTUB_SHOWER_TRIM_KIT": Decimal("0.15"),
        "default": Decimal("0.15"),
    }

    def __init__(self):
        pass

    def analyze_sku(
        self,
        sku: str,
        asin: str = "",
        selling_price: float = 0,
        units_sold: int = 0,
        landed_cost: float = 0,
        fba_fee_estimate: float = 0,
        ad_spend: float = 0,
        refund_amount: float = 0,
        period_start: str = "",
        period_end: str = "",
        category: str = "",
    ) -> ProfitBreakdown:
        """Calculate profit breakdown for a single SKU.

        This is the core calculation — all inputs should be gathered
        from upstream data sources before calling.
        """
        breakdown = ProfitBreakdown(
            sku=sku,
            asin=asin,
            period_start=period_start or (datetime.now().isoformat()),
            period_end=period_end or (datetime.now().isoformat()),
            selling_price=Decimal(str(selling_price)),
            units_sold=units_sold,
        )

        # Revenue
        breakdown.total_revenue = breakdown.selling_price * Decimal(str(units_sold))

        # Costs
        breakdown.landed_cost = Decimal(str(landed_cost)) * Decimal(str(units_sold))

        referral_rate = self._REFERRAL_RATES.get(category.upper(), self._REFERRAL_RATES["default"])
        breakdown.referral_fee = breakdown.total_revenue * referral_rate

        breakdown.fba_fees = Decimal(str(fba_fee_estimate)) * Decimal(str(units_sold))
        breakdown.ad_spend = Decimal(str(ad_spend))
        breakdown.refund_cost = Decimal(str(refund_amount))

        # Storage fee (simplified — use $0 unless FBA data available)
        breakdown.fba_storage_fees = Decimal("0")

        # Totals
        breakdown.total_cost = (
            breakdown.landed_cost
            + breakdown.fba_fees
            + breakdown.fba_storage_fees
            + breakdown.referral_fee
            + breakdown.ad_spend
            + breakdown.refund_cost
        )

        breakdown.gross_profit = breakdown.total_revenue - (
            breakdown.landed_cost + breakdown.fba_fees + breakdown.referral_fee
        )
        breakdown.net_profit = breakdown.total_revenue - breakdown.total_cost

        if breakdown.total_revenue > 0:
            breakdown.margin = breakdown.net_profit / breakdown.total_revenue
        if breakdown.total_cost > 0:
            breakdown.roi = breakdown.net_profit / breakdown.total_cost

        return breakdown

    def analyze_batch(
        self,
        sku_data: List[Dict[str, Any]],
        category: str = "",
    ) -> ProfitReport:
        """Analyze profitability for multiple SKUs.

        Args:
            sku_data: List of dicts with keys matching analyze_sku params.
            category: Product category for referral rate lookup.

        Returns:
            ProfitReport with all SKU breakdowns sorted by margin.
        """
        report = ProfitReport()

        for item in sku_data:
            breakdown = self.analyze_sku(
                sku=item.get("sku", ""),
                asin=item.get("asin", ""),
                selling_price=float(item.get("selling_price", 0)),
                units_sold=int(item.get("units_sold", 0)),
                landed_cost=float(item.get("landed_cost", 0)),
                fba_fee_estimate=float(item.get("fba_fee_estimate", 0)),
                ad_spend=float(item.get("ad_spend", 0)),
                refund_amount=float(item.get("refund_amount", 0)),
                period_start=item.get("period_start", ""),
                period_end=item.get("period_end", ""),
                category=category,
            )
            report.sku_breakdowns.append(breakdown)

        # Sort by margin descending
        report.sku_breakdowns.sort(key=lambda x: float(x.margin), reverse=True)

        # Totals
        report.total_revenue = sum((b.total_revenue for b in report.sku_breakdowns), Decimal("0"))
        report.total_cost = sum((b.total_cost for b in report.sku_breakdowns), Decimal("0"))
        report.total_profit = report.total_revenue - report.total_cost
        if report.total_revenue > 0:
            report.overall_margin = report.total_profit / report.total_revenue

        # Top/bottom
        profitable = [b for b in report.sku_breakdowns if b.units_sold > 0]
        report.top_profitable = profitable[:5]
        report.bottom_profitable = profitable[-5:] if len(profitable) > 5 else []

        return report

    def estimate_fba_fee(
        self,
        product_type: str,
        weight_lbs: float,
        longest_side_inches: float,
        is_oversize: bool = False,
    ) -> float:
        """Estimate FBA fulfillment fee (simplified US 2025 rates).

        This is a simplified model. For production use, integrate with
        SP-API Product Fees API for exact estimates.
        """
        if is_oversize:
            if weight_lbs <= 70:
                return 8.5 + weight_lbs * 0.40
            return 15.0 + (weight_lbs - 70) * 0.50

        # Standard-size tiers
        if weight_lbs <= 0.75 and longest_side_inches <= 15:
            return 3.25
        if weight_lbs <= 1.0:
            return 3.80
        if weight_lbs <= 2.0:
            return 4.50
        if weight_lbs <= 3.0:
            return 5.30
        return 5.30 + max(0, weight_lbs - 3.0) * 0.40
