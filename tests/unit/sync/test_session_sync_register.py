"""S2 split-brain + session_id 丢失 RED 测试

Bug (Critical #2/#3): chat_pipeline._sync_event 在 SessionSyncManager 找不到
ctx.session_id 时,调 create_session() 生成全新 session_id,忽略 ctx.session_id.
后果: 每次 chat 请求可能创建一个新 UnifiedSession,文件层和内存层 session_id
永不收敛 — split-brain.

链路 (BUG 状态):
  chat_pipeline._sync_event(ctx, event_type, payload):
    session_id = ctx.session_id or "default"      # 例: "abc12345"
    session = sync_manager.get_session(session_id) # None (SessionSyncManager 是空 dict)
    if not session:
        session = sync_manager.create_session(...)  # 生成 "session_xxxxxxxxxxxx"
        session_id = session.session_id              # ❌ 丢弃 "abc12345"
    broadcast_event(session_id, event)               # 广播到 "session_xxxx",前端看不到

修复策略: SessionSyncManager 新增 register_or_create_session(session_id, ...),
若 session_id 已注册则返回,否则用该 session_id 创建 UnifiedSession (不生成新 ID).
_sync_event 改调此方法,保证 ctx.session_id 与 SessionSyncManager 内 session_id 一致.

参考: ADR 0008 候选 #5 (SessionSyncManager 接入 SessionRepository ABC).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def sync_manager():
    """创建干净的 SessionSyncManager 实例 (非单例)."""
    from neurova.sync.session_sync_manager import SessionSyncManager

    # 直接构造,不走单例工厂
    return SessionSyncManager(config={"max_sessions": 100, "session_timeout": 3600})


# ── Behavior contracts ─────────────────────────────────


class TestSessionSyncManagerRegisterOrCreate:
    """S2: SessionSyncManager 应支持用外部 session_id 注册 (不生成新 ID)."""

    def test_register_with_external_session_id(self, sync_manager):
        """RED: register_or_create_session 用传入的 session_id 注册,不生成新 ID."""
        external_sid = "abc12345"  # 来自 SessionManager (文件层) 的 session_id

        session = sync_manager.register_or_create_session(
            session_id=external_sid,
            user_id="user-1",
            agent_id="default",
        )

        assert session.session_id == external_sid, (
            f"Expected session_id == '{external_sid}' (外部传入), "
            f"got '{session.session_id}'. "
            f"BUG: create_session 生成新 session_id,导致 split-brain."
        )

    def test_get_session_finds_registered_session(self, sync_manager):
        """RED: 注册后 get_session 能用同一 session_id 找到."""
        external_sid = "abc12345"

        sync_manager.register_or_create_session(
            session_id=external_sid, user_id="user-1", agent_id="default"
        )

        found = sync_manager.get_session(external_sid)
        assert found is not None, (
            "register_or_create_session 后 get_session 应找到该 session_id. "
            "BUG: SessionSyncManager 内部 session_id 与外部不一致."
        )
        assert found.session_id == external_sid

    def test_register_idempotent(self, sync_manager):
        """RED: 同一 session_id 多次注册应返回同一 session (不创建重复)."""
        external_sid = "abc12345"

        s1 = sync_manager.register_or_create_session(
            session_id=external_sid, user_id="user-1", agent_id="default"
        )
        s2 = sync_manager.register_or_create_session(
            session_id=external_sid, user_id="user-1", agent_id="default"
        )

        assert s1.session_id == external_sid
        assert s2.session_id == external_sid
        assert s1 is s2, (
            "同一 session_id 多次注册应返回同一 UnifiedSession 实例. "
            "BUG: 重复创建导致内存泄漏 + split-brain."
        )

    def test_register_none_session_id_falls_back_to_create(self, sync_manager):
        """RED: session_id=None 时退化为原 create_session 行为 (生成新 ID)."""
        session = sync_manager.register_or_create_session(
            session_id=None, user_id="user-1", agent_id="default"
        )

        # 退化为 create_session: 生成 session_<uuid12> 格式
        assert session.session_id.startswith("session_"), (
            "session_id=None 时应退化为 create_session 行为,生成 'session_<uuid12>'. "
            f"Got: '{session.session_id}'"
        )


class TestChatPipelineSyncEventUsesCtxSessionId:
    """S2: chat_pipeline._sync_event 应使用 ctx.session_id,不创建新 ID."""

    def test_sync_event_uses_ctx_session_id(self, sync_manager):
        """RED: _sync_event 应在 SessionSyncManager 中用 ctx.session_id 注册."""
        import asyncio

        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext

        # 构造最小 ChatPipeline mock
        pipeline = MagicMock(spec=ChatPipeline)
        pipeline.session_sync_manager = sync_manager
        pipeline.config = MagicMock(agent_id="default")

        ctx = ChatContext(user_input="hi", session_id="abc12345", metadata={"user_id": "user-1"})

        # 调用真实 _sync_event 方法 (async,必须用 asyncio.run await)
        async def call_sync():
            await ChatPipeline._sync_event(pipeline, ctx, "message_sent", {"content": "hi"})

        asyncio.run(call_sync())

        # 验证: SessionSyncManager 中应存在 ctx.session_id 注册的 session
        session = sync_manager.get_session("abc12345")
        assert session is not None, (
            "_sync_event 应在 SessionSyncManager 中用 ctx.session_id 注册. "
            "BUG: 当前代码 create_session 忽略 ctx.session_id,生成新 ID."
        )
        assert session.session_id == "abc12345", (
            f"Expected session_id == 'abc12345', got '{session.session_id}'."
        )

    def test_sync_event_broadcasts_to_ctx_session_id(self, sync_manager):
        """RED: broadcast_event 应广播到 ctx.session_id (而非新生成的 ID)."""
        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext

        pipeline = MagicMock(spec=ChatPipeline)
        pipeline.session_sync_manager = sync_manager
        pipeline.config = MagicMock(agent_id="default")

        ctx = ChatContext(user_input="hi", session_id="xyz98765", metadata={"user_id": "user-1"})

        # 调用真实 _sync_event
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            asyncio.coroutine(lambda: None)()  # 确保 event loop 可用
        ) if False else None  # 跳过 event loop 初始化,_sync_event 内部用 await

        # 使用 asyncio.run 调用 async _sync_event
        async def call_sync():
            await ChatPipeline._sync_event(pipeline, ctx, "message_sent", {"content": "hi"})

        asyncio.run(call_sync())

        # 验证: ctx.session_id 在 SessionSyncManager 中可查
        session = sync_manager.get_session("xyz98765")
        assert session is not None, "broadcast_event 应广播到 ctx.session_id"
        # 验证: 事件被记录在 session.history 中
        assert len(session.history) > 0, "事件应被记录在 session.history 中"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
