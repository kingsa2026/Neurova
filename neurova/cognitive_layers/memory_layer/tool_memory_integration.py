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
    """工具记忆集成"""

    def __init__(self, memory_layer=None, muscle_memory=None, confidence_threshold: float = 0.8, 
                 temperature_threshold: float = 30.0, **kwargs):
        self.memory_layer = memory_layer
        self.muscle_memory = muscle_memory
        self.confidence_threshold = confidence_threshold
        self.temperature_threshold = temperature_threshold
        self.usage_history: List[ToolUsageRecord] = []
        self.tool_stats: Dict[str, Dict[str, Any]] = {}
        logger.info("ToolMemoryIntegration initialized")

    def record_tool_usage(self, tool_name: str, success: bool, execution_time: float = 0.0, context: Dict[str, Any] = None):
        """记录工具使用"""
        record = ToolUsageRecord(
            tool_name=tool_name,
            success=success,
            execution_time=execution_time,
            context=context or {},
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
        
        Args:
            user_input: 用户输入
            
        Returns:
            (tool_memory_result, tool_decision) 元组
            tool_memory_result: 匹配的工具记忆或 None
            tool_decision: "auto_execute", "suggest", "do_not_execute"
        """
        if not self.tool_stats:
            return None, "do_not_execute"
        
        # 简单实现：基于用户输入关键词匹配工具
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
            # 检查工具名是否在输入中
            if tool_name.lower() in input_lower:
                score += 2
            
            # 检查关键词匹配
            for category, keywords in action_keywords.items():
                if any(kw in input_lower for kw in keywords):
                    if category in tool_name.lower():
                        score += 1
            
            # 考虑成功率
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
            
            # 决策逻辑
            if confidence >= self.confidence_threshold:
                return result, "auto_execute"
            elif confidence >= 0.5:
                return result, "suggest"
        
        return None, "do_not_execute"

    def clear_history(self):
        """清除历史"""
        self.usage_history.clear()
        self.tool_stats.clear()
