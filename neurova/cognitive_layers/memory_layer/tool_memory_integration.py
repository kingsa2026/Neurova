"""
工具记忆集成 - Tool Memory Integration

功能:
1. 管理工具使用记忆
2. 记录工具执行结果
3. 提供工具推荐
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List

logger = get_logger(__name__)


@dataclass
class ToolUsageRecord:
    """工具使用记录"""

    tool_name: str
    success: bool
    execution_time: float = 0.0
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ToolMemoryIntegration:
    """工具记忆集成

    完整闭环: check_tool_memory → 执行工具 → record_tool_usage → 下次匹配

    Args:
        memory_layer: 记忆层实例
        muscle_memory: 肌肉记忆实例（语义匹配）
        confidence_threshold: 基础置信度阈值
        temperature_threshold: 温度阈值
        tool_weights: 自适应工具权重（动态阈值）
        tool_lifecycle: 工具生命周期管理器（废弃检测）
    """

    def __init__(
        self,
        memory_layer=None,
        muscle_memory=None,
        confidence_threshold: float = 0.8,
        temperature_threshold: float = 30.0,
        tool_weights=None,
        tool_lifecycle=None,
        success_bonus: float = 0.1,
        failure_penalty: float = 0.05,
        decay_rate: float = 0.01,
        muscle_memory_threshold: float = 0.8,
        **kwargs,
    ):
        self.memory_layer = memory_layer
        self.muscle_memory = muscle_memory
        self.confidence_threshold = confidence_threshold
        self.temperature_threshold = temperature_threshold
        self.tool_lifecycle = tool_lifecycle
        self.usage_history: List[ToolUsageRecord] = []
        self.tool_stats: Dict[str, Dict[str, Any]] = {}
        # 并发锁：保护 usage_history 和 tool_stats 的读写
        self._lock = threading.RLock()
        # RSI 可优化参数（property 定义见类尾：success_bonus/failure_penalty/decay_rate
        # 经 configure() 转发 AdaptiveToolWeights 权重本体——A/B 融合收尾，RSI 活表；
        # muscle_memory_threshold 直接作用于 _get_dynamic_threshold 基准）。
        # 注意顺序：参数先于 tool_weights 赋值，附着时同步才有值可推。
        self.success_bonus: float = success_bonus
        self.failure_penalty: float = failure_penalty
        self.decay_rate: float = decay_rate
        self.muscle_memory_threshold: float = muscle_memory_threshold
        # tool_weights 最后赋值（property setter 会把上面参数同步进权重对象）
        self.tool_weights = tool_weights
        # 维护触发（docs/tool-memory-muscle-analysis.md P-A/P-F）：遗忘与生命周期
        # 清理原为无调用方的死代码，借 record_tool_usage 计数周期性触发
        self.maintenance_interval: int = 50
        self._ops_since_maintenance: int = 0
        logger.info("ToolMemoryIntegration initialized")

    # ── RSI 活表参数：A/B 融合收尾（docs/Neurova_OpenClaw工具技能专项对比 §7）──
    # RSI apply_optimization 以 setattr(tool_memory_system, name, value) 应用参数，
    # property setter 保持该语义不变，同时把值推进 AdaptiveToolWeights.configure。

    @property
    def success_bonus(self) -> float:
        return self._success_bonus

    @success_bonus.setter
    def success_bonus(self, value: float) -> None:
        self._success_bonus = float(value)
        self._sync_weight_params()

    @property
    def failure_penalty(self) -> float:
        return self._failure_penalty

    @failure_penalty.setter
    def failure_penalty(self, value: float) -> None:
        self._failure_penalty = float(value)
        self._sync_weight_params()

    @property
    def decay_rate(self) -> float:
        return self._decay_rate

    @decay_rate.setter
    def decay_rate(self, value: float) -> None:
        self._decay_rate = float(value)
        self._sync_weight_params()

    @property
    def tool_weights(self):
        return self._tool_weights

    @tool_weights.setter
    def tool_weights(self, value) -> None:
        self._tool_weights = value
        self._sync_weight_params()

    def _sync_weight_params(self) -> None:
        """把 RSI 参数同步进已挂载的 AdaptiveToolWeights。

        integration 是 RSI 面向的参数表面，附着/调参任一时点都保持两者一致；
        无挂载或权重对象无 configure（测试桩）时静默跳过。
        """
        weights = getattr(self, "_tool_weights", None)
        if weights is None:
            return
        configure = getattr(weights, "configure", None)
        if not callable(configure):
            return
        try:
            configure(
                success_bonus=getattr(self, "_success_bonus", None),
                failure_penalty=getattr(self, "_failure_penalty", None),
                decay_rate=getattr(self, "_decay_rate", None),
            )
        except Exception as e:  # noqa: BLE001 - 同步失败不影响主流程
            logger.debug("权重参数同步失败: %s", e)

    def record_tool_usage(
        self,
        tool_name: str = None,
        success: bool = True,
        execution_time: float = 0.0,
        context: Dict[str, Any] = None,
        problem_text: str = None,
        tool_source: str = None,
        tool_params: Dict[str, Any] = None,
        error_msg: str = None,
        **kwargs,
    ):
        """记录工具使用

        支持两种调用方式:
        1. 新接口: record_tool_usage(problem_text=..., tool_name=..., tool_source=..., ...)
        2. 旧接口: record_tool_usage(tool_name, success, execution_time, context)
        """
        # Bug 11: 统一归一化 tool_name，避免 None 污染 tool_stats 键
        tool_name = tool_name or "unknown"

        # 合并上下文
        merged_context = dict(context or {})
        if problem_text:
            merged_context["problem_text"] = problem_text
        if tool_source:
            merged_context["tool_source"] = tool_source
        if tool_params:
            merged_context["tool_params"] = tool_params
        if error_msg:
            merged_context["error_msg"] = error_msg

        record = ToolUsageRecord(
            tool_name=tool_name,
            success=success,
            execution_time=execution_time,
            context=merged_context,
        )

        with self._lock:
            self.usage_history.append(record)

            # 更新统计
            if tool_name not in self.tool_stats:
                self.tool_stats[tool_name] = {"total": 0, "success": 0, "fail": 0, "avg_time": 0.0}

            stats = self.tool_stats[tool_name]
            stats["total"] += 1
            if success:
                stats["success"] += 1
            else:
                stats["fail"] += 1

            # 更新平均时间
            total_time = stats["avg_time"] * (stats["total"] - 1) + execution_time
            stats["avg_time"] = total_time / stats["total"]

        # 传播到肌肉记忆（闭环关键）
        if self.muscle_memory:
            try:
                query = problem_text or tool_name or "unknown"
                self.muscle_memory.record_usage(
                    tool_name=tool_name,
                    query=query,
                    parameters=tool_params or {},
                    success=success,
                    result_summary=error_msg or "",
                    metadata={"tool_source": tool_source} if tool_source else None,
                )
            except (TypeError, AttributeError):
                # Bug 12: 编程错误不应被吞掉，re-raise
                raise
            except Exception as e:
                logger.exception("肌肉记忆记录失败: %s", e)

        # 周期性维护（遗忘 + 下线工具清理），计数在锁内递增
        with self._lock:
            self._ops_since_maintenance += 1
            due = self._ops_since_maintenance >= self.maintenance_interval
            if due:
                self._ops_since_maintenance = 0
        if due:
            try:
                self._run_maintenance()
            except Exception as e:  # noqa: BLE001 - 维护失败不影响主流程
                logger.warning("工具记忆维护失败: %s", e)

        logger.debug("Recorded tool usage: %s, success=%s", tool_name, success)

    def _run_maintenance(self) -> int:
        """执行一次记忆维护：遗忘检查 + 下线工具条目清理。

        P-A/P-F 修复：两者原先均无调用方（死代码），现由 record_tool_usage
        按 maintenance_interval 周期触发。返回被遗忘/清理的条目数。
        """
        cleaned = 0
        if self.muscle_memory:
            cleaned += self.muscle_memory.check_forgotten()
        cleaned += self._cleanup_deprecated_tools()
        if cleaned:
            logger.info("工具记忆维护完成: 处理 %s 个条目", cleaned)
        return cleaned

    def get_tool_stats(self, tool_name: str = None) -> Dict[str, Any]:
        """获取工具统计"""
        with self._lock:
            if tool_name:
                return self.tool_stats.get(tool_name, {})
            return self.tool_stats

    def get_tool_recommendations(self, context: Dict[str, Any] = None) -> List[str]:
        """获取工具推荐"""
        # Bug 15: sorted() 必须在锁保护下执行，防止并发修改导致 RuntimeError
        with self._lock:
            sorted_tools = sorted(
                self.tool_stats.items(),
                key=lambda x: x[1]["success"] / max(x[1]["total"], 1),
                reverse=True,
            )
            return [tool_name for tool_name, _ in sorted_tools[:5]]

    def get_feedback(self) -> Dict[str, Any]:
        """
        获取工具记忆集成的反馈信号，供 RSI 系统使用。

        Returns:
            Dict[str, Any]: 包含 total_usages, success_rate, muscle_memory_hits
        """
        total_usages = len(self.usage_history)
        success_count = sum(1 for r in self.usage_history if r.success)
        success_rate = success_count / total_usages if total_usages > 0 else 0.0

        # 肌肉记忆命中数：从 usage_history 中统计有 muscle_memory 匹配的记录
        muscle_memory_hits = sum(1 for r in self.usage_history if r.context.get("tool_source") == "muscle_memory")

        return {
            "total_usages": total_usages,
            "success_rate": success_rate,
            "muscle_memory_hits": muscle_memory_hits,
        }

    def check_tool_memory(self, user_input: str) -> tuple:
        """
        检查工具记忆，返回 (tool_memory_result, tool_decision)

        优先使用肌肉记忆进行语义匹配，降级到关键词匹配。

        Args:
            user_input: 用户输入

        Returns:
            (tool_memory_result, tool_decision) 元组
            tool_memory_result: 匹配的工具记忆或 None
            tool_decision: "auto_execute", "suggest", "do_not_execute"
        """
        # 1. 优先使用肌肉记忆
        if self.muscle_memory:
            try:
                matches = self.muscle_memory.match_by_query(user_input)
                if matches:
                    best_item, confidence = matches[0]
                    tool_name = best_item.tool_name

                    # 检查工具是否已废弃/降级
                    if self._should_demote_from_muscle_memory(tool_name):
                        logger.info("工具 %s 已废弃/降级，跳过肌肉记忆匹配", tool_name)
                        return None, "do_not_execute"

                    # 动态阈值
                    dynamic_threshold = self._get_dynamic_threshold(tool_name)

                    result = {
                        "tool_name": tool_name,
                        "tool_source": best_item.metadata.get("tool_source", "skill_system"),
                        "tool_params": best_item.parameters,
                        "confidence": confidence,
                        "match_level": best_item.level.value,
                        "dynamic_threshold": dynamic_threshold,
                    }

                    # Bug 13 修正（docs/tool-memory-muscle-analysis.md P-C）：命中
                    # 肌肉记忆本身不是一次工具执行，原实现记 success=True 会系统性
                    # 推高条目成功率（回声室）。改为只记 hit 到使用历史（供 RSI 的
                    # muscle_memory_hits 统计），成功/失败由真实执行结果另行记录
                    with self._lock:
                        self.usage_history.append(
                            ToolUsageRecord(
                                tool_name=tool_name,
                                success=True,
                                context={
                                    "tool_source": "muscle_memory",
                                    "hit_only": True,
                                    "confidence": confidence,
                                    "problem_text": user_input,
                                },
                            )
                        )

                    if confidence >= dynamic_threshold:
                        return result, "auto_execute"
                    elif confidence >= dynamic_threshold * 0.7:
                        return result, "suggest"
                    else:
                        return result, "do_not_execute"
            except Exception as e:
                logger.warning("肌肉记忆匹配失败: %s", e)

        # 2. 降级：关键词匹配
        return self._check_keyword_match(user_input)

    def _check_keyword_match(self, user_input: str) -> tuple:
        """降级的关键词匹配"""
        if not self.tool_stats:
            return None, "do_not_execute"

        input_lower = user_input.lower()
        action_keywords = {
            "read": ["read", "file", "open", "load", "读取", "打开", "文件"],
            "write": ["write", "save", "create", "写入", "保存", "创建"],
            "search": ["search", "find", "query", "搜索", "查找", "查询"],
            "execute": ["run", "execute", "command", "执行", "运行", "命令"],
        }

        best_match = None
        best_score = 0

        for tool_name, stats in self.tool_stats.items():
            score = 0
            if tool_name.lower() in input_lower:
                score += 2

            for category, keywords in action_keywords.items():
                if any(kw in input_lower for kw in keywords):
                    if category in tool_name.lower():
                        score += 1

            success_rate = stats["success"] / max(stats["total"], 1)
            score *= success_rate

            if score > best_score:
                best_score = score
                best_match = tool_name

        if best_match and best_score > 0.5:
            stats = self.tool_stats[best_match]
            confidence = min(best_score, 1.0)

            result = {
                "tool_name": best_match,
                "confidence": confidence,
                "success_rate": stats["success"] / max(stats["total"], 1),
                "total_uses": stats["total"],
            }

            if confidence >= self.confidence_threshold:
                return result, "auto_execute"
            elif confidence >= 0.5:
                return result, "suggest"

        return None, "do_not_execute"

    def _get_dynamic_threshold(self, tool_name: str) -> float:
        """获取动态置信度阈值

        高权重工具降低阈值（更容易自动执行），
        低权重工具提高阈值（更难自动执行）。

        公式: threshold = base / sqrt(adaptive_multiplier)
        限制在 [0.3, 1.0]

        基准使用 muscle_memory_threshold（RSI 可优化参数），而非
        confidence_threshold（关键词匹配的固定阈值）。此前基准写死
        confidence_threshold，导致 RSI 调 muscle_memory_threshold 后
        系统行为完全不变（死参数），闭环断裂。
        """
        if not self.tool_weights:
            return self.muscle_memory_threshold

        try:
            weight_obj = self.tool_weights.get_weight(tool_name)
            if weight_obj:
                effective_getter = getattr(self.tool_weights, "get_effective_multiplier", None)
                if callable(effective_getter):
                    # 含惰性衰减的乘数：长期未用的工具阈值回升（更难自动执行）
                    multiplier = effective_getter(tool_name)
                else:
                    multiplier = getattr(weight_obj, "adaptive_multiplier", 1.0)
                if isinstance(multiplier, (int, float)) and multiplier > 0:
                    import math

                    threshold = self.muscle_memory_threshold / math.sqrt(multiplier)
                    return max(0.3, min(1.0, threshold))
        except Exception as e:
            logger.debug("获取工具权重失败: %s", e)

        return self.muscle_memory_threshold

    def _should_demote_from_muscle_memory(self, tool_name: str) -> bool:
        """检查工具是否应从肌肉记忆中降级（已废弃/已降级）。

        H6 修复: 统一 ToolLifecycleManager 后 get_state 返回
        Optional[ToolLifecycleState] 枚举，此处显式处理 None（未注册工具）
        并与枚举常量比较，避免字符串 vs 枚举的永远 False 比较。
        """
        if not self.tool_lifecycle:
            return False

        try:
            state = self.tool_lifecycle.get_state(tool_name)
            if state is None:
                # 未注册工具不降级
                return False
            from neurova.evolution.tool_lifecycle import ToolLifecycleState

            return state in (ToolLifecycleState.ARCHIVED, ToolLifecycleState.DEGRADED)
        except Exception:
            # Bug 14: 静默吞异常改为记录日志
            logger.exception("检查工具 %s 生命周期状态失败", tool_name)
            return False

    def _cleanup_deprecated_tools(self) -> int:
        """清理已废弃工具的肌肉记忆，返回清理数量"""
        if not self.muscle_memory or not self.tool_lifecycle:
            return 0

        cleaned = 0
        from neurova.evolution.tool_lifecycle import ToolLifecycleState

        # Bug 10: 实际属性名是 _l1/_l2/_l3（不是 l1_items/l2_items/l3_items）
        for layer_name in ("_l1", "_l2", "_l3"):
            layer = getattr(self.muscle_memory, layer_name, None)
            if not layer:
                continue
            items = list(layer.items())
            for item_id, item in items:
                tool_name = getattr(item, "tool_name", None)
                if not tool_name:
                    continue
                try:
                    state = self.tool_lifecycle.get_state(tool_name)
                    if state in (ToolLifecycleState.ARCHIVED, ToolLifecycleState.DEGRADED):
                        layer.pop(item_id, None)
                        cleaned += 1
                except Exception:
                    logger.exception("清理工具 %s 时检查状态失败", tool_name)

        return cleaned

    def clear_history(self):
        """清除历史"""
        self.usage_history.clear()
        self.tool_stats.clear()
