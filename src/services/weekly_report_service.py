"""Weekly Report Service.

Aggregates data from all subsystems into a structured weekly report
for operational review.

Data sources:
  - KeywordRankingTracker: keyword position changes
  - CompetitiveIntelService: competitor price movements
  - DailyCheckService: listing issues and alerts
  - (Phase 3) Brand Analytics SQP: search query share changes
  - (Phase 3) Ads API: ad performance summary
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WeeklyReportSection:
    title: str = ""
    summary: str = ""
    details: List[str] = field(default_factory=list)
    status: str = "OK"  # OK, WARNING, CRITICAL
    recommendations: List[str] = field(default_factory=list)


@dataclass
class WeeklyReport:
    week_start: str = ""
    week_end: str = ""
    sections: List[WeeklyReportSection] = field(default_factory=list)
    top_actions: List[str] = field(default_factory=list)
    overall_status: str = "OK"


class WeeklyReportService:
    """Compiles weekly operational reports from all subsystems."""

    def __init__(self):
        self._week_start = ""
        self._week_end = ""

    def generate(
        self,
        ranking_data: Optional[Dict[str, Any]] = None,
        competitive_data: Optional[Dict[str, Any]] = None,
        listing_issue_summary: Optional[Dict[str, Any]] = None,
        ad_performance_summary: Optional[Dict[str, Any]] = None,
    ) -> WeeklyReport:
        """Generate a weekly report from available data.

        Args:
            ranking_data: Keyword ranking reports from KeywordRankingTracker.
            competitive_data: Competitive landscapes from CompetitiveIntelService.
            listing_issue_summary: Issue counts from DailyCheckService.
            ad_performance_summary: Ad metrics (Phase 3 placeholder).
        """
        now = datetime.now()
        self._week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        self._week_end = now.strftime("%Y-%m-%d")

        report = WeeklyReport(
            week_start=self._week_start,
            week_end=self._week_end,
        )

        # Section 1: Keyword Rankings
        report.sections.append(
            self._build_keyword_section(ranking_data)
        )

        # Section 2: Competitive Landscape
        report.sections.append(
            self._build_competitive_section(competitive_data)
        )

        # Section 3: Listing Health
        report.sections.append(
            self._build_listing_health_section(listing_issue_summary)
        )

        # Section 4: Ad Performance (placeholder for Phase 3)
        report.sections.append(
            self._build_ad_section(ad_performance_summary)
        )

        # Compile top actions
        report.top_actions = self._compile_top_actions(report.sections)

        # Overall status
        statuses = [s.status for s in report.sections]
        if "CRITICAL" in statuses:
            report.overall_status = "CRITICAL"
        elif "WARNING" in statuses:
            report.overall_status = "WARNING"
        else:
            report.overall_status = "OK"

        return report

    def to_feishu_sections(self, report: WeeklyReport) -> Dict[str, str]:
        """Convert report to Feishu-friendly section dict."""
        sections = {
            "周期": f"{report.week_start} → {report.week_end}",
            "整体状态": f"**{report.overall_status}**",
        }
        for sec in report.sections:
            details_str = "\n".join(f"  • {d}" for d in sec.details[:8])
            recs_str = ""
            if sec.recommendations:
                recs_str = "\n  📋 建议:\n" + "\n".join(f"    → {r}" for r in sec.recommendations[:3])
            sections[sec.title] = (
                f"[{sec.status}] {sec.summary}\n{details_str}{recs_str}"
            )
        sections["本周 Top Actions"] = "\n".join(
            f"{i+1}. {a}" for i, a in enumerate(report.top_actions[:5])
        )
        return sections

    # ── section builders ────────────────────────────────────────────

    def _build_keyword_section(self, data: Optional[Dict]) -> WeeklyReportSection:
        section = WeeklyReportSection(
            title="📈 关键词排名",
            summary="本周关键词排名追踪",
        )
        if not data:
            section.summary = "关键词排名数据暂不可用（等待 Phase 2 部署）"
            return section

        improved = data.get("improved_count", 0)
        declined = data.get("declined_count", 0)
        new_kw = data.get("new_count", 0)
        lost_kw = data.get("lost_count", 0)

        section.summary = (
            f"追踪 {data.get('total_tracked', 0)} 个关键词: "
            f"↑ {improved} 上升, ↓ {declined} 下降, "
            f"+ {new_kw} 新上榜, - {lost_kw} 下降出榜"
        )

        if data.get("top_improved"):
            section.details.append("Top 排名上升词: " + ", ".join(data["top_improved"][:5]))
        if data.get("top_declined"):
            section.details.append("Top 排名下降词: " + ", ".join(data["top_declined"][:5]))
            section.status = "WARNING"
            section.recommendations.append(
                "检查排名下降词的Listing页面和广告投放，竞品可能做了优化"
            )

        return section

    def _build_competitive_section(self, data: Optional[Dict]) -> WeeklyReportSection:
        section = WeeklyReportSection(
            title="🔍 竞品动态",
            summary="本周竞品价格与格局变化",
        )
        if not data:
            section.summary = "竞品数据暂不可用（等待 Product Pricing API 授权）"
            return section

        price_alerts = data.get("price_alerts", [])
        new_entrants = data.get("new_entrants", 0)
        score_distribution = data.get("score_distribution", {})

        section.summary = (
            f"监控 {data.get('total_monitored', 0)} 个ASIN: "
            f"价格变动告警 {len(price_alerts)}, 新进入者 {new_entrants}"
        )

        for alert in price_alerts[:5]:
            section.details.append(
                f"{alert.get('asin', '?')}: {alert.get('message', '')}"
            )

        if score_distribution:
            section.details.append(
                f"竞争力分布: S={score_distribution.get('S', 0)}, "
                f"A={score_distribution.get('A', 0)}, "
                f"B={score_distribution.get('B', 0)}, "
                f"C={score_distribution.get('C', 0)}"
            )

        if len(price_alerts) > 0:
            section.status = "WARNING"
            section.recommendations.append(
                f"{len(price_alerts)} 个竞品有价格变动，请检查是否需要调整定价"
            )

        return section

    def _build_listing_health_section(self, data: Optional[Dict]) -> WeeklyReportSection:
        section = WeeklyReportSection(
            title="✅ Listing 健康",
            summary="本周 Listing 问题汇总",
        )
        if not data:
            section.summary = "Listing 健康数据暂不可用"
            return section

        open_count = data.get("open_issues", 0)
        resolved_count = data.get("resolved_this_week", 0)
        new_count = data.get("new_this_week", 0)

        section.summary = (
            f"待处理: {open_count}, 本周新增: {new_count}, 本周解决: {resolved_count}"
        )

        if open_count > 0:
            section.status = "WARNING" if open_count < 5 else "CRITICAL"
            section.recommendations.append(
                f"还有 {open_count} 个 Listing 问题待处理，请优先修复严重问题"
            )

        return section

    def _build_ad_section(self, data: Optional[Dict]) -> WeeklyReportSection:
        section = WeeklyReportSection(
            title="📊 广告表现",
            summary="本周广告数据汇总",
        )
        if not data:
            section.summary = "广告数据暂不可用（等待 Phase 3 Ads API 集成）"
            return section

        spend = data.get("total_spend", 0)
        sales = data.get("attributed_sales", 0)
        acos = (spend / sales * 100) if sales > 0 else 0
        section.summary = (
            f"花费: ${spend:.0f}, 销售额: ${sales:.0f}, ACOS: {acos:.1f}%"
        )
        if acos > 30:
            section.status = "WARNING"
            section.recommendations.append(f"ACOS {acos:.1f}% 偏高，检查低效投放")
        return section

    @staticmethod
    def _compile_top_actions(sections: List[WeeklyReportSection]) -> List[str]:
        actions = []
        for s in sections:
            actions.extend(s.recommendations)
        return actions[:5] if actions else ["本周无需紧急操作，继续保持"]
