"""
会话同步管理器单元测试
"""

import asyncio
import pytest
from datetime import datetime, timezone

from neurova.sync.session_sync_manager import (
    EventType,
    SessionEvent,
    SessionSyncManager,
    UnifiedSession,
    get_session_sync_manager,
    reset_session_sync_manager,
)


class TestSessionEvent:
    """SessionEvent 测试"""
    
    def test_create_event(self):
        """测试创建事件"""
        event = SessionEvent(
            event_type=EventType.USER_MESSAGE,
            session_id="session_123",
            source_channel="web",
            payload={"content": "Hello"}
        )
        
        assert event.event_type == EventType.USER_MESSAGE
        assert event.session_id == "session_123"
        assert event.source_channel == "web"
        assert event.payload == {"content": "Hello"}
        assert event.event_id.startswith("evt_")
    
    def test_to_dict(self):
        """测试序列化"""
        event = SessionEvent(
            event_type=EventType.AGENT_REPLY,
            session_id="session_123",
            source_channel="web",
            payload={"content": "Hi there"}
        )
        
        data = event.to_dict()
        
        assert data["event_type"] == "agent_reply"
        assert data["session_id"] == "session_123"
        assert "timestamp" in data
        assert data["payload"]["content"] == "Hi there"
    
    def test_from_dict(self):
        """测试反序列化"""
        data = {
            "event_id": "evt_test",
            "event_type": "user_message",
            "session_id": "session_123",
            "source_channel": "web",
            "timestamp": "2026-06-07T10:00:00+00:00",
            "payload": {"content": "Hello"}
        }
        
        event = SessionEvent.from_dict(data)
        
        assert event.event_id == "evt_test"
        assert event.event_type == EventType.USER_MESSAGE
        assert event.session_id == "session_123"
    
    def test_to_json(self):
        """测试 JSON 序列化"""
        event = SessionEvent(
            event_type=EventType.USER_MESSAGE,
            payload={"content": "测试中文"}
        )
        
        json_str = event.to_json()
        
        assert "user_message" in json_str
        assert "测试中文" in json_str


class TestUnifiedSession:
    """UnifiedSession 测试"""
    
    def test_create_session(self):
        """测试创建会话"""
        session = UnifiedSession(
            user_id="user_1",
            agent_id="agent_1"
        )
        
        assert session.user_id == "user_1"
        assert session.agent_id == "agent_1"
        assert session.status == "active"
        assert session.session_id.startswith("session_")
        assert session.conversation_id.startswith("conv_")
    
    def test_add_event(self):
        """测试添加事件"""
        session = UnifiedSession(user_id="user_1")
        
        event = SessionEvent(
            event_type=EventType.USER_MESSAGE,
            payload={"content": "Hello"}
        )
        
        session.add_event(event)
        
        assert len(session.history) == 1
        assert session.history[0].session_id == session.session_id
    
    def test_history_limit(self):
        """测试历史限制"""
        session = UnifiedSession(user_id="user_1", max_history_size=5)
        
        for i in range(10):
            event = SessionEvent(
                event_type=EventType.USER_MESSAGE,
                payload={"index": i}
            )
            session.add_event(event)
        
        assert len(session.history) == 5
        assert session.history[0].payload["index"] == 5
    
    def test_get_history_with_filter(self):
        """测试带过滤器的历史查询"""
        session = UnifiedSession(user_id="user_1")
        
        # 添加不同类型的事件
        session.add_event(SessionEvent(event_type=EventType.USER_MESSAGE))
        session.add_event(SessionEvent(event_type=EventType.AGENT_REPLY))
        session.add_event(SessionEvent(event_type=EventType.USER_MESSAGE))
        session.add_event(SessionEvent(event_type=EventType.AGENT_THINKING))
        
        # 只查询用户消息
        user_messages = session.get_history(
            event_types=[EventType.USER_MESSAGE]
        )
        
        assert len(user_messages) == 2
    
    def test_register_channel(self):
        """测试注册渠道"""
        session = UnifiedSession(user_id="user_1")
        
        def send_callback(event):
            pass
        
        conn = session.register_channel("web", send_callback)
        
        assert "web" in session.active_channels
        assert conn.channel_type == "web"
        assert conn.send_callback == send_callback
    
    def test_unregister_channel(self):
        """测试注销渠道"""
        session = UnifiedSession(user_id="user_1")
        session.register_channel("web", lambda e: None)
        
        result = session.unregister_channel("web")
        
        assert result is True
        assert "web" not in session.active_channels
    
    def test_to_dict(self):
        """测试序列化"""
        session = UnifiedSession(
            user_id="user_1",
            agent_id="agent_1"
        )
        session.register_channel("web", lambda e: None)
        
        data = session.to_dict()
        
        assert data["user_id"] == "user_1"
        assert data["agent_id"] == "agent_1"
        assert "web" in data["active_channels"]


