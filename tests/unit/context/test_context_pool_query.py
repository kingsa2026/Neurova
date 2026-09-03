"""
上下文池按需检索 query API 测试 — 根因 B

Bug: ContextPool 只有 get_contexts() 返回全量, 没有按需调取语义。
修复目标: 新增 query(query, ...) 方法, 支持:
  - 关键词过滤(query 字符串)
  - 按 source 过滤
  - 按 session_id 过滤(基于 metadata)
  - 按 tags 过滤
  - 按优先级排序
  - limit 限制
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestContextPoolQueryAPI:
    """根因 B: 必须提供按需调取 query() API"""

    def test_query_method_exists(self):
        """RED: ContextPool 必须有 query() 方法"""
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        assert hasattr(pool, "query"), "ContextPool 必须提供 query() 方法"
        assert callable(pool.query)

    def test_query_returns_list(self):
        """RED: query() 必须返回 List"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        result = pool.add_context_object(
            source=ContextSource.CONVERSATION, content="x"
        ) if hasattr(pool, "add_context_object") else _add(pool, "x")

        results = pool.query(query="x")
        assert isinstance(results, list)

    def test_query_filters_by_keyword(self):
        """RED: query(query="hello") 只返回含关键词的 chunk"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        _add(pool, "hello world")
        _add(pool, "goodbye world")
        _add(pool, "hello there")

        results = pool.query(query="hello", limit=10)
        contents = [r.content for r in results]
        assert "hello world" in contents
        assert "hello there" in contents
        assert "goodbye world" not in contents

    def test_query_filters_by_source(self):
        """RED: query(source=...) 必须按 source 过滤"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        # 混合来源
        _add(pool, "msg1", ContextSource.CONVERSATION)
        _add(pool, "insight1", ContextSource.EXPERIENCE)
        _add(pool, "msg2", ContextSource.CONVERSATION)

        results = pool.query(source=ContextSource.EXPERIENCE)
        assert len(results) == 1
        assert results[0].content == "insight1"

    def test_query_filters_by_session_id(self):
        """RED: query(session_id="s2") 必须只返回 s2 的 chunk(基于 metadata)"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        # 同 agent 不同 session, 但 query 仍可按 session_id 过滤
        pool_s1 = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        pool_s2 = ContextPool(user_id="u1", agent_id="a1", session_id="s2")

        # 在 s1 添加 3 条
        for i in range(3):
            _add(pool_s1, f"s1-msg-{i}", ContextSource.CONVERSATION)
        # 在 s2 添加 2 条
        for i in range(2):
            _add(pool_s2, f"s2-msg-{i}", ContextSource.CONVERSATION)

        # pool_s1 全部有 session_id=s1 metadata
        # 验证 query 可按 session_id 过滤(虽然默认 pool 已经隔离)
        s1_only = pool_s1.query(session_id="s1")
        assert len(s1_only) == 3

    def test_query_respects_limit(self):
        """RED: query(limit=2) 只返回前 2 条"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        for i in range(10):
            _add(pool, f"item-{i}", ContextSource.CONVERSATION)

        results = pool.query(limit=3)
        assert len(results) == 3

    def test_query_sorts_by_priority_desc(self):
        """RED: query 结果应按 priority 降序排序"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextInput, ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        # 不同优先级
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="low", priority=10
        ))
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="high", priority=100
        ))
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="mid", priority=50
        ))

        results = pool.query(limit=10)
        priorities = [r.priority for r in results]
        assert priorities == sorted(priorities, reverse=True), (
            f"结果应按 priority 降序, 实际: {priorities}"
        )


def _add(pool, content, source=None):
    from neurova.context.pool_models import ContextInput, ContextSource
    src = source or ContextSource.CONVERSATION
    chunk = ContextInput(source=src, content=content)
    pool.add_context(chunk)
    return chunk


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
