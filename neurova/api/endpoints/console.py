"""
Web Console API - 控制台后端 API
"""

import asyncio
import datetime
import json
import logging
import os
import re
import time
import typing
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from neurova.api.endpoints import get_agent_instance

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Connection Manager ─────────────────────────────────


class ConnectionManager:
    def __init__(self):
        self._connections: typing.Dict[str, WebSocket] = {}
        self._messages: typing.Dict[str, list] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self._connections[client_id] = websocket

    def disconnect(self, client_id: str):
        self._connections.pop(client_id, None)

    async def send_personal_message(self, message: dict, client_id: str):
        ws = self._connections.get(client_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(client_id)

    async def broadcast(self, message: dict):
        disconnected = []
        for cid, ws in self._connections.items():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(cid)
        for cid in disconnected:
            self.disconnect(cid)

    def store_message(self, user_id: str, message: dict):
        msgs = self._messages.setdefault(user_id, [])
        message["stored_at"] = time.time()
        msgs.append(message)

    def get_messages(self, user_id: str, since: float = 0) -> list:
        return [m for m in self._messages.get(user_id, []) if m.get("stored_at", 0) > since]


_manager = ConnectionManager()
_CONSOLE_UPLOAD_DIR = Path(os.getenv("NEUROVA_CONSOLE_UPLOADS", "uploads/console"))
_CONSOLE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_CHAT_SESSIONS: typing.Dict[str, dict] = {}
_SESSIONS_FILE = Path("data/console_sessions.json")
_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_sessions_from_disk():
    """从磁盘加载会话"""
    if _SESSIONS_FILE.exists():
        try:
            with open(_SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _CHAT_SESSIONS.update(data)
                logger.info("Loaded %d sessions from disk", len(data))
        except Exception as e:
            logger.warning("Failed to load sessions: %s", e)


def _save_sessions_to_disk():
    """将会话持久化到磁盘"""
    try:
        with open(_SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(_CHAT_SESSIONS, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.warning("Failed to save sessions: %s", e)


# 启动时加载
_load_sessions_from_disk()


def _safe_filename(filename: str) -> str:
    name = re.sub(r"[^\w\.\-]", "_", filename)
    return name[:200] if name else "unnamed"


def _tail_text_file(path: str, lines: int = 100) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except Exception as e:
        return f"Error reading file: {e}"


def _get_user_id(request) -> str:
    return getattr(request.state, "user_id", "anonymous")


# ── Models ─────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: typing.Optional[str] = None
    agent_id: typing.Optional[str] = None
    stream: bool = True
    model: typing.Optional[str] = None


class CommandRequest(BaseModel):
    command: str
    args: typing.Optional[typing.List[str]] = None


# ── Chat endpoints ─────────────────────────────────────


@router.post("/chat")
async def post_console_chat(body: ChatRequest, request: Request):
    """流式聊天接口（SSE）"""
    user_id = _get_user_id(request)
    session_id = body.session_id or str(uuid.uuid4())
    session = _CHAT_SESSIONS.setdefault(
        session_id,
        {"id": session_id, "user_id": user_id, "agent_id": getattr(body, "agent_id", "") or "", "messages": [], "created_at": datetime.datetime.utcnow().isoformat()},
    )

    # 只保留最近一轮对话（避免旧消息泄漏到新请求）
    session["messages"] = [
        {"role": "user", "content": body.message, "timestamp": datetime.datetime.utcnow().isoformat()}
    ]

    # 不传递历史给 agent，每次请求独立
    history_for_agent = []

    # Try to get agent for real response
    reply = ""
    reasoning = None
    tool_messages = []
    try:
        agent = get_agent_instance(agent_id=body.agent_id or "default")
        if agent:
            response = await agent.chat(body.message, session_id=session_id, metadata={"history": history_for_agent})
            if isinstance(response, dict):
                reply = response.get("text", str(response))
                reasoning = response.get("reasoning")
                tool_messages = response.get("tool_messages", []) or []
            else:
                reply = str(response)
        else:
            reply = f"Echo: {body.message}"
    except Exception as e:
        logger.warning("Console chat error: %s", e, exc_info=True)
        reply = f"Error: {str(e)}"

    session["messages"].append(
        {"role": "assistant", "content": reply, "timestamp": datetime.datetime.utcnow().isoformat()}
    )
    _save_sessions_to_disk()

    if body.stream:

        async def event_stream():
            # 1. 发送思考过程
            if reasoning:
                yield f"data: {json.dumps({'type': 'reasoning', 'content': reasoning})}\n\n"

            # 2. 发送工具调用/结果
            for tm in tool_messages:
                if isinstance(tm, dict):
                    tm_type = tm.get("type", "")
                    if tm_type == "tool_call":
                        yield f"data: {json.dumps({'type': 'tool_call', 'name': tm.get('tool_name', ''), 'arguments': json.dumps(tm.get('params', {}), ensure_ascii=False)})}\n\n"
                    elif tm_type == "tool_result":
                        result_text = tm.get("result", "")
                        if isinstance(result_text, dict):
                            result_text = json.dumps(result_text, ensure_ascii=False)
                        yield f"data: {json.dumps({'type': 'tool_result', 'result': str(result_text)[:500]})}\n\n"

            # 3. 发送回复内容（逐词）
            words = reply.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
                await asyncio.sleep(0.02)
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return {"code": 0, "message": "success", "data": {"reply": reply, "session_id": session_id}}


@router.post("/chat/stop")
async def post_console_chat_stop(session_id: str):
    """停止运行中的对话"""
    return {"code": 0, "message": "Chat stopped", "data": {"session_id": session_id}}


@router.get("/chat/history")
async def get_chat_history(session_id: str, request: Request):
    """获取聊天历史"""
    session = _CHAT_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"code": 0, "message": "success", "data": {"messages": session["messages"], "session_id": session_id}}


@router.post("/chat/new")
async def post_console_chat_new(request: Request):
    """创建新会话"""
    user_id = _get_user_id(request)
    session_id = str(uuid.uuid4())
    _CHAT_SESSIONS[session_id] = {
        "id": session_id,
        "user_id": user_id,
        "agent_id": "",
        "messages": [],
        "created_at": datetime.datetime.utcnow().isoformat(),
    }
    _save_sessions_to_disk()
    return {"code": 0, "message": "Session created", "data": {"session_id": session_id}}


@router.get("/chat/sessions")
async def get_chat_sessions(request: Request, agent_id: str = Query(default="")):
    """列出所有会话（按 agent_id 过滤）"""
    user_id = _get_user_id(request)
    sessions = [s for s in _CHAT_SESSIONS.values() if s.get("user_id") == user_id]
    if agent_id:
        sessions = [s for s in sessions if s.get("agent_id") == agent_id]
    sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    # 只返回摘要信息，不返回完整消息列表
    summaries = [{"id": s["id"], "title": s.get("title", "新对话"), "agent_id": s.get("agent_id", ""), "created_at": s.get("created_at", "")} for s in sessions]
    return {"code": 0, "message": "success", "data": {"sessions": summaries, "total": len(summaries)}}


# ── File endpoints ─────────────────────────────────────


@router.post("/upload")
async def post_console_upload(request: Request, file: UploadFile = File(...)):
    """上传文件"""
    safe_name = _safe_filename(file.filename or "unnamed")
    file_id = str(uuid.uuid4())[:8]
    dest = _CONSOLE_UPLOAD_DIR / f"{file_id}_{safe_name}"

    content = await file.read()
    dest.write_bytes(content)

    file_info = {
        "file_id": file_id,
        "filename": safe_name,
        "size": len(content),
        "content_type": file.content_type or "application/octet-stream",
        "path": str(dest),
        "uploaded_at": datetime.datetime.utcnow().isoformat(),
    }
    return {"code": 0, "message": "File uploaded", "data": file_info}


@router.get("/uploads")
async def list_console_uploads(request: Request):
    """列出已上传文件"""
    files = []
    for f in sorted(_CONSOLE_UPLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            files.append(
                {
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "modified": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                }
            )
    return {"code": 0, "message": "success", "data": {"files": files, "total": len(files)}}


@router.get("/uploads/{filename}")
async def get_console_upload(filename: str):
    """下载文件"""
    safe = _safe_filename(filename)
    path = _CONSOLE_UPLOAD_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), filename=safe)


@router.delete("/uploads/{filename}")
async def delete_console_upload(filename: str):
    """删除文件"""
    safe = _safe_filename(filename)
    path = _CONSOLE_UPLOAD_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    path.unlink()
    return {"code": 0, "message": "File deleted"}


# ── Debug endpoints ────────────────────────────────────


@router.get("/debug/logs")
async def get_backend_debug_logs(lines: int = 100):
    """查看后端日志"""
    log_path = os.getenv("NEUROVA_LOG_FILE", "logs/neurova.log")
    if os.path.exists(log_path):
        content = _tail_text_file(log_path, lines)
    else:
        content = "Log file not found. Set NEUROVA_LOG_FILE environment variable."
    return {"code": 0, "message": "success", "data": {"content": content, "lines": lines}}


@router.get("/debug/status")
async def get_system_status():
    """系统状态"""
    import psutil

    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        status = {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / 1048576),
            "memory_total_mb": round(mem.total / 1048576),
            "disk_percent": disk.percent,
            "uptime_seconds": int(time.time() - psutil.boot_time()),
        }
    except Exception:
        status = {
            "note": "psutil not available, showing basic info",
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }
    return {"code": 0, "message": "success", "data": status}


@router.post("/debug/command")
async def post_debug_run_command(body: CommandRequest):
    """运行调试命令"""
    allowed = {"ls", "pwd", "echo", "whoami", "date", "env", "python --version", "node --version"}
    cmd = body.command.strip()
    if cmd not in allowed and not any(cmd.startswith(a) for a in ["echo "]):
        raise HTTPException(status_code=403, detail=f"Command '{cmd}' not allowed. Allowed: {sorted(allowed)}")

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        return {
            "code": 0,
            "message": "success",
            "data": {
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "returncode": proc.returncode,
            },
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Command timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── WebSocket ──────────────────────────────────────────


@router.websocket("/ws/{client_id}")
async def websocket_console(websocket: WebSocket, client_id: str):
    """WebSocket 连接，支持推送消息和双向通信。"""
    await _manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
            elif msg_type == "chat":
                message = data.get("message", "")
                ws_session_id = data.get("session_id") or str(uuid.uuid4())
                try:
                    agent = get_agent_instance()
                    reply = await agent.chat(
                        message,
                        session_id=ws_session_id,
                        metadata={"history": []},
                    ) if agent else f"Echo: {message}"
                except Exception:
                    reply = f"Echo: {message}"
                await websocket.send_json({"type": "chat_reply", "content": reply})
            else:
                await websocket.send_json({"type": "ack", "data": data})
    except WebSocketDisconnect:
        _manager.disconnect(client_id)


# ── Push message endpoints ─────────────────────────────


@router.get("/push/messages")
async def get_push_messages(request: Request, since: float = 0):
    """获取推送消息（轮询方式）"""
    user_id = _get_user_id(request)
    messages = _manager.get_messages(user_id, since)
    return {"code": 0, "message": "success", "data": {"messages": messages, "total": len(messages)}}


@router.post("/push/message")
async def post_push_message(body: dict, request: Request):
    """发送推送消息（广播给所有WebSocket连接）"""
    message = {
        "type": "push",
        "content": body.get("content", ""),
        "sender": _get_user_id(request),
        "timestamp": time.time(),
    }
    await _manager.broadcast(message)
    _manager.store_message(_get_user_id(request), message)
    return {"code": 0, "message": "Push sent"}
