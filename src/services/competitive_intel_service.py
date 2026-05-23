"""Competitive Intelligence Service.

Collects competitor pricing, BSR, and seller density data,
then computes competitiveness scores and pricing recommendations.

Data sources:
  - Product Pricing API (competitive prices, offer counts)
  - Catalog Items API (BSR, title, brand)
  - Internal cost/pricing data (Giga + PricingService)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── output models ───────────────────────────────────────────────────


@dataclass
class CompetitorProfile:
    """Snapshot of a single competitor ASIN."""

    asin: str = ""
    title: str = ""
    brand: str = ""
    lowest_fba_price: Optional[float] = None
    buy_box_price: Optional[float] = None
    offer_count: int = 0
    fba_offer_count: int = 0
    bsr: Optional[int] = None
    bsr_category: str = ""
    is_our_asin: bool = False


@dataclass
class CompetitiveLandscape:
    """Aggregated view of competitive landscape for a target ASIN."""

    target_asin: str = ""
    target_sku: str = ""
    target_price: Optional[float] = None
    target_cost: Optional[float] = None
    snapshot_time: str = ""

    competitors: List[CompetitorProfile] = field(default_factory=list)
    our_position: Optional[CompetitorProfile] = None

    # Computed metrics
    price_percentile: Optional[float] = None  # where our price sits
    seller_density: int = 0
    median_bsr: Optional[int] = None

    # Recommendations
    suggested_price: Optional[float] = None
    estimated_margin_at_suggested: Optional[float] = None
    competitiveness_score: float = 0.0  # 0-100
    competitive_label: str = "UNKNOWN"  # S / A / B / C
    alerts: List[str] = field(default_factory=list)


# ── service ─────────────────────────────────────────────────────────


class CompetitiveIntelService:
    """Analyzes competitive landscape for products."""

    def __init__(
        self,
        pricing_client: Any = None,
        catalog_client: Any = None,
    ):
        self._pricing_client = pricing_client
        self._catalog_client = catalog_client

    # ── main API ────────────────────────────────────────────────────

    def analyze(
        self,
        target_asin: str,
        target_sku: str = "",
        target_price: Optional[float] = None,
        target_cost: Optional[float] = None,
        competitor_asins: Optional[List[str]] = None,
    ) -> CompetitiveLandscape:
        """Analyze competitive landscape for a target product.

        Args:
            target_asin: Our product's ASIN.
            target_sku: Our product's SKU.
            target_price: Our current selling price.
            target_cost: Our landed cost (product + shipping + FBA).
            competitor_asins: Known competitor ASINs (if None, uses
                              same-ASIN competitive pricing only).
        """
        landscape = CompetitiveLandscape(
            target_asin=target_asin,
            target_sku=target_sku,
            target_price=target_price,
            target_cost=target_cost,
            snapshot_time=datetime.now().isoformat(),
        )

        # 1. Get our own offer data (for same-ASIN competition)
        our_offer = self._get_our_offer(target_asin)
        if our_offer:
            landscape.our_position = our_offer

        # 2. Get same-ASIN competitor pricing
        same_asin_profiles = self._get_same_asin_competitors(target_asin)
        landscape.competitors.extend(same_asin_profiles)

        # 3. If competitor ASINs provided, get their data
        if competitor_asins:
            cross_asin_profiles = self._get_cross_asin_competitors(competitor_asins)
            landscape.competitors.extend(cross_asin_profiles)

        # 4. Compute competitiveness
        landscape.seller_density = sum(c.offer_count for c in landscape.competitors)
        landscape.median_bsr = self._compute_median_bsr(landscape.competitors)
        landscape.price_percentile = self._compute_price_percentile(
            target_price, landscape.competitors
        )
        landscape.competitiveness_score, landscape.competitive_label = (
            self._score_competitiveness(landscape)
        )

        # 5. Generate pricing recommendation
        landscape.suggested_price, landscape.estimated_margin_at_suggested = (
            self._suggest_price(landscape)
        )

        # 6. Generate alerts
        landscape.alerts = self._generate_alerts(landscape)

        return landscape

    def analyze_batch(
        self,
        products: List[Dict[str, Any]],
        competitor_asin_map: Optional[Dict[str, List[str]]] = None,
    ) -> Dict[str, CompetitiveLandscape]:
        """Batch analysis for multiple products.

        Args:
            products: List of dicts with asin, sku, price, cost keys.
            competitor_asin_map: Optional mapping of asin → competitor asins.

        Returns:
            Dict keyed by target ASIN.
        """
        results = {}
        for p in products:
            asin = p.get("asin", "")
            comps = (competitor_asin_map or {}).get(asin)
            try:
                results[asin] = self.analyze(
                    target_asin=asin,
                    target_sku=p.get("sku", ""),
                    target_price=p.get("price"),
                    target_cost=p.get("cost"),
                    competitor_asins=comps,
                )
            except Exception as exc:
                logger.error("Competitive analysis failed for %s: %s", asin, exc)
                results[asin] = CompetitiveLandscape(
                    target_asin=asin,
                    alerts=[f"Analysis failed: {exc}"],
                )
        return results

    # ── data collection ─────────────────────────────────────────────

    def _get_our_offer(self, asin: str) -> Optional[CompetitorProfile]:
        """Get our own offer details from the API."""
        pricing = self._get_pricing_client()
        if pricing is None:
            return None
        try:
            resp = pricing.get_item_offers(asin)
            buy_box = pricing.extract_buy_box_price(resp)
            lowest = pricing.extract_lowest_price(resp)
            count = pricing.extract_offer_count(resp)
            profile = CompetitorProfile(
                asin=asin,
                is_our_asin=True,
                offer_count=count,
                buy_box_price=(
                    float(buy_box.get("LandedPrice", {}).get("Amount", 0))
                    if buy_box else None
                ),
                lowest_fba_price=(
                    float(lowest.get("LandedPrice", {}).get("Amount", 0))
                    if lowest else None
                ),
            )
            return profile
        except Exception as exc:
            logger.warning("Could not get our offer for %s: %s", asin, exc)
            return None

    def _get_same_asin_competitors(self, asin: str) -> List[CompetitorProfile]:
        """Get competitors selling on the same ASIN."""
        pricing = self._get_pricing_client()
        if pricing is None:
            return []
        try:
            resp = pricing.get_competitive_pricing(asins=[asin])
            items = pricing.parse_competitive_result(resp)
            profiles = []
            for item in items:
                prices = item.get("competitive_prices", [])
                fba_prices = [p for p in prices if p.get("fulfillment_channel") == "Amazon"]
                fba_offer_count = len(fba_prices)
                lowest_fba = fba_prices[0] if fba_prices else (prices[0] if prices else None)
                sales_ranks = item.get("sales_rankings", [])
                bsr = sales_ranks[0].get("rank") if sales_ranks else None
                bsr_cat = sales_ranks[0].get("category") if sales_ranks else ""

                profiles.append(CompetitorProfile(
                    asin=item.get("asin", asin),
                    lowest_fba_price=(
                        float(lowest_fba.get("landed_price", 0))
                        if lowest_fba else None
                    ),
                    fba_offer_count=fba_offer_count,
                    bsr=bsr,
                    bsr_category=bsr_cat,
                ))
            return profiles
        except Exception as exc:
            logger.warning("getCompetitivePricing failed for %s: %s", asin, exc)
            return []

    def _get_cross_asin_competitors(
        self, asins: List[str]
    ) -> List[CompetitorProfile]:
        """Get competitor data for different ASINs in the same category."""
        catalog = self._get_catalog_client()
        if catalog is None or not asins:
            return []

        summaries = catalog.batch_get_summaries(asins)

        # Get pricing for these competitor ASINs
        pricing = self._get_pricing_client()
        profiles = []
        for asin in asins:
            summary = summaries.get(asin, {})
            profile = CompetitorProfile(
                asin=asin,
                title=summary.get("title", ""),
                brand=summary.get("brand", ""),
                bsr=summary.get("bsr"),
            )

            # Try to get pricing data
            if pricing:
                try:
                    resp = pricing.get_competitive_pricing(asins=[asin])
                    items = pricing.parse_competitive_result(resp)
                    if items:
                        prices = items[0].get("competitive_prices", [])
                        fba_prices = [p for p in prices
                                      if p.get("fulfillment_channel") == "Amazon"]
                        lowest = fba_prices[0] if fba_prices else (prices[0] if prices else None)
                        if lowest:
                            profile.lowest_fba_price = float(lowest.get("landed_price", 0))
                        profile.fba_offer_count = len(fba_prices)
                        profile.offer_count = len(prices)
                        ranks = items[0].get("sales_rankings", [])
                        profile.bsr = ranks[0].get("rank") if ranks else profile.bsr
                        profile.bsr_category = ranks[0].get("category") if ranks else ""
                except Exception:
                    pass

            profiles.append(profile)
        return profiles

    # ── computation ─────────────────────────────────────────────────

    def _compute_price_percentile(
        self,
        our_price: Optional[float],
        competitors: List[CompetitorProfile],
    ) -> Optional[float]:
        """Compute where our price sits among competitors (0 = cheapest, 100 = most expensive)."""
        prices = [
            c.lowest_fba_price for c in competitors
            if c.lowest_fba_price and c.lowest_fba_price > 0
        ]
        if not prices or our_price is None:
            return None
        prices.sort()
        rank = sum(1 for p in prices if p < our_price)
        return round(rank / len(prices) * 100, 1)

    @staticmethod
    def _compute_median_bsr(competitors: List[CompetitorProfile]) -> Optional[int]:
        """Compute median BSR across competitors."""
        bsrs = sorted(c.bsr for c in competitors if c.bsr)
        if not bsrs:
            return None
        mid = len(bsrs) // 2
        return bsrs[mid]

    def _score_competitiveness(
        self, landscape: CompetitiveLandscape
    ) -> Tuple[float, str]:
        """Compute 0-100 competitiveness score.

        Factors:
          - Price position (30%): optimal near 30-50th percentile
          - Seller density (20%): fewer sellers = better
          - Margin health (30%): higher margin = better
          - BSR signal (20%): lower BSR = stronger demand
        """
        score = 50.0  # neutral baseline

        # Price position: being slightly below median is ideal
        if landscape.price_percentile is not None:
            pp = landscape.price_percentile
            if 20 <= pp <= 50:
                score += 15  # well-positioned
            elif pp < 20:
                score += 5  # possibly leaving money on the table
            elif pp < 80:
                score -= 10  # more expensive than most
            else:
                score -= 20  # most expensive

        # Seller density
        sd = landscape.seller_density
        if sd < 3:
            score += 15  # very low competition
        elif sd < 10:
            score += 8  # manageable
        elif sd < 25:
            score -= 5  # getting crowded
        else:
            score -= 15  # highly competitive

        # Margin health
        if landscape.estimated_margin_at_suggested is not None:
            margin = landscape.estimated_margin_at_suggested
            if margin > 0.25:
                score += 15
            elif margin > 0.15:
                score += 8
            elif margin > 0.05:
                score += 0
            else:
                score -= 10

        # BSR signal
        if landscape.median_bsr is not None:
            bsr = landscape.median_bsr
            if bsr < 5000:
                score += 10  # strong demand
            elif bsr < 20000:
                score += 5
            elif bsr < 50000:
                score += 0
            else:
                score -= 5  # weak demand

        score = max(0, min(100, score))

        if score >= 75:
            label = "S (强势推荐)"
        elif score >= 60:
            label = "A (可投放)"
        elif score >= 40:
            label = "B (需调价)"
        else:
            label = "C (不建议)"

        return score, label

    def _suggest_price(
        self, landscape: CompetitiveLandscape
    ) -> Tuple[Optional[float], Optional[float]]:
        """Suggest optimal price based on competitive analysis."""
        target_price = landscape.target_price
        target_cost = landscape.target_cost

        # Find the lowest FBA competitor price
        comp_prices = [
            c.lowest_fba_price for c in landscape.competitors
            if c.lowest_fba_price and c.lowest_fba_price > 0
        ]
        if not comp_prices:
            return target_price, None

        comp_prices.sort()
        lowest_comp = comp_prices[0]
        median_comp = comp_prices[len(comp_prices) // 2]

        # Strategy: price at or slightly below the lowest competitor
        # if margin allows; otherwise at median
        if target_cost and lowest_comp:
            if lowest_comp <= target_cost * 1.05:
                # Can't compete on lowest — target median
                suggested = round(median_comp * 0.99, 2)
            else:
                # Price 1-2% below lowest competitor
                suggested = round(lowest_comp * 0.98, 2)
                suggested = max(suggested, target_cost * 1.15)  # ensure min 15% margin

            margin = (suggested - target_cost) / suggested if suggested > 0 else 0
            return suggested, round(margin, 3)

        return target_price, None

    def _generate_alerts(self, landscape: CompetitiveLandscape) -> List[str]:
        """Generate human-readable alerts from the analysis."""
        alerts = []

        if landscape.price_percentile is not None:
            pp = landscape.price_percentile
            if pp > 70:
                alerts.append(
                    f"价格偏高（高于{pp:.0f}%竞品），建议降价以提高竞争力"
                )
            elif pp < 5:
                alerts.append("价格已是市场最低，可考虑小幅提价以提升利润")

        if landscape.seller_density > 20:
            alerts.append(f"竞争激烈（{landscape.seller_density}个卖家），差异化Listing/A+是核心策略")

        if landscape.suggested_price and landscape.target_price:
            diff = landscape.suggested_price - landscape.target_price
            if abs(diff) > 1:
                direction = "降价" if diff < 0 else "提价"
                alerts.append(
                    f"建议{direction}至 ${landscape.suggested_price:.2f}（当前 ${landscape.target_price:.2f}）"
                )

        if landscape.estimated_margin_at_suggested is not None:
            m = landscape.estimated_margin_at_suggested
            if m < 0.05:
                alerts.append(f"⚠️ 建议价下毛利率仅 {m:.1%}，需重新评估成本或放弃此品类")
            elif m < 0.10:
                alerts.append(f"毛利率偏低（{m:.1%}），盈利空间有限")

        return alerts

    # ── lazy client access ──────────────────────────────────────────

    def _get_pricing_client(self):
        if self._pricing_client is not None:
            return self._pricing_client
        try:
            from infrastructure.amazon.pricing_client import AmazonPricingClient
            self._pricing_client = AmazonPricingClient()
            return self._pricing_client
        except Exception as exc:
            logger.warning("Could not create AmazonPricingClient: %s", exc)
            return None

    def _get_catalog_client(self):
        if self._catalog_client is not None:
            return self._catalog_client
        try:
            from infrastructure.amazon.catalog_client import AmazonCatalogClient
            self._catalog_client = AmazonCatalogClient()
            return self._catalog_client
        except Exception as exc:
            logger.warning("Could not create AmazonCatalogClient: %s", exc)
            return None
