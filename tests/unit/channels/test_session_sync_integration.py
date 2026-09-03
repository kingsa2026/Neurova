"""
Session Sync 集成测试

测试 ChannelManager 和 ChatPipeline 与 SessionSyncManager 的集成。
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)
from neurova.channels.manager import ChannelManager, _get_session_sync_manager
from neurova.sync.session_sync_manager import (
    EventType,
    SessionEvent,
    SessionSyncManager,
    get_session_sync_manager,
    reset_session_sync_manager,
)


@pytest.fixture
def sync_manager():
    """创建测试用 SessionSyncManager"""
    reset_session_sync_manager()
    manager = get_session_sync_manager()
    # 清除 ChannelManager 中的缓存引用
    import neurova.channels.manager as cm
    cm._session_sync_manager = manager
    yield manager
    cm._session_sync_manager = None
    reset_session_sync_manager()


@pytest.fixture
def mock_adapter():
    """创建模拟渠道适配器"""
    adapter = MagicMock(spec=ChannelAdapter)
    adapter.channel_type = "test_channel"
    adapter.config = ChannelConfig(channel_type="test_channel", enabled=True)
    adapter.is_connected = True
    adapter.send_message = AsyncMock(return_value="msg_123")
    adapter.connect = AsyncMock(return_value=True)
    adapter.disconnect = AsyncMock()
    adapter.health_check = AsyncMock(return_value={"connected": True})
    return adapter


@pytest.fixture
def channel_manager():
    """创建测试用 ChannelManager"""
    # 重置单例
    ChannelManager._instance = None
    manager = ChannelManager()
    yield manager
    ChannelManager._instance = None


class TestChannelManagerSync:
    """测试 ChannelManager 与 SessionSyncManager 的集成"""

    @pytest.mark.asyncio
    async def test_sync_user_message(self, channel_manager, mock_adapter, sync_manager):
        """测试用户消息同步到 SessionSyncManager"""
        # 注册适配器
        channel_manager.register_adapter(mock_adapter)
        
        # 创建会话
        session = sync_manager.create_session(
            user_id="user_123",
            agent_id="default",
            external_id="chat_123"
        )
        
        # 创建测试消息
        message = ChannelMessage(
            channel_type="test_channel",
            chat_id="chat_123",
            sender_id="user_123",
            sender_name="Test User",
            content="Hello, world!",
            message_type="text",
            message_id="msg_001",
        )
        
        # 触发消息接收事件
        await channel_manager._on_channel_event(
            ChannelEventType.MESSAGE_RECEIVED,
            message
        )
        
        # 验证事件被广播
        history = session.get_history(limit=10)
        user_messages = [
            e for e in history 
            if e.event_type == EventType.USER_MESSAGE
        ]
        
        assert len(user_messages) >= 1
        assert user_messages[0].payload["content"] == "Hello, world!"
        assert user_messages[0].source_channel == "test_channel"

    @pytest.mark.asyncio
    async def test_sync_reply_message(self, channel_manager, mock_adapter, sync_manager):
        """测试回复消息同步到 SessionSyncManager"""
        # 注册适配器
        channel_manager.register_adapter(mock_adapter)
        
        # 创建会话
        session = sync_manager.create_session(
            user_id="user_123",
            agent_id="default",
            external_id="chat_123"
        )
        
        # 发送回复消息
        await channel_manager.send_message(
            "test_channel",
            "chat_123",
            "Hello from agent!"
        )
        
        # 验证事件被广播
        history = session.get_history(limit=10)
        reply_messages = [
            e for e in history 
            if e.event_type == EventType.AGENT_REPLY
        ]
        
        assert len(reply_messages) >= 1
        assert reply_messages[0].payload["content"] == "Hello from agent!"

    @pytest.mark.asyncio
    async def test_sync_channel_connected(self, channel_manager, mock_adapter, sync_manager):
        """测试渠道连接事件同步"""
        # 注册适配器
        channel_manager.register_adapter(mock_adapter)
        
        # 创建会话
        session = sync_manager.create_session(
            user_id="user_123",
            agent_id="default",
            external_id="chat_123"
        )
        
        # 创建连接事件消息
        message = ChannelMessage(
            channel_type="test_channel",
            chat_id="chat_123",
            sender_id="system",
            sender_name="System",
            content="",
            message_type="event",
            message_id="msg_002",
        )
        
        # 触发连接事件
        await channel_manager._on_channel_event(
            ChannelEventType.BOT_CONNECTED,
            message
        )
        
        # 验证事件被广播
        history = session.get_history(limit=10)
        connected_events = [
            e for e in history 
            if e.event_type == EventType.CHANNEL_CONNECTED
        ]
        
        assert len(connected_events) >= 1

    @pytest.mark.asyncio
    async def test_sync_creates_session_if_not_exists(self, channel_manager, mock_adapter, sync_manager):
        """测试如果会话不存在，自动创建"""
        # 注册适配器
        channel_manager.register_adapter(mock_adapter)
        
        # 创建测试消息（使用不存在的 chat_id）
        message = ChannelMessage(
            channel_type="test_channel",
            chat_id="new_chat_456",
            sender_id="user_456",
            sender_name="New User",
            content="First message",
            message_type="text",
            message_id="msg_003",
        )
        
        # 触发消息接收事件
        await channel_manager._on_channel_event(
            ChannelEventType.MESSAGE_RECEIVED,
            message
        )
        
        # 验证会话被创建
        session = sync_manager.get_session_by_external_id("new_chat_456")
        assert session is not None
        assert session.user_id == "user_456"

    @pytest.mark.asyncio
    async def test_sync_excludes_source_channel(self, channel_manager, mock_adapter, sync_manager):
        """测试事件不广播到源渠道"""
        # 注册适配器
        channel_manager.register_adapter(mock_adapter)
        
        # 创建会话并注册两个渠道
        session = sync_manager.create_session(
            user_id="user_123",
            agent_id="default",
            external_id="chat_123"
        )
        
        # 模拟注册两个渠道
        received_events = {"web": [], "mobile": []}
        
        async def web_callback(event):
            received_events["web"].append(event)
        
        async def mobile_callback(event):
            received_events["mobile"].append(event)
        
        sync_manager.register_channel(
            session.session_id,
            "web",
            web_callback
        )
        
        sync_manager.register_channel(
            session.session_id,
            "mobile",
            mobile_callback
        )
        
        # 创建消息（来自 web 渠道）
        message = ChannelMessage(
            channel_type="web",
            chat_id="chat_123",
            sender_id="user_123",
            sender_name="Test User",
            content="Hello from web",
            message_type="text",
            message_id="msg_004",
        )
        
        # 触发消息接收事件
        await channel_manager._on_channel_event(
            ChannelEventType.MESSAGE_RECEIVED,
            message
        )
        
        # 等待事件传播
        await asyncio.sleep(0.1)
        
        # 验证事件只发送到 mobile 渠道
        assert len(received_events["web"]) == 0
        assert len(received_events["mobile"]) >= 1


class TestChatPipelineSync:
    """测试 ChatPipeline 与 SessionSyncManager 的集成"""

    @pytest.mark.asyncio
    async def test_sync_final_reply(self, sync_manager):
        """测试最终回复同步"""
        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
        
        # 创建模拟 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.agent_id = "test_agent"
        mock_agent.config.llm_config = MagicMock()
        mock_agent.config.llm_config.model = "test-model"
        mock_agent._current_reasoning = "Test reasoning"
        mock_agent._tool_messages_list = []
        mock_agent._turn_count = 0
        
        # 创建 ChatPipeline
        pipeline = ChatPipeline(mock_agent)
        
        # 创建 ChatContext
        ctx = ChatContext(
            user_input="Hello",
            reply="Hi there!",
            session_id=None,
            metadata={"user_id": "user_123"},
        )
        
        # 调用 _sync_final_reply
        await pipeline._sync_final_reply(ctx)
        
        # 验证事件被创建
        sessions = sync_manager.list_sessions()
        assert len(sessions) >= 1
        
        # 查找刚创建的会话
        session = None
        for s in sessions:
            if s.user_id == "user_123":
                session = s
                break
        
        assert session is not None
        
        # 验证事件
        history = session.get_history(limit=10)
        reply_events = [
            e for e in history 
            if e.event_type == EventType.AGENT_REPLY
        ]
        
        assert len(reply_events) >= 1
        assert reply_events[0].payload["content"] == "Hi there!"
        assert reply_events[0].payload["reasoning"] == "Test reasoning"

    @pytest.mark.asyncio
    async def test_sync_event_method(self, sync_manager):
        """测试通用事件同步方法"""
        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
        
        # 创建模拟 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.agent_id = "test_agent"
        
        # 创建 ChatPipeline
        pipeline = ChatPipeline(mock_agent)
        
        # 创建 ChatContext
        ctx = ChatContext(
            user_input="Hello",
            session_id="test_session",
            metadata={"user_id": "user_456"},
        )
        
        # 调用 _sync_event
        await pipeline._sync_event(
            ctx,
            EventType.AGENT_THINKING,
            {"stage": "llm_call", "tools_count": 5}
        )
        
        # 验证事件被创建
        sessions = sync_manager.list_sessions()
        session = None
        for s in sessions:
            if s.user_id == "user_456":
                session = s
                break
        
        assert session is not None
        
        # 验证事件
        history = session.get_history(limit=10)
        thinking_events = [
            e for e in history 
            if e.event_type == EventType.AGENT_THINKING
        ]
        
        assert len(thinking_events) >= 1
        assert thinking_events[0].payload["stage"] == "llm_call"


class TestSessionSyncManagerHelper:
    """测试 _get_session_sync_manager 辅助函数"""

    def test_returns_manager_instance(self, sync_manager):
        """测试返回管理器实例"""
        import neurova.channels.manager as cm
        cm._session_sync_manager = sync_manager
        manager = cm._get_session_sync_manager()
        assert manager is sync_manager

    def test_returns_none_on_import_error(self):
        """测试导入失败时返回 None"""
        import neurova.channels.manager as cm
        # 重置缓存，使延迟导入生效
        cm._session_sync_manager = None
        with patch('neurova.channels.manager._get_session_sync_manager', return_value=None):
            manager = cm._get_session_sync_manager()
            assert manager is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])