"""
记忆管理 Skill Executor

从 neurova.skill_system.MemorySkill 提取的同步执行器，提供
search / store 两类操作。语义与 MemorySkill 一致：

- 持有 memory_manager 时，调用真实检索/存储能力；
- 未持有 memory_manager（None）时，search 返回空列表、store 返回
  成功标记（保持降级行为，不抛异常）；
- 任何异常都被捕获并转为 SkillResult(success=False, error=...)，
  避免把执行器内部错误冒泡到调用方。
"""

from __future__ import annotations

import time
from typing import Any, Dict

from neurova.skills.executor import BaseSkillExecutor, SkillResult


class MemorySkillExecutor(BaseSkillExecutor):
    """记忆管理执行器：search / store"""

    def __init__(self, memory_manager: Any = None) -> None:
        super().__init__(skill_id="memory", skill_name="记忆管理技能")
        self.memory_manager = memory_manager

    def execute(self, params: Dict[str, Any]) -> SkillResult:
        start_time = time.time()
        action = params.get("action", "search")

        if action == "search":
            return self._search(params, start_time)
        if action == "store":
            return self._store(params, start_time)

        return SkillResult(
            success=False,
            error=f"未知操作: {action}",
            metadata={"action": action, "execution_time": time.time() - start_time},
        )

    def _search(self, params: Dict[str, Any], start_time: float) -> SkillResult:
        query = params.get("query", "")
        limit = int(params.get("limit", 10))

        if self.memory_manager is None:
            # 无记忆管理器：降级返回空结果（与 MemorySkill 语义一致）
            return SkillResult(
                success=True,
                output=[],
                metadata={
                    "action": "search",
                    "query": query,
                    "execution_time": time.time() - start_time,
                },
            )

        try:
            results = self.memory_manager.recall(
                query=query, limit=max(1, limit)
            )
            return SkillResult(
                success=True,
                output=results or [],
                metadata={
                    "action": "search",
                    "query": query,
                    "count": len(results or []),
                    "execution_time": time.time() - start_time,
                },
            )
        except Exception as exc:
            return SkillResult(
                success=False,
                error=f"记忆检索失败: {exc}",
                metadata={
                    "action": "search",
                    "query": query,
                    "execution_time": time.time() - start_time,
                },
            )

    def _store(self, params: Dict[str, Any], start_time: float) -> SkillResult:
        content = params.get("content", "")
        if not content:
            return SkillResult(
                success=False,
                error="store 操作缺少 content 参数",
                metadata={
                    "action": "store",
                    "execution_time": time.time() - start_time,
                },
            )

        if self.memory_manager is None:
            # 无记忆管理器：降级返回成功标记（语义与 MemorySkill 一致）
            return SkillResult(
                success=True,
                output={"stored": True, "degraded": True},
                metadata={
                    "action": "store",
                    "execution_time": time.time() - start_time,
                },
            )

        try:
            category = params.get("category", "general")
            memory_type = params.get("memory_type", "semantic")
            self.memory_manager.remember(
                content=content,
                category=category,
                memory_type=memory_type,
            )
            return SkillResult(
                success=True,
                output={"stored": True},
                metadata={
                    "action": "store",
                    "category": category,
                    "memory_type": memory_type,
                    "execution_time": time.time() - start_time,
                },
            )
        except Exception as exc:
            return SkillResult(
                success=False,
                error=f"记忆存储失败: {exc}",
                metadata={
                    "action": "store",
                    "execution_time": time.time() - start_time,
                },
            )
