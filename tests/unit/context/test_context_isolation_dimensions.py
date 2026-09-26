"""上下文池隔离维度测试

**B6-10 批次 F 范围收窄（2026-09-26）**：池注册表的多池机制已退场（它是被 T-02
取代的第二套隔离机制——按池分会话 vs 真设计的单池 + `chat_scope` 作用域标签）。
依赖 `reg.get_or_create` / `reg.query_agent` 的用例随之退役；**被锁的隔离契约
搬到真面**：user / agent / session 三层隔离由池自身的 `isolation_key` 与写入
咽喉打标承载（`tests/unit/context/test_pool_scope_wiring.py` /
`test_context_pool_isolation.py`），按 session 过滤由 `ContextPool.query` 承载
（`test_context_pool_query.py`）。

本文件保留不依赖注册表的两组：

- 维度 1 按需调取：`query()` 默认按 session 过滤、不返回全库；
- 维度 3 metadata 契约：每条 chunk 的 metadata 必须带 sessionID。

退役文件（整份只测多池机制）：`test_context_pool_registry.py` /
`test_context_pool_end_to_end.py` / `test_current_session_priority_e2e.py`；
`test_default_session_priority.py` 的 registry 组退役、pool 组保留。
"""
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestDimension1OnDemandQuery:
    """维度 1: 按需调取 — query 必须显式触发, 不预加载全库"""

    def test_query_default_not_returns_all(self):
        """默认 query() 只返回符合过滤条件的 chunk, 不返回所有"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        # 加 10 条
        for i in range(10):
            pool.add_context(ContextInput(
                source=ContextSource.CONVERSATION,
                content=f"msg-{i}", priority=50,
            ))

        # query 限制 limit=3, 只返回 3 条
        results = pool.query(limit=3)
        assert len(results) == 3
        # 关键词过滤: 只返回命中 "msg-5" 的
        results2 = pool.query(query="5", limit=10)
        assert len(results2) == 1
        assert "5" in results2[0].content

    def test_query_is_lazy_not_eager(self):
        """query() 在调用前不会预过滤/聚合, 是真正的 lazy"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="u", agent_id="a", session_id="s1")
        # 加 100 条
        for i in range(100):
            pool.add_context(ContextInput(
                source=ContextSource.CONVERSATION,
                content=f"chunk-{i}", priority=50,
            ))

        # 不调 query 就不会触发 filter
        # query 之后只返回 limit
        results = pool.query(query="chunk-42", limit=10)
        assert len(results) == 1
        assert "42" in results[0].content


class TestDimension3SessionIDCrossSession:
    """维度 3: sessionID 跨会话 — 同 agent 不同 session 可跨调"""

    def test_chunk_metadata_carries_session_id(self):
        """每个 chunk 的 metadata 必须带 sessionID, 供跨会话查询识别"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="u", agent_id="a", session_id="session_xyz")
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="hello", priority=10
        ))

        results = pool.query(limit=1)
        assert results[0].metadata.get("session_id") == "session_xyz"

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