class TestSessionSyncManager:
    """SessionSyncManager 测试"""
    
    def setup_method(self):
        """测试前重置"""
        reset_session_sync_manager()
        self.manager = SessionSyncManager()
    
    def test_create_session(self):
        """测试创建会话"""
        session = self.manager.create_session(
            user_id="user_1",
            agent_id="agent_1"
        )
        
        assert session.user_id == "user_1"
        assert session.agent_id == "agent_1"
        assert session.status == "active"
    
    def test_get_existing_session(self):
        """测试获取已有会话"""
        session1 = self.manager.create_session(user_id="user_1", agent_id="agent_1")
        session2 = self.manager.create_session(user_id="user_1", agent_id="agent_1")
        
        # 应该返回同一个会话
        assert session1.session_id == session2.session_id
    
    def test_get_session_by_user(self):
        """测试通过用户 ID 获取会话"""
        session = self.manager.create_session(user_id="user_1", agent_id="agent_1")
        
        found = self.manager.get_session_by_user("user_1", "agent_1")
        
        assert found is not None
        assert found.session_id == session.session_id
    
    def test_get_session_by_external_id(self):
        """测试通过外部 ID 获取会话"""
        session = self.manager.create_session(
            user_id="user_1",
            external_id="ext_123"
        )
        
        found = self.manager.get_session_by_external_id("ext_123")
        
        assert found is not None
        assert found.session_id == session.session_id
    
    def test_end_session(self):
        """测试结束会话"""
        session = self.manager.create_session(user_id="user_1")
        
        result = self.manager.end_session(session.session_id)
        
        assert result is True
        
        # 会话应该被标记为结束
        ended_session = self.manager.get_session(session.session_id)
        assert ended_session.status == "ended"
    
    def test_register_channel(self):
        """测试注册渠道"""
        session = self.manager.create_session(user_id="user_1")
        
        conn = self.manager.register_channel(
            session_id=session.session_id,
            channel_type="web",
            send_callback=lambda e: None
        )
        
        assert conn is not None
        assert conn.channel_type == "web"
    
    def test_unregister_channel(self):
        """测试注销渠道"""
        session = self.manager.create_session(user_id="user_1")
        self.manager.register_channel(
            session_id=session.session_id,
            channel_type="web",
            send_callback=lambda e: None
        )
        
        result = self.manager.unregister_channel(session.session_id, "web")
        
        assert result is True
    
    def test_broadcast_event_sync(self):
        """测试同步广播事件"""
        session = self.manager.create_session(user_id="user_1")
        
        received_events = []
        
        def send_callback(event):
            received_events.append(event)
        
        self.manager.register_channel(
            session_id=session.session_id,
            channel_type="web",
            send_callback=send_callback
        )
        
        event = SessionEvent(
            event_type=EventType.AGENT_REPLY,
            payload={"content": "Hello"}
        )
        
        sent_count = self.manager.broadcast_event_sync(session.session_id, event)
        
        assert sent_count == 1
        assert len(received_events) == 1
        assert received_events[0].event_type == EventType.AGENT_REPLY
    
    def test_get_history(self):
        """测试获取历史"""
        session = self.manager.create_session(user_id="user_1")
        
        # 添加事件
        for i in range(5):
            event = SessionEvent(
                event_type=EventType.USER_MESSAGE,
                payload={"index": i}
            )
            self.manager.broadcast_event_sync(session.session_id, event)
        
        history = self.manager.get_history(session.session_id, limit=3)
        
        assert len(history) == 3
    
    def test_list_sessions(self):
        """测试列出会话"""
        self.manager.create_session(user_id="user_1", agent_id="agent_1")
        self.manager.create_session(user_id="user_1", agent_id="agent_2")
        self.manager.create_session(user_id="user_2", agent_id="agent_1")
        
        # 列出所有会话
        all_sessions = self.manager.list_sessions()
        assert len(all_sessions) == 3
        
        # 按用户过滤
        user1_sessions = self.manager.list_sessions(user_id="user_1")
        assert len(user1_sessions) == 2
        
        # 按 agent 过滤
        agent1_sessions = self.manager.list_sessions(agent_id="agent_1")
        assert len(agent1_sessions) == 2
    
    def test_cleanup_expired_sessions(self):
        """测试清理过期会话

        #5 深化后：cleanup_expired_sessions 真正从 _sessions 删除过期会话
        （原行为仅标记 status='ended'，导致内存无限增长）。
        """
        # 创建一个会话并手动设置为过期
        session = self.manager.create_session(user_id="user_1")
        session.last_activity = datetime(2020, 1, 1, tzinfo=timezone.utc)

        cleaned = self.manager.cleanup_expired_sessions()

        assert cleaned == 1
        # #5 改造：cleanup 后会话从 _sessions 删除，get_session 返回 None
        assert self.manager.get_session(session.session_id) is None
    
    def test_get_statistics(self):
        """测试获取统计信息"""
        self.manager.create_session(user_id="user_1")
        self.manager.create_session(user_id="user_2")
        
        stats = self.manager.get_statistics()
        
        assert stats["total_sessions"] == 2
        assert stats["active_sessions"] == 2
    
    def test_map_external_id(self):
        """测试映射外部 ID"""
        session = self.manager.create_session(user_id="user_1")
        
        self.manager.map_external_id("ext_abc", session.session_id)
        
        found = self.manager.resolve_external_id("ext_abc")
        assert found == session.session_id


