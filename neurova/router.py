"""
Message Router - 消息路由器
根据输入类型和内容，将消息路由到不同的处理模块

D1 任务重构版本：
- 注入 SkillRegistry 和 MemoryManager，实现完整的 Skill/记忆路由
- 支持通过 Agent 处理普通聊天消息
- 支持事件总线触发（预留接口）
- 集成 LLMRouter 实现智能模型选择
"""

import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

# LLM Router 导入（条件导入）
try:
    from neurova.llm.llm_router import LLMRouter, RequestType, get_llm_router, select_model_for_request, detect_request_type
    LLM_ROUTER_AVAILABLE = True
except ImportError:
    LLM_ROUTER_AVAILABLE = False
    # 定义占位符
    class RequestType(Enum):
        CHAT = "chat"
        IMAGE_UNDERSTANDING = "image_understanding"
        AUDIO_UNDERSTANDING = "audio_understanding"
        VIDEO_UNDERSTANDING = "video_understanding"
        TEXT_TO_IMAGE = "text_to_image"
        IMAGE_TO_IMAGE = "image_to_image"
        TEXT_TO_VIDEO = "text_to_video"
        IMAGE_TO_VIDEO = "image_to_video"
        TEXT_TO_SPEECH = "text_to_speech"
        SPEECH_TO_TEXT = "speech_to_text"

    def get_llm_router():
        return None

    def select_model_for_request(request_type):
        return None

    def detect_request_type(content):
        return RequestType.CHAT

class MessageType(Enum):
    """消息类型"""
    CHAT = "chat"
    COMMAND = "command"
    SKILL_REQUEST = "skill_request"
    MEMORY_REQUEST = "memory_request"
    SYSTEM = "system"
    UNKNOWN = "unknown"

@dataclass
class Message:
    """消息数据结构"""
    content: str
    message_type: MessageType = MessageType.UNKNOWN
    sender_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """初始化后处理"""
        if self.message_type == MessageType.UNKNOWN:
            self.message_type = self._detect_type()

    def _detect_type(self) -> MessageType:
        """检测消息类型"""
        if self.content.startswith("/"):
            return MessageType.COMMAND
        elif "skill" in self.content.lower():
            return MessageType.SKILL_REQUEST
        elif "memory" in self.content.lower() or "记忆" in self.content:
            return MessageType.MEMORY_REQUEST
        else:
            return MessageType.CHAT

@dataclass
class RouteResult:
    """路由结果"""
    success: bool = True
    response: str = ""
    handler: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0

