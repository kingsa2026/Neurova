from __future__ import annotations

"""
对话接口 - Chat Endpoint

功能:
1. 普通对话 (POST /api/v1/chat)
2. 流式对话 SSE (POST /api/v1/chat/stream)
3. 清空对话历史 (DELETE /api/v1/chat/history)
4. 获取对话历史 (GET /api/v1/chat/history)
"""

import asyncio
import datetime
import json
import logging
from pathlib import Path
import re
import time
import typing
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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


def _user_can_access_agent(user_id: str, agent_id: str) -> bool:
    """检查用户是否有权访问 Agent"""
    # TODO: 实现权限检查
    return True


@router.post("")
async def chat(request: Request, body: ChatRequest):
    """普通对话"""
    request_id = _get_request_id(request)

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
        # 调用 Agent 的 chat 方法
        response = await agent.chat(
            user_input=body.message,
            session_id=body.session_id,
            metadata=body.metadata,
        )

        return {
            "code": 0,
            "message": "success",
            "data": {
                "response": response,
                "agent_id": body.agent_id,
                "session_id": body.session_id or "default",
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
async def chat_stream(request: Request, body: ChatStreamRequest):
    """流式对话 SSE"""
    request_id = _get_request_id(request)

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

            # 调用 Agent 的流式 chat 方法
            if hasattr(agent, "chat_stream"):
                async for chunk in agent.chat_stream(
                    user_input=body.message,
                    session_id=body.session_id,
                    metadata=body.metadata,
                ):
                    yield f"event: message\ndata: {json.dumps({'content': chunk})}\n\n"
            else:
                # 降级到非流式
                response = await agent.chat(
                    user_input=body.message,
                    session_id=body.session_id,
                    metadata=body.metadata,
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


@router.get("/history")
async def get_chat_history(
    request: Request,
    agent_id: str = Query(default="default"),
    session_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """获取对话历史"""
    request_id = _get_request_id(request)

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
    agent_id: str = Query(default="default"),
    session_id: Optional[str] = Query(default=None),
):
    """清空对话历史"""
    request_id = _get_request_id(request)

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
