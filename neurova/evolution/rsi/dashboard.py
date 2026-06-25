"""
RSI 仪表盘

为 RSI 提供实时监控界面
"""

from neurova.core.logger import get_logger
from typing import Any, Dict, List

from .convergence_analyzer import ConvergenceAnalyzer
from .metrics import RSIMetrics

logger = get_logger(__name__)


class RSIDashboard:
    """RSI 仪表盘"""

    def __init__(self, metrics: RSIMetrics, convergence_analyzer: ConvergenceAnalyzer):
        """
        初始化仪表盘

        Args:
            metrics: RSI 监控指标管理器
            convergence_analyzer: 收敛性分析器
        """
        self.metrics = metrics
        self.convergence_analyzer = convergence_analyzer

        logger.info("RSIDashboard initialized")

    def get_overview(self) -> Dict[str, Any]:
        """
        获取概览数据

        Returns:
            Dict[str, Any]: 概览数据
        """
        # 获取指标数据
        metrics_data = self.metrics.get_dashboard_data()

        # 获取收敛性分析
        convergence_data = self.convergence_analyzer.analyze_convergence()

        return {
            "metrics": metrics_data["metrics"],
            "alerts": metrics_data["alerts"],
            "summary": metrics_data["summary"],
            "convergence": convergence_data,
        }

    def get_convergence_chart(self) -> Dict[str, Any]:
        """
        获取收敛性趋势图数据

        Returns:
            Dict[str, Any]: 趋势图数据
        """
        # 获取历史记录
        gains = self.convergence_analyzer.gain_history
        costs = self.convergence_analyzer.cost_history

        # 提取数据
        iterations = list(range(len(gains)))

        # 计算 ROI 趋势
        roi_trend = []
        total_gain = 0
        total_cost = 0
        for i in range(len(gains)):
            total_gain += gains[i]
            total_cost += costs[i]
            if total_cost > 0:
                roi_trend.append(total_gain / total_cost)
            else:
                roi_trend.append(0)

        return {
            "iterations": iterations,
            "gains": gains,
            "costs": costs,
            "roi_trend": roi_trend,
        }

    def get_gate_pass_rate(self) -> Dict[str, Any]:
        """
        获取棘轮门通过率

        Returns:
            Dict[str, Any]: 通过率数据
        """
        total_candidates = self.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_GENERATED) or 0
        pruned_candidates = self.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_PRUNED) or 0

        # 计算通过率
        pass_rate = 0
        if total_candidates > 0:
            pass_rate = (total_candidates - pruned_candidates) / total_candidates

        return {
            "total_candidates": total_candidates,
            "pruned_candidates": pruned_candidates,
            "pass_rate": pass_rate,
        }

    def get_candidate_statistics(self) -> Dict[str, Any]:
        """
        获取候选方案统计

        Returns:
            Dict[str, Any]: 统计数据
        """
        total_generated = self.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_GENERATED) or 0
        total_pruned = self.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_PRUNED) or 0
        gate_failures = self.metrics.get_metric(RSIMetrics.RSI_GATE_FAILURES) or 0

        # 计算成功率
        success_rate = 0
        if total_generated > 0:
            success_rate = (total_generated - total_pruned) / total_generated

        return {
            "total_generated": total_generated,
            "total_pruned": total_pruned,
            "gate_failures": gate_failures,
            "success_rate": success_rate,
        }

    def get_rollback_history(self) -> List[Dict[str, Any]]:
        """
        获取回滚历史

        Returns:
            List[Dict[str, Any]]: 回滚历史记录
        """
        # 这里需要从 RSIRollbackManager 获取历史
        # 暂时返回空列表
        return []


def create_rsi_dashboard(metrics: RSIMetrics, convergence_analyzer: ConvergenceAnalyzer) -> RSIDashboard:
    """
    创建 RSI 仪表盘实例

    Args:
        metrics: RSI 监控指标管理器
        convergence_analyzer: 收敛性分析器

    Returns:
        RSIDashboard: RSI 仪表盘实例
    """
    return RSIDashboard(metrics, convergence_analyzer)