class MessageRouter:
    """消息路由器"""

    def __init__(self, agent=None, skill_registry=None, memory_manager=None):
        """
        初始化消息路由器

        Args:
            agent: Agent 实例
            skill_registry: Skill 注册表
            memory_manager: 记忆管理器
        """
        self._agent = agent
        self._skill_registry = skill_registry
        self._memory_manager = memory_manager
        self._handlers: Dict[MessageType, Callable] = {}
        self._command_handlers: Dict[str, Callable] = {}
        self._stats = {
            "total_messages": 0,
            "processed_messages": 0,
            "failed_messages": 0,
            "by_type": {},
        }

        # 初始化默认处理器
        self._init_default_handlers()

    def _init_default_handlers(self):
        """初始化默认处理器"""
        # 注册默认命令处理器
        self._command_handlers["help"] = _help_command
        self._command_handlers["stats"] = _stats_command
        self._command_handlers["clear"] = _clear_command
        self._command_handlers["skills"] = _skills_command
        self._command_handlers["memory"] = _memory_command

    def register_handler(self, message_type: MessageType, handler: Callable):
        """注册消息处理器"""
        self._handlers[message_type] = handler

    def register_command_handler(self, command: str, handler: Callable):
        """注册命令处理器"""
        self._command_handlers[command] = handler

    async def route(self, message: Message) -> RouteResult:
        """
        路由消息

        Args:
            message: 消息对象

        Returns:
            路由结果
        """
        start_time = datetime.now()

        try:
            # 更新统计
            self._stats["total_messages"] += 1
            msg_type = message.message_type.value
            self._stats["by_type"][msg_type] = self._stats["by_type"].get(msg_type, 0) + 1

            # 根据消息类型路由
            if message.message_type == MessageType.COMMAND:
                result = await self._route_command(message)
            elif message.message_type == MessageType.SKILL_REQUEST:
                result = await self._route_skill_request(message)
            elif message.message_type == MessageType.MEMORY_REQUEST:
                result = await self._route_memory_request(message)
            elif message.message_type == MessageType.CHAT:
                result = await self._route_chat(message)
            else:
                result = RouteResult(
                    success=False,
                    response="未知消息类型",
                    handler="unknown",
                )

            # 更新统计
            self._stats["processed_messages"] += 1
            result.execution_time = (datetime.now() - start_time).total_seconds()

            return result

        except Exception as e:
            self._stats["failed_messages"] += 1
            return RouteResult(
                success=False,
                response=f"路由失败: {e}",
                execution_time=(datetime.now() - start_time).total_seconds(),
            )

    async def _route_command(self, message: Message) -> RouteResult:
        """路由命令消息"""
        # 解析命令
        parts = message.content.split(maxsplit=1)
        command = parts[0][1:]  # 去掉 '/' 前缀
        args = parts[1] if len(parts) > 1 else ""

        # 查找命令处理器
        if command in self._command_handlers:
            handler = self._command_handlers[command]
            return await handler(message, args)
        else:
            return RouteResult(
                success=False,
                response=f"未知命令: /{command}",
                handler="command",
            )

    async def _route_skill_request(self, message: Message) -> RouteResult:
        """路由 Skill 请求"""
        if not self._skill_registry:
            return RouteResult(
                success=False,
                response="Skill 系统未初始化",
                handler="skill",
            )

        # 解析 Skill 名称和参数
        parts = message.content.split(maxsplit=1)
        skill_name = parts[0]
        params_str = parts[1] if len(parts) > 1 else "{}"

        # 解析参数
        try:
            # 尝试解析为 JSON
            params = json.loads(params_str) if params_str else {}
        except json.JSONDecodeError:
            params = {"raw": params_str}

        # 执行 Skill
        result = await self._skill_registry.execute_skill(skill_name, params, message.metadata)

        return RouteResult(
            success=result.success,
            response=str(result.data) if result.success else result.error,
            handler="skill",
            metadata={"skill_name": skill_name, "execution_time": result.execution_time},
        )

    async def _route_memory_request(self, message: Message) -> RouteResult:
        """路由记忆请求"""
        if not self._memory_manager:
            return RouteResult(
                success=False,
                response="记忆系统未初始化",
                handler="memory",
            )

        # 解析记忆操作
        content = message.content.lower()
        if "search" in content or "搜索" in content:
            # 搜索记忆
            query = message.content.replace("memory", "").replace("记忆", "").strip()
            results = await self._memory_manager.search(query)
            return RouteResult(
                success=True,
                response=f"找到 {len(results)} 条相关记忆",
                handler="memory",
                metadata={"results": results},
            )
        elif "stats" in content or "统计" in content:
            # 记忆统计
            stats = await self._memory_manager.get_stats()
            return RouteResult(
                success=True,
                response=str(stats),
                handler="memory",
                metadata={"stats": stats},
            )
        else:
            return RouteResult(
                success=False,
                response="请使用 /memory search <关键词> 或 /memory stats",
                handler="memory",
            )

    async def _route_chat(self, message: Message) -> RouteResult:
        """路由聊天消息"""
        if not self._agent:
            return RouteResult(
                success=False,
                response="Agent 未初始化",
                handler="chat",
            )

        try:
            # 检查是否是语音消息（通过 metadata 中的 media_type）
            metadata = message.metadata or {}
            media_type = metadata.get("media_type")
            
            if media_type == "voice":
                # 语音消息：调用 process_multimodal 处理
                response = await self._agent.process_multimodal(
                    content=message.content,
                    media_type="voice",
                    metadata=metadata,
                )
            else:
                # 普通文本消息：使用 Agent 处理聊天
                response = await self._agent.chat(message.content, message.metadata)
            
            return RouteResult(
                success=True,
                response=response,
                handler="chat",
            )
        except Exception as e:
            return RouteResult(
                success=False,
                response=f"聊天处理失败: {e}",
                handler="chat",
            )

    def get_route_stats(self) -> Dict[str, Any]:
        """获取路由统计"""
        return self._stats.copy()

    def clear_stats(self):
        """清空统计"""
        self._stats = {
            "total_messages": 0,
            "processed_messages": 0,
            "failed_messages": 0,
            "by_type": {},
        }

