"""
#5 SessionSyncManager 深化为事件总线 deep module TDD 测试

验证 4 个深化点（基于 zoom-out 调研报告）：
- A. max_sessions 配置未执行（L232 配置后无引用，会话无限增长）
- B. 读操作无锁（get_session/list_sessions/get_history 等未加 RLock）
- C. 自动过期清理无调度（cleanup_expired_sessions 存在但无自动触发）
- D. 缺少消息事件过滤 API（调用方需自行过滤 SessionEvent）

按 bug-hunt Phase 0-3：先 RED 验证 bug 存在，再 GREEN 修复。
"""
from __future__ import annotations

import inspect
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from neurova.sync.session_sync_manager import (
    EventType,
    SessionEvent,
    SessionSyncManager,
    UnifiedSession,
    get_session_sync_manager,
    reset_session_sync_manager,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def manager():
    """每个测试用独立的 SessionSyncManager 实例（不走单例）"""
    reset_session_sync_manager()
    m = SessionSyncManager(config={"max_sessions": 3, "session_timeout": 60, "max_history_size": 100})
    try:
        yield m
    finally:
        reset_session_sync_manager()


# ============================================================
# A. max_sessions 配置未执行
# ============================================================

class TestMaxSessionsEnforced:
    """A: max_sessions 配置应被执行，超限后清理最旧会话"""

    def test_max_sessions_config_read(self, manager):
        """配置应被读取到 _max_sessions 属性"""
        assert manager._max_sessions == 3

    def test_create_session_beyond_max_evicts_oldest(self, manager):
        """RED: 超过 max_sessions 后应驱逐最旧会话"""
        # 创建 3 个会话（达到上限）
        s1 = manager.create_session(user_id="u1", agent_id="a1")
        s2 = manager.create_session(user_id="u2", agent_id="a1")
        s3 = manager.create_session(user_id="u3", agent_id="a1")
        assert len(manager._sessions) == 3

        # 模拟时间流逝，让 s1 最旧
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        manager._sessions[s1.session_id].last_activity = old_time

        # 创建第 4 个会话，应驱逐 s1
        s4 = manager.create_session(user_id="u4", agent_id="a1")

        # GREEN 期望：sessions 仍为 3，s1 已被驱逐
        assert len(manager._sessions) <= 3, \
            f"A 失败：max_sessions={manager._max_sessions} 未执行，实际会话数 {len(manager._sessions)}"
        assert s1.session_id not in manager._sessions, \
            "A 失败：最旧会话未被驱逐"

    def test_create_session_at_max_no_eviction(self, manager):
        """边界：恰好达到 max_sessions 不应驱逐"""
        manager.create_session(user_id="u1", agent_id="a1")
        manager.create_session(user_id="u2", agent_id="a1")
        manager.create_session(user_id="u3", agent_id="a1")
        assert len(manager._sessions) == 3
        # 再创建一个会触发驱逐
        manager.create_session(user_id="u4", agent_id="a1")
        assert len(manager._sessions) == 3


# ============================================================
# B. 读操作锁补全
# ============================================================

class TestReadOperationsThreadSafe:
    """B: 读操作应通过 RLock 保护，避免读到不一致状态"""

    READ_METHODS = [
        "get_session",
        "get_session_by_user",
        "get_session_by_external_id",
        "list_sessions",
        "get_history",
        "get_history_by_user",
        "get_statistics",
    ]

    @pytest.mark.parametrize("method_name", READ_METHODS)
    def test_read_method_uses_lock(self, manager, method_name):
        """RED: 每个读方法应通过 self._lock 保护"""
        method = getattr(manager, method_name)
        source = inspect.getsource(method)
        # GREEN 期望：方法体内含 self._lock（with self._lock: 或 self._lock.acquire）
        assert "self._lock" in source, \
            f"B 失败：{method_name} 未使用 self._lock 保护读操作"

    def test_concurrent_read_during_write_safe(self, manager):
        """并发读写不应抛异常（粗粒度验证）"""
        manager.create_session(user_id="u1", agent_id="a1")

        errors = []

        def writer():
            try:
                for i in range(20):
                    manager.create_session(user_id=f"u{i}", agent_id="a1")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(20):
                    manager.list_sessions()
                    manager.get_statistics()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert not errors, f"B 失败：并发读写抛异常：{errors}"


# ============================================================
# C. 自动过期清理调度
# ============================================================

class TestAutoCleanupScheduled:
    """C: cleanup_expired_sessions 应被自动触发"""

    def test_create_session_triggers_cleanup(self, manager):
        """RED: create_session 后应触发 _cleanup_expired_unlocked"""
        # 创建一个会话，让它过期
        s1 = manager.create_session(user_id="u1", agent_id="a1")
        manager._sessions[s1.session_id].last_activity = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        )
        # 此时过期会话数为 1（timeout=60s）

        # 调用 create_session 应触发清理（patch 私有方法，因 create_session 持锁后调用无锁版本）
        with patch.object(manager, "_cleanup_expired_unlocked", wraps=manager._cleanup_expired_unlocked) as mock_cleanup:
            manager.create_session(user_id="u2", agent_id="a1")
            # GREEN 期望：_cleanup_expired_unlocked 被调用
            assert mock_cleanup.called, \
                "C 失败：create_session 未触发 _cleanup_expired_unlocked"

    def test_expired_session_evicted_after_create(self, manager):
        """过期会话在 create_session 后应被驱逐"""
        s1 = manager.create_session(user_id="u1", agent_id="a1")
        manager._sessions[s1.session_id].last_activity = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        )

        # 触发 create_session
        manager.create_session(user_id="u2", agent_id="a1")

        # GREEN 期望：s1 已被清理
        assert s1.session_id not in manager._sessions, \
            "C 失败：过期会话未被自动清理"


