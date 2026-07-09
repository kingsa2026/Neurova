from __future__ import annotations

"""
对话接口 - Chat Endpoint

功能:
1. 普通对话 (POST /api/v1/chat)
2. 流式对话 SSE (POST /api/v1/chat/stream)
3. 清空对话历史 (DELETE /api/v1/chat/history)
4. 获取对话历史 (GET /api/v1/chat/history)
"""

import datetime
import json
from neurova.core.logger import get_logger
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user

logger = get_logger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """对话请求"""

    message: str = Field(..., description="用户消息")
    agent_id: str = Field(default="default", description="Agent ID")
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    model: Optional[str] = Field(default=None, description="指定模型")
    temperature: Optional[float] = Field(default=None, description="温度参数")
    max_tokens: Optional[int] = Field(default=None, description="最大 token 数")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class ChatStreamRequest(BaseModel):
    """流式对话请求"""

    message: str = Field(..., description="用户消息")
    agent_id: str = Field(default="default", description="Agent ID")
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    model: Optional[str] = Field(default=None, description="指定模型")
    temperature: Optional[float] = Field(default=None, description="温度参数")
    max_tokens: Optional[int] = Field(default=None, description="最大 token 数")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class AttachmentRequest(BaseModel):
    """附件请求"""

    file_path: str
    file_type: str = "file"
    description: str = ""


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _user_can_access_agent(user_id: str, agent_id: str, role: str = "user") -> bool:
    """
    检查用户是否有权访问 Agent

    权限规则:
    1. admin 角色: 可访问所有 Agent
    2. 普通用户: 只能访问自己创建的 Agent (owner_user_id 匹配)
    3. agent 无 owner_user_id: 仅 admin 可访问（防止未授权访问）
    """
    if role == "admin":
        return True

    agent = _get_agent(agent_id)
    if not agent:
        return False

    # 获取 Agent 的 owner_user_id
    owner_user_id = getattr(agent.config, "owner_user_id", None)

    # 无 owner: 普通用户无法访问
    if not owner_user_id:
        return False

    # 仅 owner 可访问
    return owner_user_id == user_id


@router.post("")
async def chat(request: Request, body: ChatRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    """普通对话"""
    request_id = _get_request_id(request)

    # 权限检查
    user_id = current_user.get("user_id", "")
    role = current_user.get("role", "user")
    if not _user_can_access_agent(user_id, body.agent_id, role):
        return JSONResponse(
            status_code=403,
            content={
                "code": 4003,
                "message": "Permission denied: you don't have access to this Agent",
                "request_id": request_id,
            },
        )

    agent = _get_agent(body.agent_id)
    if not agent:
        return JSONResponse(
            status_code=404,
            content={
                "code": 3000,
                "message": f"Agent '{body.agent_id}' not found",
                "request_id": request_id,
            },
        )

    try:
        # Bug V2-3 修复:不强制传 {"history": []} 给 agent。
        # 原代码 `body.metadata if "history" in body.metadata else {"history": []}`
        # 在调用方未传 history 键时,丢掉 metadata 中其他字段(voice_context 等),
        # 且强制空历史导致 LLM 缺对话上下文,工具参数指代不清("搜一下他"不知道"他"是谁)。
        # 现在不强制注入,让 chat_pipeline 自行从 session 恢复历史。
        call_metadata = body.metadata or {}

        # 调用 Agent 的 chat 方法
        response = await agent.chat(
            user_input=body.message,
            session_id=body.session_id,
            metadata=call_metadata,
        )

        # 提取响应数据，适配前端期望格式
        reply_text = ""
        audio_info = None

        if isinstance(response, dict):
            # Agent.chat() 返回字典格式：{"text": "...", "audio_path": "...", "audio_data": "..."}
            reply_text = response.get("text", "")
            audio_path = response.get("audio_path")
            audio_data = response.get("audio_data")

            if audio_path or audio_data:
                audio_info = {
                    "url": audio_path,
                    "data": audio_data,
                    "filename": f"tts_{int(__import__('time').time())}.wav",
                }
        else:
            # 如果返回字符串，直接作为回复文本
            reply_text = str(response)

        return {
            "code": 0,
            "message": "success",
            "data": {
                "reply": reply_text,
                "audio": audio_info,
                "agent_id": body.agent_id,
                "session_id": body.session_id or "default",
                "tool_messages": response.get("tool_messages", []) if isinstance(response, dict) else [],
                "reasoning": response.get("reasoning", "") if isinstance(response, dict) else "",
            },
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "code": 5000,
                "message": f"Chat failed: {str(e)}",
                "request_id": request_id,
            },
        )


