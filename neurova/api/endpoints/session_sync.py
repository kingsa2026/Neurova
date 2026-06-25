"""
会话同步 API 端点

提供 WebSocket 和 REST API 用于跨渠道会话同步。

WebSocket 端点：
- WS /api/v1/sync/ws/{session_id} - 实时同步连接

REST API：
- POST /api/v1/sync/sessions - 创建会话
- GET /api/v1/sync/sessions/{session_id} - 获取会话信息
- GET /api/v1/sync/sessions/{session_id}/history - 获取历史
- POST /api/v1/sync/sessions/{session_id}/messages - 发送消息（REST 降级）
"""

from __future__ import annotations

import json
from neurova.core.logger import get_logger
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from neurova.sync.session_sync_manager import (
    EventType,
    SessionEvent,
    get_session_sync_manager,
)

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    """创建会话请求"""

    user_id: str = Field(..., description="用户 ID")
    agent_id: str = Field(default="default", description="Agent ID")
    external_id: Optional[str] = Field(default=None, description="外部 ID（渠道特定）")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="会话元数据")


class SendMessageRequest(BaseModel):
    """发送消息请求"""

    content: str = Field(..., description="消息内容")
    channel_type: str = Field(default="api", description="渠道类型")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="消息元数据")


class SessionResponse(BaseModel):
    """会话响应"""

    session_id: str
    user_id: str
    agent_id: str
    conversation_id: str
    created_at: str
    last_activity: str
    status: str
    active_channels: List[str]
    history_size: int


# ---------------------------------------------------------------------------
# WebSocket 连接管理
# ---------------------------------------------------------------------------


class WebSocketConnection:
    """WebSocket 连接包装器"""

    def __init__(self, websocket: WebSocket, session_id: str, channel_type: str = "web"):
        self.websocket = websocket
        self.session_id = session_id
        self.channel_type = channel_type
        self.connection_id = f"ws_{uuid.uuid4().hex[:12]}"
        self.connected_at = datetime.now(timezone.utc)
        self.last_heartbeat = datetime.now(timezone.utc)

    async def send_event(self, event: SessionEvent):
        """发送事件到 WebSocket 客户端"""
        try:
            data = event.to_json()
            await self.websocket.send_text(data)
        except Exception as e:
            logger.error("WebSocket send error: %s", e)
            raise

    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = datetime.now(timezone.utc)


# 活跃的 WebSocket 连接
_ws_connections: Dict[str, List[WebSocketConnection]] = {}


# ---------------------------------------------------------------------------
# WebSocket 端点
# ---------------------------------------------------------------------------


@router.websocket("/ws/{session_id}")
async def websocket_sync(websocket: WebSocket, session_id: str, channel_type: str = "web"):
    """
    WebSocket 实时同步连接

    连接后会自动接收该会话的所有事件。
    客户端可以发送消息，会自动广播到其他渠道。

    消息格式：
    - 发送：{"type": "user_message", "content": "..."}
    - 接收：SessionEvent JSON
    """
    await websocket.accept()

    manager = get_session_sync_manager()
    session = manager.get_session(session_id)

    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    # 创建连接包装器
    ws_conn = WebSocketConnection(websocket, session_id, channel_type)

    # 注册到连接列表
    if session_id not in _ws_connections:
        _ws_connections[session_id] = []
    _ws_connections[session_id].append(ws_conn)

    # 注册到 SessionSyncManager
    async def send_callback(event: SessionEvent):
        await ws_conn.send_event(event)

    manager.register_channel(
        session_id=session_id,
        channel_type=channel_type,
        send_callback=send_callback,
        metadata={"connection_id": ws_conn.connection_id},
    )

    # 发送历史事件（最近 50 条）
    history = session.get_history(limit=50)
    for event in history:
        try:
            await ws_conn.send_event(event)
        except Exception:
            break

    try:
        # 消息循环
        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            msg_type = message.get("type", "user_message")

            # 处理心跳
            if msg_type == "heartbeat":
                ws_conn.update_heartbeat()
                manager.update_heartbeat(session_id, channel_type)
                await websocket.send_json({"type": "heartbeat_ack"})
                continue

            # 处理用户消息
            if msg_type == "user_message":
                content = message.get("content", "")
                if not content:
                    await websocket.send_json({"error": "Empty message"})
                    continue

                # 创建事件
                event = SessionEvent(
                    event_type=EventType.USER_MESSAGE,
                    session_id=session_id,
                    source_channel=channel_type,
                    payload={"content": content, "metadata": message.get("metadata", {})},
                )

                # 广播到其他渠道
                await manager.broadcast_event(session_id, event, exclude_channel=channel_type)

                # 确认发送
                await websocket.send_json({"type": "message_sent", "event_id": event.event_id})

                # TODO: 触发 Agent 处理
                # 这里应该调用 Agent 的 chat 方法

            # 处理同步请求
            elif msg_type == "sync_request":
                limit = message.get("limit", 100)
                history = session.get_history(limit=limit)

                await websocket.send_json({"type": "sync_response", "events": [e.to_dict() for e in history]})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", ws_conn.connection_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        # 清理连接
        if session_id in _ws_connections:
            _ws_connections[session_id] = [
                c for c in _ws_connections[session_id] if c.connection_id != ws_conn.connection_id
            ]
            if not _ws_connections[session_id]:
                del _ws_connections[session_id]

        manager.unregister_channel(session_id, channel_type)


