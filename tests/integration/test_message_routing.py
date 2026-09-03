"""
消息路由与渠道接口测试

验证三大组件的闭环：
1. MessageRouter: 消息类型检测 + 路由分发
2. ChannelAdapter: 渠道适配器接口
3. ChannelManager: 适配器生命周期 + 消息分发
"""
import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock


# ═══════════════════════════════════════════════════════
# 1. Message 数据模型测试
# ═══════════════════════════════════════════════════════

class TestMessage:
    """Message 数据模型测试"""

    def test_chat_message(self):
        """普通聊天消息"""
        from neurova.router import Message, MessageType
        m = Message(content="你好")
        assert m.message_type == MessageType.CHAT

    def test_command_message(self):
        """命令消息"""
        from neurova.router import Message, MessageType
        m = Message(content="/help")
        assert m.message_type == MessageType.COMMAND

    def test_skill_request(self):
        """Skill 请求"""
        from neurova.router import Message, MessageType
        m = Message(content="skill web_search query=python")
        assert m.message_type == MessageType.SKILL_REQUEST

    def test_memory_request(self):
        """记忆请求"""
        from neurova.router import Message, MessageType
        m = Message(content="搜索记忆 python")
        assert m.message_type == MessageType.MEMORY_REQUEST

    def test_explicit_type(self):
        """显式指定类型"""
        from neurova.router import Message, MessageType
        m = Message(content="hello", message_type=MessageType.SYSTEM)
        assert m.message_type == MessageType.SYSTEM


# ═══════════════════════════════════════════════════════
# 2. MessageRouter 路由测试
# ═══════════════════════════════════════════════════════

class TestMessageRouter:
    """MessageRouter 路由测试"""

    @pytest.fixture
    def router(self):
        from neurova.router import MessageRouter
        agent = MagicMock()
        agent.chat = AsyncMock(return_value="Hello from agent")
        return MessageRouter(agent=agent)

    @pytest.mark.asyncio
    async def test_route_chat(self, router):
        """路由聊天消息"""
        from neurova.router import Message
        result = await router.route(Message(content="你好"))
        assert result.success is True
        assert result.response == "Hello from agent"
        assert result.handler == "chat"

    @pytest.mark.asyncio
    async def test_route_command(self, router):
        """路由命令消息"""
        from neurova.router import Message
        result = await router.route(Message(content="/help"))
        assert result.success is True
        assert "帮助" in result.response or "help" in result.response.lower()

    @pytest.mark.asyncio
    async def test_route_unknown_command(self, router):
        """路由未知命令"""
        from neurova.router import Message
        result = await router.route(Message(content="/unknown_cmd"))
        assert result.success is False
        assert "未知命令" in result.response

    @pytest.mark.asyncio
    async def test_route_stats_command(self, router):
        """路由统计命令"""
        from neurova.router import Message
        result = await router.route(Message(content="/stats"))
        assert result.success is True
        assert result.handler == "command"

    @pytest.mark.asyncio
    async def test_custom_handler(self, router):
        """自定义处理器"""
        from neurova.router import Message, MessageType, RouteResult
        async def my_handler(msg):
            return RouteResult(success=True, response="custom response")
        router.register_handler(MessageType.CHAT, my_handler)
        result = await router.route(Message(content="test"))
        assert result.response == "custom response"

    @pytest.mark.asyncio
    async def test_custom_command(self, router):
        """自定义命令"""
        from neurova.router import Message
        async def my_cmd(msg, args):
            from neurova.router import RouteResult
            return RouteResult(success=True, response="my command result")
        router.register_command_handler("mycmd", my_cmd)
        result = await router.route(Message(content="/mycmd arg1"))
        assert result.response == "my command result"

    @pytest.mark.asyncio
    async def test_stats_tracking(self, router):
        """统计追踪"""
        from neurova.router import Message
        await router.route(Message(content="hello"))
        await router.route(Message(content="/help"))
        stats = router.get_route_stats()
        assert stats["total_messages"] == 2
        assert stats["processed_messages"] == 2
        assert stats["failed_messages"] == 0

    @pytest.mark.asyncio
    async def test_agent_chat_failure(self):
        """Agent 聊天失败"""
        from neurova.router import MessageRouter, Message
        agent = MagicMock()
        agent.chat = AsyncMock(side_effect=Exception("LLM error"))
        router = MessageRouter(agent=agent)
        result = await router.route(Message(content="hello"))
        assert result.success is False
        assert "LLM error" in result.response


