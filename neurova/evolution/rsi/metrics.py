"""
RSI 监控指标管理器

为 RSI 提供可观测性，人类需要能够理解和审计每层递归的改进
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class AlertLevel(Enum):
    """告警级别"""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class Alert:
    """告警"""

    level: AlertLevel
    metric: str
    message: str
    value: float
    threshold: float


class RSIMetrics:
    """RSI 监控指标管理器"""

    # 7 个核心指标
    RSI_CYCLES_TOTAL = "rsi_cycles_total"
    RSI_IMPROVEMENT_RATE = "rsi_improvement_rate"
    RSI_CONVERGENCE_ROI = "rsi_convergence_roi"
    RSI_ROLLBACK_COUNT = "rsi_rollback_count"
    RSI_CANDIDATES_GENERATED = "rsi_candidates_generated"
    RSI_CANDIDATES_PRUNED = "rsi_candidates_pruned"
    RSI_GATE_FAILURES = "rsi_gate_failures"

    # 经验族指标（工单 008）：让"经验质量"从自我声明变成可告警读数。
    # 写入方 = RSIOrchestrator._refresh_experience_metrics（每轮迭代刷新）
    EXPERIENCE_ROWS = "experience_rows"
    EXPERIENCE_UNEVIDENCED_RATIO = "experience_unevidenced_ratio"
    EXPERIENCE_HIT_RATE = "experience_hit_rate"
    EXPERIENCE_ADOPTION_SUCCESS_RATE = "experience_adoption_success_rate"
    EXPERIENCE_ADOPTION_DECISIONS = "experience_adoption_decisions"

    # 告警阈值
    ALERT_THRESHOLDS = {
        "roi_warning": 0.1,
        "roi_critical": 0.0,
        "gate_failures_error": 3,
        # 经验族：过半条目没有客观回执 = 质量位不携带信息，必须出声（002 的病根）
        "experience_unevidenced_ratio_warning": 0.5,
        # 采纳后成功率低于此值说明"照经验做"整体在帮倒忙
        "experience_adoption_success_rate_warning": 0.5,
        # 少于此决策数不下结论：一次成败是噪声，不是趋势
        "experience_adoption_min_decisions": 2,
    }

    def __init__(self):
        """初始化 RSI 监控指标管理器"""
        self._metrics: Dict[str, float] = {}

        # 初始化所有指标为 0
        self._metrics[self.RSI_CYCLES_TOTAL] = 0
        self._metrics[self.RSI_IMPROVEMENT_RATE] = 0
        self._metrics[self.RSI_CONVERGENCE_ROI] = 0
        self._metrics[self.RSI_ROLLBACK_COUNT] = 0
        self._metrics[self.RSI_CANDIDATES_GENERATED] = 0
        self._metrics[self.RSI_CANDIDATES_PRUNED] = 0
        self._metrics[self.RSI_GATE_FAILURES] = 0
        self._metrics[self.EXPERIENCE_ROWS] = 0
        self._metrics[self.EXPERIENCE_UNEVIDENCED_RATIO] = 0.0
        self._metrics[self.EXPERIENCE_HIT_RATE] = 0.0
        self._metrics[self.EXPERIENCE_ADOPTION_SUCCESS_RATE] = 0.0
        self._metrics[self.EXPERIENCE_ADOPTION_DECISIONS] = 0

        logger.info("RSIMetrics initialized")

    def record_metric(self, metric_name: str, value: float) -> None:
        """
        记录指标

        Args:
            metric_name: 指标名称
            value: 指标值
        """
        self._metrics[metric_name] = value
        logger.debug("Recorded metric: %s = %s", metric_name, value)

    def get_metric(self, metric_name: str) -> Optional[float]:
        """
        获取指标值

        Args:
            metric_name: 指标名称

        Returns:
            Optional[float]: 指标值，如果不存在返回 None
        """
        return self._metrics.get(metric_name)

    def check_alerts(self) -> List[Alert]:
        """
        检查告警规则

        Returns:
            List[Alert]: 触发的告警列表
        """
        alerts = []

        # INFO: RSI 循环完成
        cycles = self._metrics.get(self.RSI_CYCLES_TOTAL, 0)
        if cycles > 0:
            alerts.append(
                Alert(
                    level=AlertLevel.INFO,
                    metric=self.RSI_CYCLES_TOTAL,
                    message=f"RSI 循环完成 {cycles} 次",
                    value=cycles,
                    threshold=0,
                )
            )

        # WARNING: ROI 低于阈值
        roi = self._metrics.get(self.RSI_CONVERGENCE_ROI, 0)
        if 0 < roi < self.ALERT_THRESHOLDS["roi_warning"]:
            alerts.append(
                Alert(
                    level=AlertLevel.WARNING,
                    metric=self.RSI_CONVERGENCE_ROI,
                    message=f"ROI 低于阈值: {roi:.2f} < {self.ALERT_THRESHOLDS['roi_warning']}",
                    value=roi,
                    threshold=self.ALERT_THRESHOLDS["roi_warning"],
                )
            )

        # ERROR: 连续失败
        gate_failures = self._metrics.get(self.RSI_GATE_FAILURES, 0)
        if gate_failures >= self.ALERT_THRESHOLDS["gate_failures_error"]:
            alerts.append(
                Alert(
                    level=AlertLevel.ERROR,
                    metric=self.RSI_GATE_FAILURES,
                    message=f"连续失败 {gate_failures} 次",
                    value=gate_failures,
                    threshold=self.ALERT_THRESHOLDS["gate_failures_error"],
                )
            )

        # CRITICAL: 发散检测（负 ROI）
        if roi < self.ALERT_THRESHOLDS["roi_critical"]:
            alerts.append(
                Alert(
                    level=AlertLevel.CRITICAL,
                    metric=self.RSI_CONVERGENCE_ROI,
                    message=f"检测到发散: ROI = {roi:.2f}",
                    value=roi,
                    threshold=self.ALERT_THRESHOLDS["roi_critical"],
                )
            )

        # 经验族告警（工单 008）——两条都必须先看样本量，没数据不下结论
        exp_rows = self._metrics.get(self.EXPERIENCE_ROWS, 0)
        unevidenced_ratio = self._metrics.get(self.EXPERIENCE_UNEVIDENCED_RATIO, 0.0)
        _ratio_threshold = self.ALERT_THRESHOLDS["experience_unevidenced_ratio_warning"]
        if exp_rows > 0 and unevidenced_ratio >= _ratio_threshold:
            alerts.append(
                Alert(
                    level=AlertLevel.WARNING,
                    metric=self.EXPERIENCE_UNEVIDENCED_RATIO,
                    message=(
                        f"经验条目 {unevidenced_ratio:.0%} 无客观回执"
                        f"（{int(exp_rows)} 条，阈值 {_ratio_threshold:.0%}）"
                    ),
                    value=unevidenced_ratio,
                    threshold=_ratio_threshold,
                )
            )

        decisions = self._metrics.get(self.EXPERIENCE_ADOPTION_DECISIONS, 0)
        adoption_rate = self._metrics.get(self.EXPERIENCE_ADOPTION_SUCCESS_RATE, 0.0)
        _rate_threshold = self.ALERT_THRESHOLDS["experience_adoption_success_rate_warning"]
        _min_decisions = self.ALERT_THRESHOLDS["experience_adoption_min_decisions"]
        if decisions >= _min_decisions and adoption_rate < _rate_threshold:
            alerts.append(
                Alert(
                    level=AlertLevel.WARNING,
                    metric=self.EXPERIENCE_ADOPTION_SUCCESS_RATE,
                    message=(
                        f"采纳后成功率 {adoption_rate:.0%} 低于阈值 {_rate_threshold:.0%}"
                        f"（决策数 {int(decisions)}）——照经验做在帮倒忙"
                    ),
                    value=adoption_rate,
                    threshold=_rate_threshold,
                )
            )

        return alerts

    def experience_quality_readout(self) -> Dict[str, Any]:
        """经验质量读数 → 阶段晋升判据吃的那一份（工单 016 的唯一供值口）。

        算式仍只有一份：`EKB.quality_snapshot()` 由
        `RSIOrchestrator._refresh_experience_metrics()` 搬进本类的规范指标，
        这里只做"指标面 → 判据面"的**语义还原**，不重算任何数。

        为什么必须还原：指标面是 `Dict[str, float]`，快照里
        `adoption_success_rate=None`（分母为零）落到盘上只能记成 0.0。
        判据面直接把 0.0 读成"照经验做全都失败"，就是把"没测到"当成"测出来是坏的"
        ——与本批一路在拆的"没测到当成没出问题"是同一枚硬币的两面。
        所以按 008 的最小决策数门槛把它还原成 `None`＝"这条判据没有读数"。

        阈值取自 `ALERT_THRESHOLDS` 同一张表，且在**调用时刻**读：告警说的是
        "该有人来看了"，晋升说的是"该不该给更多自主权"，两边吃同一份数才不会漂移。
        """
        rows = int(self._metrics.get(self.EXPERIENCE_ROWS, 0) or 0)
        decisions = int(self._metrics.get(self.EXPERIENCE_ADOPTION_DECISIONS, 0) or 0)
        min_decisions = self.ALERT_THRESHOLDS["experience_adoption_min_decisions"]
        return {
            "rows": rows,
            "adoption_decisions": decisions,
            "adoption_success_rate": (
                self._metrics.get(self.EXPERIENCE_ADOPTION_SUCCESS_RATE)
                if decisions >= min_decisions
                else None
            ),
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        获取仪表盘数据

        Returns:
            Dict[str, Any]: 仪表盘数据
        """
        alerts = self.check_alerts()

        # 计算摘要
        total_cycles = self._metrics.get(self.RSI_CYCLES_TOTAL, 0)
        improvement_rate = self._metrics.get(self.RSI_IMPROVEMENT_RATE, 0)
        roi = self._metrics.get(self.RSI_CONVERGENCE_ROI, 0)

        summary = {
            "total_cycles": total_cycles,
            "improvement_rate": improvement_rate,
            "roi": roi,
            "status": (
                "healthy" if not any(a.level in [AlertLevel.ERROR, AlertLevel.CRITICAL] for a in alerts) else "warning"
            ),
        }

        return {
            "metrics": self._metrics.copy(),
            "experience": {
                "rows": self._metrics.get(self.EXPERIENCE_ROWS, 0),
                "unevidenced_ratio": self._metrics.get(self.EXPERIENCE_UNEVIDENCED_RATIO, 0.0),
                "hit_rate": self._metrics.get(self.EXPERIENCE_HIT_RATE, 0.0),
                "adoption_decisions": self._metrics.get(self.EXPERIENCE_ADOPTION_DECISIONS, 0),
                "adoption_success_rate": self._metrics.get(
                    self.EXPERIENCE_ADOPTION_SUCCESS_RATE, 0.0
                ),
            },
            "alerts": [
                {
                    "level": a.level.value,
                    "metric": a.metric,
                    "message": a.message,
                    "value": a.value,
                    "threshold": a.threshold,
                }
                for a in alerts
            ],
            "summary": summary,
        }


def create_rsi_metrics() -> RSIMetrics:
    """
    创建 RSI 监控指标管理器实例

    Returns:
        RSIMetrics: RSI 监控指标管理器实例
    """
    return RSIMetrics()
