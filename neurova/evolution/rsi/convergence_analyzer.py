"""
收敛性分析器

为 RSI 提供严格的数学证明，确保递归过程不会发散
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


# 收敛状态词表（工单 008 交付项 1）：分析器只发这六种结论。
# 晋升判据（deployment_controller）与响应面（result_summary）都按这张表分派 ——
# 新增第七态必须同时改判据，否则它会落进"不认识即放行"的分支。
STATE_CONVERGED = "converged"
STATE_CONVERGING = "converging"
STATE_OSCILLATING = "oscillating"
STATE_DIVERGING = "diverging"
STATE_INSUFFICIENT_DATA = "insufficient_data"
STATE_MEASUREMENT_BLIND = "measurement_blind"

CONVERGENCE_STATES = (
    STATE_CONVERGED,
    STATE_CONVERGING,
    STATE_OSCILLATING,
    STATE_DIVERGING,
    STATE_INSUFFICIENT_DATA,
    STATE_MEASUREMENT_BLIND,
)


@dataclass
class ConvergenceMetrics:
    """收敛性指标"""

    mean_gain: float
    std_dev: float
    trend_slope: float


class ConvergenceAnalyzer:
    """收敛性分析器 - 数学保证 RSI 收敛"""

    def __init__(self, window_size: int = 20, convergence_threshold: float = 0.01, divergence_threshold: float = -0.05):
        """
        初始化收敛性分析器

        Args:
            window_size: 滑动窗口大小
            convergence_threshold: 收敛阈值（增益小于此值认为收敛）
            divergence_threshold: 发散阈值（增益小于此值认为发散）
        """
        # C-16: window_size<=0 会使 len(gain_history) < window_size 恒假，
        # 收敛计算退化为空切片求均值（ZeroDivisionError）——非法值回落默认窗口
        if not isinstance(window_size, int) or window_size <= 0:
            logger.warning(
                "ConvergenceAnalyzer 收到非法 window_size=%r，回落默认值 20", window_size
            )
            window_size = 20
        self.window_size = window_size
        self.convergence_threshold = convergence_threshold
        self.divergence_threshold = divergence_threshold
        self.gain_history: List[float] = []
        self.cost_history: List[float] = []
        # 每轮增益是否来自有效测量（工单 008）；与 gain_history 等长
        self.evidence_history: List[bool] = []

        logger.info("ConvergenceAnalyzer initialized with window_size=%s", window_size)

    def record_iteration(self, gain: float, cost: float, evidenced: bool = True) -> None:
        """
        记录一轮 RSI 迭代的增益和成本

        Args:
            gain: 改进增益
            cost: 计算成本
            evidenced: 该增益是否来自一次有效测量（工单 008）。
                False 表示评测集度量失明（用例全部回退到 setpoint）：
                只记成本与"这轮量过但没量出来"的痕迹，**不记增益** ——
                增益史是收敛统计的唯一输入，掺进量不出来的 0
                就会把零证据窗口算成"已收敛"，连锁让进化永久自停。
        """
        if evidenced:
            self.gain_history.append(gain)
        self.cost_history.append(cost)
        self.evidence_history.append(bool(evidenced))
        self._trim_history()

    def _trim_history(self) -> None:
        """三条历史各自封顶 2×window（工单 008 后它们不再等长）。"""
        cap = self.window_size * 2
        if len(self.gain_history) > cap:
            self.gain_history = self.gain_history[-cap:]
        if len(self.cost_history) > cap:
            self.cost_history = self.cost_history[-cap:]
        if len(self.evidence_history) > cap:
            self.evidence_history = self.evidence_history[-cap:]

    def _roi_readout(self) -> Optional[float]:
        """成本核算读数（工单 006）。

        无成本记录时返回 None 而不是 0.0 —— "还没花过钱"与"花了钱零回报"
        是两件事，后者才是 `roi < 0` 这类守卫要比较的量。
        样本未达收敛窗口也照样给出：roi 是成本核算，与收敛判定的样本量无关，
        用样本门槛去掐它等于让阶段判据在起步期永远拿不到读数。
        """
        if not self.cost_history or sum(self.cost_history) == 0:
            return None
        return self.compute_roi()

    def analyze_convergence(self) -> Dict[str, Any]:
        """
        分析收敛状态

        Returns:
            Dict[str, Any]: 收敛分析结果
        """
        roi = self._roi_readout()

        # 工单 008：度量失明抢在样本量门槛之前判定。
        # "窗口里一次有效测量都没有"与样本量无关 —— 全是失明尝试时，
        # 多等也不会自动变出证据；此时报 insufficient_data（"再等等"）
        # 指派的运维动作与真症结（"去修测量"）正好相反。
        recent_evidence = self.evidence_history[-self.window_size:]
        if recent_evidence and not any(recent_evidence):
            return {
                "status": STATE_MEASUREMENT_BLIND,
                "confidence": 0.0,
                "recommendation": (
                    f"最近 {len(recent_evidence)} 轮全部无有效测量（评测集用例回退到 setpoint）："
                    "gain 恒为 0 是量不出来的结果，不是没有改善空间 —— 先修测量再谈收敛"
                ),
                "metrics": {
                    "mean_gain": 0.0,
                    "std_dev": 0.0,
                    "trend_slope": 0.0,
                    "roi": roi,
                    "evidenced_iterations": 0,
                },
            }

        if len(self.gain_history) < self.window_size:
            return {
                "status": STATE_INSUFFICIENT_DATA,
                "confidence": 0.0,
                "recommendation": "需要更多数据点",
                # roi 与收敛样本量无关（工单 006）：此前该分支固定返回空 metrics，
                # 使 run_iteration 的 roi 守卫读不到任何键、只能兜底成 0.0 空转。
                "metrics": ({} if roi is None else {"roi": roi}),
            }

        recent_gains = self.gain_history[-self.window_size :]

        # 计算统计量
        mean_gain = sum(recent_gains) / len(recent_gains)
        variance = sum((g - mean_gain) ** 2 for g in recent_gains) / len(recent_gains)
        std_dev = variance**0.5

        # 趋势分析（线性回归斜率）
        n = len(recent_gains)
        x_mean = (n - 1) / 2
        y_mean = mean_gain

        numerator = sum((i - x_mean) * (g - y_mean) for i, g in enumerate(recent_gains))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        trend_slope = numerator / denominator if denominator != 0 else 0

        # 判断收敛状态
        status = STATE_OSCILLATING
        confidence = 0.5
        recommendation = "继续观察"

        # 检查发散
        if mean_gain < self.divergence_threshold:
            status = STATE_DIVERGING
            confidence = min(0.9, abs(mean_gain / self.divergence_threshold))
            recommendation = "立即停止 RSI，检测到发散"

        # 检查收敛
        elif abs(mean_gain) < self.convergence_threshold and abs(trend_slope) < 0.001:
            status = STATE_CONVERGED
            confidence = 0.9
            recommendation = "已收敛，转入降频巡检"

        # 检查收敛趋势（增益为正且逐渐减小）
        elif mean_gain > 0 and trend_slope < 0:
            status = STATE_CONVERGING
            confidence = 0.7
            recommendation = "正在收敛，继续观察"

        # 检查收敛趋势（增益很小）
        elif mean_gain < self.convergence_threshold * 2:
            status = STATE_CONVERGING
            confidence = 0.6
            recommendation = "正在收敛，继续观察"

        return {
            "status": status,
            "confidence": confidence,
            "recommendation": recommendation,
            "metrics": {
                "mean_gain": mean_gain,
                "std_dev": std_dev,
                "trend_slope": trend_slope,
                "roi": roi,
            },
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

        recent_gains = self.gain_history[-self.window_size :]

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
            recent_gains = self.gain_history[-self.window_size :]
            mean_gain = sum(recent_gains) / len(recent_gains)

            if mean_gain < self.divergence_threshold:
                return False

        return True


def create_convergence_analyzer(
    window_size: int = 20, convergence_threshold: float = 0.01, divergence_threshold: float = -0.05
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
