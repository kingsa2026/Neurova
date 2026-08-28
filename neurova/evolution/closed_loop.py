"""
闭环进化系统 — 工具执行 → 进化更新 → 经验反哺 → 权重更新

实现核心类：
1. ToolLifecycleManager (closed_loop) - 工具生命周期管理（简易版）
2. AdaptiveToolWeights - 自适应权重管理
3. EvolutionOrchestrator - 进化编排器
4. PatternMiner (pattern_miner.py) - PrefixSpan 频繁模式挖掘
5. ToolGeneticEngine (genetic_engine.py) - 工具基因编程引擎
6. ExperienceFeedback (experience_feedback.py) - 经验反哺系统
7. ToolLifecycleManager (tool_lifecycle.py) - 工具生命周期管理（完整版）
"""

from neurova.core.logger import get_logger
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

# H7 修复: 删除本地 Version A ToolLifecycleManager（touch 仅 1 参、get_state 返回字符串），
# 统一 re-export tool_lifecycle.py 的 Version B（touch 接受 success、get_state 返回枚举、有锁）。
# 这消除 split-brain：tool_executor.py 调用 touch(name, success) 不再 TypeError，
# _should_demote_from_muscle_memory 的枚举比较不再永远 False。
from neurova.evolution.tool_lifecycle import ToolLifecycleManager, ToolLifecycleState

logger = get_logger(__name__)


@dataclass
class ToolWeight:
    """工具权重数据"""

    tool_name: str
    success_count: int = 0
    failure_count: int = 0
    total_latency: float = 0.0
    last_used: Optional[datetime] = None
    adaptive_multiplier: float = 1.0
    lifecycle_state: str = "active"  # active, degraded, archived, frozen


class AdaptiveToolWeights:
    """自适应权重管理器 — 根据工具表现调整权重"""

    def __init__(self):
        self._weights: Dict[str, ToolWeight] = {}
        self._lock = threading.RLock()  # CL-1: RLock 支持读路径间的可重入调用
        logger.info("AdaptiveToolWeights initialized")

    def register_tool(self, tool_name: str, base_weight: float = 1.0) -> None:
        """注册工具（预设基础权重）"""
        with self._lock:
            if tool_name not in self._weights:
                self._weights[tool_name] = ToolWeight(
                    tool_name=tool_name,
                    adaptive_multiplier=base_weight,
                )

    def get_weight(self, tool_name: str) -> Optional[ToolWeight]:
        """获取工具权重"""
        with self._lock:
            return self._weights.get(tool_name)

    def update_weight(self, tool_name: str, success: bool, latency: float = 0.0) -> None:
        """更新工具权重"""
        with self._lock:
            if tool_name not in self._weights:
                self._weights[tool_name] = ToolWeight(tool_name=tool_name)

            weight = self._weights[tool_name]
            if success:
                weight.success_count += 1
                # 成功时增加自适应乘数（最多增加50%）
                weight.adaptive_multiplier = min(1.5, weight.adaptive_multiplier * 1.05)
            else:
                weight.failure_count += 1
                # 失败时降低自适应乘数（最少降到30%）
                weight.adaptive_multiplier = max(0.3, weight.adaptive_multiplier * 0.95)

            weight.total_latency += latency
            weight.last_used = datetime.now(UTC)
            logger.debug(
                f"Weight updated for {tool_name}: success={success}, multiplier={weight.adaptive_multiplier:.3f}"
            )

    def get_effective_weight(self, tool_name: str) -> float:
        """获取工具的有效权重（考虑自适应乘数）"""
        weight = self.get_weight(tool_name)
        if not weight:
            return 1.0

        # 基础权重基于成功率
        total = weight.success_count + weight.failure_count
        if total == 0:
            base_weight = 1.0
        else:
            base_weight = weight.success_count / total

        # 应用自适应乘数
        return base_weight * weight.adaptive_multiplier

    def get_ranked_tools(self, tool_names: List[str]) -> List[str]:
        """按权重对工具进行排序"""

        def sort_key(tool_name: str) -> float:
            return self.get_effective_weight(tool_name)

        return sorted(tool_names, key=sort_key, reverse=True)


