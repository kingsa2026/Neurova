"""
上下文池 SessionID 标签注入测试 — 根因 A

Bug: ContextPool.add_context() 不把 session_id/agent_id/user_id 注入到
ContextInput.metadata, 导致按需调取时无法按 sessionID 过滤。

修复目标: 每次 add_context() 必须自动注入 3 个标签到 metadata。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestContextPoolMetadataInjection:
    """根因 A: chunk 必须带 session_id/agent_id/user_id 标签"""

    def test_add_context_injects_session_id_into_metadata(self):
        """RED: add_context() 后, chunk.metadata 必须包含 session_id"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        chunk = pool.add_context_with_id(
            source=ContextSource.CONVERSATION,
            content="hello",
        ) if hasattr(pool, "add_context_with_id") else _add(pool, "hello")

        assert "session_id" in chunk.metadata, (
            "add_context 必须自动注入 session_id 到 chunk.metadata"
        )
        assert chunk.metadata["session_id"] == "s1"

    def test_add_context_injects_agent_id(self):
        """RED: chunk.metadata 必须包含 agent_id"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="u1", agent_id="agent_alpha", session_id="s1")
        chunk = _add(pool, "msg")
        assert chunk.metadata.get("agent_id") == "agent_alpha"

    def test_add_context_injects_user_id(self):
        """RED: chunk.metadata 必须包含 user_id"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="user_42", agent_id="a1", session_id="s1")
        chunk = _add(pool, "msg")
        assert chunk.metadata.get("user_id") == "user_42"

    def test_chunk_metadata_keys_complete(self):
        """RED: 3 个标签必须同时存在(完整性)"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s_xyz")
        chunk = _add(pool, "any")
        for key in ("session_id", "agent_id", "user_id"):
            assert key in chunk.metadata, f"chunk.metadata 缺少 {key}"
            assert chunk.metadata[key], f"{key} 不能为空"

    def test_existing_user_metadata_preserved(self):
        """GREEN: 用户传入的 metadata 不能被覆盖"""
        from neurova.context_pool import ContextPool
        from neurova.context.pool_models import ContextSource

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        # 通过 metadata 参数显式传入 session_id, 应当被尊重(不可覆盖)
        from neurova.context.pool_models import ContextInput
        chunk = ContextInput(
            source=ContextSource.CONVERSATION,
            content="msg",
            metadata={"session_id": "explicit_s", "custom": "v"},
        )
        pool.add_context(chunk)
        # 用户显式 session_id 优先
        assert chunk.metadata.get("session_id") == "explicit_s"
        assert chunk.metadata.get("custom") == "v"
        # agent_id/user_id 仍被注入
        assert chunk.metadata.get("agent_id") == "a1"
        assert chunk.metadata.get("user_id") == "u1"


def _add(pool, content):
    """辅助: 简化 add_context 调用"""
    from neurova.context.pool_models import ContextInput, ContextSource
    chunk = ContextInput(source=ContextSource.CONVERSATION, content=content)
    pool.add_context(chunk)
    return chunk


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
