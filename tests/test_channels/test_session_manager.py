"""
会话管理测试

测试目标：neurova/channels/__init__.py 中的 SessionManager
"""

import tempfile
import os
import pytest
from neurova.channels import SessionManager, MessageChannel


class TestSessionManager:
    """会话管理器"""

    @pytest.fixture
    def manager(self):
        """创建临时存储的 SessionManager"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionManager(enable_persistence=True, storage_path=tmpdir)
            yield sm

    def test_init_default(self):
        sm = SessionManager()
        assert sm is not None

    def test_generate_session_id(self, manager):
        sid = manager.generate_session_id(
            agent_id="agent_001",
            global_user_id="user_001",
            channel=MessageChannel.WECHAT,
        )
        assert isinstance(sid, str)
        assert len(sid) > 0
        # 相同输入应生成相同 session_id
        sid2 = manager.generate_session_id(
            agent_id="agent_001",
            global_user_id="user_001",
            channel=MessageChannel.WECHAT,
        )
        assert sid == sid2

    def test_generate_session_id_different_agent(self, manager):
        sid1 = manager.generate_session_id("agent_001", "user_001", MessageChannel.WECHAT)
        sid2 = manager.generate_session_id("agent_002", "user_001", MessageChannel.WECHAT)
        assert sid1 != sid2

    def test_generate_session_id_different_channel(self, manager):
        """
        默认共享模式下不同渠道生成相同 session_id
        （通过 MessageChannel.value 传入渠道字符串，共享模式忽略渠道）
        """
        sid1 = manager.generate_session_id("agent_001", "user_001", MessageChannel.WECHAT.value)
        sid2 = manager.generate_session_id("agent_001", "user_001", MessageChannel.FEISHU.value)
        # 共享模式下渠道不影响 session ID
        assert sid1 == sid2

    def test_generate_session_id_with_channel_string(self):
        """直接传入渠道字符串"""
        sm = SessionManager(enable_persistence=False)
        sid = sm.generate_session_id("agent_001", "user_001", "wechat")
        assert isinstance(sid, str)
        assert len(sid) == 16

    def test_get_or_create_session(self, manager):
        session = manager.get_or_create_session(
            agent_id="agent_001",
            global_user_id="user_001",
            channel=MessageChannel.WECHAT,
        )
        assert session is not None
        assert session.agent_id == "agent_001"
        assert session.global_user_id == "user_001"
        assert session.channel == MessageChannel.WECHAT
        assert session.session_id is not None

    def test_get_or_create_session_reuses_existing(self, manager):
        s1 = manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        s2 = manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        assert s1.session_id == s2.session_id

    def test_get_session(self, manager):
        created = manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        retrieved = manager.get_session(created.session_id)
        assert retrieved is not None
        assert retrieved.session_id == created.session_id

    def test_get_session_not_found(self, manager):
        assert manager.get_session("nonexistent") is None

    def test_get_session_by_agent_user(self, manager):
        created = manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        found = manager.get_session_by_agent_user("agent_001", "user_001")
        assert found is not None
        assert found.session_id == created.session_id

    def test_get_session_by_agent_user_not_found(self, manager):
        assert manager.get_session_by_agent_user("no_agent", "no_user") is None

    def test_list_sessions(self, manager):
        manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        manager.get_or_create_session("agent_001", "user_002", MessageChannel.FEISHU)
        sessions = manager.list_sessions()
        assert len(sessions) >= 2

    def test_list_sessions_by_agent(self, manager):
        manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        manager.get_or_create_session("agent_001", "user_002", MessageChannel.FEISHU)
        manager.get_or_create_session("agent_002", "user_003", MessageChannel.API)
        sessions = manager.list_sessions(agent_id="agent_001")
        assert len(sessions) == 2

    def test_clear_history(self, manager):
        session = manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        manager.add_message_to_history(session.session_id, {"role": "user", "content": "你好"})
        history = manager.get_conversation_history(session.session_id)
        assert len(history) == 1
        manager.clear_history(session.session_id)
        history = manager.get_conversation_history(session.session_id)
        assert len(history) == 0

    def test_add_message_to_history(self, manager):
        session = manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        manager.add_message_to_history(session.session_id, {"role": "user", "content": "你好"})
        manager.add_message_to_history(session.session_id, {"role": "assistant", "content": "你好！有什么可以帮助你的？"})
        history = manager.get_conversation_history(session.session_id)
        assert len(history) == 2

    def test_conversation_history_limit(self, manager):
        session = manager.get_or_create_session("agent_001", "user_001", MessageChannel.WECHAT)
        for i in range(10):
            manager.add_message_to_history(session.session_id, {"role": "user", "content": f"msg {i}"})
        history = manager.get_conversation_history(session.session_id, limit=3)
        assert len(history) == 3
