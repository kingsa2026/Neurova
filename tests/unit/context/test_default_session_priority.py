"""默认 Session 优先调取测试

需求: 同 agent 同 session 在调取上下文时, 默认优先返回当前 sessionID 的内容
(而非跨所有 session 平均分配)。

关键场景（均在 `ContextPool.query` 真面上）：
  1. 默认应优先返回自身 session_id 的 chunk
  2. 显式 session_id 参数时仍可强制限定
  3. limit 内应尽可能填满当前 session, 再用跨 session 兜底
  4. 池无 session_id 时按 priority 降序（向后兼容）

**B6-10 批次 F 范围收窄（2026-09-26）**：原第 4 条是
`ContextPoolRegistry.query_agent(current_session_id=...)` 的"当前 session 优先
+ 跨 session 兜底"。该注册表多池机制已退场（被 T-02 的单池 + `chat_scope`
作用域标签设计取代，且实测分区读路径在生产取不回任何内容），故
`TestRegistryCurrentSessionPriority` 整组退役。**被锁的契约未丢**：池自身
`query()` 的"当前 session 优先 + 跨 session 兜底"由本文件前三条继续钉住。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestContextPoolCurrentSessionPriority:
    """ContextPool.query() — 默认当前 session 优先"""

    def test_query_default_returns_current_session(self):
        """GREEN: query() 默认按 pool 自身 session_id 过滤(因为同 pool 内
        所有 chunk 的 session_id 都相同)"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="u", agent_id="a", session_id="s_current")
        # pool 内所有 chunk 都会被打上 s_current 的 sessionID
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="msg1", priority=10
        ))
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="msg2", priority=99
        ))

        results = pool.query(limit=5)
        # 全部命中, 按 priority 降序
        assert len(results) == 2
        assert results[0].content == "msg2"  # priority=99
        assert results[1].content == "msg1"  # priority=10
        # 全部带 s_current sessionID
        assert all(c.metadata["session_id"] == "s_current" for c in results)

    def test_query_explicit_session_id_filters_strictly(self):
        """GREEN: 显式 session_id 严格限定(即使 pool 是其他 session)"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        # 准备一个"全景 pool"——通过 metadata 强制注入不同 session_id
        # (这模拟从其他池导入 chunks 的场景)
        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        c1 = ContextInput(source=ContextSource.CONVERSATION, content="from-s1", priority=10)
        c1.metadata = {"session_id": "s1"}
        c2 = ContextInput(source=ContextSource.CONVERSATION, content="from-s2", priority=99)
        c2.metadata = {"session_id": "s2"}
        # 用 _collector 直接 add(绕过 _inject_isolation_tags 覆盖)
        pool._collector.add_context(c1)
        pool._collector.add_context(c2)
        pool._cache_version += 1

        # 显式 session_id="s2" 应只返回 s2 的
        results = pool.query(session_id="s2")
        assert len(results) == 1
        assert results[0].content == "from-s2"

    def test_query_default_prioritizes_own_session_in_mixed_pool(self):
        """核心场景: 全景 pool(混合多个 session chunks), 默认查询应:
           1) 当前 session 排在最前
           2) 跨 session 兜底在后面
        """
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        # 模拟"调取时的全景 pool": pool.session_id='s_current',
        # 但内部有来自其他 session 的 chunks(通过手动注入)
        pool = ContextPool(user_id="u", agent_id="a", session_id="s_current")

        # 跨 session 块(高 priority)
        for i in range(3):
            c = ContextInput(
                source=ContextSource.CONVERSATION,
                content=f"other-{i}", priority=90 + i,
            )
            c.metadata = {"session_id": f"s_other_{i}"}
            pool._collector.add_context(c)
            pool._cache_version += 1

        # 当前 session 块(低 priority)
        c_current = ContextInput(
            source=ContextSource.CONVERSATION,
            content="current-msg", priority=10,
        )
        c_current.metadata = {"session_id": "s_current"}
        pool._collector.add_context(c_current)
        pool._cache_version += 1

        # 默认 query: 当前 session 优先
        results = pool.query(limit=10)
        assert len(results) == 4
        # 第 1 条必须是当前 session 的(即使 priority 最低)
        assert results[0].content == "current-msg"
        assert results[0].metadata["session_id"] == "s_current"
        # 后续是跨 session 兜底(按 priority 降序)
        assert all(c.metadata["session_id"] != "s_current" for c in results[1:])

    def test_query_limit_fills_current_first(self):
        """核心场景: limit=2, 当前 1 条, 兜底 1 条跨 session"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="u", agent_id="a", session_id="s_current")
        c = ContextInput(source=ContextSource.CONVERSATION, content="current", priority=10)
        c.metadata = {"session_id": "s_current"}
        pool._collector.add_context(c)

        c2 = ContextInput(source=ContextSource.CONVERSATION, content="other-high", priority=99)
        c2.metadata = {"session_id": "s_other"}
        pool._collector.add_context(c2)
        pool._cache_version += 1

        results = pool.query(limit=2)
        assert len(results) == 2
        # 当前 session 占第 1 位
        assert results[0].content == "current"
        # 跨 session 兜底占第 2 位
        assert results[1].content == "other-high"

    def test_query_no_session_id_falls_back_to_priority(self):
        """向后兼容: pool 无 session_id 时按 priority 降序"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="u", agent_id="a")  # 无 session_id
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="msg1", priority=10
        ))
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="msg2", priority=99
        ))

        results = pool.query(limit=5)
        assert results[0].priority == 99
        assert results[1].priority == 10
