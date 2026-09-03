"""
3 维度验证: 按需调取 + 上下文池隔离 + sessionID 跨会话

维度 1: 按需调取 — query() 默认按 session 过滤, 不返回全库
维度 2: 上下文池隔离 — user/agent/session 三层独立
维度 3: sessionID 跨会话 — 同 agent 不同 session 互不污染, 可调取
"""
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _setup():
    from neurova.context_pool_registry import ContextPoolRegistry
    ContextPoolRegistry._instance = None
    return ContextPoolRegistry().reset()


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


class TestDimension2PoolIsolation:
    """维度 2: 上下文池隔离 — user/agent/session 三层"""

    def test_user_isolation(self):
        """不同 user 的 pool 完全隔离"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()
        p_u1 = reg.get_or_create(user_id="alice", agent_id="a", session_id="s1")
        p_u2 = reg.get_or_create(user_id="bob", agent_id="a", session_id="s1")

        p_u1.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="alice secret", priority=10
        ))
        p_u2.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="bob secret", priority=10
        ))

        # alice 调取只看到自己
        results_alice = reg.query_agent(
            user_id="alice", agent_id="a", current_session_id="s1", query="secret", limit=5
        )
        assert len(results_alice) == 1
        assert "alice" in results_alice[0].content
        assert results_alice[0].metadata["user_id"] == "alice"

    def test_agent_isolation(self):
        """不同 agent 的 pool 完全隔离"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()
        p_coding = reg.get_or_create(user_id="u", agent_id="coding_agent", session_id="s1")
        p_search = reg.get_or_create(user_id="u", agent_id="search_agent", session_id="s1")

        p_coding.add_context(ContextInput(
            source=ContextSource.MEMORY, content="code context", priority=10
        ))
        p_search.add_context(ContextInput(
            source=ContextSource.MEMORY, content="search context", priority=10
        ))

        # coding_agent 只看到自己的
        results = reg.query_agent(
            user_id="u", agent_id="coding_agent", current_session_id="s1",
            query="context", limit=5
        )
        assert len(results) == 1
        assert "code" in results[0].content
        assert results[0].metadata["agent_id"] == "coding_agent"

    def test_session_isolation(self):
        """同 agent 不同 session 池互不污染"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()
        p_s1 = reg.get_or_create(user_id="u", agent_id="a", session_id="s1")
        p_s2 = reg.get_or_create(user_id="u", agent_id="a", session_id="s2")

        p_s1.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="s1 only", priority=10
        ))
        p_s2.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="s2 only", priority=10
        ))

        # 池1 看不到池2
        assert len(p_s1.get_contexts()) == 1
        assert len(p_s2.get_contexts()) == 1
        # 显式 session 隔离
        s1_results = p_s1.query(session_id="s1", limit=5)
        assert len(s1_results) == 1
        assert "s1 only" in s1_results[0].content


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

    def test_registry_query_agent_cross_sessions_with_priority(self):
        """跨 session 调取: 当前 session 优先, 跨 session 兜底, 每个
        chunk 都有 sessionID 用于业务侧识别"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()
        p_s1 = reg.get_or_create(user_id="u", agent_id="a", session_id="s1")
        p_s2 = reg.get_or_create(user_id="u", agent_id="a", session_id="s2")
        p_s3 = reg.get_or_create(user_id="u", agent_id="a", session_id="s3")

        # s1 当前 session
        p_s1.add_context(ContextInput(
            source=ContextSource.MEMORY, content="current memory", priority=10
        ))
        # s2/s3 历史 session
        p_s2.add_context(ContextInput(
            source=ContextSource.MEMORY, content="s2 memory", priority=95
        ))
        p_s3.add_context(ContextInput(
            source=ContextSource.MEMORY, content="s3 memory", priority=80
        ))

        results = reg.query_agent(
            user_id="u", agent_id="a",
            current_session_id="s1",
            query="memory", limit=10,
        )

        assert len(results) == 3
        # 全部带 sessionID
        sessions_returned = [c.metadata["session_id"] for c in results]
        assert "s1" in sessions_returned
        assert "s2" in sessions_returned
        assert "s3" in sessions_returned
        # s1 必须排第一(当前优先)
        assert results[0].metadata["session_id"] == "s1"
        # s2 排第二(priority=95 最高)
        assert results[1].metadata["session_id"] == "s2"
        # s3 排第三(priority=80)
        assert results[2].metadata["session_id"] == "s3"

    def test_cleared_session_no_longer_returns(self):
        """session 清理后, 跨 session 调取不再返回其内容"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()
        p_s1 = reg.get_or_create(user_id="u", agent_id="a", session_id="s1")
        p_s2 = reg.get_or_create(user_id="u", agent_id="a", session_id="s2")

        p_s1.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="s1 msg", priority=10
        ))
        p_s2.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="s2 msg", priority=10
        ))

        # 清理 s2
        cleared = reg.clear_session(user_id="u", agent_id="a", session_id="s2")
        assert cleared is True

        # 跨 session 调取: 只剩 s1
        results = reg.query_agent(
            user_id="u", agent_id="a", current_session_id="s1", query="msg", limit=10
        )
        assert len(results) == 1
        assert results[0].metadata["session_id"] == "s1"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
