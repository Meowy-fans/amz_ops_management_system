"""Product Lifecycle State Machine.

Tracks each product through its lifecycle:
  SELECTED → PREPARING → LAUNCHED → GROWING → MATURE → DECLINING

Each state defines:
  - Entry criteria (automatic or manual transition triggers)
  - Recommended actions (checklist for operations)
  - Anomaly detection rules (what signals trouble)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class LifecycleStage(str, Enum):
    SELECTED = "SELECTED"  # Chosen from supplier catalog
    PREPARING = "PREPARING"  # Keyword research, content, images ready
    LAUNCHED = "LAUNCHED"  # SP-API submitted, listing active
    GROWING = "GROWING"  # First sale, actively scaling
    MATURE = "MATURE"  # Stable sales, optimizing profit
    DECLINING = "DECLINING"  # Falling sales, competition eroding margins


STAGE_LABELS = {
    LifecycleStage.SELECTED: "选品期",
    LifecycleStage.PREPARING: "准备期",
    LifecycleStage.LAUNCHED: "上线期",
    LifecycleStage.GROWING: "成长期",
    LifecycleStage.MATURE: "成熟期",
    LifecycleStage.DECLINING: "衰退期",
}

STAGE_TRANSITIONS: Dict[LifecycleStage, List[LifecycleStage]] = {
    LifecycleStage.SELECTED: [LifecycleStage.PREPARING],
    LifecycleStage.PREPARING: [LifecycleStage.LAUNCHED, LifecycleStage.SELECTED],
    LifecycleStage.LAUNCHED: [LifecycleStage.GROWING],
    LifecycleStage.GROWING: [LifecycleStage.MATURE],
    LifecycleStage.MATURE: [LifecycleStage.DECLINING, LifecycleStage.GROWING],
    LifecycleStage.DECLINING: [LifecycleStage.MATURE],
}

# ── tasks per stage ──────────────────────────────────────────────────

STAGE_TASK_CHECKLISTS: Dict[LifecycleStage, List[Dict[str, str]]] = {
    LifecycleStage.SELECTED: [
        {"action": "competitive_analysis", "label": "竞品分析（价格+BSR+卖家密度）", "auto": True},
        {"action": "profit_estimate", "label": "毛利预估（成本+FBA费 vs 竞品价）", "auto": True},
        {"action": "manual_review", "label": "人工审核选品", "auto": False},
    ],
    LifecycleStage.PREPARING: [
        {"action": "keyword_research", "label": "关键词研究+分层", "auto": True},
        {"action": "generate_content", "label": "生成 Listing 内容（标题+5点+描述）", "auto": True},
        {"action": "cosmo_attributes", "label": "填充 COSMO 后台属性", "auto": True},
        {"action": "image_brief", "label": "生成图片拍摄 Brief", "auto": True},
        {"action": "pricing_strategy", "label": "确定定价策略", "auto": False},
        {"action": "a_plus_content", "label": "准备 A+ 内容", "auto": False},
    ],
    LifecycleStage.LAUNCHED: [
        {"action": "submit_listing", "label": "SP-API 提交 Listing", "auto": True},
        {"action": "launch_ppc", "label": "创建初始广告 Campaign", "auto": True},
        {"action": "vine_enrollment", "label": "Vine 计划注册提醒", "auto": False},
        {"action": "verify_active", "label": "验证 Listing 激活成功", "auto": True},
    ],
    LifecycleStage.GROWING: [
        {"action": "daily_check", "label": "每日巡检", "auto": True},
        {"action": "keyword_tracking", "label": "每周关键词排名追踪", "auto": True},
        {"action": "ppc_optimization", "label": "每周广告优化（收割+否定）", "auto": True},
        {"action": "competitor_monitoring", "label": "竞品价格监控", "auto": True},
        {"action": "review_analysis", "label": "评论情感分析", "auto": True},
        {"action": "inventory_check", "label": "库存健康检查", "auto": True},
        {"action": "profit_analysis", "label": "月度利润核算", "auto": True},
    ],
    LifecycleStage.MATURE: [
        {"action": "price_elasticity_test", "label": "价格弹性测试（小幅提价2-3%）", "auto": False},
        {"action": "acos_optimization", "label": "广告效率优化（降低ACOS）", "auto": True},
        {"action": "competitor_defense", "label": "竞品防御（跟卖/低价检测）", "auto": True},
        {"action": "variation_expansion", "label": "变体拓展评估", "auto": False},
        {"action": "product_improvement", "label": "产品改进信号收集（评论反馈）", "auto": True},
        {"action": "inventory_efficiency", "label": "库存周转效率优化", "auto": True},
    ],
    LifecycleStage.DECLINING: [
        {"action": "liquidation_coupon", "label": "创建清货Coupon/促销", "auto": True},
        {"action": "removal_order", "label": "移除订单评估", "auto": False},
        {"action": "replacement_plan", "label": "替代品推荐（供应商新品）", "auto": True},
        {"action": "exit_decision", "label": "退出/保留决策", "auto": False},
    ],
}


@dataclass
class ProductLifecycleState:
    """Current lifecycle state of a product."""

    sku: str = ""
    asin: str = ""
    stage: LifecycleStage = LifecycleStage.SELECTED
    entered_stage_at: str = ""
    last_stage_change: str = ""

    # Metrics that drive stage transitions
    days_in_stage: int = 0
    weekly_sales_units: int = 0
    weekly_sales_trend: str = "STABLE"  # UP, DOWN, STABLE
    bsr_trend: str = "STABLE"
    acos: float = 0.0
    margin: float = 0.0

    # Checklist
    completed_tasks: List[str] = field(default_factory=list)
    pending_tasks: List[str] = field(default_factory=list)


class ProductLifecycleManager:
    """Manages product lifecycle states and transitions.

    Integrates with all Phase 1-3 services to drive automated
    action execution at each lifecycle stage.
    """

    def __init__(self):
        self._products: Dict[str, ProductLifecycleState] = {}

    # ── registration ─────────────────────────────────────────────────

    def register(
        self,
        sku: str,
        asin: str = "",
        stage: LifecycleStage = LifecycleStage.SELECTED,
    ) -> ProductLifecycleState:
        """Register a product in the lifecycle manager."""
        now = datetime.now().isoformat()
        state = ProductLifecycleState(
            sku=sku,
            asin=asin,
            stage=stage,
            entered_stage_at=now,
            last_stage_change=now,
        )
        state.pending_tasks = self._get_tasks_for_stage(stage)
        self._products[sku] = state
        logger.info("Product %s registered at stage %s", sku, stage.value)
        return state

    def get_state(self, sku: str) -> Optional[ProductLifecycleState]:
        """Get current lifecycle state for a product."""
        return self._products.get(sku)

    def list_by_stage(self, stage: LifecycleStage) -> List[ProductLifecycleState]:
        """List all products in a given lifecycle stage."""
        return [p for p in self._products.values() if p.stage == stage]

    # ── transitions ──────────────────────────────────────────────────

    def transition(self, sku: str, target_stage: LifecycleStage) -> bool:
        """Attempt to move a product to a new lifecycle stage.

        Validates the transition is allowed and records the change.
        """
        state = self._products.get(sku)
        if state is None:
            logger.warning("Product %s not registered", sku)
            return False

        if target_stage not in STAGE_TRANSITIONS.get(state.stage, []):
            logger.warning(
                "Invalid transition: %s → %s (allowed: %s)",
                state.stage.value,
                target_stage.value,
                [s.value for s in STAGE_TRANSITIONS.get(state.stage, [])],
            )
            return False

        now = datetime.now().isoformat()
        old_stage = state.stage
        state.stage = target_stage
        state.days_in_stage = 0
        state.entered_stage_at = now
        state.last_stage_change = now
        state.pending_tasks = self._get_tasks_for_stage(target_stage)
        state.completed_tasks = []

        logger.info(
            "Product %s: %s → %s", sku, old_stage.value, target_stage.value
        )
        return True

    def evaluate_auto_transitions(
        self,
        sku: str,
        weekly_sales: int = 0,
        bsr: Optional[int] = None,
        acos: float = 0.0,
        margin: float = 0.0,
    ) -> Optional[LifecycleStage]:
        """Evaluate whether a product qualifies for automatic stage transition.

        Returns the target stage if a transition is recommended, else None.
        """
        state = self._products.get(sku)
        if state is None:
            return None

        # Update metrics
        state.weekly_sales_units = weekly_sales
        state.acos = acos
        state.margin = margin
        state.days_in_stage = getattr(state, "days_in_stage", 0)

        # Thresholds
        WEEKS_FOR_GROWING_TO_MATURE = 4  # stable for 4 weeks = mature
        WEEKS_FOR_MATURE_TO_DECLINING = 4  # declining for 4 weeks = declining

        if state.stage == LifecycleStage.LAUNCHED:
            # Move to GROWING after first meaningful sale
            if weekly_sales >= 3:
                return LifecycleStage.GROWING

        elif state.stage == LifecycleStage.GROWING:
            # Move to MATURE after sustained stable sales + healthy ACOS
            if weekly_sales >= 10 and acos <= 0.25 and margin >= 0.10:
                return LifecycleStage.MATURE

        elif state.stage == LifecycleStage.MATURE:
            # Move to DECLINING after sustained decline
            if weekly_sales == 0 and state.days_in_stage > 28:
                return LifecycleStage.DECLINING

        return None

    # ── task management ──────────────────────────────────────────────

    def get_checklist(self, sku: str) -> List[Dict[str, str]]:
        """Get current stage task checklist with completion status."""
        state = self._products.get(sku)
        if state is None:
            return []
        return STAGE_TASK_CHECKLISTS.get(state.stage, [])

    def complete_task(self, sku: str, task_action: str) -> bool:
        """Mark a task as completed for a product."""
        state = self._products.get(sku)
        if state is None:
            return False
        if task_action in state.pending_tasks:
            state.pending_tasks.remove(task_action)
            state.completed_tasks.append(task_action)
            return True
        return False

    def get_auto_tasks(self, sku: str) -> List[str]:
        """Get automated tasks for a product's current stage."""
        checklist = self.get_checklist(sku)
        return [t["action"] for t in checklist if t.get("auto") and t["action"] not in (self._products.get(sku, ProductLifecycleState()).completed_tasks)]

    def get_manual_tasks(self, sku: str) -> List[str]:
        """Get manual (human-required) tasks for a product's current stage."""
        checklist = self.get_checklist(sku)
        state = self._products.get(sku)
        completed = state.completed_tasks if state else []
        return [t["label"] for t in checklist if not t.get("auto") and t["action"] not in completed]

    @staticmethod
    def _get_tasks_for_stage(stage: LifecycleStage) -> List[str]:
        """Get task action names for a stage."""
        return [t["action"] for t in STAGE_TASK_CHECKLISTS.get(stage, [])]

    # ── reporting ────────────────────────────────────────────────────

    def get_lifecycle_summary(self) -> Dict[str, int]:
        """Get product count per lifecycle stage."""
        summary: Dict[str, int] = {}
        for stage in LifecycleStage:
            summary[stage.value] = len(self.list_by_stage(stage))
        return summary

    def get_stage_recommendations(self, stage: LifecycleStage) -> Dict[str, Any]:
        """Get operational recommendations for a lifecycle stage."""
        return {
            "stage": stage.value,
            "label": STAGE_LABELS.get(stage, stage.value),
            "product_count": len(self.list_by_stage(stage)),
            "tasks": STAGE_TASK_CHECKLISTS.get(stage, []),
            "key_focus": _STAGE_FOCUS.get(stage, ""),
        }


_STAGE_FOCUS = {
    LifecycleStage.SELECTED: "选品决策：找竞争低、利润高的品类机会",
    LifecycleStage.PREPARING: "上架准备：关键词→Listing内容→图片→定价",
    LifecycleStage.LAUNCHED: "冷启动：SP-API提交→初始广告→Vine→验证激活",
    LifecycleStage.GROWING: "增长放大：收割关键词→优化ACOS→监控竞品→积累评论",
    LifecycleStage.MATURE: "利润优化：提价测试→品牌词防守→变体拓展→提效降本",
    LifecycleStage.DECLINING: "清退出局：Coupon/移除→替代品选品→退出决策",
}
