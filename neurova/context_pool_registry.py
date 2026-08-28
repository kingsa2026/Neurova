"""
ContextPoolRegistry - Agent 专属上下文池注册表

根因 D 修复: 提供按 (user_id, agent_id, session_id) 索引的 ContextPool 池注册表,
支持:
  1. 同 agent 多个 session 隔离缓存
  2. 同 agent 跨 session 按需调取
  3. 不同 agent 池互不串扰
  4. session 池的生命周期管理
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from neurova.context_pool import ContextPool


class ContextPoolRegistry:
    """Agent 专属上下文池注册表（线程安全）

    数据结构:
        _pools: {(user_id, agent_id, session_id): ContextPool}
    """

    _instance: Optional["ContextPoolRegistry"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True
        self._pools: Dict[tuple, ContextPool] = {}
        self._lock = threading.RLock()

    def get_or_create(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        max_tokens: int = 16000,
        auto_tag: bool = False,
    ) -> ContextPool:
        """获取或创建指定 (user, agent, session) 的 ContextPool

        同三元组重复调用返回同一实例(缓存), 不同 session 隔离。
        """
        key = (user_id, agent_id, session_id)
        with self._lock:
            if key in self._pools:
                return self._pools[key]
            pool = ContextPool(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                max_tokens=max_tokens,
                auto_tag=auto_tag,
                ttl_seconds=0,  # 无损归档
            )
            self._pools[key] = pool
            return pool

    def query_agent(
        self,
        user_id: str,
        agent_id: str,
        query: Optional[str] = None,
        source=None,
        session_id: Optional[str] = None,
        current_session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> list:
        """跨 session 按需调取某 agent 的上下文(默认当前 session 优先)

        Args:
            user_id: 用户ID
            agent_id: Agent ID
            query: 关键词过滤
            source: 按 ContextSource 过滤
            session_id: 若指定, 只检索该 session(否则跨所有 session)
            current_session_id: 当前活跃 session, 其内容优先返回; 剩余名额
                                跨 session 兜底
            tags: tags 过滤
            limit: 总数上限

        Returns:
            List[ContextInput], current_session 优先; 同 session 内按 priority 降序
        """
        # 显式 session_id 模式: 严格限定单个 session
        if session_id is not None:
            with self._lock:
                if not self._has_session_locked(user_id, agent_id, session_id):
                    return []
            pool = self.get_or_create(user_id, agent_id, session_id)
            return pool.query(
                query=query,
                source=source,
                session_id=session_id,
                tags=tags,
                limit=limit,
            )

        # 跨 session 模式: 获取所有 session
        with self._lock:
            all_sessions = self._list_sessions_locked(user_id, agent_id)

        # 当前 session 优先 + 跨 session 兜底
        ordered_sessions = []
        if current_session_id and current_session_id in all_sessions:
            ordered_sessions.append(current_session_id)
            ordered_sessions.extend(s for s in all_sessions if s != current_session_id)
        else:
            ordered_sessions = all_sessions

        # 从每个 session 调取, 直到 limit 填满
        all_results = []
        remaining = limit
        for sid in ordered_sessions:
            if remaining <= 0:
                break
            pool = self.get_or_create(user_id, agent_id, sid)
            # 用 query 拿该 session 的所有候选, 调取 limit 个
            results = pool.query(
                query=query,
                source=source,
                session_id=sid,  # 严格限定单 session, 避免跨 session 串扰
                tags=tags,
                limit=remaining,
            )
            all_results.extend(results)
            remaining -= len(results)

        # 不传 current_session_id 时, 跨 session 重新按 priority 降序(向后兼容)
        if not current_session_id:
            all_results.sort(key=lambda c: c.priority, reverse=True)
            all_results = all_results[:limit]

        return all_results

    def _has_session_locked(self, user_id: str, agent_id: str, session_id: str) -> bool:
        """调用方必须已持锁"""
        return (user_id, agent_id, session_id) in self._pools

    def list_sessions(self, user_id: str, agent_id: str) -> List[str]:
        """返回该 (user, agent) 下的所有 session_id"""
        with self._lock:
            return self._list_sessions_locked(user_id, agent_id)

    def _list_sessions_locked(self, user_id: str, agent_id: str) -> List[str]:
        """内部辅助: 调用方必须已持锁"""
        prefix = (user_id, agent_id)
        return [sid for (u, a, sid) in self._pools.keys() if u == user_id and a == agent_id]

    def clear_session(self, user_id: str, agent_id: str, session_id: str) -> bool:
        """清除指定 session 的 pool 缓存(返回是否成功移除)"""
        key = (user_id, agent_id, session_id)
        with self._lock:
            if key in self._pools:
                del self._pools[key]
                return True
            return False

    def get_pool_count(self) -> int:
        """调试用: 返回当前池总数"""
        with self._lock:
            return len(self._pools)

    def reset(self) -> None:
        """清空所有缓存(用于测试隔离)"""
        with self._lock:
            self._pools.clear()


# 提供单例便捷访问
def get_registry() -> ContextPoolRegistry:
    return ContextPoolRegistry()
