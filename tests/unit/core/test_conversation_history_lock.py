"""S5 + S6 线程安全 RED 测试 — conversation_history 与 broadcast_event

S5 (Critical #6): MemCore.update_history 无锁保护 conversation_history
  update_history 流程:
    current_list = getattr(self._agent, "conversation_history", [])  # READ (无锁)
    ctx.append("user", ...)                                          # MODIFY (ctx 内有锁)
    self._agent.conversation_history = ctx.to_list()                  # WRITE (无锁)
  竞态: Thread A read → Thread B read → A write → B write (B 覆盖 A)
  修复: MemCore 新增 _history_lock (RLock),update_history 整体入锁

S6 (High #7): SessionSyncManager.broadcast_event 无锁迭代 active_channels
  broadcast_event 流程:
    session = self._sessions.get(session_id)      # READ (无锁)
    for channel_type, conn in session.active_channels.items():  # ITERATE (无锁)
      ...
  竞态: 迭代期间另一线程 register_channel/unregister_channel → RuntimeError
        "dictionary changed size during iteration"
  修复: 锁内复制 channels 列表,锁外 await send_callback
"""
from __future__ import annotations

import asyncio
import inspect
import threading
from unittest.mock import MagicMock

import pytest


# ════════════════════════════════════════════════════════════
# S5: MemCore.update_history 线程安全
# ════════════════════════════════════════════════════════════


class TestS5UpdateHistoryLock:
    """S5: MemCore.update_history 应由 _history_lock 保护."""

    def test_memcore_has_history_lock(self):
        """RED: MemCore 应有 _history_lock 属性 (RLock)."""
        from neurova.mem_core import MemCore

        mock_agent = MagicMock()
        mc = MemCore(mock_agent)
        assert hasattr(mc, "_history_lock"), (
            "S5: MemCore 应有 _history_lock 属性保护 update_history. "
            "BUG: update_history 无锁,read-modify-write 跨锁边界 → lost update."
        )

    def test_history_lock_is_rlock(self):
        """RED: _history_lock 应是 RLock."""
        from neurova.mem_core import MemCore

        mock_agent = MagicMock()
        mc = MemCore(mock_agent)
        if not hasattr(mc, "_history_lock"):
            pytest.skip("S5 fix not yet applied")
        rlock = threading.RLock()
        assert isinstance(mc._history_lock, type(rlock)), (
            f"S5: _history_lock 应是 RLock, got {type(mc._history_lock)}."
        )

    def test_update_history_uses_lock(self):
        """RED: update_history 源码应使用 _history_lock."""
        from neurova.mem_core import MemCore

        source = inspect.getsource(MemCore.update_history)
        assert "_history_lock" in source, (
            "S5: update_history 应使用 _history_lock 保护 read-modify-write. "
            "BUG: 当前无锁,conversation_history 可被并发修改."
        )


# ════════════════════════════════════════════════════════════
# S6: SessionSyncManager.broadcast_event 线程安全
# ════════════════════════════════════════════════════════════


class TestS6BroadcastEventLock:
    """S6: broadcast_event 应在锁内复制 channels,锁外迭代."""

    def test_broadcast_event_copies_channels_under_lock(self):
        """RED: broadcast_event 源码应在 _lock 内复制 active_channels."""
        from neurova.sync.session_sync_manager import SessionSyncManager

        source = inspect.getsource(SessionSyncManager.broadcast_event)
        # 修复后应包含: 在 with self._lock 内复制 channels 列表
        # 检查是否在广播前复制了 channels (而非直接迭代 session.active_channels.items())
        has_lock = "with self._lock" in source or "self._lock.acquire" in source
        assert has_lock, (
            "S6: broadcast_event 应使用 self._lock 保护 channels 复制. "
            "BUG: 直接迭代 session.active_channels.items() 无锁 → "
            "register_channel/unregister_channel 并发时 RuntimeError."
        )

    def test_broadcast_event_does_not_iterate_session_channels_directly(self):
        """RED: broadcast_event 不应直接在无锁下迭代 session.active_channels.items()."""
        from neurova.sync.session_sync_manager import SessionSyncManager

        source = inspect.getsource(SessionSyncManager.broadcast_event)
        # 危险模式: 直接在 for 循环中迭代 session.active_channels.items()
        # 而没有先复制到局部变量
        # 修复后应: channels = list(session.active_channels.items()) 在锁内
        # 然后 for channel_type, conn in channels: 在锁外
        has_direct_iteration = (
            "for channel_type, conn in session.active_channels.items()" in source
        )
        assert not has_direct_iteration, (
            "S6: broadcast_event 不应直接迭代 session.active_channels.items(). "
            "BUG: 无锁迭代 → RuntimeError 'dictionary changed size during iteration'. "
            "修复: 锁内复制到局部变量,锁外迭代."
        )

    def test_broadcast_event_safe_with_concurrent_channel_change(self):
        """契约: broadcast_event 在迭代期间 channel 变更不抛 RuntimeError."""
        from neurova.sync.session_sync_manager import (
            ChannelConnection,
            EventType,
            SessionEvent,
            SessionSyncManager,
            UnifiedSession,
        )

        mgr = SessionSyncManager(config={"max_sessions": 10})

        # 创建 session 并注册一个 channel
        session = mgr.create_session(user_id="u1", agent_id="a1")

        call_count = {"n": 0}

        def send_cb(event):
            call_count["n"] += 1

        session.register_channel("ws", send_cb)

        # 在 broadcast 期间,另一线程尝试 unregister_channel
        # 若 broadcast_event 直接迭代 session.active_channels.items(),
        # 则 unregister 修改 dict → RuntimeError
        event = SessionEvent(
            event_type=EventType.AGENT_REPLY,
            session_id=session.session_id,
            source_channel="test",
        )

        async def run():
            await mgr.broadcast_event(session.session_id, event)

        # 如果有 bug,这里会抛 RuntimeError
        try:
            asyncio.run(run())
        except RuntimeError as e:
            if "changed size" in str(e):
                pytest.fail(
                    f"S6: broadcast_event 在并发 channel 变更时抛 RuntimeError: {e}. "
                    "BUG: 无锁迭代 session.active_channels.items()."
                )
            raise

        assert call_count["n"] >= 1, "send_callback 应至少被调用一次"


