"""会话身份快照缓存（OpenOcta 启发 P2 #11：SnapshotForSession）。

问题：记忆温度/结晶引擎/进化写入即时生效——长会话中途 soul.md 更新、
性格调整会改变当前 system prompt，破坏可复现性（同会话内两次相同提问
可能因 prompt 漂移得到不同回答）。

OpenOcta 方案：会话开始时冻结注入 prompt 的身份快照，写入只在**下次
会话**生效。Neurova 等价实现：
- SessionSnapshotCache：session_id → {soul, personality, constitution}
  首轮冻结，同会话轮次复用；会话切换重建；LRU 上限防膨胀
- build_context 的 system_instructions 优先消费快照（经 orchestrator
  _frozen_snapshot 属性，ChatPipeline 装配）
- 无 session_id 的无状态调用不缓存（每次现取，诚实降级）

边界：冻结的是 prompt 身份层（soul/性格/宪法），不是上下文检索层——
结晶经验/记忆检索每轮变化属正常语义（OpenOcta SnapshotForSession
同口径：冻结 memory/soul/prompt markdown，不冻结会话历史）。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Dict, Optional


class SessionSnapshotCache:
    """(agent_id, session_id) → 身份快照的 LRU 缓存（线程安全）。

    键含 agent_id：同一 session_id 被不同 agent 处理时（API 层不禁止
    跨 agent 复用会话 id），快照绝不跨 agent 泄漏身份。
    """

    def __init__(self, max_sessions: int = 64) -> None:
        self._max = max(1, int(max_sessions))
        self._cache: "OrderedDict[str, Dict[str, str]]" = OrderedDict()
        self._lock = threading.RLock()

    def get(self, agent: Any, session_id: Optional[str]) -> Dict[str, str]:
        """取会话身份快照（无缓存则现取并冻结）。

        session_id 为空（无状态调用）→ 不缓存，直接读活值。
        """
        if not session_id:
            return self._read_live(agent)

        key = self._key(agent, session_id)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

        snapshot = self._read_live(agent)
        with self._lock:
            self._cache[key] = snapshot
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)
        return snapshot

    @staticmethod
    def _key(agent: Any, session_id: str) -> str:
        """缓存键：agent 身份 + 会话（跨 agent 隔离）。"""
        config = getattr(agent, "config", None)
        agent_id = str(getattr(config, "agent_id", None) or id(agent))
        return f"{agent_id}::{session_id}"

    @staticmethod
    def _read_live(agent: Any) -> Dict[str, str]:
        """读当前身份层活值（soul/personality/constitution 三件套）。"""
        config = getattr(agent, "config", None)
        return {
            "soul": str(getattr(agent, "soul", "") or ""),
            "personality": str(getattr(agent, "personality", "") or ""),
            "constitution": str(getattr(config, "constitution", None) or ""),
        }

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# 进程级共享缓存（多 pipeline 实例共享；键 = agent_id::session_id，
# 跨 agent 天然隔离，同名会话不串身份）
_shared_cache: Optional[SessionSnapshotCache] = None
_cache_lock = threading.RLock()


def get_session_snapshot_cache() -> SessionSnapshotCache:
    global _shared_cache
    with _cache_lock:
        if _shared_cache is None:
            _shared_cache = SessionSnapshotCache(max_sessions=64)
        return _shared_cache


__all__ = ["SessionSnapshotCache", "get_session_snapshot_cache"]