class TestSingleton:
    """单例模式测试"""
    
    def setup_method(self):
        """测试前重置"""
        reset_session_sync_manager()
    
    def test_get_singleton(self):
        """测试获取单例"""
        manager1 = get_session_sync_manager()
        manager2 = get_session_sync_manager()
        
        assert manager1 is manager2
    
    def test_reset_singleton(self):
        """测试重置单例"""
        manager1 = get_session_sync_manager()
        reset_session_sync_manager()
        manager2 = get_session_sync_manager()
        
        assert manager1 is not manager2


@pytest.mark.asyncio
class TestAsyncBroadcast:
    """异步广播测试"""
    
    def setup_method(self):
        """测试前重置"""
        reset_session_sync_manager()
        self.manager = SessionSyncManager()
    
    async def test_broadcast_event_async(self):
        """测试异步广播事件"""
        session = self.manager.create_session(user_id="user_1")
        
        received_events = []
        
        async def send_callback(event):
            received_events.append(event)
        
        self.manager.register_channel(
            session_id=session.session_id,
            channel_type="web",
            send_callback=send_callback
        )
        
        event = SessionEvent(
            event_type=EventType.AGENT_REPLY,
            payload={"content": "Hello"}
        )
        
        sent_count = await self.manager.broadcast_event(session.session_id, event)
        
        assert sent_count == 1
        assert len(received_events) == 1
    
    async def test_broadcast_exclude_channel(self):
        """测试排除渠道的广播"""
        session = self.manager.create_session(user_id="user_1")
        
        web_events = []
        mobile_events = []
        
        async def web_callback(event):
            web_events.append(event)
        
        async def mobile_callback(event):
            mobile_events.append(event)
        
        self.manager.register_channel(
            session_id=session.session_id,
            channel_type="web",
            send_callback=web_callback
        )
        
        self.manager.register_channel(
            session_id=session.session_id,
            channel_type="mobile",
            send_callback=mobile_callback
        )
        
        event = SessionEvent(
            event_type=EventType.AGENT_REPLY,
            payload={"content": "Hello"}
        )
        
        # 广播时排除 web 渠道
        sent_count = await self.manager.broadcast_event(
            session.session_id, event, exclude_channel="web"
        )
        
        assert sent_count == 1
        assert len(web_events) == 0
        assert len(mobile_events) == 1
