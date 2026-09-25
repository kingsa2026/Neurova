"""上下文池注册表——按身份查**已登记**的池（读侧唯一入口）。

## 职责（B6-10 批次 F 收窄后）

只做一件事：编排器构造池时就地 `adopt`（登记），消费方按身份 `get_pool` 取回
**同一个实例**。端点 `/context/build`、工作流上下文节点都经它取池——不登记的话，
读侧取不到就只能各自新建，"写入即丢"（审计 P2-3）。

## 为什么不再按 session 分池

改前本模块还带一套多池机制（`get_or_create` 按 `(user, agent, session)` 造池 +
`query_agent` 跨 session 分区调取 + `list_sessions` / `clear_session` /
`get_pool_count` 生命周期管理）。那是**按池分会话**的隔离设计，与
`ContextPool.isolation_key` 同源；而 T-02 / ADR-0015 交付的真设计是
**单池 + 作用域标签**：池是"永不丢失"的归档，隔离由内容的 `chat_scope`
（随写入咽喉落进 metadata）经 `filter_by_scope` 判，池归属不承担隔离。

两套并存的结果实测（2026-09-26，真 `ContextOrchestrator` 构造面）：

   生产构造后登记池数: 1
   登记键: [('u1', 'yi_ling', '')]     ← 一个 agent 一个池，session 段恒空
   池自身 draw 取得: ['真归档']          ← 真读路径取得到
   registry.query_agent 同身份: []       ← 分区读路径一条都取不回来

`query_agent` 的跨 session 模式按 `_list_sessions_locked()` 枚举 `''` 这个键，
再 `pool.query(session_id='')`；而池的 `session_id` 每轮由 `build_context` 刷成
本轮身份，与注册表键里的 `''` 无因果。于是池里明明有内容也取不回来，且**返回空
列表而不是报错**——消费方分不出"没有"与"坏掉"（教义第 2 条）。

那套机制生产侧零调用点，故整批退场，留下单池读侧的两个入口 `adopt` / `get_pool`。
"""
from __future__ import annotations

import threading
from typing import Dict, Optional

from neurova.context_pool import ContextPool


class ContextPoolRegistry:
    """按身份索引的池注册表（线程安全，进程内单例）。

    数据结构: `_pools: {(user_id, agent_id, session_id): ContextPool}`。
    键里的 `session_id` 段取自池的**构造期**归属；生产池由编排器以
    `session_id=None` 构造（每轮身份刷在 `pool.session_id` 上），故生产键的
    session 段恒空——这正是"按身份查已登记的池"够用的原因（一个 agent 一个池）。
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

    @staticmethod
    def _identityKey(user_id: str, agent_id: str, session_id: Optional[str]) -> tuple:
        """身份键归一：session_id 的 None 与 "" 是同一个归属。

        不归一就会出现"Agent 用 None 登记、调用方用 '' 查询"这类查不到的
        静默失配——池明明活着，取池却返回 None。
        """
        return (str(user_id or ""), str(agent_id or ""), str(session_id or ""))

    def adopt(self, pool) -> None:
        """登记一个**已存在**的池实例（写侧唯一入口）。

        只登记，不造池：生产对话链的池由 `ContextOrchestrator` 构造，只有登记
        进来，端点/工作流节点才能取到**同一个**池（而不是各造一个、写入即丢）。
        注册表刻意不自持生命周期——"取池顺带造池"会让调用方把空池当真池用
        （审计 P2-3 的形态）。
        """
        key = self._identityKey(pool.user_id, pool.agent_id, getattr(pool, "session_id", None))
        with self._lock:
            self._pools[key] = pool

    def get_pool(self, user_id: str, agent_id: str, session_id: Optional[str] = None):
        """按身份取**已登记**的池（无则 None）。

        刻意不建池：取池路径一旦能隐式造池，"取到了但那是新池"就无从分辨，
        调用方会把空池当成真池用（P2-3 的形态）。
        """
        key = self._identityKey(user_id, agent_id, session_id)
        with self._lock:
            return self._pools.get(key)

    def reset(self) -> None:
        """清空所有缓存(用于测试隔离)"""
        with self._lock:
            self._pools.clear()


# 提供单例便捷访问
def get_registry() -> ContextPoolRegistry:
    return ContextPoolRegistry()
