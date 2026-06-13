"""
经验结晶器 — Hebb 学习替代 LLM 调用

深度模块设计：小接口（observe/retrieve），深实现（模式提取+结晶）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from .cognitive_storage_engine import CognitiveStorageEngine, MemoryType, UnifiedMemoryNode

logger = logging.getLogger(__name__)


class PatternCrystallizer:
    """
    经验结晶器 — Hebb 学习替代 LLM 调用

    核心思想：
      1. 观察工具使用模式
      2. 当同一模式出现3次以上且成功率>60%时结晶
      3. 结晶经验存储为 PATTERN 类型记忆
      4. 不调用 LLM，成本降97%
    """

    def __init__(
        self,
        engine: CognitiveStorageEngine,
        evolution_orchestrator=None,
    ):
        """
        初始化经验结晶器

        Args:
            engine: CognitiveStorageEngine 实例
            evolution_orchestrator: EvolutionOrchestrator 实例（可选）
        """
        self.engine = engine
        self.evolution = evolution_orchestrator
        self._buffer: Dict[str, List[Dict[str, Any]]] = {}

        logger.info("PatternCrystallizer 初始化完成")

    def observe(
        self,
        tool_name: str,
        context: str,
        success: bool,
        result: Any = None,
    ) -> None:
        """
        观察工具使用

        Args:
            tool_name: 工具名称
            context: 使用上下文
            success: 是否成功
            result: 工具结果（可选）
        """
        key = self._extract_pattern_key(context)

        if key not in self._buffer:
            self._buffer[key] = []

        self._buffer[key].append(
            {
                "tool": tool_name,
                "success": success,
                "context": context[:200],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        logger.debug("观察到工具使用: %s, 模式键: %s", tool_name, key)

        # 当同一模式观察3次时尝试结晶
        if len(self._buffer[key]) >= 3:
            self._try_crystallize(key)

    def _try_crystallize(self, key: str) -> None:
        """
        尝试结晶

        Args:
            key: 模式键
        """
        entries = self._buffer.get(key, [])
        if not entries:
            return

        # 计算成功率
        success_count = sum(1 for e in entries if e["success"])
        rate = success_count / len(entries)

        # 成功率低于60%不结晶
        if rate < 0.6:
            logger.debug("模式 '%s' 成功率 %.0f%% < 60%%，不结晶", key, rate * 100)
            del self._buffer[key]
            return

        # 找出最常用的工具
        tool_counts: Dict[str, int] = {}
        for e in entries:
            tool_counts[e["tool"]] = tool_counts.get(e["tool"], 0) + 1
        primary_tool = max(tool_counts.items(), key=lambda x: x[1])[0]

        # 创建结晶记忆节点
        node = UnifiedMemoryNode(
            content=f"模式: '{key}' 类任务用 {primary_tool} 成功率 {rate * 100:.0f}%%",
            memory_type=MemoryType.PATTERN,
            category="crystallized",
            temperature=rate * 100.0,  # 成功率即温度（0-100）
            metadata={
                "pattern_key": key,
                "primary_tool": primary_tool,
                "success_rate": rate,
                "sample_count": len(entries),
            },
        )

        # 存储
        self.engine.store(node)
        logger.info("结晶成功: '%s' → %s (成功率 %.0f%%)", key, primary_tool, rate * 100)

        # 通知 EvolutionOrchestrator
        if self.evolution:
            try:
                from neurova.evolution.evolution_facade import EvolutionFacade
                facade = EvolutionFacade(self.evolution)
                facade.record_experience(
                    node.content,
                    key,
                    [primary_tool],
                    True,
                )
            except Exception as e:
                logger.warning("通知 EvolutionOrchestrator 失败: %s", e)

        # 清空缓冲区
        del self._buffer[key]

    def retrieve(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        检索结晶经验

        Args:
            query: 查询文本
            limit: 返回数量限制

        Returns:
            结晶经验列表
        """
        nodes = self.engine.retrieve(
            query,
            limit=limit,
            filters={"memory_type": "pattern"},
        )

        return [
            {
                "id": n.id,
                "content": n.content,
                "method": n.metadata.get("primary_tool", ""),
                "confidence": n.metadata.get("success_rate", 0),
                "score": n.temperature,
                "source": "crystallized",
            }
            for n in nodes
        ]

    def _extract_pattern_key(self, context: str) -> str:
        """
        提取模式关键词

        Args:
            context: 上下文文本

        Returns:
            模式键（前50字符，去除空白）
        """
        # 简单实现：取前50字符作为模式标识
        return context[:50].strip()