# ---------------------------------------------------------------------------
# REST API 端点
# ---------------------------------------------------------------------------


@router.post("/sessions", response_model=SessionResponse)
async def create_session(body: CreateSessionRequest):
    """创建同步会话"""
    manager = get_session_sync_manager()

    session = manager.create_session(
        user_id=body.user_id, agent_id=body.agent_id, external_id=body.external_id, metadata=body.metadata
    )

    return SessionResponse(**session.to_dict())


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """获取会话信息"""
    manager = get_session_sync_manager()
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse(**session.to_dict())


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 100):
    """获取会话历史"""
    manager = get_session_sync_manager()
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    history = session.get_history(limit=limit)

    return {"session_id": session_id, "total": len(history), "events": [e.to_dict() for e in history]}


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: SendMessageRequest):
    """
    发送消息（REST 降级方案）

    当 WebSocket 不可用时，可以使用此端点发送消息。
    """
    manager = get_session_sync_manager()
    session = manager.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 创建事件
    event = SessionEvent(
        event_type=EventType.USER_MESSAGE,
        session_id=session_id,
        source_channel=body.channel_type,
        payload={"content": body.content, "metadata": body.metadata},
    )

    # 广播事件
    sent_count = await manager.broadcast_event(session_id, event)

    return {"success": True, "event_id": event.event_id, "sent_to_channels": sent_count}


@router.delete("/sessions/{session_id}")
async def end_session(session_id: str):
    """结束会话"""
    manager = get_session_sync_manager()

    if not manager.end_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    return {"success": True, "session_id": session_id}


@router.get("/sessions")
async def list_sessions(user_id: Optional[str] = None, agent_id: Optional[str] = None, status: Optional[str] = None):
    """列出会话"""
    manager = get_session_sync_manager()
    sessions = manager.list_sessions(user_id=user_id, agent_id=agent_id, status=status)

    return {"total": len(sessions), "sessions": [s.to_dict() for s in sessions]}


@router.get("/statistics")
async def get_statistics():
    """获取同步统计信息"""
    manager = get_session_sync_manager()
    return manager.get_statistics()


@router.get("/connections")
async def get_connections():
    """获取活跃 WebSocket 连接信息"""
    connections = []

    for session_id, conns in _ws_connections.items():
        for conn in conns:
            connections.append(
                {
                    "session_id": session_id,
                    "connection_id": conn.connection_id,
                    "channel_type": conn.channel_type,
                    "connected_at": conn.connected_at.isoformat(),
                    "last_heartbeat": conn.last_heartbeat.isoformat(),
                }
            )

    return {"total": len(connections), "connections": connections}
