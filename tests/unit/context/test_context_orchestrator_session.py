"""
ContextOrchestrator session_id 绑定测试 — 根因 C

Bug: ContextOrchestrator.__init__ 创建 ContextPool 时不传 session_id,
导致 "session 隔离" 在 pool 级别未生效。
修复目标: ContextOrchestrator 必须接受 session_id 并将其传递给 ContextPool。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestContextOrchestratorSessionBinding:
    """根因 C: ContextOrchestrator 创建时必须绑定 session_id"""

    def test_init_accepts_session_id(self):
        """RED: ContextOrchestrator(session_id='s1') 必须被接受"""
        from neurova.context.orchestrator import ContextOrchestrator

        mock_agent = MagicMock()
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.user_id = "u1"
        mock_agent.agent_id = "a1"

        # 不抛 TypeError 即通过
        co = ContextOrchestrator(mock_agent, use_pool=True, session_id="s_xyz")
        assert co.context_pool is not None
        assert co.context_pool.session_id == "s_xyz", (
            f"ContextPool.session_id 应该是 's_xyz', 实际: {co.context_pool.session_id}"
        )

    def test_init_without_session_id_keeps_legacy_behavior(self):
        """GREEN: 不传 session_id 时, 默认 None(向后兼容)"""
        from neurova.context.orchestrator import ContextOrchestrator

        mock_agent = MagicMock()
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.user_id = "u1"
        mock_agent.agent_id = "a1"

        co = ContextOrchestrator(mock_agent, use_pool=True)
        assert co.context_pool is not None
        # 默认 None
        assert co.context_pool.session_id is None

    def test_session_id_propagates_to_chunks(self):
        """RED: chunks 必须带 session_id metadata"""
        from neurova.context.orchestrator import ContextOrchestrator
        from neurova.context.pool_models import ContextSource

        mock_agent = MagicMock()
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.user_id = "u1"
        mock_agent.agent_id = "a1"

        co = ContextOrchestrator(mock_agent, use_pool=True, session_id="s_test")
        co.context_pool.add_context_object(
            source=ContextSource.CONVERSATION, content="x"
        ) if hasattr(co.context_pool, "add_context_object") else _add(co.context_pool, "x")

        # chunk 必须有 session_id
        chunks = co.context_pool.get_contexts()
        assert len(chunks) >= 1
        assert chunks[0].metadata.get("session_id") == "s_test"

    def test_set_session_id_runtime(self):
        """RED: 应支持运行时切换 session_id(用于跨 session 调取)"""
        from neurova.context.orchestrator import ContextOrchestrator

        mock_agent = MagicMock()
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.user_id = "u1"
        mock_agent.agent_id = "a1"

        co = ContextOrchestrator(mock_agent, use_pool=True, session_id="s1")
        # 切换 session
        co.set_session_id("s2")
        assert co.context_pool.session_id == "s2"


def _add(pool, content):
    from neurova.context.pool_models import ContextInput, ContextSource
    chunk = ContextInput(source=ContextSource.CONVERSATION, content=content)
    pool.add_context(chunk)
    return chunk


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
