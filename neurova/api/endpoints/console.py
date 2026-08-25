"""
Web Console API - 控制台后端 API
"""

import asyncio
import datetime
import json
from neurova.core import config
from neurova.core.logger import get_logger
import os
import re
import time
import typing
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Any, Dict

from neurova.api.deps import require_admin
from neurova.api.endpoints import get_agent_instance
from neurova.session_repository import get_session_repository

logger = get_logger(__name__)
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
_CONSOLE_UPLOAD_DIR = Path(config.get("NEUROVA_CONSOLE_UPLOADS", "uploads/console"))
_CONSOLE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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


def _extract_approval_payload(result_text, tm: dict) -> dict:
    """
    从工具结果中提取治理 ASK 待审批信息。

    Args:
        result_text: 工具结果（JSON 字符串或原始对象，未截断）
        tm: tool_message 原始条目（兜底取 tool_name）

    Returns:
        非空 dict 表示需要前端弹审批框；空 dict 表示普通结果。
    """
    parsed = None
    if isinstance(result_text, dict):
        parsed = result_text
    elif isinstance(result_text, str):
        try:
            candidate = json.loads(result_text)
            if isinstance(candidate, dict):
                parsed = candidate
        except Exception:
            # 结果可能被上游截断：退化用正则抽取关键字段
            m = re.search(r'"approval_id"\s*:\s*"([^"]+)"', result_text)
            if m and '"pending_approval"' in result_text:
                return {
                    "approval_id": m.group(1),
                    "tool_name": tm.get("tool_name", ""),
                    "params": {},
                    "reason": "",
                }
    if parsed and parsed.get("pending_approval"):
        return {
            "approval_id": parsed.get("approval_id"),
            "tool_name": parsed.get("tool_name") or tm.get("tool_name", ""),
            "params": parsed.get("params") or {},
            "reason": parsed.get("error", ""),
            "governance": parsed.get("governance") or {},
        }
    return {}


@router.post("/chat")
async def post_console_chat(body: ChatRequest, request: Request):
    """流式聊天接口（SSE）"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    agent_id = getattr(body, "agent_id", "") or ""

    # 会话 ID：客户端传入或新建
    if body.session_id:
        session_id = body.session_id
    else:
        session_id = repo.create_session(agent_id=agent_id, user_id=user_id, title="新对话")

    # S1 修复 (Critical #1 双写冲突): console 不再调 repo.save_message.
    # 持久化完全委托给 ChatPipeline._step_save_session → _save_to_session →
    # sm.add_message (成对原子写入 user+assistant).
    # 原代码 console + pipeline 各自独立写 session 文件,单次对话后
    # messages 数组含 4 条 [user, user, assistant, assistant].
    # Bug B-2 修复:不强制传空历史给 agent,让 agent.chat() 自己从 session 恢复历史.

    # Try to get agent for real response
    reply = ""
    reasoning = None
    tool_messages = []
    try:
        agent = get_agent_instance(agent_id=body.agent_id or "default")
        if agent:
            # WARN #3 修复: 传 metadata={"user_id": user_id}.
            # 原代码不传 metadata,ChatPipeline 用 "anonymous" 兜底,
            # 导致记忆保存/事件广播拿不到真实 user_id.
            response = await agent.chat(
                body.message,
                session_id=session_id,
                metadata={"user_id": user_id},
            )
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

    # S1: assistant_metadata 仅用于 SSE event_stream (reasoning/tool_messages 展示),
    # 不再传给 repo.save_message (持久化由 pipeline 负责).
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

                        # P0 人工确认弹窗: 检测治理 ASK 结果，推送结构化审批事件。
                        # 必须在截断前的完整文本上解析。
                        approval_payload = _extract_approval_payload(result_text, tm)
                        if approval_payload:
                            yield (
                                "data: "
                                + json.dumps(
                                    {"type": "approval_required", **approval_payload},
                                    ensure_ascii=False,
                                )
                                + "\n\n"
                            )

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
    repo = get_session_repository()
    # history 端点没有 agent_id 参数，用空字符串查询（SessionManager 支持）
    messages = repo.get_history(agent_id="", session_id=session_id)
    if not messages:
        # 尝试扫描所有 agent 目录（session_id 唯一）
        sessions = repo.list_sessions()
        matched = [s for s in sessions if s.get("session_id") == session_id or s.get("id") == session_id]
        if not matched:
            raise HTTPException(status_code=404, detail="Session not found")
        agent_id = matched[0].get("agent_id", "")
        messages = repo.get_history(agent_id=agent_id, session_id=session_id)
    return {"code": 0, "message": "success", "data": {"messages": messages, "session_id": session_id}}


@router.post("/chat/new")
async def post_console_chat_new(request: Request):
    """创建新会话"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    agent_id = ""
    title = "新对话"
    try:
        body = await request.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        agent_id = body.get("agent_id") or ""
        title = body.get("title") or "新对话"
    session_id = repo.create_session(agent_id=agent_id, user_id=user_id, title=title)
    return {"code": 0, "message": "Session created", "data": {"session_id": session_id}}


