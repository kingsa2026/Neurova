"""
端到端: 当前 session 优先调取规则

完整场景:
  - 模拟真实 agent 在 s1 会话中
  - 历史 s2 会话已积累了相关经验
  - 当前 query 应优先用 s1 内容, 跨 s2 兜底
  - 切换到 s2 时, s2 自动成为当前 session
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


class TestCurrentSessionPriorityE2E:
    """端到端: 当前 session 优先规则"""

    def test_scenario_realistic_agent_conversation(self):
        """真实场景: 用户在 s1 问 Python, 历史 s2 已学过 Python"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()

        # === 历史 session s2: 之前学过的经验(高 priority) ===
        p_s2 = reg.get_or_create(user_id="alice", agent_id="coding_agent", session_id="s2")
        p_s2.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="Python GIL 是全局解释器锁, 限制多线程并行",
            priority=95,
        ))
        p_s2.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="Python 用 with 语句管理资源",
            priority=85,
        ))

        # === 当前 session s1: 用户的当前对话 ===
        p_s1 = reg.get_or_create(user_id="alice", agent_id="coding_agent", session_id="s1")
        p_s1.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="用户当前问: 帮我写个 Python 函数计算斐波那契",
            priority=50,
        ))

        # === 用户 query: "Python" ===
        # 当前 session 优先
        results = reg.query_agent(
            user_id="alice",
            agent_id="coding_agent",
            current_session_id="s1",
            query="Python",
            limit=5,
        )

        # 全部命中 3 条
        assert len(results) == 3
        # 第 1 条: 当前 session(即使 priority 最低)
        assert "斐波那契" in results[0].content
        assert results[0].metadata["session_id"] == "s1"
        # 后续 2 条: s2 跨 session 兜底(按 priority 降序)
        assert all(c.metadata["session_id"] == "s2" for c in results[1:])
        assert results[1].priority == 95  # GIL
        assert results[2].priority == 85  # with

    def test_scenario_switch_active_session(self):
        """切换当前 session: s2 变成当前时, s2 优先"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()
        p_s1 = reg.get_or_create(user_id="u", agent_id="a", session_id="s1")
        p_s2 = reg.get_or_create(user_id="u", agent_id="a", session_id="s2")

        p_s1.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="s1 low", priority=10
        ))
        p_s2.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="s2 high", priority=99
        ))

        # 切到 s2: s2 优先
        results = reg.query_agent(
            user_id="u", agent_id="a",
            current_session_id="s2",
            query="", limit=5,
        )
        assert results[0].content == "s2 high"
        assert results[0].metadata["session_id"] == "s2"

    def test_scenario_empty_current_session_falls_back_to_others(self):
        """当前 session 还没数据时, 应跨 session 兜底"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()
        p_s1 = reg.get_or_create(user_id="u", agent_id="a", session_id="s1")
        p_s2 = reg.get_or_create(user_id="u", agent_id="a", session_id="s2")

        # s1 空(当前)
        # s2 有数据
        p_s2.add_context(ContextInput(
            source=ContextSource.CONVERSATION, content="s2-msg", priority=99
        ))

        results = reg.query_agent(
            user_id="u", agent_id="a",
            current_session_id="s1",
            query="msg", limit=5,
        )
        # 应拿到 s2 的兜底
        assert len(results) == 1
        assert results[0].content == "s2-msg"
        assert results[0].metadata["session_id"] == "s2"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
