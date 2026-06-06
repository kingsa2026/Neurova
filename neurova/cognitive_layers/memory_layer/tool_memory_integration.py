"""
工具记忆集成 - Tool Memory Integration

功能:
1. 管理工具使用记忆
2. 记录工具执行结果
3. 提供工具推荐
"""

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


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

    def __init__(self, memory_layer=None, muscle_memory=None, confidence_threshold: float = 0.8,
                 temperature_threshold: float = 30.0, tool_weights=None, tool_lifecycle=None, **kwargs):
        self.memory_layer = memory_layer
        self.muscle_memory = muscle_memory
        self.confidence_threshold = confidence_threshold
        self.temperature_threshold = temperature_threshold
        self.tool_weights = tool_weights
        self.tool_lifecycle = tool_lifecycle
        self.usage_history: List[ToolUsageRecord] = []
        self.tool_stats: Dict[str, Dict[str, Any]] = {}
        logger.info("ToolMemoryIntegration initialized")

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
            tool_name=tool_name or "unknown",
            success=success,
            execution_time=execution_time,
            context=merged_context,
        )
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
                    tool_name=tool_name or "unknown",
                    query=query,
                    parameters=tool_params or {},
                    success=success,
                    result_summary=error_msg or "",
                    metadata={"tool_source": tool_source} if tool_source else None,
                )
            except Exception as e:
                logger.debug(f"肌肉记忆记录失败: {e}")

        logger.debug(f"Recorded tool usage: {tool_name}, success={success}")

    def get_tool_stats(self, tool_name: str = None) -> Dict[str, Any]:
        """获取工具统计"""
        if tool_name:
            return self.tool_stats.get(tool_name, {})
        return self.tool_stats

    def get_tool_recommendations(self, context: Dict[str, Any] = None) -> List[str]:
        """获取工具推荐"""
        # 基于成功率排序
        sorted_tools = sorted(
            self.tool_stats.items(),
            key=lambda x: x[1]["success"] / max(x[1]["total"], 1),
            reverse=True,
        )
        return [tool_name for tool_name, _ in sorted_tools[:5]]

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
                        logger.info(f"工具 {tool_name} 已废弃/降级，跳过肌肉记忆匹配")
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

                    if confidence >= dynamic_threshold:
                        return result, "auto_execute"
                    elif confidence >= dynamic_threshold * 0.7:
                        return result, "suggest"
                    else:
                        return result, "do_not_execute"
            except Exception as e:
                logger.warning(f"肌肉记忆匹配失败: {e}")

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
        """
        if not self.tool_weights:
            return self.confidence_threshold

        try:
            weight_obj = self.tool_weights.get_weight(tool_name)
            if weight_obj:
                multiplier = getattr(weight_obj, 'adaptive_multiplier', 1.0)
                if multiplier > 0:
                    import math
                    threshold = self.confidence_threshold / math.sqrt(multiplier)
                    return max(0.3, min(1.0, threshold))
        except Exception as e:
            logger.debug(f"获取工具权重失败: {e}")

        return self.confidence_threshold

    def _should_demote_from_muscle_memory(self, tool_name: str) -> bool:
        """检查工具是否应从肌肉记忆中降级（已废弃/已降级）"""
        if not self.tool_lifecycle:
            return False

        try:
            state = self.tool_lifecycle.get_state(tool_name)
            from neurova.evolution.tool_lifecycle import ToolLifecycleState
            return state in (ToolLifecycleState.ARCHIVED, ToolLifecycleState.DEGRADED)
        except Exception:
            return False

    def _cleanup_deprecated_tools(self) -> int:
        """清理已废弃工具的肌肉记忆，返回清理数量"""
        if not self.muscle_memory or not self.tool_lifecycle:
            return 0

        cleaned = 0
        from neurova.evolution.tool_lifecycle import ToolLifecycleState

        for layer_name in ("l1_items", "l2_items", "l3_items"):
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
                    pass

        return cleaned

    def clear_history(self):
        """清除历史"""
        self.usage_history.clear()
        self.tool_stats.clear()
