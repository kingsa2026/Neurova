"""
RSI 编排器

协调 RSI 迭代的执行，包括：
- 从四大闭环系统收集反馈信号
- 生成优化建议
- 应用优化
- 监控收敛性
- 管理回滚和部署
"""

import logging
from typing import Any, Dict, List, Optional

from .convergence_analyzer import create_convergence_analyzer
from .deployment_controller import create_deployment_controller
from .integration_manager import create_rsi_integration_manager
from .metrics import create_rsi_metrics
from .rollback_manager import create_rollback_manager

logger = logging.getLogger(__name__)


class RSIOrchestrator:
    """
    RSI 编排器 - 协调递归自我改进的完整流程

    职责：
    1. 协调四大闭环系统（睡眠、情感、经验、工具记忆）
    2. 执行 RSI 迭代
    3. 监控收敛性
    4. 管理回滚和部署
    """

    def __init__(
        self, sleep_system: Any, emotion_system: Any, experience_system: Any, tool_memory_system: Any, **kwargs
    ):
        """
        初始化 RSI 编排器

        Args:
            sleep_system: 睡眠闭环系统
            emotion_system: 情感闭环系统
            experience_system: 经验闭环系统
            tool_memory_system: 工具记忆闭环系统
        """
        # 创建集成管理器
        self.integration_manager = create_rsi_integration_manager(
            sleep_system=sleep_system,
            emotion_system=emotion_system,
            experience_system=experience_system,
            tool_memory_system=tool_memory_system,
        )

        # 创建收敛性分析器
        self.convergence_analyzer = create_convergence_analyzer()

        # 创建监控指标管理器
        self.metrics = create_rsi_metrics()

        # 创建回滚管理器
        self.rollback_manager = create_rollback_manager()

        # 创建部署控制器
        self.deployment_controller = create_deployment_controller()

        # 迭代计数器
        self._iteration_count = 0

        logger.info("RSIOrchestrator initialized")

    def run_iteration(self) -> Dict[str, Any]:
        """
        运行一次 RSI 迭代

        Returns:
            Dict[str, Any]: 迭代结果，包含：
                - feedback_signals: 反馈信号
                - convergence: 收敛性分析
                - optimizations: 优化建议
                - metrics: 监控指标
        """
        # 1. 收集反馈信号
        feedback_signals = self.collect_feedback_signals()

        # 2. 分析收敛性
        convergence = self.convergence_analyzer.analyze_convergence()

        # 3. 生成优化建议
        optimizations = self.generate_optimizations(feedback_signals)

        # 4. 应用优化（如果部署控制器允许低风险自动执行）
        if self.deployment_controller.can_auto_execute("low"):
            self.apply_optimizations(optimizations)

        # 5. 更新指标
        self.metrics.record_metric("iteration_count", self._iteration_count)
        self.metrics.record_metric("feedback_signals_count", len(feedback_signals))

        # 6. 更新迭代计数
        self._iteration_count += 1

        return {
            "feedback_signals": feedback_signals,
            "convergence": convergence,
            "optimizations": optimizations,
            "metrics": self.metrics.get_dashboard_data(),
        }

    def collect_feedback_signals(self) -> Dict[str, Any]:
        """
        从四大闭环系统收集反馈信号

        Returns:
            Dict[str, Any]: 反馈信号字典，包含 sleep、emotion、experience、tool_memory 四个键
        """
        return self.integration_manager.collect_feedback_signals()

    def generate_optimizations(self, signals: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        根据反馈信号生成优化建议

        Args:
            signals: 反馈信号字典

        Returns:
            List[Dict[str, Any]]: 优化建议列表
        """
        optimizations = []

        # 获取可优化参数
        optimizable_params = self.integration_manager.get_optimizable_parameters()

        # 基于反馈信号生成优化建议
        for system_name, params in optimizable_params.items():
            system_signals = signals.get(system_name, {})

            for param_info in params:
                # 简单的优化策略：基于系统信号调整参数
                optimization = self._generate_optimization_for_param(system_name, param_info, system_signals)
                if optimization:
                    optimizations.append(optimization)

        return optimizations

    def _generate_optimization_for_param(
        self, system_name: str, param_info: Any, signals: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        为单个参数生成优化建议

        Args:
            system_name: 系统名称
            param_info: 参数信息
            signals: 系统信号

        Returns:
            Optional[Dict[str, Any]]: 优化建议或 None
        """
        # 默认不生成优化建议，除非有明确的信号
        # 这里可以添加更复杂的优化逻辑
        return None

    def apply_optimizations(self, optimizations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        应用优化建议

        Args:
            optimizations: 优化建议列表

        Returns:
            List[Dict[str, Any]]: 应用结果列表
        """
        results = []

        for optimization in optimizations:
            parameter = optimization.get("parameter")
            new_value = optimization.get("new_value")

            if parameter and new_value is not None:
                success = self.integration_manager.apply_optimization(parameter, new_value)
                results.append(
                    {
                        "parameter": parameter,
                        "new_value": new_value,
                        "applied": success,
                    }
                )
            else:
                results.append(
                    {
                        "parameter": parameter,
                        "new_value": new_value,
                        "applied": False,
                        "error": "Invalid optimization format",
                    }
                )

        return results

    def should_continue(self) -> bool:
        """
        判断是否应该继续 RSI 迭代

        Returns:
            bool: 是否继续
        """
        # 检查收敛性
        convergence = self.convergence_analyzer.analyze_convergence()
        status = convergence.get("status", "insufficient_data")

        # 如果已经收敛，可以停止
        if status == "converged":
            return False

        # 如果发散，需要回滚
        if status == "diverging":
            logger.warning("RSI diverging, considering rollback")
            return True  # 继续迭代，但可能需要回滚

        # 默认继续
        return True

    def get_status(self) -> Dict[str, Any]:
        """
        获取 RSI 状态

        Returns:
            Dict[str, Any]: 状态信息，包含：
                - iteration_count: 迭代次数
                - convergence_status: 收敛状态
                - deployment_phase: 部署阶段
                - metrics: 监控指标
        """
        convergence = self.convergence_analyzer.analyze_convergence()

        return {
            "iteration_count": self._iteration_count,
            "convergence_status": convergence.get("status", "unknown"),
            "deployment_phase": self.deployment_controller.get_current_phase(),
            "metrics": self.metrics.get_dashboard_data(),
        }


def create_rsi_orchestrator(
    sleep_system: Any, emotion_system: Any, experience_system: Any, tool_memory_system: Any, **kwargs
) -> RSIOrchestrator:
    """
    创建 RSI 编排器的工厂函数

    Args:
        sleep_system: 睡眠闭环系统
        emotion_system: 情感闭环系统
        experience_system: 经验闭环系统
        tool_memory_system: 工具记忆闭环系统

    Returns:
        RSIOrchestrator: RSI 编排器实例
    """
    return RSIOrchestrator(
        sleep_system=sleep_system,
        emotion_system=emotion_system,
        experience_system=experience_system,
        tool_memory_system=tool_memory_system,
        **kwargs,
    )