# ═══════════════════════════════════════════════════════
# 3. ChannelAdapter 接口测试
# ═══════════════════════════════════════════════════════

class TestChannelAdapter:
    """ChannelAdapter 接口测试"""

    def test_adapter_interface(self):
        """适配器接口完整性"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        # 验证抽象方法
        methods = ['connect', 'disconnect', 'send_message']
        for method in methods:
            assert hasattr(ChannelAdapter, method), f"Missing method: {method}"

    def test_adapter_properties(self):
        """适配器属性"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        class TestAdapter(ChannelAdapter):
            async def connect(self): return True
            async def disconnect(self): pass
            async def send_message(self, chat_id, content, message_type="text", **kwargs): return "msg_1"

        config = ChannelConfig(channel_type="test")
        adapter = TestAdapter(config)
        assert adapter.channel_type == "test"
        assert adapter.is_connected is False

    def test_make_message(self):
        """构造统一消息"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        class TestAdapter(ChannelAdapter):
            async def connect(self): return True
            async def disconnect(self): pass
            async def send_message(self, chat_id, content, message_type="text", **kwargs): return "msg_1"

        config = ChannelConfig(channel_type="test")
        adapter = TestAdapter(config)
        msg = adapter._make_message(
            message_id="m1", sender_id="u1", sender_name="User",
            content="Hello", chat_id="c1"
        )
        assert msg.channel_type == "test"
        assert msg.content == "Hello"

    @pytest.mark.asyncio
    async def test_health_check(self):
        """健康检查"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        class TestAdapter(ChannelAdapter):
            async def connect(self): return True
            async def disconnect(self): pass
            async def send_message(self, chat_id, content, message_type="text", **kwargs): return "msg_1"

        config = ChannelConfig(channel_type="test")
        adapter = TestAdapter(config)
        health = await adapter.health_check()
        assert health["channel_type"] == "test"
        assert health["connected"] is False


# ═══════════════════════════════════════════════════════
# 4. ChannelManager 测试
# ═══════════════════════════════════════════════════════

