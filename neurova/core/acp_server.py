from __future__ import annotations

"""
ACP Server - Agent Control Protocol 服务器

实现标准的 Agent 控制协议，支持：
1. 会话管理（新建/加载/恢复/关闭）
2. 流式输出（delta 增量更新）
3. 工具调用和思考过程可视化
4. 模型切换
5. 配置管理

架构位置：接口层 - API/协议适配层
"""

import asyncio
from dataclasses import dataclass, field
import datetime
import enum
import json
import logging
from pathlib import Path
import threading
import typing
import uuid
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
import fastapi.responses

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class ACPSessionStatus(enum.Enum):
    """会话状态枚举"""
    CREATED = "created"      # 已创建
    ACTIVE = "active"        # 活跃中
    PAUSED = "paused"        # 已暂停
    CLOSED = "closed"        # 已关闭
    ERROR = "error"          # 错误状态


class ACPMessageRole(enum.Enum):
    """消息角色枚举"""
    USER = "user"            # 用户
    ASSISTANT = "assistant"  # 助手
    SYSTEM = "system"        # 系统
    TOOL = "tool"            # 工具


class ACPStreamEventType(enum.Enum):
    """流式事件类型枚举"""
    TEXT_DELTA = "text_delta"        # 文本增量
    TOOL_CALL = "tool_call"          # 工具调用
    TOOL_RESULT = "tool_result"      # 工具结果
    THINKING = "thinking"            # 思考过程
    ERROR = "error"                  # 错误
    DONE = "done"                    # 完成


@dataclass
class ACPMessage:
    """ACP消息数据类"""
    role: ACPMessageRole
    content: str
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: datetime.datetime.now().timestamp())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "role": self.role.value,
            "content": self.content,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


@dataclass
class ACPStreamChunk:
    """流式数据块数据类"""
    event_type: ACPStreamEventType
    data: Any
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: datetime.datetime.now().timestamp())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_type": self.event_type.value,
            "data": self.data,
            "chunk_id": self.chunk_id,
            "timestamp": self.timestamp
        }
    
    def to_sse(self) -> str:
        """转换为SSE格式"""
        return f"event: {self.event_type.value}\ndata: {json.dumps(self.to_dict())}\n\n"


@dataclass
class ACPToolCall:
    """工具调用数据类"""
    tool_name: str
    arguments: Dict[str, Any]
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: datetime.datetime.now().timestamp())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "call_id": self.call_id,
            "timestamp": self.timestamp
        }


@dataclass
class ACPToolResult:
    """工具结果数据类"""
    call_id: str
    result: Any
    success: bool = True
    error: Optional[str] = None
    timestamp: float = field(default_factory=lambda: datetime.datetime.now().timestamp())
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "call_id": self.call_id,
            "result": self.result,
            "success": self.success,
            "error": self.error,
            "timestamp": self.timestamp
        }


@dataclass
class ACPThinkingStep:
    """思考步骤数据类"""
    step_type: str  # reasoning, planning, reflection, etc.
    content: str
    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: datetime.datetime.now().timestamp())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "step_type": self.step_type,
            "content": self.content,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


@dataclass
class ACPModelConfig:
    """模型配置数据类"""
    model_id: str
    model_name: str
    provider: str
    capabilities: List[str] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "provider": self.provider,
            "capabilities": self.capabilities,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "metadata": self.metadata
        }


@dataclass
class ACPSessionConfig:
    """会话配置数据类"""
    system_prompt: str = ""
    max_context_length: int = 8192
    auto_save: bool = True
    stream_enabled: bool = True
    tool_calls_enabled: bool = True
    thinking_visible: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "system_prompt": self.system_prompt,
            "max_context_length": self.max_context_length,
            "auto_save": self.auto_save,
            "stream_enabled": self.stream_enabled,
            "tool_calls_enabled": self.tool_calls_enabled,
            "thinking_visible": self.thinking_visible,
            "metadata": self.metadata
        }


@dataclass
class ACPSession:
    """ACP会话数据类"""
    session_id: str
    user_id: str
    model_config: ACPModelConfig
    session_config: ACPSessionConfig = field(default_factory=ACPSessionConfig)
    status: ACPSessionStatus = ACPSessionStatus.CREATED
    created_at: float = field(default_factory=lambda: datetime.datetime.now().timestamp())
    updated_at: float = field(default_factory=lambda: datetime.datetime.now().timestamp())
    messages: List[ACPMessage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "model_config": self.model_config.to_dict(),
            "session_config": self.session_config.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [msg.to_dict() for msg in self.messages],
            "metadata": self.metadata
        }