@router.get("/chat/sessions")
async def get_chat_sessions(request: Request, agent_id: str = Query(default="")):
    """列出所有会话（按 agent_id 过滤）"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    sessions = repo.list_sessions(agent_id=agent_id, user_id=user_id)
    # 只返回摘要信息，不返回完整消息列表
    summaries = [
        {
            "id": s.get("session_id") or s.get("id", ""),
            "title": s.get("title", "新对话"),
            "agent_id": s.get("agent_id", ""),
            "created_at": s.get("created_at", ""),
        }
        for s in sessions
    ]
    return {"code": 0, "message": "success", "data": {"sessions": summaries, "total": len(summaries)}}


@router.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str, request: Request):
    """删除指定会话"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    # 查找 session 验证 user_id（SessionRepository 不接受 user_id 参数）
    sessions = repo.list_sessions()
    target = [s for s in sessions if s.get("session_id") == session_id or s.get("id") == session_id]
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    # user_id 校验与 SessionManager.list_sessions (session_manager.py:598) 过滤逻辑一致:
    # 空 user_id (None 或 "") 视为"共享", 允许任何已认证用户删除.
    # 修复 "看得到删不掉" 死锁 — list 端点宽松过滤让空 user_id 的 session 对所有用户可见,
    # delete 端点必须一致地允许删除, 否则用户能在列表看到却无法删除.
    # 详见 docs/bugfix-delete-session-userid-mismatch.md
    target_user_id = target[0].get("user_id") or ""
    if target_user_id and user_id and target_user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    agent_id = target[0].get("agent_id", "")
    repo.delete_session(agent_id=agent_id, session_id=session_id)
    return {"code": 0, "message": "Session deleted"}


class RenameSessionRequest(BaseModel):
    title: str


@router.put("/chat/sessions/{session_id}")
async def rename_chat_session(session_id: str, body: RenameSessionRequest, request: Request):
    """重命名指定会话"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    # 查找 session 验证 user_id（与 delete_chat_session 保持一致：空 user_id 视为共享，
    # 允许任何已认证用户重命名，避免"看得到改不了"的死锁，P2-#20）。
    sessions = repo.list_sessions()
    target = [s for s in sessions if s.get("session_id") == session_id or s.get("id") == session_id]
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    target_user_id = target[0].get("user_id") or ""
    if target_user_id and user_id and target_user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    agent_id = target[0].get("agent_id", "")
    new_title = body.title.strip() or target[0].get("title", "新对话")
    repo.rename_session(agent_id=agent_id, session_id=session_id, title=new_title)
    return {"code": 0, "message": "Session renamed", "data": {"id": session_id, "title": new_title}}


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
        "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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
    log_path = config.get("NEUROVA_LOG_FILE", "logs/neurova.log")
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
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    return {"code": 0, "message": "success", "data": status}


@router.post("/debug/command")
async def post_debug_run_command(
    body: CommandRequest, current_user: Dict[str, Any] = Depends(require_admin())
):
    """运行调试命令（仅限管理员，避免任意命令执行 / 密钥泄露）"""
    # 注意： deliberately 排除 `env` —— 它会泄露全部环境变量（含密钥/令牌），
    # 属安全敏感命令，绝不允许通过 HTTP 调试接口执行（P1-#7）。
    allowed = {"ls", "pwd", "echo", "whoami", "date", "python --version", "node --version"}
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
                    # Bug V2-4 修复:不强制传 metadata={"history": []}。
                    # 原代码强制空历史,LLM 缺对话上下文,工具参数指代不清。
                    # 现在不传 metadata,让 agent.chat() 自行从 session 恢复历史。
                    reply = await agent.chat(
                        message,
                        session_id=ws_session_id,
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
