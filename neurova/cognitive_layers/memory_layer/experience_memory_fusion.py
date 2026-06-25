"""
经验记忆融合器

将工具使用经验与知识图谱关联，形成完整的"知识→行为→结果"推理链。
"""

from neurova.core.logger import get_logger
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class FusedMemory:
    """融合后的记忆"""
    tool_name: str
    success: bool
    execution_time: float
    graph_context: Dict[str, Any]
    confidence: float
    fused_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExperienceMemoryFusion:
    """
    经验记忆融合器
    
    将工具使用经验与知识图谱关联，形成完整的"知识→行为→结果"推理链。
    """
    
    def __init__(self, dependency_graph: Any = None):
        """
        初始化经验记忆融合器
        
        Args:
            dependency_graph: 依赖图谱实例（可选）
        """
        self.dependency_graph = dependency_graph
        self._fused_memories: List[Dict[str, Any]] = []
        self._fusion_cache: Dict[str, Dict] = {}
        logger.info("ExperienceMemoryFusion 初始化完成")
    
    def fuse(
        self,
        tool_result: Dict[str, Any],
        graph_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        融合工具经验与图谱上下文
        
        Args:
            tool_result: 工具执行结果
            graph_context: 图谱上下文
            
        Returns:
            融合后的记忆
        """
        graph_context = graph_context or {}
        
        # 提取工具信息
        tool_name = tool_result.get("tool_name", "")
        success = tool_result.get("success", False)
        execution_time = tool_result.get("execution_time", 0.0)
        
        # 计算融合置信度
        confidence = self._calculate_confidence(
            success=success,
            has_graph_context=bool(graph_context),
            execution_time=execution_time,
        )
        
        # 构建融合记忆
        fused = {
            "tool_name": tool_name,
            "success": success,
            "execution_time": execution_time,
            "graph_context": graph_context,
            "confidence": confidence,
            "fused_at": time.time(),
            "metadata": {
                "problem_text": tool_result.get("problem_text", ""),
                "tool_source": tool_result.get("tool_source", ""),
            },
        }
        
        # 存储融合结果
        self._fused_memories.append(fused)
        
        # 限制缓存大小
        if len(self._fused_memories) > 1000:
            self._fused_memories = self._fused_memories[-500:]
        
        logger.debug("融合记忆: tool=%s, success=%s, confidence=%.2f", 
                     tool_name, success, confidence)
        
        return fused
    
    def _calculate_confidence(
        self,
        success: bool,
        has_graph_context: bool,
        execution_time: float,
    ) -> float:
        """
        计算融合置信度
        
        Args:
            success: 工具执行是否成功
            has_graph_context: 是否有图谱上下文
            execution_time: 执行时间
            
        Returns:
            置信度 0.0-1.0
        """
        confidence = 0.5  # 基础置信度
        
        # 成功加分
        if success:
            confidence += 0.3
        
        # 有图谱上下文加分
        if has_graph_context:
            confidence += 0.1
        
        # 执行时间合理加分（< 1秒）
        if execution_time < 1.0:
            confidence += 0.1
        
        return min(1.0, confidence)
    
    def get_fused_memories(
        self,
        tool_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        获取融合记忆
        
        Args:
            tool_name: 工具名称过滤（可选）
            limit: 返回数量限制
            
        Returns:
            融合记忆列表
        """
        memories = self._fused_memories
        
        if tool_name:
            memories = [m for m in memories if m.get("tool_name") == tool_name]
        
        return memories[-limit:]
    
    def get_tool_statistics(self, tool_name: str) -> Dict[str, Any]:
        """
        获取工具统计信息
        
        Args:
            tool_name: 工具名称
            
        Returns:
            统计信息
        """
        tool_memories = [m for m in self._fused_memories if m.get("tool_name") == tool_name]
        
        if not tool_memories:
            return {"tool_name": tool_name, "count": 0}
        
        total = len(tool_memories)
        successes = sum(1 for m in tool_memories if m.get("success"))
        avg_time = sum(m.get("execution_time", 0) for m in tool_memories) / total
        avg_confidence = sum(m.get("confidence", 0) for m in tool_memories) / total
        
        return {
            "tool_name": tool_name,
            "count": total,
            "success_rate": successes / total if total > 0 else 0.0,
            "avg_execution_time": avg_time,
            "avg_confidence": avg_confidence,
        }
    
    def clear(self):
        """清空融合记忆"""
        self._fused_memories.clear()
        self._fusion_cache.clear()
        logger.debug("融合记忆已清空")