@router.post("/stream")
async def chat_stream(
    request: Request, body: ChatStreamRequest, current_user: Dict[str, Any] = Depends(get_current_user)
):
    """流式对话 SSE"""
    request_id = _get_request_id(request)

    # 权限检查
    user_id = current_user.get("user_id", "")
    role = current_user.get("role", "user")
    if not _user_can_access_agent(user_id, body.agent_id, role):
        return JSONResponse(
            status_code=403,
            content={
                "code": 4003,
                "message": "Permission denied: you don't have access to this Agent",
                "request_id": request_id,
            },
        )

    agent = _get_agent(body.agent_id)
    if not agent:
        return JSONResponse(
            status_code=404,
            content={
                "code": 3000,
                "message": f"Agent '{body.agent_id}' not found",
                "request_id": request_id,
            },
        )

    async def event_generator():
        """SSE 事件生成器"""
        try:
            # 发送开始事件
            yield f"event: start\ndata: {json.dumps({'request_id': request_id})}\n\n"

            # Bug V2-3 修复:不强制传 {"history": []}(同 POST /api/v1/chat 修复)
            call_metadata = body.metadata or {}

            # 调用 Agent 的流式 chat 方法
            if hasattr(agent, "chat_stream"):
                async for chunk in agent.chat_stream(
                    user_input=body.message,
                    session_id=body.session_id,
                    metadata=call_metadata,
                ):
                    yield f"event: message\ndata: {json.dumps({'content': chunk})}\n\n"
            else:
                # 降级到非流式
                response = await agent.chat(
                    user_input=body.message,
                    session_id=body.session_id,
                    metadata=call_metadata,
                )
                yield f"event: message\ndata: {json.dumps({'content': response})}\n\n"

            # 发送完成事件
            yield f"event: done\ndata: {json.dumps({'request_id': request_id})}\n\n"

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": request_id,
        },
    )


# #7 已删除 4 个 /sessions 死端点:
# - GET /sessions(与 console.py /chat/sessions 重复,且 hasattr(agent, "get_sessions") 守卫
#   Agent 类无 get_sessions 方法,只有 session_manager 属性)
# - POST /sessions(与 console.py /chat/sessions POST 重复)
# - PUT /sessions/{session_id}(纯 stub,注释明确说"我们没有实际的会话存储")
# - DELETE /sessions/{session_id}(纯 stub,注释明确说"我们没有实际的会话存储")
# 前端只用 /api/v1/console/chat/sessions(console.py 路由,已通过 SessionRepository 接入真实存储)。
# 详见 docs/adr/0008-session-repository.md


@router.get("/history")
async def get_chat_history(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    agent_id: str = Query(default="default"),
    session_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """获取对话历史"""
    request_id = _get_request_id(request)

    # 权限检查
    user_id = current_user.get("user_id", "")
    role = current_user.get("role", "user")
    if not _user_can_access_agent(user_id, agent_id, role):
        return JSONResponse(
            status_code=403,
            content={
                "code": 4003,
                "message": "Permission denied: you don't have access to this Agent",
                "request_id": request_id,
            },
        )

    agent = _get_agent(agent_id)
    if not agent:
        return JSONResponse(
            status_code=404,
            content={
                "code": 3000,
                "message": f"Agent '{agent_id}' not found",
                "request_id": request_id,
            },
        )

    try:
        # 获取对话历史
        history = []
        if hasattr(agent, "get_conversation_history"):
            history = agent.get_conversation_history(
                session_id=session_id,
                limit=limit,
            )

        return {
            "code": 0,
            "message": "success",
            "data": {
                "history": history,
                "agent_id": agent_id,
                "session_id": session_id,
            },
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Get history error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "code": 5000,
                "message": f"Failed to get history: {str(e)}",
                "request_id": request_id,
            },
        )


@router.delete("/history")
async def clear_chat_history(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    agent_id: str = Query(default="default"),
    session_id: Optional[str] = Query(default=None),
):
    """清空对话历史"""
    request_id = _get_request_id(request)

    # 权限检查
    user_id = current_user.get("user_id", "")
    role = current_user.get("role", "user")
    if not _user_can_access_agent(user_id, agent_id, role):
        return JSONResponse(
            status_code=403,
            content={
                "code": 4003,
                "message": "Permission denied: you don't have access to this Agent",
                "request_id": request_id,
            },
        )

    agent = _get_agent(agent_id)
    if not agent:
        return JSONResponse(
            status_code=404,
            content={
                "code": 3000,
                "message": f"Agent '{agent_id}' not found",
                "request_id": request_id,
            },
        )

    try:
        if hasattr(agent, "clear_conversation_history"):
            agent.clear_conversation_history(session_id=session_id)

        return {
            "code": 0,
            "message": "History cleared",
            "data": {
                "agent_id": agent_id,
                "session_id": session_id,
            },
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Clear history error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "code": 5000,
                "message": f"Failed to clear history: {str(e)}",
                "request_id": request_id,
            },
        )


@router.post("/attachment")
async def add_attachment(request: Request, body: AttachmentRequest):
    """添加附件到对话"""
    request_id = _get_request_id(request)

    try:
        # TODO: 实现附件处理
        return {
            "code": 0,
            "message": "Attachment added",
            "data": {
                "file_path": body.file_path,
                "file_type": body.file_type,
            },
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Add attachment error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "code": 5000,
                "message": f"Failed to add attachment: {str(e)}",
                "request_id": request_id,
            },
        )