# ═══════════════════════════════════════════════════════════════
# 默认命令处理器
# ═══════════════════════════════════════════════════════════════

async def _help_command(message: Message, groups: str) -> RouteResult:
    """帮助命令"""
    help_text = """可用命令：
/help - 显示帮助
/stats - 显示路由统计
/clear - 清空对话历史
/skills - 列出可用 Skill
/skill <名称> <参数> - 执行 Skill
/memory search <关键词> - 搜索记忆
/memory stats - 记忆统计"""

    return RouteResult(
        success=True,
        response=help_text,
        handler="help",
    )

async def _stats_command(message: Message, groups: str) -> RouteResult:
    """统计命令"""
    router = message.metadata.get("router")
    if router:
        stats = router.get_route_stats()
        return RouteResult(
            success=True,
            response=f"路由统计：{stats}",
            handler="stats",
        )
    else:
        return RouteResult(
            success=False,
            response="统计功能开发中...",
            handler="stats",
        )

async def _clear_command(message: Message, groups: str) -> RouteResult:
    """清空命令"""
    agent = message.metadata.get("agent")
    if agent:
        agent.clear_history()
        return RouteResult(
            success=True,
            response="对话历史已清空",
            handler="clear",
        )
    else:
        return RouteResult(
            success=False,
            response="清空功能开发中...",
            handler="clear",
        )

async def _skills_command(message: Message, groups: str) -> RouteResult:
    """列出可用 Skill"""
    skill_registry = message.metadata.get("skill_registry")
    if skill_registry:
        skills = skill_registry.list_skills()
        if not skills:
            return RouteResult(
                success=True,
                response="当前没有可用的 Skill",
                handler="skills",
            )

        lines = ["可用 Skill："]
        for skill in skills:
            lines.append(f"- {skill.name}: {skill.description}")

        return RouteResult(
            success=True,
            response="\n".join(lines),
            handler="skills",
        )
    else:
        return RouteResult(
            success=False,
            response="Skill 系统未初始化",
            handler="skills",
        )

async def _memory_command(message: Message, groups: str) -> RouteResult:
    """记忆相关命令"""
    args = message.content.replace("/memory", "").replace("记忆", "").strip()

    if "search" in args or "搜索" in args:
        query = args.replace("search", "").replace("搜索", "").strip()
        if query:
            message.message_type = MessageType.MEMORY_REQUEST
            message.content = f"memory search {query}"
            # 重新路由
            router = message.metadata.get("router")
            if router:
                return await router.route(message)

        return RouteResult(
            success=False,
            response="请使用 /memory search <关键词> 格式",
            handler="memory",
        )
    elif "stats" in args or "统计" in args:
        return RouteResult(
            success=True,
            response="记忆统计功能开发中...",
            handler="memory",
        )
    else:
        return RouteResult(
            success=False,
            response="请使用 /memory search <关键词> 或 /memory stats",
            handler="memory",
        )

def create_default_router(
    agent=None,
    skill_registry=None,
    memory_manager=None,
    enable_llm_router: bool = True,
) -> MessageRouter:
    """
    创建默认路由器

    Args:
        agent: Agent 实例
        skill_registry: Skill 注册表
        memory_manager: 记忆管理器
        enable_llm_router: 是否启用 LLM 路由器

    Returns:
        MessageRouter 实例
    """
    router = MessageRouter(agent, skill_registry, memory_manager)

    # 注册默认处理器
    router.register_handler(MessageType.CHAT, lambda msg: agent.chat(msg.content) if agent else None)
    router.register_handler(MessageType.COMMAND, lambda msg: None)  # 已内置处理
    router.register_handler(MessageType.SKILL_REQUEST, lambda msg: None)  # 已内置处理
    router.register_handler(MessageType.MEMORY_REQUEST, lambda msg: None)  # 已内置处理

    return router