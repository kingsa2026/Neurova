"""
RSI 部署控制器

RSI 风险较高，必须采用渐进式部署，从被动观察到完全自动化
"""

from neurova.core.logger import get_logger
from typing import Any, Dict

logger = get_logger(__name__)


class RSIDeploymentController:
    """RSI 部署控制器"""

    # 部署阶段常量
    PHASE_0_OBSERVATION = 0
    PHASE_1_MANUAL = 1
    PHASE_2_SEMI_AUTO = 2
    PHASE_3_CONDITIONAL_AUTO = 3
    PHASE_4_FULL_AUTO = 4

    def __init__(self, initial_phase: int = 0):
        """
        初始化部署控制器

        Args:
            initial_phase: 初始阶段
        """
        # 验证初始阶段
        if initial_phase < 0 or initial_phase > 4:
            raise ValueError("Initial phase must be between 0 and 4")

        self._current_phase = initial_phase

        # 阶段描述
        self._phase_descriptions = {
            0: "观察阶段 - 只收集数据，不执行优化",
            1: "手动阶段 - 生成优化建议，人工审批",
            2: "半自动阶段 - 低风险优化自动执行",
            3: "有条件自动阶段 - 中风险优化自动执行",
            4: "完全自动阶段 - 所有优化自动执行",
        }

        # 风险级别对应的最低自动执行阶段
        self._risk_phase_mapping = {
            "low": 2,  # Phase 2 可以自动执行低风险
            "medium": 3,  # Phase 3 可以自动执行中风险
            "high": 4,  # Phase 4 可以自动执行高风险
        }

        logger.info("RSIDeploymentController initialized at phase %s", initial_phase)

    def get_current_phase(self) -> int:
        """
        获取当前部署阶段

        Returns:
            int: 当前阶段
        """
        return self._current_phase

    def can_auto_execute(self, risk_level: str) -> bool:
        """
        判断是否可以自动执行

        Args:
            risk_level: 风险级别 ('low', 'medium', 'high')

        Returns:
            bool: 是否可以自动执行
        """
        # 获取风险级别对应的最低自动执行阶段
        min_phase = self._risk_phase_mapping.get(risk_level, 4)

        # 当前阶段必须大于等于最低阶段
        return self._current_phase >= min_phase

    def evaluate_phase_transition(self, metrics: Dict[str, Any]) -> bool:
        """
        评估是否应该进入下一阶段

        Args:
            metrics: 当前指标

        Returns:
            bool: 是否应该进入下一阶段
        """
        # 如果已经在最高阶段，不能继续
        if self._current_phase >= 4:
            return False

        # 检查收敛状态
        convergence_status = metrics.get("convergence_status", "")
        if convergence_status == "diverging":
            logger.warning("Divergence detected, not advancing phase")
            return False

        # 检查 ROI
        roi = metrics.get("roi", 0)
        if roi < 0:
            logger.warning("Negative ROI, not advancing phase")
            return False

        # 检查无回滚天数
        days_without_rollback = metrics.get("days_without_rollback", 0)

        # 根据当前阶段检查无回滚天数要求
        required_days = {
            0: 0,  # Phase 0 → 1: 无要求
            1: 7,  # Phase 1 → 2: 7 天
            2: 7,  # Phase 2 → 3: 7 天
            3: 30,  # Phase 3 → 4: 30 天
        }

        if days_without_rollback < required_days.get(self._current_phase, 0):
            logger.info(
                f"Not enough days without rollback: {days_without_rollback} < {required_days.get(self._current_phase, 0)}"
            )
            return False

        return True

    def advance_phase(self) -> int:
        """
        进入下一阶段

        Returns:
            int: 新的阶段
        """
        # 如果已经在最高阶段，不能继续
        if self._current_phase >= 4:
            logger.warning("Already at maximum phase (4)")
            return self._current_phase

        # 进入下一阶段
        self._current_phase += 1

        logger.info("Advanced to phase %s: %s", self._current_phase, self._phase_descriptions[self._current_phase])
        return self._current_phase


def create_deployment_controller(initial_phase: int = 0) -> RSIDeploymentController:
    """
    创建 RSI 部署控制器实例

    Args:
        initial_phase: 初始阶段

    Returns:
        RSIDeploymentController: RSI 部署控制器实例
    """
    return RSIDeploymentController(initial_phase)


def create_deployment_controller_with_settings(settings) -> RSIDeploymentController:
    """按治理设置创建部署控制器（治理遗留收口 2026-09-05）。

    settings 里带 rsi_phase（0..4）则以之为初始阶段（管理员在设置页配置的
    部署阶段），否则维持 phase=0 观察期。非法值回退 0。
    """
    phase = 0
    try:
        raw = (settings or {}).get("rsi_phase")
        if raw is not None:
            phase = int(raw)
    except (TypeError, ValueError):
        phase = 0
    if phase < 0 or phase > 4:
        phase = 0
    return RSIDeploymentController(initial_phase=phase)