# Pydantic 请求/响应模型
class ACPSessionCreateRequest(BaseModel):
    """创建会话请求"""
    user_id: str
    model_id: str = "default"
    system_prompt: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ACPSessionLoadRequest(BaseModel):
    """加载会话请求"""
    session_id: str


class ACPChatRequest(BaseModel):
    """聊天请求"""
    session_id: str
    message: str
    stream: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ACPToolCallRequest(BaseModel):
    """工具调用请求"""
    session_id: str
    tool_name: str
    arguments: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ACPModelSwitchRequest(BaseModel):
    """模型切换请求"""
    session_id: str
    model_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ACPConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    session_id: str
    config: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ACPServer:
    """
    ACP服务器
    
    管理会话、处理请求和流式输出。
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化ACP服务器
        
        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 会话存储
        self._sessions: Dict[str, ACPSession] = {}
        
        # 可用模型
        self._models: Dict[str, ACPModelConfig] = {}
        
        # 注册默认模型
        self._register_default_models()
        
        # 创建路由器
        self.router = APIRouter(prefix="/acp", tags=["ACP"])
        self._register_routes()
        
        logger.info("ACPServer 初始化完成")
    
    def _register_default_models(self) -> None:
        """注册默认模型"""
        default_models = [
            ACPModelConfig(
                model_id="default",
                model_name="GPT-3.5 Turbo",
                provider="openai",
                capabilities=["text", "chat"],
                max_tokens=4096
            ),
            ACPModelConfig(
                model_id="gpt4",
                model_name="GPT-4",
                provider="openai",
                capabilities=["text", "chat", "reasoning"],
                max_tokens=8192
            ),
            ACPModelConfig(
                model_id="claude",
                model_name="Claude 3 Sonnet",
                provider="anthropic",
                capabilities=["text", "chat", "reasoning"],
                max_tokens=4096
            )
        ]
        
        for model in default_models:
            self._models[model.model_id] = model
    
    def _register_routes(self) -> None:
        """注册API路由"""
        
        @self.router.post("/sessions")
        async def create_session_endpoint(request: ACPSessionCreateRequest):
            return await self.create_session(
                user_id=request.user_id,
                model_id=request.model_id,
                system_prompt=request.system_prompt,
                metadata=request.metadata
            )
        
        @self.router.get("/sessions/{session_id}")
        async def get_session_endpoint(session_id: str):
            session = self.load_session(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            return session.to_dict()
        
        @self.router.post("/sessions/{session_id}/chat")
        async def chat_endpoint(session_id: str, request: ACPChatRequest):
            return await self.chat_stream(
                session_id=session_id,
                message=request.message,
                stream=request.stream
            )
        
        @self.router.get("/sessions")
        async def list_sessions_endpoint():
            return self.list_sessions()
        
        @self.router.post("/sessions/{session_id}/close")
        async def close_session_endpoint(session_id: str):
            return self.close_session(session_id)
    
    async def create_session(self, user_id: str, model_id: str = "default",
                           system_prompt: str = "", metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        创建新会话
        
        Args:
            user_id: 用户ID
            model_id: 模型ID
            system_prompt: 系统提示
            metadata: 元数据
            
        Returns:
            会话信息
        """
        with self._lock:
            # 获取模型配置
            model_config = self._models.get(model_id)
            if model_config is None:
                model_config = self._models.get("default")
            
            # 创建会话配置
            session_config = ACPSessionConfig(
                system_prompt=system_prompt,
                metadata=metadata or {}
            )
            
            # 创建会话
            session = ACPSession(
                session_id=str(uuid.uuid4()),
                user_id=user_id,
                model_config=model_config,
                session_config=session_config,
                status=ACPSessionStatus.ACTIVE,
                metadata=metadata or {}
            )
            
            # 添加系统消息
            if system_prompt:
                system_message = ACPMessage(
                    role=ACPMessageRole.SYSTEM,
                    content=system_prompt
                )
                session.messages.append(system_message)
            
            # 存储会话
            self._sessions[session.session_id] = session
            
            logger.info(f"创建会话: {session.session_id} (用户: {user_id})")
            return session.to_dict()
    
    def load_session(self, session_id: str) -> Optional[ACPSession]:
        """
        加载会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话对象，不存在返回 None
        """
        with self._lock:
            return self._sessions.get(session_id)
    
    async def resume_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        恢复会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话信息，不存在返回 None
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            
            # 更新状态
            session.status = ACPSessionStatus.ACTIVE
            session.updated_at = datetime.datetime.now().timestamp()
            
            logger.info(f"恢复会话: {session_id}")
            return session.to_dict()
    
    def close_session(self, session_id: str) -> Dict[str, Any]:
        """
        关闭会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            操作结果
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            
            # 更新状态
            session.status = ACPSessionStatus.CLOSED
            session.updated_at = datetime.datetime.now().timestamp()
            
            logger.info(f"关闭会话: {session_id}")
            return {"success": True, "session_id": session_id}
    
    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """
        获取会话状态
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话状态信息
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            
            return {
                "session_id": session.session_id,
                "status": session.status.value,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "message_count": len(session.messages),
                "model": session.model_config.model_name
            }
    
    async def chat_stream(self, session_id: str, message: str, stream: bool = True) -> Any:
        """
        流式对话
        
        Args:
            session_id: 会话ID
            message: 用户消息
            stream: 是否流式输出
            
        Returns:
            流式响应或完整响应
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            
            if session.status != ACPSessionStatus.ACTIVE:
                raise HTTPException(status_code=400, detail="会话未激活")
            
            # 添加用户消息
            user_message = ACPMessage(
                role=ACPMessageRole.USER,
                content=message
            )
            session.messages.append(user_message)
            
            # 更新会话时间
            session.updated_at = datetime.datetime.now().timestamp()
        
        if stream:
            # 流式响应
            return self._generate_stream_response(session_id, message)
        else:
            # 非流式响应
            return await self._generate_normal_response(session_id, message)
    
    async def _generate_stream_response(self, session_id: str, message: str):
        """
        生成流式响应
        
        Args:
            session_id: 会话ID
            message: 用户消息
        """
        # 这里应该调用实际的LLM生成
        # 简化实现：返回模拟的流式数据
        
        async def generate():
            # 模拟思考过程
            yield ACPStreamChunk(
                event_type=ACPStreamEventType.THINKING,
                data={"step": "analyzing", "content": "正在分析您的问题..."}
            ).to_sse()
            
            await asyncio.sleep(0.1)
            
            # 模拟文本生成
            response_text = f"这是对您消息的回复: {message}"
            for i in range(0, len(response_text), 10):
                chunk = response_text[i:i+10]
                yield ACPStreamChunk(
                    event_type=ACPStreamEventType.TEXT_DELTA,
                    data={"content": chunk}
                ).to_sse()
                await asyncio.sleep(0.05)
            
            # 完成
            yield ACPStreamChunk(
                event_type=ACPStreamEventType.DONE,
                data={"message": "生成完成"}
            ).to_sse()
        
        return fastapi.responses.StreamingResponse(
            generate(),
            media_type="text/event-stream"
        )
    
    async def _generate_normal_response(self, session_id: str, message: str) -> Dict[str, Any]:
        """
        生成普通响应
        
        Args:
            session_id: 会话ID
            message: 用户消息
            
        Returns:
            响应内容
        """
        # 模拟生成
        response_text = f"这是对您消息的回复: {message}"
        
        # 添加助手消息
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                assistant_message = ACPMessage(
                    role=ACPMessageRole.ASSISTANT,
                    content=response_text
                )
                session.messages.append(assistant_message)
        
        return {
            "session_id": session_id,
            "message": response_text,
            "timestamp": datetime.datetime.now().timestamp()
        }
    
    async def switch_model(self, session_id: str, model_id: str) -> Dict[str, Any]:
        """
        切换模型
        
        Args:
            session_id: 会话ID
            model_id: 模型ID
            
        Returns:
            切换结果
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            
            # 获取新模型配置
            new_model = self._models.get(model_id)
            if new_model is None:
                raise HTTPException(status_code=400, detail="模型不存在")
            
            # 切换模型
            old_model = session.model_config.model_name
            session.model_config = new_model
            session.updated_at = datetime.datetime.now().timestamp()
            
            logger.info(f"会话 {session_id} 切换模型: {old_model} -> {new_model.model_name}")
            
            return {
                "success": True,
                "session_id": session_id,
                "old_model": old_model,
                "new_model": new_model.model_name
            }
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """
        获取可用模型列表
        
        Returns:
            模型列表
        """
        with self._lock:
            return [model.to_dict() for model in self._models.values()]
    
    def detect_model_capabilities(self, model_id: str) -> Dict[str, Any]:
        """
        检测模型能力
        
        Args:
            model_id: 模型ID
            
        Returns:
            模型能力信息
        """
        with self._lock:
            model = self._models.get(model_id)
            if model is None:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            return {
                "model_id": model.model_id,
                "capabilities": model.capabilities,
                "max_tokens": model.max_tokens,
                "supports_stream": True,
                "supports_tools": "tool_use" in model.capabilities
            }
    
    async def update_session_config(self, session_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        更新会话配置
        
        Args:
            session_id: 会话ID
            config: 配置字典
            
        Returns:
            更新结果
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            
            # 更新配置
            for key, value in config.items():
                if hasattr(session.session_config, key):
                    setattr(session.session_config, key, value)
            
            session.updated_at = datetime.datetime.now().timestamp()
            
            logger.info(f"更新会话配置: {session_id}")
            return {"success": True, "session_id": session_id}
    
    def get_session_config(self, session_id: str) -> Dict[str, Any]:
        """
        获取会话配置
        
        Args:
            session_id: 会话ID
            
        Returns:
            会话配置
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            
            return session.session_config.to_dict()
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有会话
        
        Returns:
            会话列表
        """
        with self._lock:
            sessions = []
            for session in self._sessions.values():
                sessions.append({
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "status": session.status.value,
                    "model": session.model_config.model_name,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "message_count": len(session.messages)
                })
            return sessions


# 全局实例管理
_acp_server: Optional[ACPServer] = None
_server_lock = threading.Lock()


def get_acp_server(config: Dict[str, Any] = None) -> ACPServer:
    """
    获取 ACP Server 单例
    
    Args:
        config: 配置字典
        
    Returns:
        ACPServer 实例
    """
    global _acp_server
    if _acp_server is None:
        with _server_lock:
            if _acp_server is None:
                _acp_server = ACPServer(config)
    return _acp_server


def reset_acp_server() -> None:
    """
    重置 ACP Server 单例
    """
    global _acp_server
    with _server_lock:
        _acp_server = None


# API 端点函数（用于直接调用）
async def create_session(user_id: str, model_id: str = "default",
                        system_prompt: str = "", metadata: Dict[str, Any] = None) -> Dict[str, Any]:
    """创建新 ACP 会话"""
    server = get_acp_server()
    return await server.create_session(user_id, model_id, system_prompt, metadata)


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    """加载已有 ACP 会话"""
    server = get_acp_server()
    session = server.load_session(session_id)
    return session.to_dict() if session else None


async def resume_session(session_id: str) -> Optional[Dict[str, Any]]:
    """恢复 ACP 会话"""
    server = get_acp_server()
    return await server.resume_session(session_id)


def close_session(session_id: str) -> Dict[str, Any]:
    """关闭 ACP 会话"""
    server = get_acp_server()
    return server.close_session(session_id)


def get_session_status(session_id: str) -> Dict[str, Any]:
    """获取 ACP 会话状态"""
    server = get_acp_server()
    return server.get_session_status(session_id)


async def chat_stream(session_id: str, message: str, stream: bool = True) -> Any:
    """ACP 流式对话"""
    server = get_acp_server()
    return await server.chat_stream(session_id, message, stream)


async def submit_tool_result(session_id: str, tool_call_id: str, result: Any) -> Dict[str, Any]:
    """提交工具调用结果"""
    # 简化实现
    return {"success": True, "session_id": session_id, "tool_call_id": tool_call_id}


async def switch_model(session_id: str, model_id: str) -> Dict[str, Any]:
    """切换模型"""
    server = get_acp_server()
    return await server.switch_model(session_id, model_id)


def get_models() -> List[Dict[str, Any]]:
    """获取可用模型列表"""
    server = get_acp_server()
    return server.get_available_models()


def detect_capabilities(model_id: str) -> Dict[str, Any]:
    """探测模型能力"""
    server = get_acp_server()
    return server.detect_model_capabilities(model_id)


async def update_config(session_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """更新会话配置"""
    server = get_acp_server()
    return await server.update_session_config(session_id, config)


def get_config(session_id: str) -> Dict[str, Any]:
    """获取会话配置"""
    server = get_acp_server()
    return server.get_session_config(session_id)


def list_sessions() -> List[Dict[str, Any]]:
    """列出所有活跃的 ACP 会话"""
    server = get_acp_server()
    return server.list_sessions()