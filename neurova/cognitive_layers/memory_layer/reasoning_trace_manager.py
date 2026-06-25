"""
推理链管理器 — 记录完整推理过程

深度模块设计：小接口（start_trace/add_step/finish_trace），深实现。
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from .cognitive_storage_engine import CognitiveStorageEngine, MemoryType, UnifiedMemoryNode

logger = get_logger(__name__)


@dataclass
class ReasoningStep:
    """推理步骤"""

    step_id: str
    action: str  # "retrieve" | "crystallize" | "llm_call" | "tool_call"
    input_summary: str
    output_summary: str
    memory_ids: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ReasoningTrace:
    """推理链"""

    trace_id: str
    query: str
    steps: List[ReasoningStep] = field(default_factory=list)
    final_answer: str = ""
    total_tokens: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ReasoningTraceManager:
    """
    推理链管理器 — 记录完整推理过程

    核心思想：
      1. 开始推理链 → 记录查询
      2. 添加推理步骤 → 记录检索、结晶、LLM调用等
      3. 完成推理链 → 存储为可检索的记忆节点
      4. 推理链可被检索 → 类似问题可参照
    """

    def __init__(self, engine: CognitiveStorageEngine):
        """
        初始化推理链管理器

        Args:
            engine: CognitiveStorageEngine 实例
        """
        self.engine = engine
        self._active_traces: Dict[str, ReasoningTrace] = {}

        logger.info("ReasoningTraceManager 初始化完成")

    def start_trace(self, query: str) -> str:
        """
        开始一条推理链

        Args:
            query: 用户查询

        Returns:
            trace_id
        """
        trace_id = str(uuid.uuid4())
        self._active_traces[trace_id] = ReasoningTrace(
            trace_id=trace_id,
            query=query,
            steps=[],
            final_answer="",
        )

        logger.debug("开始推理链: %s, 查询: %s", trace_id, query[:50])
        return trace_id

    def add_step(
        self,
        trace_id: str,
        action: str,
        input_summary: str,
        output_summary: str,
        memory_ids: List[str] = None,
    ) -> None:
        """
        添加推理步骤

        Args:
            trace_id: 推理链ID
            action: 动作类型
            input_summary: 输入摘要
            output_summary: 输出摘要
            memory_ids: 引用的记忆节点ID列表
        """
        trace = self._active_traces.get(trace_id)
        if not trace:
            logger.debug("忽略无效 trace_id: %s", trace_id)
            return

        step = ReasoningStep(
            step_id=str(uuid.uuid4()),
            action=action,
            input_summary=input_summary[:200],
            output_summary=output_summary[:200],
            memory_ids=memory_ids or [],
        )
        trace.steps.append(step)

        logger.debug("添加推理步骤: %s, " f"动作: %s, 步骤数: %s", trace_id, action, len(trace.steps))

    def finish_trace(
        self,
        trace_id: str,
        final_answer: str,
        total_tokens: int = 0,
    ) -> None:
        """
        完成推理链，存储为记忆

        Args:
            trace_id: 推理链ID
            final_answer: 最终回复
            total_tokens: 总 token 数
        """
        trace = self._active_traces.pop(trace_id, None)
        if not trace:
            logger.debug("忽略无效 trace_id: %s", trace_id)
            return

        trace.final_answer = final_answer[:500]
        trace.total_tokens = total_tokens

        # 收集所有引用的记忆ID
        all_memory_ids = []
        for step in trace.steps:
            all_memory_ids.extend(step.memory_ids)

        # 存储为记忆节点（可被检索）
        node = UnifiedMemoryNode(
            content=f"推理链: {trace.query} → {trace.final_answer}",
            memory_type=MemoryType.EPISODIC,
            category="reasoning_trace",
            temperature=100.0,
            trace_id=trace_id,
            metadata={
                "steps_count": len(trace.steps),
                "actions": [s.action for s in trace.steps],
                "memory_ids": all_memory_ids,
                "total_tokens": total_tokens,
            },
        )
        self.engine.store(node)

        logger.info("完成推理链: %s, " f"步骤数: %s, " f"Token: %s", trace_id, len(trace.steps), total_tokens)

    def get_recent_traces(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取最近的推理链

        Args:
            limit: 返回数量限制

        Returns:
            推理链列表
        """
        nodes = self.engine.retrieve(
            "",
            limit=limit,
            filters={"category": "reasoning_trace"},
        )

        return [
            {
                "trace_id": n.trace_id,
                "content": n.content,
                "steps_count": n.metadata.get("steps_count", 0),
                "created_at": n.created_at.isoformat(),
            }
            for n in nodes
        ]
