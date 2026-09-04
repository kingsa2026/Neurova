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

    def __init__(self, memory_manager: Any = None, pending_store: Any = None) -> None:
        super().__init__(skill_id="memory", skill_name="记忆管理技能")
        self.memory_manager = memory_manager
        # P1-2 待确认队列（opt-in 挂载；None = 待确认通道不可用，store 全直写）
        self.pending_store = pending_store

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

    def _resolve_proposed_by(self, params: Dict[str, Any]) -> str:
        """提议人归属：记忆隔离作用域（服务端可信）优先，参数自报兜底。"""
        mm = self.memory_manager
        try:
            if mm is not None and hasattr(mm, "effective_user_id"):
                uid = str(mm.effective_user_id() or "")
                if uid and uid != "default":
                    return uid
        except Exception:  # noqa: BLE001 — 身份解析失败回退参数
            pass
        return str(params.get("proposed_by", "") or "")

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

        # P1-2 待确认中间态：挂载了 pending_store 的实例，交互式单条写入
        # 默认进待审队列（Utopia 0018：人就在对话里，确认成本最低）；
        # confirm=True 按次强制直写；未挂载实例保持原直写语义（opt-in 在
        # 构造处，不挂载 = 行为完全不变）。
        if self.pending_store is not None and params.get("confirm") is not True:
            try:
                rec = self.pending_store.propose(
                    content=content,
                    category=params.get("category", "general"),
                    memory_type=params.get("memory_type", "semantic"),
                    source_sentence=params.get("source_sentence", ""),
                    # P1-2 修 F：归属以服务端隔离作用域身份优先（防调用方
                    # 伪造 proposed_by 把内容栽进他人待审队列）；无作用域
                    # 环境（CLI 等）才回退参数自报
                    proposed_by=self._resolve_proposed_by(params),
                )
                if rec.get("rejected"):
                    return SkillResult(
                        success=True,
                        output={"pending": True, "rejected": True, "reason": rec.get("reason", "")},
                        metadata={
                            "action": "store",
                            "execution_time": time.time() - start_time,
                        },
                    )
                return SkillResult(
                    success=True,
                    output={"pending": True, "review_id": rec["id"]},
                    metadata={
                        "action": "store",
                        "category": params.get("category", "general"),
                        "memory_type": params.get("memory_type", "semantic"),
                        "execution_time": time.time() - start_time,
                    },
                )
            except Exception as exc:
                return SkillResult(
                    success=False,
                    error=f"记忆待确认队列写入失败: {exc}",
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