class TestChannelManager:
    """ChannelManager 管理器测试"""

    @pytest.fixture
    def manager(self):
        from neurova.channels.manager import ChannelManager
        ChannelManager._instance = None
        mgr = ChannelManager.get_instance()
        yield mgr
        ChannelManager._instance = None

    def test_singleton(self):
        """单例模式"""
        from neurova.channels.manager import ChannelManager
        ChannelManager._instance = None
        m1 = ChannelManager.get_instance()
        m2 = ChannelManager.get_instance()
        assert m1 is m2
        ChannelManager._instance = None

    def test_register_adapter(self, manager):
        """注册适配器"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        class MockAdapter(ChannelAdapter):
            async def connect(self): return True
            async def disconnect(self): pass
            async def send_message(self, chat_id, content, message_type="text", **kwargs): return "msg_1"

        adapter = MockAdapter(ChannelConfig(channel_type="test_ch"))
        manager.register_adapter(adapter)
        assert manager.get_adapter("test_ch") is adapter

    def test_unregister_adapter(self, manager):
        """注销适配器"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        class MockAdapter(ChannelAdapter):
            async def connect(self): return True
            async def disconnect(self): pass
            async def send_message(self, chat_id, content, message_type="text", **kwargs): return "msg_1"

        adapter = MockAdapter(ChannelConfig(channel_type="test_ch"))
        manager.register_adapter(adapter)
        assert manager.unregister_adapter("test_ch") is True
        assert manager.get_adapter("test_ch") is None

    def test_list_adapters(self, manager):
        """列出适配器"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        class MockAdapter(ChannelAdapter):
            async def connect(self): return True
            async def disconnect(self): pass
            async def send_message(self, chat_id, content, message_type="text", **kwargs): return "msg_1"

        manager.register_adapter(MockAdapter(ChannelConfig(channel_type="ch_a")))
        manager.register_adapter(MockAdapter(ChannelConfig(channel_type="ch_b")))
        adapters = manager.list_adapters()
        assert len(adapters) == 2
        assert "ch_a" in adapters
        assert "ch_b" in adapters

    @pytest.mark.asyncio
    async def test_send_message(self, manager):
        """发送消息"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        class MockAdapter(ChannelAdapter):
            async def connect(self): self._connected = True; return True
            async def disconnect(self): pass
            async def send_message(self, chat_id, content, message_type="text", **kwargs):
                return "msg_sent"

        adapter = MockAdapter(ChannelConfig(channel_type="test_ch"))
        adapter._connected = True
        manager.register_adapter(adapter)

        result = await manager.send_message("test_ch", "chat_1", "Hello")
        assert result == "msg_sent"

    @pytest.mark.asyncio
    async def test_send_no_adapter(self, manager):
        """无适配器发送"""
        result = await manager.send_message("nonexistent", "chat_1", "Hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_message_handler(self, manager):
        """消息处理器"""
        from neurova.channels.base import ChannelMessage
        handler = AsyncMock(return_value="processed")
        manager.set_message_handler(handler)

        # 验证处理器被设置
        assert manager._message_handler is handler


# ═══════════════════════════════════════════════════════
# 5. ChannelMessage 跨平台消息格式测试
# ═══════════════════════════════════════════════════════

class TestChannelMessage:
    """ChannelMessage 跨平台消息格式测试"""

    def test_create_message(self):
        """创建消息"""
        from neurova.channels.base import ChannelMessage
        msg = ChannelMessage(
            channel_type="feishu", message_id="m1", sender_id="u1",
            sender_name="Alice", content="Hello"
        )
        assert msg.channel_type == "feishu"
        assert msg.chat_type == "p2p"
        assert msg.message_type == "text"

    def test_message_with_metadata(self):
        """带元数据的消息"""
        from neurova.channels.base import ChannelMessage
        msg = ChannelMessage(
            channel_type="dingtalk", message_id="m2", sender_id="u2",
            sender_name="Bob", content="Hi",
            metadata={"key": "value"}
        )
        assert msg.metadata["key"] == "value"

    def test_group_message(self):
        """群聊消息"""
        from neurova.channels.base import ChannelMessage
        msg = ChannelMessage(
            channel_type="wechat", message_id="m3", sender_id="u3",
            sender_name="Charlie", content="Hello group",
            chat_id="group_1", chat_type="group"
        )
        assert msg.chat_type == "group"


# ═══════════════════════════════════════════════════════
# 6. 端到端: 消息→路由→处理→响应 闭环
# ═══════════════════════════════════════════════════════

class TestRoutingE2E:
    """消息路由端到端闭环"""

    @pytest.mark.asyncio
    async def test_full_routing_flow(self):
        """完整路由流程"""
        from neurova.router import MessageRouter, Message, MessageType

        # 1. 创建 Agent mock
        agent = MagicMock()
        agent.chat = AsyncMock(return_value="Agent response")

        # 2. 创建 Router
        router = MessageRouter(agent=agent)

        # 3. 测试各种消息类型
        r1 = await router.route(Message(content="你好"))
        assert r1.success is True
        assert r1.handler == "chat"

        r2 = await router.route(Message(content="/help"))
        assert r2.success is True
        assert r2.handler == "command"

        # 4. 验证统计
        stats = router.get_route_stats()
        assert stats["total_messages"] == 2
        assert stats["processed_messages"] == 2

    @pytest.mark.asyncio
    async def test_channel_adapter_to_manager(self):
        """适配器→管理器 流程"""
        from neurova.channels.base import ChannelAdapter, ChannelConfig
        from neurova.channels.manager import ChannelManager

        ChannelManager._instance = None
        manager = ChannelManager.get_instance()

        # 创建并注册适配器
        class MockAdapter(ChannelAdapter):
            def __init__(self, config):
                super().__init__(config)
                self._sent_messages = []
            async def connect(self):
                self._connected = True
                return True
            async def disconnect(self):
                self._connected = False
            async def send_message(self, chat_id, content, message_type="text", **kwargs):
                self._sent_messages.append({"chat_id": chat_id, "content": content})
                return "msg_" + str(len(self._sent_messages))

        adapter = MockAdapter(ChannelConfig(channel_type="test_ch"))
        adapter._connected = True
        manager.register_adapter(adapter)

        # 发送消息
        msg_id = await manager.send_message("test_ch", "user_1", "Hello!")
        assert msg_id == "msg_1"
        assert adapter._sent_messages[0]["content"] == "Hello!"

        ChannelManager._instance = None
