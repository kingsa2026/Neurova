"""
端到端测试: 上下文池全功能链路 — 验证根因 A+B+C+D 联合工作

完整场景:
  - 同 agent 3 个 session 各自独立
  - 跨 session 按需调取(关键词+source+session 过滤)
  - session 隔离(同 agent 不同 session 数据不串扰)
  - 优先级排序 + 限流
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


class TestEndToEndContextPoolFlow:
    """根因 4 端到端: 4 个根因联合工作"""

    def test_full_signal_chain(self):
        """完整链路: add → metadata 注入 → session 隔离 → 跨 session query"""
        from neurova.context_pool_registry import ContextPoolRegistry
        from neurova.context.pool_models import ContextInput, ContextSource

        _setup()
        reg = ContextPoolRegistry()

        # === 场景 1: 同 agent 3 个 session ===
        p_s1 = reg.get_or_create(user_id="alice", agent_id="assistant", session_id="s1")
        p_s2 = reg.get_or_create(user_id="alice", agent_id="assistant", session_id="s2")
        p_s3 = reg.get_or_create(user_id="alice", agent_id="assistant", session_id="s3")

        # === Step 1: add_context 自动注入 sessionID 标签(根因 A) ===
        p_s1.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="用户问了 Python 的 GIL 是什么",
            priority=80,
        ))
        p_s2.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="用户偏好简洁回答",
            priority=60,
        ))
        p_s3.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="用户问了 Java 的 GC",
            priority=70,
        ))

        # === Step 2: 每个 chunk 都带正确的 sessionID metadata ===
        s1_chunks = p_s1.get_contexts()
        assert s1_chunks[0].metadata["session_id"] == "s1"
        assert s1_chunks[0].metadata["agent_id"] == "assistant"
        assert s1_chunks[0].metadata["user_id"] == "alice"

        # === Step 3: 单 session 内部按需调取(根因 B) ===
        s1_results = p_s1.query(query="Python")
        assert len(s1_results) == 1
        assert s1_results[0].content.startswith("用户问了 Python")

        # === Step 4: 跨 session 按需调取(根因 D) ===
        all_results = reg.query_agent(
            user_id="alice", agent_id="assistant", query="用户"
        )
        assert len(all_results) == 3  # 3 个 session 各 1 条

        # 优先级降序: 80, 70, 60
        priorities = [r.priority for r in all_results]
        assert priorities == [80, 70, 60]

        # === Step 5: 跨 session 关键词过滤 ===
        python_results = reg.query_agent(
            user_id="alice", agent_id="assistant", query="Python"
        )
        assert len(python_results) == 1
        assert python_results[0].metadata["session_id"] == "s1"

        # === Step 6: 跨 session source 过滤 ===
        memory_results = reg.query_agent(
            user_id="alice", agent_id="assistant", source=ContextSource.MEMORY
        )
        assert len(memory_results) == 1
        assert memory_results[0].metadata["session_id"] == "s2"

        # === Step 7: 限定 session 调取 ===
        s3_only = reg.query_agent(
            user_id="alice", agent_id="assistant", session_id="s3"
        )
        assert len(s3_only) == 1
        assert s3_only[0].content.startswith("用户问了 Java")

        # === Step 8: 跨 agent 隔离 ===
        reg.get_or_create(user_id="alice", agent_id="other_agent", session_id="s1")
        other_results = reg.query_agent(
            user_id="alice", agent_id="other_agent"
        )
        assert len(other_results) == 0  # other_agent 没有数据

        # === Step 9: list_sessions ===
        sessions = reg.list_sessions(user_id="alice", agent_id="assistant")
        assert set(sessions) == {"s1", "s2", "s3"}

    def test_pool_cache_dedup(self):
        """缓存去重: 同 session 多次获取返回同一 pool"""
        from neurova.context_pool_registry import ContextPoolRegistry

        _setup()
        reg = ContextPoolRegistry()
        p1 = reg.get_or_create(user_id="u", agent_id="a", session_id="s")
        p2 = reg.get_or_create(user_id="u", agent_id="a", session_id="s")
        assert p1 is p2
        assert reg.get_pool_count() == 1

    def test_session_pool_lifecycle(self):
        """session 池生命周期: 创建 → 列表 → 清除"""
        from neurova.context_pool_registry import ContextPoolRegistry

        _setup()
        reg = ContextPoolRegistry()
        reg.get_or_create(user_id="u", agent_id="a", session_id="s1")
        reg.get_or_create(user_id="u", agent_id="a", session_id="s2")
        reg.get_or_create(user_id="u", agent_id="a", session_id="s3")
        assert reg.get_pool_count() == 3

        # 清除 s2
        ok = reg.clear_session(user_id="u", agent_id="a", session_id="s2")
        assert ok is True
        assert reg.get_pool_count() == 2
        assert "s2" not in reg.list_sessions(user_id="u", agent_id="a")

        # 重复清除应返回 False
        ok2 = reg.clear_session(user_id="u", agent_id="a", session_id="s2")
        assert ok2 is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
