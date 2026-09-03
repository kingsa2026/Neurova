"""
消息路由器测试 - MessageRouter 完整测试覆盖

注意：router.py 经过异步化重构（route() 及命令处理器均为 async），
且消息类型识别逻辑已并入 Message._detect_type()，旧的 command_patterns /
keyword_patterns / _identify_message_type / register_command / create_message /
MessageType.QUESTION 等 API 均已移除。本测试基于当前 router.py 的真实行为编写。
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

from neurova.router import (
    MessageRouter, Message, MessageType, RouteResult,
    create_default_router, _help_command, _stats_command, _clear_command,
    _skills_command, _memory_command,
)


@pytest.fixture
def sample_memory_manager():
    """示例记忆管理器（异步接口）"""
    manager = AsyncMock()
    manager.search = AsyncMock(return_value=[])
    manager.get_stats = AsyncMock(return_value={})
    return manager


class TestMessage:
    """测试Message对象"""

    def test_create_message(self):
        """创建基本消息"""
        msg = Message(content="你好")
        assert msg.content == "你好"
        assert isinstance(msg.sender_id, str)
        assert msg.message_type == MessageType.CHAT

    def test_message_auto_timestamp(self):
        """消息应自动设置时间戳"""
        msg = Message(content="测试")
        assert msg.timestamp is not None
        assert isinstance(msg.timestamp, datetime)

    def test_message_custom_timestamp(self):
        """消息应支持自定义时间戳"""
        custom_time = datetime(2024, 1, 1, 12, 0)
        msg = Message(content="测试", timestamp=custom_time)
        assert msg.timestamp == custom_time

    def test_message_metadata(self):
        """消息应支持元数据"""
        msg = Message(content="测试", metadata={"key": "value"})
        assert msg.metadata["key"] == "value"

    def test_message_default_metadata(self):
        """消息元数据默认应为空字典"""
        msg = Message(content="测试")
        assert msg.metadata == {}

    def test_message_with_sender(self):
        """消息可以指定发送者"""
        msg = Message(content="测试", sender_id="admin")
        assert msg.sender_id == "admin"


class TestMessageType:
    """测试消息类型枚举"""

    def test_all_types_exist(self):
        """所有（当前）消息类型应该存在"""
        assert MessageType.CHAT.value == "chat"
        assert MessageType.COMMAND.value == "command"
        assert MessageType.SKILL_REQUEST.value == "skill_request"
        assert MessageType.MEMORY_REQUEST.value == "memory_request"
        assert MessageType.SYSTEM.value == "system"
        assert MessageType.UNKNOWN.value == "unknown"
        # 说明：重构后 QUESTION 类型已移除，识别逻辑并入 Message._detect_type()


class TestRouteResult:
    """测试路由结果"""

    def test_success_result(self):
        """成功结果"""
        result = RouteResult(success=True, response="回复")
        assert result.success is True
        assert result.response == "回复"

    def test_error_result(self):
        """错误结果"""
        result = RouteResult(success=False, response="出错了")
        assert result.success is False
        assert result.response == "出错了"


class TestMessageRouter:
    """测试消息路由器初始化与处理器注册"""

    def test_init(self):
        """初始化应注册默认命令处理器"""
        router = MessageRouter()
        assert isinstance(router._handlers, dict)
        assert isinstance(router._command_handlers, dict)
        # 默认注册了 help/stats/clear/skills/memory 命令处理器
        for cmd in ("help", "stats", "clear", "skills", "memory"):
            assert cmd in router._command_handlers

    def test_register_handler(self):
        """注册消息处理器（使用 _handlers）"""
        router = MessageRouter()
        handler = MagicMock()
        router.register_handler(MessageType.CHAT, handler)
        assert MessageType.CHAT in router._handlers
        assert router._handlers[MessageType.CHAT] is handler

    def test_register_command_handler(self):
        """注册命令处理器（使用 register_command_handler）"""
        router = MessageRouter()
        handler = MagicMock()
        router.register_command_handler("test", handler)
        assert "test" in router._command_handlers
        assert router._command_handlers["test"] is handler


class TestMessageDetection:
    """消息类型识别（重构后由 Message._detect_type 负责）"""

    def test_detect_command(self):
        """斜杠开头应识别为命令"""
        assert Message("/help").message_type == MessageType.COMMAND

    def test_detect_skill_request(self):
        """内容包含 'skill' 关键词应识别为 skill 请求"""
        assert Message("帮我使用skill开发一个插件").message_type == MessageType.SKILL_REQUEST

    def test_detect_memory_request(self):
        """'记忆' 关键词应识别为记忆请求"""
        assert Message("搜索我的记忆").message_type == MessageType.MEMORY_REQUEST

    def test_detect_chat(self):
        """普通文本应识别为聊天"""
        assert Message("你好").message_type == MessageType.CHAT


class TestMessageRouting:
    """路由消息（route() 为 async，需 await）"""

    @pytest.mark.asyncio
    async def test_route_command_help(self):
        """命令 /help 应路由到 help 处理器"""
        router = MessageRouter()
        msg = Message("/help")
        result = await router.route(msg)
        assert result.success
        assert result.handler == "help"
        assert "/help" in result.response

    @pytest.mark.asyncio
    async def test_route_unknown_command(self):
        """未知命令应返回失败"""
        router = MessageRouter()
        msg = Message("/nonexistent")
        result = await router.route(msg)
        assert not result.success
        assert "未知命令" in result.response

    @pytest.mark.asyncio
    async def test_route_skill_request_without_registry(self):
        """无 Skill 系统时应返回失败"""
        router = MessageRouter()
        msg = Message("使用skill开发一个插件")
        result = await router.route(msg)
        assert not result.success
        assert "Skill" in result.response

    @pytest.mark.asyncio
    async def test_route_skill_request_with_registry(self):
        """有 Skill 系统时应成功路由"""
        skill_registry = MagicMock()
        skill_registry.execute_skill = AsyncMock(
            return_value=MagicMock(success=True, data="ok", error=None, execution_time=0.1)
        )
        router = MessageRouter(skill_registry=skill_registry)
        msg = Message("使用skill开发一个插件")
        result = await router.route(msg)
        assert result.success
        assert result.handler == "skill"
        skill_registry.execute_skill.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_memory_request_without_manager(self):
        """无记忆系统时应返回失败"""
        router = MessageRouter()
        msg = Message("搜索记忆")
        result = await router.route(msg)
        assert not result.success
        assert "记忆" in result.response

    @pytest.mark.asyncio
    async def test_route_memory_request_with_manager(self, sample_memory_manager):
        """有记忆系统时应成功路由"""
        router = MessageRouter(memory_manager=sample_memory_manager)
        msg = Message("memory search 测试")
        result = await router.route(msg)
        assert result.success
        assert "相关记忆" in result.response

    @pytest.mark.asyncio
    async def test_route_chat_without_agent(self):
        """无 Agent 时应返回失败"""
        router = MessageRouter()
        msg = Message("你好")
        result = await router.route(msg)
        assert not result.success
        assert "Agent" in result.response

    @pytest.mark.asyncio
    async def test_route_chat_with_agent(self):
        """有 Agent 时应成功路由到 chat"""
        agent = MagicMock()
        agent.chat = AsyncMock(return_value="回复内容")
        router = MessageRouter(agent=agent)
        msg = Message("你好")
        result = await router.route(msg)
        assert result.success
        assert result.response == "回复内容"
        assert result.handler == "chat"
        agent.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_fallback_unknown_type(self):
        """未注册的消息类型应回退为失败"""
        router = MessageRouter()
        msg = Message("测试")
        msg.message_type = MessageType.UNKNOWN
        result = await router.route(msg)
        assert not result.success
        assert "未知消息类型" in result.response


class TestDefaultRouter:
    """默认路由器（create_default_router）命令测试"""

    @pytest.mark.asyncio
    async def test_default_router_help_command(self):
        router = create_default_router()
        msg = Message("/help")
        result = await router.route(msg)
        assert result.success
        assert result.handler == "help"
        assert "/help" in result.response

    @pytest.mark.asyncio
    async def test_default_router_stats_command(self):
        router = create_default_router()
        msg = Message("/stats")
        msg.metadata = {"router": router}
        result = await router.route(msg)
        assert result.success
        assert "路由统计" in result.response

    @pytest.mark.asyncio
    async def test_default_router_clear_command(self):
        agent = MagicMock()
        agent.clear_history = MagicMock()
        router = create_default_router(agent=agent)
        msg = Message("/clear")
        msg.metadata = {"agent": agent}
        result = await router.route(msg)
        assert result.success
        assert "清空" in result.response
        agent.clear_history.assert_called_once()


class TestDefaultCommands:
    """直接调用命令处理器（均为 async）"""

    @pytest.mark.asyncio
    async def test_help_command(self):
        msg = Message("/help")
        result = await _help_command(msg, "")
        assert result.success
        assert "/help" in result.response

    @pytest.mark.asyncio
    async def test_stats_command(self):
        router = MessageRouter()
        msg = Message("/stats")
        msg.metadata = {"router": router}
        result = await _stats_command(msg, "")
        assert result.success
        assert "路由统计" in result.response

    @pytest.mark.asyncio
    async def test_clear_command(self):
        agent = MagicMock()
        agent.clear_history = MagicMock()
        msg = Message("/clear")
        msg.metadata = {"agent": agent}
        result = await _clear_command(msg, "")
        assert result.success
        assert "清空" in result.response
        agent.clear_history.assert_called_once()
