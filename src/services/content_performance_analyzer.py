"""Content Performance Analyzer.

Evaluates the effectiveness of listing content changes:
  - A+ Content before/after CVR comparison
  - Bullet content A/B effect estimation
  - Listing version tracking
  - Content optimization recommendations

Phase 3 uses internal metrics (order data, session data).
Phase 3+ integrates with Brand Analytics and Manage Your Experiments.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContentVersion:
    """Snapshot of a listing's content at a point in time."""

    sku: str = ""
    asin: str = ""
    version_id: str = ""
    recorded_at: str = ""

    title: str = ""
    bullets: List[str] = field(default_factory=list)
    description: str = ""
    search_terms: str = ""
    generic_keyword: str = ""

    has_a_plus: bool = False
    a_plus_modules: int = 0
    image_count: int = 0
    video_count: int = 0

    # Performance data for this version
    sessions: int = 0
    orders: int = 0
    cvr: float = 0.0
    units_ordered: int = 0


@dataclass
class ContentPerformanceReport:
    """Analysis of listing content effectiveness."""

    asin: str = ""
    sku: str = ""
    versions: List[ContentVersion] = field(default_factory=list)

    cvr_trend: str = "STABLE"  # IMPROVING, DECLINING, STABLE
    recommendations: List[str] = field(default_factory=list)
    a_plus_impact: Optional[str] = None


class ContentPerformanceAnalyzer:
    """Analyzes how content changes affect listing performance."""

    def __init__(self):
        self._versions: Dict[str, List[ContentVersion]] = {}

    def record_version(
        self,
        sku: str,
        asin: str,
        title: str,
        bullets: List[str],
        description: str,
        search_terms: str = "",
        generic_keyword: str = "",
        has_a_plus: bool = False,
        a_plus_modules: int = 0,
        image_count: int = 0,
        video_count: int = 0,
    ) -> ContentVersion:
        """Record a content snapshot for future comparison."""
        version = ContentVersion(
            sku=sku,
            asin=asin,
            version_id=f"{asin}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            recorded_at=datetime.now().isoformat(),
            title=title,
            bullets=bullets,
            description=description,
            search_terms=search_terms,
            generic_keyword=generic_keyword,
            has_a_plus=has_a_plus,
            a_plus_modules=a_plus_modules,
            image_count=image_count,
            video_count=video_count,
        )
        if asin not in self._versions:
            self._versions[asin] = []
        self._versions[asin].append(version)
        return version

    def analyze(
        self,
        asin: str,
        sku: str = "",
        current_sessions: int = 0,
        current_orders: int = 0,
        current_units: int = 0,
    ) -> ContentPerformanceReport:
        """Compare current performance against previously recorded versions.

        Args:
            asin: Product ASIN.
            sku: Product SKU.
            current_sessions: Sessions in current period.
            current_orders: Orders in current period.
            current_units: Units ordered in current period.
        """
        report = ContentPerformanceReport(asin=asin, sku=sku)

        prev_versions = self._versions.get(asin, [])
        if not prev_versions:
            report.recommendations.append(
                "No previous content versions recorded. Record now as baseline."
            )
            # Record baseline
            self.record_version(
                sku=sku, asin=asin,
                title="", bullets=[], description="",
            )
            return report

        # Current CVR
        current_cvr = current_orders / current_sessions if current_sessions > 0 else 0

        # Compare with most recent previous version
        prev = prev_versions[-1]
        prev_cvr = prev.cvr

        if prev_cvr > 0:
            cvr_change = (current_cvr - prev_cvr) / prev_cvr
            if cvr_change > 0.05:
                report.cvr_trend = "IMPROVING"
                report.recommendations.append(
                    f"CVR 提升 {cvr_change:.1%} — 最近的 Listing 优化方向正确，继续保持"
                )
            elif cvr_change < -0.05:
                report.cvr_trend = "DECLINING"
                report.recommendations.append(
                    f"CVR 下降 {abs(cvr_change):.1%} — 检查是否最近的标题/图片/A+ 变更导致"
                )
                report.recommendations.append(
                    "建议：回滚到上一版本或检查竞品是否做了优化"
                )
            else:
                report.cvr_trend = "STABLE"

        # A+ impact analysis
        if current_cvr > 0 and len(prev_versions) >= 2:
            # Find version where A+ was first added
            a_plus_added_version = None
            for v in prev_versions:
                if v.has_a_plus:
                    a_plus_added_version = v
                    break
            if a_plus_added_version:
                # Simplified A+ analysis
                pre_a_plus = prev_versions[0]
                if pre_a_plus.cvr > 0 and not pre_a_plus.has_a_plus:
                    lift = (current_cvr - pre_a_plus.cvr) / pre_a_plus.cvr
                    report.a_plus_impact = f"A+ 内容上线后 CVR 变化: {lift:.1%}"
                    if lift > 0.05:
                        report.recommendations.append(
                            "A+ 内容效果积极，建议增加 Premium A+ 模块"
                        )

        # General content recommendations
        if current_cvr < 0.05 and current_sessions > 100:
            report.recommendations.append(
                "CVR 偏低（<5%），检查：标题是否准确传达价值、主图是否清晰、Bullets 是否量化卖点"
            )

        report.versions = prev_versions[-5:]  # return last 5 versions
        return report

    def compare_bullets(
        self,
        asin: str,
        old_bullets: List[str],
        new_bullets: List[str],
        old_cvr: float,
        new_cvr: float,
    ) -> Dict[str, Any]:
        """Simple A/B bullet comparison (for manual review)."""
        return {
            "asin": asin,
            "cvr_change": new_cvr - old_cvr,
            "cvr_change_pct": (new_cvr - old_cvr) / old_cvr if old_cvr > 0 else 0,
            "old_bullets": old_bullets,
            "new_bullets": new_bullets,
            "recommendation": (
                "Keep new bullets" if new_cvr > old_cvr else "Revert to old bullets"
            ),
        }