from neurova.evolution.experience_feedback import ExperienceFeedback
from neurova.evolution.genetic_engine import ToolGeneticEngine

# 从真实实现导入，替代占位符
from neurova.evolution.pattern_miner import PatternMiner


class PatternBasedToolSynthesizer:
    """基于频繁模式的工具合成器 — 从 PatternMiner 的频繁模式生成工具模板。

    Bug N-2 修复: 原类名 NLToolSynthesizer 与 nl_synthesizer.py 的真实
    NLToolSynthesizer（502 行完整实现）同名冲突，导致 EvolutionOrchestrator
    持有 stub 实例而非真实 NL 合成器。重命名为 PatternBasedToolSynthesizer
    以消除歧义——此类只做基于模式的合成，不做 NL 描述合成。
    """

    def __init__(self, pattern_miner: Optional[PatternMiner] = None):
        self.pattern_miner = pattern_miner
        logger.info("PatternBasedToolSynthesizer initialized")

    def synthesize_from_patterns(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """从频繁模式合成工具模板列表。"""
        if not self.pattern_miner:
            return []
        return self.pattern_miner.to_skill_template_list(top_n=top_n)


class EvolutionOrchestrator:
    """进化编排器 — 协调工具进化、权重更新和经验反哺"""

    def __init__(
        self,
        tool_lifecycle: Optional[Any] = None,
        crystallizer: Optional[Any] = None,
        rsi_orchestrator: Optional[Any] = None,
    ):
        self.tool_weights = AdaptiveToolWeights()
        self.tool_lifecycle = tool_lifecycle or ToolLifecycleManager()
        self.pattern_miner = PatternMiner()
        self.genetic_engine = ToolGeneticEngine()
        self.tool_synthesizer = PatternBasedToolSynthesizer(self.pattern_miner)
        self.experience_feedback = ExperienceFeedback()
        self.crystallizer = crystallizer

        # 根因 2 修复: 持有 RSIOrchestrator 引用, 使经验/工具/记忆信号可触发递归进化
        self.rsi_orchestrator = rsi_orchestrator

        # RSI 迭代节流: 避免每条经验都触发全量进化(默认 60s 一次)
        self._last_rsi_iteration_at: float = 0.0
        self._rsi_iteration_interval: float = 60.0
        self._rsi_iteration_count: int = 0

        # 工具注册表
        self._registered_tools: List[str] = []

        # 生命周期评估时间追踪
        self._last_lifecycle_eval: float = time.time()
        self._lifecycle_eval_interval: float = 3600.0  # 1 小时

        logger.info("EvolutionOrchestrator initialized")

    def register_tools(self, tool_names: List[str]) -> None:
        """注册工具列表（同时注册到权重和生命周期管理器）"""
        self._registered_tools = tool_names.copy()
        for name in tool_names:
            if hasattr(self.tool_lifecycle, "register_tool"):
                self.tool_lifecycle.register_tool(name)
        logger.info("Registered %s tools", len(tool_names))

    def on_before_tool_selection(
        self,
        available_tools: Optional[List[str]] = None,
        context: str = "",
        tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        工具选择前钩子 — 过滤归档/冻结工具，降级工具降权，返回按权重排序的工具列表

        Args:
            available_tools: 可用工具列表
            context: 上下文信息
            tools: 可用工具列表（别名参数）

        Returns:
            包含排序后工具列表的字典
        """
        tool_list = tools or available_tools or []

        filtered: List[str] = []
        ranking: List[str] = []

        for tool in tool_list:
            state = None
            if hasattr(self.tool_lifecycle, "get_state"):
                state = self.tool_lifecycle.get_state(tool)

            # 从 ToolLifecycleState 枚举或字符串比较
            state_value = state.value if hasattr(state, "value") else str(state) if state else "active"

            if state_value in ("archived", "frozen"):
                filtered.append(tool)
                continue

            ranking.append(tool)

        # 按权重排序
        ranked_tools = self.tool_weights.get_ranked_tools(ranking)

        # 构建权重字典（降级工具降权30%）
        weights = {}
        for tool in ranked_tools:
            w = self.tool_weights.get_effective_weight(tool)
            state = None
            if hasattr(self.tool_lifecycle, "get_state"):
                state = self.tool_lifecycle.get_state(tool)
            state_value = state.value if hasattr(state, "value") else str(state) if state else "active"

            if state_value == "degraded":
                w *= 0.7
            weights[tool] = w

        return {
            "ranking": ranked_tools,
            "weights": weights,
            "filtered": filtered,
        }

    def on_after_tool_execution(
        self,
        tool_name: str,
        success: bool,
        context: str = "",
        latency: float = 0.0,
    ) -> None:
        """
        工具执行后钩子 — 更新工具权重和生命周期

        Args:
            tool_name: 工具名称
            success: 是否成功
            context: 上下文信息
            latency: 执行延迟
        """
        # 更新权重
        self.tool_weights.update_weight(tool_name, success, latency)

        # 更新生命周期（touch 只记录使用，不关心成败）
        self.tool_lifecycle.touch(tool_name)

        # 可能触发生命周期评估
        self._maybe_evaluate_lifecycle()

        logger.debug("Tool execution recorded: %s, success=%s", tool_name, success)

    def on_experience_recorded(self, text: str, task: str, tools: List[str], success: bool) -> Dict[str, Any]:
        """
        经验记录后钩子 — 使用 ExperienceFeedback 提取洞察并更新权重

        Args:
            text: 经验文本
            task: 任务描述
            tools: 使用的工具列表
            success: 是否成功

        Returns:
            包含洞察信息的字典
        """
        # 使用 ExperienceFeedback 处理经验
        outcome = "success" if success else "failure"
        result = self.experience_feedback.process_experience(
            experience_text=text,
            task_type=task,
        )

        # 更新权重
        for tool in tools:
            if tool in self._registered_tools:
                self.tool_weights.update_weight(tool, success)

        # 更新模式挖掘器
        if tools:
            self.pattern_miner.add_sequence(tools, context=task)

        # 触发经验结晶
        if self.crystallizer and tools:
            for tool in tools:
                try:
                    self.crystallizer.observe(
                        tool_name=tool,
                        context=task,
                        success=success,
                    )
                except Exception as e:
                    logger.warning("经验结晶观察失败: %s", e)

        logger.info("Experience recorded: task='%s', tools=%s, success=%s", task, tools, success)

        # 根因 1 修复: 经验记录后, 触发 RSI 闭环(节流保护)
        rsi_state = self._maybe_trigger_rsi(force=False)
        if rsi_state is None:
            rsi_state = {"triggered": False, "reason": "throttled_or_no_rsi"}

        return {
            "insights_count": result.get("insights_created", 0),
            "tools_mentioned": result.get("tools_mentioned", []),
            "outcome": result.get("outcome", outcome),
            "task": task,
            "success": success,
            "association": result.get("associations_updated", 0),
            # 根因 1 修复: 返回 RSI 状态字段, 让调用方可观测闭环是否真正生效
            "rsi": rsi_state,
        }

    def on_rsi_iterate(self, force: bool = False) -> Dict[str, Any]:
        """
        根因 2 修复: 主动触发一次 RSI 迭代(棘轮剪枝递归进化)

        Args:
            force: True 跳过节流(用于测试/手动触发), False 受 _rsi_iteration_interval 限制

        Returns:
            包含 RSI 迭代结果的字典; 若 RSI 未配置, 返回 {"triggered": False, "reason": "no_rsi"}
        """
        if self.rsi_orchestrator is None:
            logger.debug("RSI 跳过: 未配置 rsi_orchestrator")
            return {"triggered": False, "reason": "no_rsi"}

        if not force:
            now = time.time()
            if now - self._last_rsi_iteration_at < self._rsi_iteration_interval:
                return {"triggered": False, "reason": "throttled"}

        try:
            rsi_result = self.rsi_orchestrator.run_iteration()
            self._last_rsi_iteration_at = time.time()
            self._rsi_iteration_count += 1
            # RSI 标准返回 Dict, 包含 convergence/applied_count/gain
            if not isinstance(rsi_result, dict):
                rsi_result = {"raw": rsi_result}
            should_continue = False
            try:
                should_continue = bool(self.rsi_orchestrator.should_continue())
            except Exception:
                pass
            return {
                "triggered": True,
                "iteration": self._rsi_iteration_count,
                "convergence": rsi_result.get("convergence"),
                "applied_count": rsi_result.get("applied_count", 0),
                "gain": rsi_result.get("gain", 0.0),
                "should_continue": should_continue,
                "rsi_result": rsi_result,
            }
        except Exception as e:
            logger.warning("RSI 迭代失败: %s", e)
            return {"triggered": False, "reason": "error", "error": str(e)}

    def _maybe_trigger_rsi(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """内部辅助: 尝试触发 RSI 迭代(节流控制), 无 RSI 时返回 None"""
        if self.rsi_orchestrator is None:
            return None
        return self.on_rsi_iterate(force=force)

    def _maybe_evaluate_lifecycle(self) -> None:
        """检查是否需要触发生命周期评估。"""
        now = time.time()
        if now - self._last_lifecycle_eval < self._lifecycle_eval_interval:
            return

        self._last_lifecycle_eval = now

        if hasattr(self.tool_lifecycle, "evaluate"):
            self.tool_lifecycle.evaluate()

        if hasattr(self.tool_lifecycle, "apply_decay"):
            self.tool_lifecycle.apply_decay()

        logger.debug("Lifecycle evaluation triggered")

    def get_statistics(self) -> Dict[str, Any]:
        """获取进化统计信息（包含生命周期信息）"""
        # 基础统计
        stats = {
            "registered_tools": len(self._registered_tools),
            "tools_with_weights": len(self.tool_weights._weights),
        }

        # 生命周期统计
        if hasattr(self.tool_lifecycle, "get_lifecycle_report"):
            stats["lifecycle"] = self.tool_lifecycle.get_lifecycle_report()

        # 每个工具的详细统计
        tool_stats = {}
        for tool_name in self._registered_tools:
            tool_info = {
                "weight": self.tool_weights.get_effective_weight(tool_name),
            }

            # 生命周期状态
            if hasattr(self.tool_lifecycle, "get_state"):
                state = self.tool_lifecycle.get_state(tool_name)
                tool_info["lifecycle_state"] = state.value if hasattr(state, "value") else str(state) or "active"

            tool_stats[tool_name] = tool_info

        stats["tools"] = tool_stats

        return stats


# 单例管理
_evolution_orchestrator: Optional[EvolutionOrchestrator] = None
_orchestrator_lock = threading.Lock()


def get_evolution_orchestrator() -> EvolutionOrchestrator:
    """
    获取 EvolutionOrchestrator 单例

    Returns:
        EvolutionOrchestrator 实例
    """
    global _evolution_orchestrator
    if _evolution_orchestrator is None:
        with _orchestrator_lock:
            if _evolution_orchestrator is None:
                _evolution_orchestrator = EvolutionOrchestrator()
    return _evolution_orchestrator


def reset_evolution_orchestrator() -> None:
    """
    重置 EvolutionOrchestrator 单例（用于测试）
    """
    global _evolution_orchestrator
    with _orchestrator_lock:
        _evolution_orchestrator = None
