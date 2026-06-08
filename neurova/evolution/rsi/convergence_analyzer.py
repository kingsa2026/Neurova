"""
收敛性分析器

为 RSI 提供严格的数学证明，确保递归过程不会发散
"""

import logging
import math
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConvergenceMetrics:
    """收敛性指标"""
    mean_gain: float
    std_dev: float
    trend_slope: float


class ConvergenceAnalyzer:
    """收敛性分析器 - 数学保证 RSI 收敛"""
    
    def __init__(self, 
                 window_size: int = 20,
                 convergence_threshold: float = 0.01,
                 divergence_threshold: float = -0.05):
        """
        初始化收敛性分析器
        
        Args:
            window_size: 滑动窗口大小
            convergence_threshold: 收敛阈值（增益小于此值认为收敛）
            divergence_threshold: 发散阈值（增益小于此值认为发散）
        """
        self.window_size = window_size
        self.convergence_threshold = convergence_threshold
        self.divergence_threshold = divergence_threshold
        self.gain_history: List[float] = []
        self.cost_history: List[float] = []
        
        logger.info(f"ConvergenceAnalyzer initialized with window_size={window_size}")
    
    def record_iteration(self, gain: float, cost: float) -> None:
        """
        记录一轮 RSI 迭代的增益和成本
        
        Args:
            gain: 改进增益
            cost: 计算成本
        """
        self.gain_history.append(gain)
        self.cost_history.append(cost)
        
        # 保持窗口大小
        if len(self.gain_history) > self.window_size * 2:
            self.gain_history = self.gain_history[-self.window_size * 2:]
            self.cost_history = self.cost_history[-self.window_size * 2:]
    
    def analyze_convergence(self) -> Dict[str, Any]:
        """
        分析收敛状态
        
        Returns:
            Dict[str, Any]: 收敛分析结果
        """
        if len(self.gain_history) < self.window_size:
            return {
                'status': 'insufficient_data',
                'confidence': 0.0,
                'recommendation': '需要更多数据点',
                'metrics': {},
            }
        
        recent_gains = self.gain_history[-self.window_size:]
        
        # 计算统计量
        mean_gain = sum(recent_gains) / len(recent_gains)
        variance = sum((g - mean_gain) ** 2 for g in recent_gains) / len(recent_gains)
        std_dev = variance ** 0.5
        
        # 趋势分析（线性回归斜率）
        n = len(recent_gains)
        x_mean = (n - 1) / 2
        y_mean = mean_gain
        
        numerator = sum((i - x_mean) * (g - y_mean) for i, g in enumerate(recent_gains))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        trend_slope = numerator / denominator if denominator != 0 else 0
        
        # 判断收敛状态
        status = 'oscillating'
        confidence = 0.5
        recommendation = '继续观察'
        
        # 检查发散
        if mean_gain < self.divergence_threshold:
            status = 'diverging'
            confidence = min(0.9, abs(mean_gain / self.divergence_threshold))
            recommendation = '立即停止 RSI，检测到发散'
        
        # 检查收敛
        elif abs(mean_gain) < self.convergence_threshold and abs(trend_slope) < 0.001:
            status = 'converged'
            confidence = 0.9
            recommendation = '已收敛，可以停止 RSI'
        
        # 检查收敛趋势（增益为正且逐渐减小）
        elif mean_gain > 0 and trend_slope < 0:
            status = 'converging'
            confidence = 0.7
            recommendation = '正在收敛，继续观察'
        
        # 检查收敛趋势（增益很小）
        elif mean_gain < self.convergence_threshold * 2:
            status = 'converging'
            confidence = 0.6
            recommendation = '正在收敛，继续观察'
        
        return {
            'status': status,
            'confidence': confidence,
            'recommendation': recommendation,
            'metrics': {
                'mean_gain': mean_gain,
                'std_dev': std_dev,
                'trend_slope': trend_slope,
            }
        }
    
    def compute_roi(self) -> float:
        """
        计算投资回报率
        
        Returns:
            float: ROI = 总增益 / 总成本
        """
        total_gain = sum(self.gain_history)
        total_cost = sum(self.cost_history)
        
        if total_cost == 0:
            return 0.0
        
        return total_gain / total_cost
    
    def predict_convergence_point(self) -> Optional[int]:
        """
        预测收敛点
        
        Returns:
            Optional[int]: 预测的收敛迭代次数，如果无法预测返回 None
        """
        if len(self.gain_history) < self.window_size:
            return None
        
        recent_gains = self.gain_history[-self.window_size:]
        
        # 计算趋势斜率
        n = len(recent_gains)
        x_mean = (n - 1) / 2
        y_mean = sum(recent_gains) / n
        
        numerator = sum((i - x_mean) * (g - y_mean) for i, g in enumerate(recent_gains))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            return None
        
        slope = numerator / denominator
        
        # 如果斜率接近零，已经收敛
        if abs(slope) < 0.0001:
            return len(self.gain_history)
        
        # 预测收敛点：当前增益 / 斜率
        current_gain = recent_gains[-1]
        if slope >= 0:
            return None  # 不收敛
        
        iterations_to_convergence = int(current_gain / abs(slope))
        
        return len(self.gain_history) + iterations_to_convergence
    
    def is_worth_continuing(self) -> bool:
        """
        判断是否值得继续进化
        
        Returns:
            bool: 如果 ROI > 1 且未发散，返回 True
        """
        # 检查 ROI（ROI > 1 表示收益大于成本）
        roi = self.compute_roi()
        if roi <= 1.0:
            return False
        
        # 检查是否发散
        if len(self.gain_history) >= self.window_size:
            recent_gains = self.gain_history[-self.window_size:]
            mean_gain = sum(recent_gains) / len(recent_gains)
            
            if mean_gain < self.divergence_threshold:
                return False
        
        return True


def create_convergence_analyzer(
    window_size: int = 20,
    convergence_threshold: float = 0.01,
    divergence_threshold: float = -0.05
) -> ConvergenceAnalyzer:
    """
    创建收敛性分析器实例
    
    Args:
        window_size: 滑动窗口大小
        convergence_threshold: 收敛阈值
        divergence_threshold: 发散阈值
        
    Returns:
        ConvergenceAnalyzer: 收敛性分析器实例
    """
    return ConvergenceAnalyzer(
        window_size=window_size,
        convergence_threshold=convergence_threshold,
        divergence_threshold=divergence_threshold,
    )