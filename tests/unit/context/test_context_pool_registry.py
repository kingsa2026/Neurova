"""
ContextPoolRegistry 跨 session 调取测试 — 根因 D

Bug: 没有"agent 专属上下文池"显式映射, 同 agent 跨 session 调取上下文
需要手动管理多个 ContextPool 实例, 无法按 agentID 索引。

修复目标: 新增 ContextPoolRegistry, 提供:
  - 按 agentID 索引所有 session 的 ContextPool
  - 同 agent 跨 session 按需调取(query agent-scoped)
  - 跨 session 关键词检索
  - 池缓存避免重复创建
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestContextPoolRegistry:
    """根因 D: ContextPoolRegistry 必须支持同 agent 跨 session 调取"""

    def setup_method(self):
        """每个测试前重置单例, 避免测试间状态污染"""
        from neurova.context_pool_registry import ContextPoolRegistry
        ContextPoolRegistry._instance = None
        ContextPoolRegistry().reset()

    def test_registry_class_exists(self):
        """RED: 必须存在 ContextPoolRegistry 类"""
        try:
            from neurova.context_pool_registry import ContextPoolRegistry
        except ImportError:
            pytest.fail("必须存在 neurova.context_pool_registry.ContextPoolRegistry")
        assert ContextPoolRegistry is not None

    def test_get_or_create_for_agent_session(self):
        """RED: get_or_create(agent_id, session_id) 返回/创建 ContextPool"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context_pool import ContextPool

        reg = ContextPoolRegistry()
        pool = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s1")
        assert isinstance(pool, ContextPool)
        assert pool.user_id == "u1"
        assert pool.agent_id == "a1"
        assert pool.session_id == "s1"

    def test_same_session_returns_same_pool(self):
        """RED: 同 (agent_id, session_id) 多次调用返回同一 pool 实例(缓存)"""
        from neurova.context_pool_registry import ContextPoolRegistry

        reg = ContextPoolRegistry()
        p1 = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s1")
        p2 = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s1")
        assert p1 is p2, "同 session 应返回同一 pool 实例(避免重复创建)"

    def test_different_sessions_isolated(self):
        """RED: 不同 session_id 返回不同 pool 实例(隔离)"""
        from neurova.context_pool_registry import ContextPoolRegistry

        reg = ContextPoolRegistry()
        p1 = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s1")
        p2 = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s2")
        assert p1 is not p2
        assert p1.session_id == "s1"
        assert p2.session_id == "s2"

    def test_query_across_sessions_for_agent(self):
        """RED: 跨 session 按需调取 - 同 agent 多个 session 一起检索"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        reg = ContextPoolRegistry()
        # 创建 2 个 session
        p1 = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s1")
        p2 = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s2")

        # 在两个 session 分别添加上下文
        p1.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="hello from s1"
        ))
        p2.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="hello from s2"
        ))
        p1.add_context(ContextInput(
            source=ContextSource.MEMORY, content="memory entry"
        ))

        # 跨 session 调取 "hello" 关键词
        results = reg.query_agent(user_id="u1", agent_id="a1", query="hello")
        contents = [r.content for r in results]
        assert "hello from s1" in contents
        assert "hello from s2" in contents
        assert "memory entry" not in contents  # 不匹配

    def test_query_filters_by_specific_session(self):
        """RED: query_agent(session_id='s1') 只检索指定 session"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        reg = ContextPoolRegistry()
        p1 = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s1")
        p2 = reg.get_or_create(user_id="u1", agent_id="a1", session_id="s2")

        p1.add_context(ContextInput(source=ContextSource.CONVERSATION, content="s1-msg"))
        p2.add_context(ContextInput(source=ContextSource.CONVERSATION, content="s2-msg"))

        # 只检索 s1
        results = reg.query_agent(
            user_id="u1", agent_id="a1", session_id="s1", query="msg"
        )
        assert len(results) == 1
        assert results[0].content == "s1-msg"
        assert results[0].metadata.get("session_id") == "s1"

    def test_query_different_agents_isolated(self):
        """RED: 不同 agent 的数据互不干扰"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        reg = ContextPoolRegistry()
        reg.get_or_create(user_id="u1", agent_id="agent_a", session_id="s1").add_context(
            ContextInput(source=ContextSource.CONVERSATION, content="agent-a-data")
        )
        reg.get_or_create(user_id="u1", agent_id="agent_b", session_id="s1").add_context(
            ContextInput(source=ContextSource.CONVERSATION, content="agent-b-data")
        )

        a_results = reg.query_agent(user_id="u1", agent_id="agent_a", query="data")
        b_results = reg.query_agent(user_id="u1", agent_id="agent_b", query="data")

        assert len(a_results) == 1
        assert a_results[0].content == "agent-a-data"
        assert len(b_results) == 1
        assert b_results[0].content == "agent-b-data"

    def test_list_sessions_for_agent(self):
        """RED: list_sessions(agent_id) 返回该 agent 的所有 session_id"""
        from neurova.context_pool_registry import ContextPoolRegistry

        reg = ContextPoolRegistry()
        reg.get_or_create(user_id="u1", agent_id="a1", session_id="s1")
        reg.get_or_create(user_id="u1", agent_id="a1", session_id="s2")
        reg.get_or_create(user_id="u1", agent_id="a1", session_id="s3")
        reg.get_or_create(user_id="u1", agent_id="a2", session_id="s1")

        sessions = reg.list_sessions(user_id="u1", agent_id="a1")
        assert set(sessions) == {"s1", "s2", "s3"}

    def test_clear_session(self):
        """RED: clear_session 释放某 session 的 pool"""
        from neurova.context_pool_registry import ContextPoolRegistry

        reg = ContextPoolRegistry()
        reg.get_or_create(user_id="u1", agent_id="a1", session_id="s1")
        reg.get_or_create(user_id="u1", agent_id="a1", session_id="s2")
        assert len(reg.list_sessions(user_id="u1", agent_id="a1")) == 2

        reg.clear_session(user_id="u1", agent_id="a1", session_id="s1")
        assert "s1" not in reg.list_sessions(user_id="u1", agent_id="a1")
        assert "s2" in reg.list_sessions(user_id="u1", agent_id="a1")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