# ============================================================
# D. 消息事件过滤 API
# ============================================================

class TestMessageFilterApi:
    """D: 提供 get_messages() 方法过滤出消息事件（USER_MESSAGE + AGENT_REPLY）"""

    def test_get_messages_method_exists(self, manager):
        """RED: SessionSyncManager 应有 get_messages 方法"""
        assert hasattr(manager, "get_messages"), \
            "D 失败：SessionSyncManager 缺少 get_messages 方法"

    def test_get_messages_returns_only_message_events(self, manager):
        """get_messages 应只返回 USER_MESSAGE 和 AGENT_REPLY 事件"""
        if not hasattr(manager, "get_messages"):
            pytest.skip("D 未实现")

        session = manager.create_session(user_id="u1", agent_id="a1")

        # 添加多种事件类型
        session.add_event(SessionEvent(
            event_type=EventType.USER_MESSAGE,
            session_id=session.session_id,
            payload={"content": "你好"},
        ))
        session.add_event(SessionEvent(
            event_type=EventType.AGENT_THINKING,
            session_id=session.session_id,
            payload={"content": "思考中..."},
        ))
        session.add_event(SessionEvent(
            event_type=EventType.AGENT_TOOL_CALL,
            session_id=session.session_id,
            payload={"tool": "weather"},
        ))
        session.add_event(SessionEvent(
            event_type=EventType.AGENT_REPLY,
            session_id=session.session_id,
            payload={"content": "你好，今天天气不错"},
        ))

        messages = manager.get_messages(session.session_id)

        # GREEN 期望：只返回 2 条（USER_MESSAGE + AGENT_REPLY）
        assert len(messages) == 2, \
            f"D 失败：get_messages 返回 {len(messages)} 条，期望 2 条（仅消息事件）"
        event_types = [m["event_type"] for m in messages]
        assert "agent_thinking" not in event_types
        assert "agent_tool_call" not in event_types
        assert "user_message" in event_types
        assert "agent_reply" in event_types

    def test_get_messages_returns_list_of_dict(self, manager):
        """get_messages 应返回 List[Dict]（与 SessionRepository ABC 一致）"""
        if not hasattr(manager, "get_messages"):
            pytest.skip("D 未实现")

        session = manager.create_session(user_id="u1", agent_id="a1")
        session.add_event(SessionEvent(
            event_type=EventType.USER_MESSAGE,
            session_id=session.session_id,
            payload={"content": "测试"},
        ))

        messages = manager.get_messages(session.session_id)
        assert isinstance(messages, list)
        assert all(isinstance(m, dict) for m in messages), \
            "D 失败：get_messages 应返回 List[Dict]"

    def test_get_messages_with_limit(self, manager):
        """get_messages 应支持 limit 参数"""
        if not hasattr(manager, "get_messages"):
            pytest.skip("D 未实现")

        session = manager.create_session(user_id="u1", agent_id="a1")
        for i in range(5):
            session.add_event(SessionEvent(
                event_type=EventType.USER_MESSAGE,
                session_id=session.session_id,
                payload={"content": f"消息{i}"},
            ))

        messages = manager.get_messages(session.session_id, limit=3)
        assert len(messages) == 3, \
            f"D 失败：limit=3 未生效，返回 {len(messages)} 条"

    def test_get_messages_nonexistent_session(self, manager):
        """不存在的 session_id 应返回空列表"""
        if not hasattr(manager, "get_messages"):
            pytest.skip("D 未实现")

        messages = manager.get_messages("nonexistent-sid")
        assert messages == [], \
            "D 失败：不存在的 session 应返回空列表"


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
