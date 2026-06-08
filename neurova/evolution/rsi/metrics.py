"""
RSI 监控指标管理器

为 RSI 提供可观测性，人类需要能够理解和审计每层递归的改进
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


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
    
    # 告警阈值
    ALERT_THRESHOLDS = {
        'roi_warning': 0.1,
        'roi_critical': 0.0,
        'gate_failures_error': 3,
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
        
        logger.info("RSIMetrics initialized")
    
    def record_metric(self, metric_name: str, value: float) -> None:
        """
        记录指标
        
        Args:
            metric_name: 指标名称
            value: 指标值
        """
        self._metrics[metric_name] = value
        logger.debug(f"Recorded metric: {metric_name} = {value}")
    
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
            alerts.append(Alert(
                level=AlertLevel.INFO,
                metric=self.RSI_CYCLES_TOTAL,
                message=f"RSI 循环完成 {cycles} 次",
                value=cycles,
                threshold=0,
            ))
        
        # WARNING: ROI 低于阈值
        roi = self._metrics.get(self.RSI_CONVERGENCE_ROI, 0)
        if 0 < roi < self.ALERT_THRESHOLDS['roi_warning']:
            alerts.append(Alert(
                level=AlertLevel.WARNING,
                metric=self.RSI_CONVERGENCE_ROI,
                message=f"ROI 低于阈值: {roi:.2f} < {self.ALERT_THRESHOLDS['roi_warning']}",
                value=roi,
                threshold=self.ALERT_THRESHOLDS['roi_warning'],
            ))
        
        # ERROR: 连续失败
        gate_failures = self._metrics.get(self.RSI_GATE_FAILURES, 0)
        if gate_failures >= self.ALERT_THRESHOLDS['gate_failures_error']:
            alerts.append(Alert(
                level=AlertLevel.ERROR,
                metric=self.RSI_GATE_FAILURES,
                message=f"连续失败 {gate_failures} 次",
                value=gate_failures,
                threshold=self.ALERT_THRESHOLDS['gate_failures_error'],
            ))
        
        # CRITICAL: 发散检测（负 ROI）
        if roi < self.ALERT_THRESHOLDS['roi_critical']:
            alerts.append(Alert(
                level=AlertLevel.CRITICAL,
                metric=self.RSI_CONVERGENCE_ROI,
                message=f"检测到发散: ROI = {roi:.2f}",
                value=roi,
                threshold=self.ALERT_THRESHOLDS['roi_critical'],
            ))
        
        return alerts
    
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
            'total_cycles': total_cycles,
            'improvement_rate': improvement_rate,
            'roi': roi,
            'status': 'healthy' if not any(a.level in [AlertLevel.ERROR, AlertLevel.CRITICAL] for a in alerts) else 'warning',
        }
        
        return {
            'metrics': self._metrics.copy(),
            'alerts': [
                {
                    'level': a.level.value,
                    'metric': a.metric,
                    'message': a.message,
                    'value': a.value,
                    'threshold': a.threshold,
                }
                for a in alerts
            ],
            'summary': summary,
        }


def create_rsi_metrics() -> RSIMetrics:
    """
    创建 RSI 监控指标管理器实例
    
    Returns:
        RSIMetrics: RSI 监控指标管理器实例
    """
    return RSIMetrics()