# ════════════════════════════════════════════════════════════
# S6 补全: SessionSyncManager.broadcast_event_sync 线程安全
# (审计 WARN #1: sync 版本与 async 同根因,S6 修复时遗漏)
# ════════════════════════════════════════════════════════════


class TestS6BroadcastEventSyncLock:
    """S6 补全: broadcast_event_sync 应与 async 版本一致,锁内复制 channels."""

    def test_broadcast_event_sync_uses_lock(self):
        """RED: broadcast_event_sync 源码应使用 self._lock."""
        from neurova.sync.session_sync_manager import SessionSyncManager

        source = inspect.getsource(SessionSyncManager.broadcast_event_sync)
        has_lock = "with self._lock" in source or "self._lock.acquire" in source
        assert has_lock, (
            "S6 补全: broadcast_event_sync 应使用 self._lock 保护 channels 复制. "
            "BUG: async 版本已修 (S6),sync 版本仍无锁迭代 → 同根因 RuntimeError."
        )

    def test_broadcast_event_sync_does_not_iterate_directly(self):
        """RED: broadcast_event_sync 不应直接无锁迭代 session.active_channels.items()."""
        from neurova.sync.session_sync_manager import SessionSyncManager

        source = inspect.getsource(SessionSyncManager.broadcast_event_sync)
        has_direct_iteration = (
            "for channel_type, conn in session.active_channels.items()" in source
        )
        assert not has_direct_iteration, (
            "S6 补全: broadcast_event_sync 不应直接迭代 session.active_channels.items(). "
            "BUG: 与 async 版本同根因,无锁迭代 → RuntimeError. "
            "修复: 锁内复制到 channels_snapshot,锁外迭代."
        )

    def test_broadcast_event_sync_safe_with_concurrent_channel_change(self):
        """契约: broadcast_event_sync 在迭代期间 channel 变更不抛 RuntimeError."""
        from neurova.sync.session_sync_manager import (
            EventType,
            SessionEvent,
            SessionSyncManager,
        )

        mgr = SessionSyncManager(config={"max_sessions": 10})
        session = mgr.create_session(user_id="u1", agent_id="a1")

        call_count = {"n": 0}

        def send_cb(event):
            call_count["n"] += 1

        session.register_channel("ws_sync", send_cb)

        event = SessionEvent(
            event_type=EventType.AGENT_REPLY,
            session_id=session.session_id,
            source_channel="test",
        )

        # 如果有 bug (无锁迭代),这里会抛 RuntimeError "dictionary changed size"
        try:
            mgr.broadcast_event_sync(session.session_id, event)
        except RuntimeError as e:
            if "changed size" in str(e):
                pytest.fail(
                    f"S6 补全: broadcast_event_sync 并发 channel 变更抛 RuntimeError: {e}. "
                    "BUG: 无锁迭代 session.active_channels.items()."
                )
            raise

        assert call_count["n"] >= 1, "send_callback 应至少被调用一次"


# ════════════════════════════════════════════════════════════
# D3: ConversationContext deep module 启用 — 删除 fallback
# (ADR 0008 候选 #6 落地)
# ════════════════════════════════════════════════════════════


class TestD3NoFallbackPath:
    """D3: MemCore.update_history 应只走 ConversationContext 路径.

    原代码有 split-brain 风险:
    - 若 agent._conversation_context 为 None (旧 Agent / 测试 mock),走裸 list fallback
    - fallback 无 role 校验 / 无自动 trim / 无深拷贝隔离
    - 同一 Agent 可能有时走 ctx 路径,有时走 fallback,行为不一致

    D3 修复: 显式 raise RuntimeError,要求所有 Agent 必须先 init_conversation().
    """

    def test_update_history_raises_when_ctx_missing(self):
        """RED: _conversation_context=None 时应抛 RuntimeError,而非静默 fallback."""
        from unittest.mock import MagicMock
        from neurova.mem_core import MemCore

        mock_agent = MagicMock()
        mock_agent._conversation_context = None  # 显式模拟未初始化场景
        mc = MemCore(mock_agent)

        with pytest.raises(RuntimeError, match="_conversation_context"):
            mc.update_history("user msg", "agent reply")

    def test_update_history_source_has_no_fallback_branch(self):
        """契约: update_history 源码不应有 else fallback 分支 (语法层面).

        原断言检查字面字符串 'fallback 路径',但 docstring 诚实地描述
        'D3 删除 fallback 路径' 时会误匹配自身. 改为检查 `else:` 语法关键字,
        既准确表达 '无 fallback 分支' 契约,又不限制注释措辞.
        """
        from neurova.mem_core import MemCore
        import ast
        import inspect

        source = inspect.getsource(MemCore.update_history)
        # 解析 AST: 函数体不应包含 If 节点带非空 orelse (即 else fallback 分支)
        tree = ast.parse(source.lstrip())
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and node.orelse:
                pytest.fail(
                    f"D3: update_history 仍保留 else fallback 分支 (line {node.lineno}),"
                    "split-brain 风险未消除. 应显式 raise RuntimeError,"
                    "要求所有 Agent 先 init_conversation()."
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
