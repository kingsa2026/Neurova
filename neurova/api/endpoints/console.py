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
from typing import Any, Dict, Optional

from neurova.api.deps import get_current_user, require_admin
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
    # 思考程度：light(简单) / standard(标准) / deep(深度)；空串=默认
    thinking_effort: typing.Optional[str] = ""
    # R-3 修复: 附件文件 ID 列表（前端 /files/upload 后携带）。此前 Pydantic
    # 静默丢弃该字段，模型完全感知不到上传文件。
    file_ids: typing.Optional[typing.List[str]] = None
    # 前端发送时刻（ISO）。随 metadata 持久化到该轮两条消息，作为轮次
    # 操作（编辑覆写/删除一轮/反馈）的双路定位键之一 — 服务端 add_message
    # 用自己的 now 落盘，客户端时间戳不落盘会导致实时轮次无法定位。
    client_timestamp: typing.Optional[str] = None
    # 补课 8（断线重连+replay 快进）：从该缓冲序号起重放事件（客户端已
    # 消费的最后序号）；None=全新请求（不重放）。配合会话级事件缓冲使用。
    replay_from: typing.Optional[int] = None


def attach_files(file_ids: typing.Optional[typing.List[str]], user_id: str) -> typing.List[dict]:
    """解析前端携带的 file_ids 为附件元数据列表（仅属主可见）。

    R-3 修复: 按 id 从 files_api 存储读取元数据；无效/非属主 id 跳过，
    不中断整轮对话。结果可 JSON 序列化（metadata 落盘经 _json_safe）。
    """
    if not file_ids:
        return []
    try:
        from neurova.api.endpoints import files_api
    except Exception:  # noqa: BLE001 - 依赖缺失时降级为空附件列表
        return []
    attachments: typing.List[dict] = []
    for fid in file_ids:
        info = files_api.get_attachment_info(fid, user_id)
        if not info:
            continue
        attachments.append(
            {
                "file_id": info.get("file_id", ""),
                "filename": info.get("filename", ""),
                "file_type": info.get("file_type", "file"),
                "mime_type": info.get("mime_type", ""),
                "size": info.get("size", 0),
                "path": info.get("path", ""),
            }
        )
    return attachments


# 真流式：发射器队列的结束哨兵
_EMIT_DONE = object()

# ── 断线重连事件缓冲（补课 8）──────────────────────────────
# 每 session 保留最近一轮 SSE 事件的有序缓冲：客户端断线后带
# replay_from=<已消费序号> 重连，服务端快进重放尾部（不重放已确认段）。
# 内存有界：每 session 上限 MAX_BUFFERED_EVENTS，session 数上限
# MAX_REPLAY_SESSIONS（LRU 淘汰），空闲 TTL 清理——防长会话内存膨胀。
_REPLAY_BUFFER_TTL_SECONDS = 600.0
MAX_BUFFERED_EVENTS = 500
MAX_REPLAY_SESSIONS = 50
_replay_buffers: Dict[str, Dict[str, Any]] = {}
_replay_buffers_lock = asyncio.Lock()


def _buffer_replay_events(session_id: str, events: typing.List[Dict[str, Any]]) -> None:
    """把一轮事件追加进会话缓冲（有界，超限丢最旧）。"""
    buf = _replay_buffers.get(session_id)
    if buf is None:
        if len(_replay_buffers) >= MAX_REPLAY_SESSIONS:
            # LRU：淘汰最旧 last_active
            oldest = min(_replay_buffers.items(), key=lambda kv: kv[1]["last_active"])
            _replay_buffers.pop(oldest[0], None)
        buf = {"events": [], "next_seq": 0, "last_active": time.time()}
        _replay_buffers[session_id] = buf
    buf["last_active"] = time.time()
    for event in events:
        seq = buf["next_seq"]
        buf["next_seq"] += 1
        buf["events"].append((seq, event))
    if len(buf["events"]) > MAX_BUFFERED_EVENTS:
        buf["events"] = buf["events"][-MAX_BUFFERED_EVENTS:]


def _get_replay_tail(session_id: str, replay_from: int) -> typing.List[Dict[str, Any]]:
    """取 seq > replay_from 的待重放事件；缓冲不存在/过期返回空。"""
    buf = _replay_buffers.get(session_id)
    if buf is None:
        return []
    buf["last_active"] = time.time()
    if time.time() - buf["last_active"] > _REPLAY_BUFFER_TTL_SECONDS:
        return []
    return [event for seq, event in buf["events"] if seq > replay_from]


async def _gc_replay_buffers() -> None:
    """TTL 清理过期缓冲（每轮请求顺带触发，无独立任务）。"""
    async with _replay_buffers_lock:
        now = time.time()
        expired = [sid for sid, b in _replay_buffers.items() if now - b["last_active"] > _REPLAY_BUFFER_TTL_SECONDS]
        for sid in expired:
            _replay_buffers.pop(sid, None)


def _sse_events_from_emitter_item(
    item: Any,
    seen_calls: set,
    seen_results: set,
) -> typing.List[dict]:
    """把管线的 (kind, data) 发射器事件转成 0~N 个 SSE 事件 dict。

    - content → chunk；reasoning → reasoning
    - tool_call（loop 原生 {id, function:{name,arguments}}）→ tool_call
    - tool_result（{tool_call_id,name,content}）→ tool_result [+approval_required]
      超长字段脱敏；按 key 去重防止收尾 flush 时重复推送
    """
    try:
        kind, data = item
        if kind == "content":
            text = str(data or "")
            return [{"type": "chunk", "content": text}] if text else []
        if kind == "memory_progress":
            # 实时检索进度（UI 临时显示，不落盘不记录）
            payload = data if isinstance(data, dict) else {}
            return [{"type": "memory_progress", **payload}] if payload else []
        if kind == "reasoning":
            text = str(data or "")
            return [{"type": "reasoning", "content": text}] if text else []
        if kind == "tool_call":
            fn = (data or {}).get("function") or {}
            name = str(fn.get("name") or "")
            arguments = fn.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            key = f"{name}:{arguments}"
            if not name or key in seen_calls:
                return []
            seen_calls.add(key)
            return [{"type": "tool_call", "name": name, "arguments": arguments}]
        if kind == "tool_result":
            tm = data or {}
            name = str(tm.get("name") or tm.get("tool_name") or "")
            content = tm.get("content", tm.get("result", ""))
            if isinstance(content, dict):
                content = json.dumps(content, ensure_ascii=False)
            content = str(content)
            # 去重 key 必须与收尾 flush（_build_tool_events 路径）共享同一空间：
            # 两边都以"完整 content 的 hash"为 key —— native tool message 的 content
            # 与文本模式条目的 result 同源（base.py 完整保留，不再预截断）。
            # 不用 [:120] 前缀：同一计划 create/mark_step 的渲染文本前缀几乎一致，
            # 前缀去重会把后者的 result 误判为重复（实测缺陷）；精确 hash 两全
            key = f"{name}:{_result_key_hash(content)}"
            if key in seen_results:
                return []
            seen_results.add(key)
            events = [
                {
                    "type": "tool_result",
                    "name": name,
                    "result": _strip_heavy_payload(content)[:2000],
                }
            ]
            approval_payload = _extract_approval_payload(content, {"tool_name": name})
            if approval_payload:
                events.append({"type": "approval_required", **approval_payload})
            return events
    except Exception:  # noqa: BLE001 - 映射失败丢弃该事件，不中断流
        return []
    return []


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


def _result_key_hash(content: str) -> str:
    """工具结果去重 key 的内容摘要（完整内容精确去重，避免前缀撞车误杀）"""
    import hashlib

    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:32]


def _strip_heavy_payload(result_text: str, max_value_len: int = 1000) -> str:
    """替换工具结果中超长的字符串字段值（如截图 base64），避免大对象涌入 SSE。

    非 JSON 文本原样返回；截断统一由调用方的 [:500] 处理。
    """
    try:
        parsed = json.loads(result_text)
    except Exception:
        return result_text
    if isinstance(parsed, dict):
        cleaned = {
            k: (f"<{len(v)} chars omitted>" if isinstance(v, str) and len(v) > max_value_len else v)
            for k, v in parsed.items()
        }
        return json.dumps(cleaned, ensure_ascii=False)
    return result_text


def _build_tool_events(tm: dict) -> typing.List[dict]:
    """把单条 tool_message 转成 0~2 个 SSE 事件 dict。

    - tool_call → {"type": "tool_call", name, arguments}
    - tool_result → {"type": "tool_result", name, result}（超长字段已脱敏）
      命中治理 ASK 待审批时追加 {"type": "approval_required", ...}
    """
    events: typing.List[dict] = []
    if not isinstance(tm, dict):
        return events
    tm_type = tm.get("type", "")
    # _tool_messages_list 同时存在两种形状：
    # - 文本模式条目（handle_tool_calls 写入）：{type, tool_name, params/result, ...}
    # - 原生事件包装（_call_loop_stream C1 写入）：{type, data: {...}}
    # 包装条目没有 tool_name，且语义与文本模式条目重复（同一次工具调用），
    # 直接跳过，避免产出空 name 的 SSE 事件
    if not tm.get("tool_name"):
        return events
    if tm_type == "tool_call":
        events.append(
            {
                "type": "tool_call",
                "name": tm.get("tool_name", ""),
                "arguments": json.dumps(tm.get("params", {}), ensure_ascii=False),
            }
        )
    elif tm_type == "tool_result":
        result_text = tm.get("result", "")
        if isinstance(result_text, dict):
            result_text = json.dumps(result_text, ensure_ascii=False)
        result_text = _strip_heavy_payload(str(result_text))
        events.append({"type": "tool_result", "name": tm.get("tool_name", ""), "result": result_text[:500]})

        # P0 人工确认弹窗: 检测治理 ASK 结果，推送结构化审批事件。
        # 必须在脱敏/截断前的完整文本上解析。
        approval_payload = _extract_approval_payload(result_text, tm)
        if approval_payload:
            events.append({"type": "approval_required", **approval_payload})
    return events


@router.post("/chat")
async def post_console_chat(
    body: ChatRequest,
    request: Request,
    current_user: typing.Dict[str, typing.Any] = Depends(get_current_user),
):
    """流式聊天接口（SSE）"""
    # R-3: 附件归属用 JWT 用户身份（与 /files/upload 一致）。
    # _get_user_id(request) 读 request.state.user_id——中间件从未注入，
    # 恒为 "anonymous"，导致 attach_files 找不到属主文件。
    user_id = str(current_user.get("user_id", "")) if isinstance(current_user, dict) else _get_user_id(request)
    repo = get_session_repository()
    agent_id = getattr(body, "agent_id", "") or ""

    # 会话 ID：客户端传入或新建
    if body.session_id:
        session_id = body.session_id
    else:
        session_id = repo.create_session(agent_id=agent_id, user_id=user_id, title="新对话")

    await _gc_replay_buffers()

    # 断线重连分支（补课 8）：带 replay_from 的请求不启动新 run——
    # 快进重放该 session 缓冲中 seq > replay_from 的事件，至 done 为止。
    # 无缓冲（服务重启/超时/全新会话）→ 落回正常新请求（客户端视为失败重发）。
    if body.replay_from is not None:
        tail = _get_replay_tail(session_id, int(body.replay_from))
        if tail or _replay_buffers.get(session_id):

            async def replay_stream():
                replayed = 0
                # 已缓冲段立即快进
                for event in tail:
                    replayed += 1
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                # run 未结束则持续跟踪缓冲尾部
                while True:
                    buf = _replay_buffers.get(session_id)
                    if not buf:
                        break
                    events = buf["events"]
                    fresh = [e for s, e in events if s > body.replay_from + replayed]
                    if fresh:
                        for event in fresh:
                            replayed += 1
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if buf.get("done"):
                        break
                    await asyncio.sleep(0.05)

            return StreamingResponse(replay_stream(), media_type="text/event-stream")
        # 无缓冲：继续走正常新请求（客户端重试语义由前端决定）

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
    agent = None
    try:
        agent = get_agent_instance(agent_id=body.agent_id or "default")
        if not agent:
            reply = f"Echo: {body.message}"
    except Exception as e:
        logger.warning("Console chat error: %s", e, exc_info=True)
        reply = f"Error: {str(e)}"

    # S1: assistant_metadata 仅用于 SSE event_stream (reasoning/tool_messages 展示),
    # 不再传给 repo.save_message (持久化由 pipeline 负责).

    if body.stream and not agent:
        async def echo_stream():
            events = [
                {"type": "chunk", "content": reply},
                {"type": "done", "session_id": session_id},
            ]
            _buffer_replay_events(session_id, events)
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            buf = _replay_buffers.get(session_id)
            if buf:
                buf["done"] = True

        return StreamingResponse(echo_stream(), media_type="text/event-stream")

    if body.stream:

        async def event_stream():
            """真流式：agent.chat 后台执行，管线产生的思考/内容/工具事件
            经 event_emitter → 队列 → SSE 即时推送，不再等整轮结束。"""
            nonlocal reply, reasoning, tool_messages

            queue: asyncio.Queue = asyncio.Queue()

            def _emit(kind, data):
                # 管线在事件循环线程内同步回调；put_nowait 不阻塞主流程
                try:
                    queue.put_nowait((kind, data))
                except Exception:  # noqa: BLE001 - 队列异常不拖垮聊天
                    pass

            metadata = {
                "user_id": user_id,
                "thinking_effort": (body.thinking_effort or "").lower(),
                "event_emitter": _emit,
                # 开启工具事件实时转发（默认关闭以保持蜂群子 Agent 纯文本流契约）
                "emit_tool_events": True,
            }
            # R-3 修复: 附件元数据注入（file_ids → attachments，供 pipeline 附件注入）
            attachments = attach_files(getattr(body, "file_ids", None), user_id)
            logger.info("[附件注入] file_ids=%s user_id=%s → attachments=%d",
                        getattr(body, "file_ids", None), user_id, len(attachments))
            if attachments:
                metadata["attachments"] = attachments
            # 客户端时间戳随 metadata 落盘到该轮两条消息（_json_safe 会剔除
            # event_emitter 等不可序列化对象，字符串保留），作为轮次定位键
            if body.client_timestamp:
                metadata["client_timestamp"] = body.client_timestamp

            async def run_chat():
                try:
                    response = await agent.chat(
                        body.message,
                        stream=True,
                        session_id=session_id,
                        metadata=metadata,
                        model=getattr(body, "model", None) or None,
                    )
                    if isinstance(response, dict):
                        return {
                            "text": response.get("text", str(response)),
                            "reasoning": response.get("reasoning"),
                            "tool_messages": response.get("tool_messages", []) or [],
                        }
                    return {"text": str(response), "reasoning": None, "tool_messages": []}
                except Exception as e:
                    logger.warning("Console chat error: %s", e, exc_info=True)
                    return {"text": f"Error: {str(e)}", "reasoning": None, "tool_messages": []}
                finally:
                    # 通知消费循环：本轮事件已全部产生
                    queue.put_nowait(_EMIT_DONE)

            task = asyncio.create_task(run_chat())
            seen_calls: set = set()
            seen_results: set = set()

            try:
                live_events: typing.List[Dict[str, Any]] = []
                while True:
                    # 15s 无事件发 SSE 注释心跳（": ping"）：agent 工具执行/LLM
                    # 慢响应期间流可能长时间无数据，代理/杀软/网络栈会掐空闲
                    # 连接造成"对话中断"。SSE 规范里冒号开头是注释，前端解析
                    # 器天然忽略，客户端收不到任何业务语义。
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    if item is _EMIT_DONE:
                        break
                    for event in _sse_events_from_emitter_item(item, seen_calls, seen_results):
                        live_events.append(event)  # 补课 8：断线重连缓冲
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                _buffer_replay_events(session_id, live_events)
                result = await task
                reply = result["text"]
                reasoning = result["reasoning"]
                tool_messages = result["tool_messages"]

                flush_events: typing.List[Dict[str, Any]] = []
                # 收尾 flush：文本模式等未经发射器的工具消息（去重后）
                for tm in tool_messages:
                    for event in _build_tool_events(tm):
                        etype = event.get("type")
                        if etype == "tool_call":
                            key = f"{event.get('name', '')}:{event.get('arguments', '')}"
                            if key in seen_calls:
                                continue
                            seen_calls.add(key)
                        elif etype == "tool_result":
                            # key 基于完整原始 result 的 hash（native content 同源，
                            # 见 live 侧注释）；event.result 是归一化+截断后的展示形式，不可用作 key
                            key = str(event.get("name", "")) + ":" + _result_key_hash(str(tm.get("result", "")))
                            if key in seen_results:
                                continue
                            seen_results.add(key)
                        flush_events.append(event)
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                flush_events.append({"type": "done", "session_id": session_id})
                # QwenPaw turn_usage 对齐:done 之前发一次真实 usage 事件
                # (入账已在 MultiModelLLMClient 下沉,此处只读 last_call 不双计;
                #  无记录时不发——不伪造数据)
                try:
                    from neurova.core.usage_accounting import get_usage_accounting

                    last = get_usage_accounting().last_call()
                    if last:
                        usage_event = {
                            "type": "usage",
                            "model": last.get("model", ""),
                            "provider": last.get("provider", ""),
                            "prompt_tokens": int(last.get("prompt_tokens", 0)),
                            "completion_tokens": int(last.get("completion_tokens", 0)),
                            "total_tokens": int(last.get("total_tokens", 0)),
                            "estimated": bool(last.get("estimated", False)),
                        }
                        flush_events.append(usage_event)
                        yield f"data: {json.dumps(usage_event, ensure_ascii=False)}\n\n"
                except Exception:  # noqa: BLE001 — usage 读取失败不影响 done
                    pass
                _buffer_replay_events(session_id, flush_events)
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
                buf = _replay_buffers.get(session_id)
                if buf:
                    buf["done"] = True

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
            "updated_at": s.get("updated_at", ""),
            "pinned": bool(s.get("pinned", False)),
            "sort_order": int(s.get("sort_order", 0) or 0),
        }
        for s in sessions
    ]
    return {"code": 0, "message": "success", "data": {"sessions": summaries, "total": len(summaries)}}


class ReorderSessionsRequest(BaseModel):
    agent_id: str = ""
    ordered_ids: typing.List[str]


@router.post("/chat/sessions/reorder")
async def reorder_chat_sessions(body: ReorderSessionsRequest, request: Request):
    """按用户拖拽顺序持久化会话排序（QwenPaw /chats/groups/order 对齐）。"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    ordered_ids = [sid for sid in (body.ordered_ids or []) if sid]
    if not ordered_ids:
        raise HTTPException(status_code=400, detail="ordered_ids is required")
    # 越权防护:逐一校验会话归属(空 user_id 会话视为共享,与 delete 端点口径一致)
    sessions = repo.list_sessions(agent_id=body.agent_id)
    visible = {s.get("session_id") or s.get("id", "") for s in sessions}
    unknown = [sid for sid in ordered_ids if sid not in visible]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Sessions not found: {unknown[:5]}")
    if not repo.set_sessions_sort_order(agent_id=body.agent_id, ordered_ids=ordered_ids):
        raise HTTPException(status_code=500, detail="Failed to persist session order")
    return {"code": 0, "message": "ok", "data": {"agent_id": body.agent_id, "ordered_ids": ordered_ids}}


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


@router.post("/chat/sessions/{session_id}/auto-title")
async def auto_title_chat_session(session_id: str, request: Request):
    """
    会话语义标题自动填充：LLM 概括首轮对话，失败回退首条用户消息截断。

    仅当会话仍为默认标题（新对话/新建对话）时应被调用（前端判定）；
    端点为幂等重命名，失败不返回 500（标题生成内部已兜底）。
    """
    user_id = _get_user_id(request)
    repo = get_session_repository()
    sessions = repo.list_sessions()
    target = [s for s in sessions if s.get("session_id") == session_id or s.get("id") == session_id]
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    target_user_id = target[0].get("user_id") or ""
    if target_user_id and user_id and target_user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    agent_id = target[0].get("agent_id", "")

    messages = repo.get_history(agent_id=agent_id, session_id=session_id)
    first_user = next((m for m in messages if m.get("role") == "user"), None)
    if first_user is None or not (first_user.get("content") or "").strip():
        raise HTTPException(status_code=400, detail="会话暂无对话内容")
    assistant_reply = next(
        (m for m in messages if m.get("role") == "assistant" and (m.get("content") or "").strip()),
        None,
    )

    # 函数内导入：测试可 monkeypatch neurova.session_title.generate_semantic_title
    from neurova.session_title import generate_semantic_title

    # 优先用会话 agent 的 LLM 客户端（与聊天同机制：带 provider/model 上下文）；
    # 拿不到 agent 时传 None，生成器回退多模型客户端/截断（绝不 500）。
    llm = None
    try:
        agent = get_agent_instance(agent_id=agent_id or "default")
        llm = getattr(agent, "llm_client", None)
    except Exception:
        llm = None

    title = await generate_semantic_title(
        first_user.get("content", ""),
        (assistant_reply or {}).get("content", ""),
        llm=llm,
    )
    repo.rename_session(agent_id=agent_id, session_id=session_id, title=title)
    return {"code": 0, "message": "success", "data": {"session_id": session_id, "title": title}}


# ── 会话存档（删除 → 存档：历史列表隐藏，可随时恢复） ──────────────────

def _check_session_ownership(target: Dict[str, Any], user_id: str) -> None:
    """user_id 校验与 delete_chat_session 一致：空 user_id 视为共享。"""
    target_user_id = target.get("user_id") or ""
    if target_user_id and user_id and target_user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")


def _session_summary(s: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": s.get("session_id") or s.get("id", ""),
        "title": s.get("title", "新对话"),
        "agent_id": s.get("agent_id", ""),
        "created_at": s.get("created_at", ""),
    }


@router.get("/chat/sessions/archived")
async def get_archived_chat_sessions(request: Request, agent_id: str = Query(default="")):
    """列出存档会话"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    sessions = repo.list_archived_sessions(agent_id=agent_id, user_id=user_id)
    summaries = [_session_summary(s) for s in sessions]
    return {"code": 0, "message": "success", "data": {"sessions": summaries, "total": len(summaries)}}


class PinSessionRequest(BaseModel):
    pinned: bool


@router.post("/chat/sessions/{session_id}/pin")
async def pin_chat_session(session_id: str, body: PinSessionRequest, request: Request):
    """置顶/取消置顶会话（补课 2.3）"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    target = _find_session_target(repo, session_id, user_id)
    agent_id = target.get("agent_id", "")
    if not repo.set_session_pinned(agent_id=agent_id, session_id=session_id, pinned=body.pinned):
        raise HTTPException(status_code=404, detail="Session files not found")
    return {"code": 0, "message": "ok", "data": {"session_id": session_id, "pinned": body.pinned}}


@router.post("/chat/sessions/{session_id}/archive")
async def archive_chat_session(session_id: str, request: Request):
    """存档会话（历史列表隐藏，数据保留，可恢复）"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    target = _find_session_target(repo, session_id, user_id)
    agent_id = target.get("agent_id", "")
    if not repo.archive_session(agent_id=agent_id, session_id=session_id):
        raise HTTPException(status_code=404, detail="Session files not found")
    return {"code": 0, "message": "Session archived", "data": {"session_id": session_id}}


@router.post("/chat/sessions/{session_id}/unarchive")
async def unarchive_chat_session(session_id: str, request: Request):
    """恢复存档会话为正常会话"""
    user_id = _get_user_id(request)
    repo = get_session_repository()
    archived = repo.list_archived_sessions()
    target = next(
        (s for s in archived if s.get("session_id") == session_id or s.get("id") == session_id),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Archived session not found")
    _check_session_ownership(target, user_id)
    agent_id = target.get("agent_id", "")
    if not repo.unarchive_session(agent_id=agent_id, session_id=session_id):
        raise HTTPException(status_code=404, detail="Archived session files not found")
    return {"code": 0, "message": "Session restored", "data": {"session_id": session_id}}


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


# ── Round operations（chat 页：编辑最后一条用户消息 / 删除一轮 / 点赞点踩） ──


def _find_session_target(repo, session_id: str, user_id: str) -> Dict[str, Any]:
    """按 session_id 定位会话并校验 user_id 权限。

    与既有 delete/rename 端点的过滤逻辑一致：空 user_id 视为"共享"，
    允许任何已认证用户操作（避免"看得到删不掉"死锁，P2-#20）。
    """
    sessions = repo.list_sessions()
    target = [s for s in sessions if s.get("session_id") == session_id or s.get("id") == session_id]
    if not target:
        raise HTTPException(status_code=404, detail="Session not found")
    target_user_id = target[0].get("user_id") or ""
    if target_user_id and user_id and target_user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return target[0]


def _sync_agent_history_from_session(agent, agent_id: str, session_id: str, repo) -> None:
    """把存活 agent 的内存会话历史强制同步为 session 文件现状。

    根因: ChatPipeline._restore_session_history 只在"文件比内存长"时覆盖
    内存历史。删除/覆写轮次后文件变短 → 内存历史不收缩 → 已删轮会在
    下一轮 LLM 调用中复活（上下文污染）。此处强制重建内存历史。
    """
    if not agent:
        return
    try:
        msgs = repo.get_history(agent_id=agent_id, session_id=session_id)
        history = [
            {"role": m.get("role"), "content": m.get("content")}
            for m in msgs
            if isinstance(m, dict) and m.get("role") and m.get("content")
        ]
        agent.conversation_history = history
        ctx = getattr(agent, "_conversation_context", None)
        if ctx is not None and hasattr(ctx, "clear") and hasattr(ctx, "extend"):
            ctx.clear()
            ctx.extend(history)
        logger.info("已同步 agent 内存历史: session=%s, 消息数=%s", session_id, len(history))
    except Exception as e:
        logger.warning("同步 agent 内存历史失败 (session=%s): %s", session_id, e)


@router.delete("/chat/rounds")
async def delete_chat_round(session_id: str, timestamp: str, request: Request):
    """删除一轮对话（user 消息 + 相邻 assistant 回复）。

    同时清除该轮对应的记忆并同步存活 agent 的内存会话历史，
    否则 agent 仍会"记得"已删除的轮次。前端"编辑最后一条用户消息"
    也复用本端点（删旧轮 → 走原发送链路重发 → 管线写入新轮记录与记忆）。
    """
    user_id = _get_user_id(request)
    repo = get_session_repository()
    target = _find_session_target(repo, session_id, user_id)
    agent_id = target.get("agent_id", "")

    deleted = repo.delete_round(agent_id=agent_id, session_id=session_id, timestamp=timestamp)
    if not deleted:
        raise HTTPException(status_code=404, detail="Round not found")

    # 记忆清除 + 内存历史同步（best-effort，不改变 session 删除结果）
    try:
        agent = get_agent_instance(agent_id=agent_id or "default")
    except Exception as e:
        logger.warning("获取 agent 实例失败 (session=%s): %s", session_id, e)
        agent = None

    if agent is not None:
        user_content = next((m.get("content", "") for m in deleted if m.get("role") == "user"), "")
        assistant_content = next(
            (m.get("content", "") for m in deleted if m.get("role") == "assistant"), ""
        )
        memory_agent = getattr(agent, "memory_agent", None)
        if memory_agent is not None and hasattr(memory_agent, "delete_round_memories"):
            try:
                purged = memory_agent.delete_round_memories(
                    session_id=session_id,
                    user_input=user_content,
                    agent_response=assistant_content,
                    approx_ts=timestamp,
                )
                logger.info("轮次记忆已清除: session=%s, 条数=%s", session_id, purged)
            except Exception as e:
                logger.warning("删除轮次记忆失败 (session=%s): %s", session_id, e)
        _sync_agent_history_from_session(agent, agent_id, session_id, repo)

    return {"code": 0, "message": "Round deleted", "data": {"deleted": len(deleted)}}


class FeedbackRequest(BaseModel):
    session_id: str
    timestamp: str
    # None 表示取消已有反馈（清除点赞/点踩）
    feedback: typing.Optional[typing.Literal["like", "dislike"]] = None
    # P2 标注闭环：点赞 + 人工修正答案 → 固化为"精准回复"命中表
    corrected_answer: typing.Optional[str] = None


def _apply_feedback_to_memory(
    repo, agent_id: str, session_id: str, timestamp: str, feedback: str
) -> None:
    """反馈质量闭环：点赞强化 / 点踩抑制该轮记忆温度（best-effort）。

    点赞的记忆温度 +10（更易被召回），点踩 -15（加速遗忘），
    由 MemCore.apply_feedback_to_memories 实现。
    """
    try:
        agent = get_agent_instance(agent_id=agent_id or "default")
    except Exception as e:
        logger.warning("获取 agent 实例失败 (session=%s): %s", session_id, e)
        return
    if agent is None:
        return
    memory_agent = getattr(agent, "memory_agent", None)
    if memory_agent is None or not hasattr(memory_agent, "apply_feedback_to_memories"):
        return
    try:
        round_data = repo.get_round(agent_id=agent_id, session_id=session_id, timestamp=timestamp)
        if not round_data:
            return

        def _content(msg) -> str:
            return msg.get("content", "") if isinstance(msg, dict) else ""

        memory_agent.apply_feedback_to_memories(
            session_id=session_id,
            user_input=_content(round_data.get("user")),
            agent_response=_content(round_data.get("assistant")),
            feedback=feedback,
            approx_ts=timestamp,
        )
    except Exception as e:
        logger.warning("反馈记忆温度更新失败 (session=%s): %s", session_id, e)


def _maybe_crystallize_annotation(
    store,
    feedback: str,
    user_input: str,
    agent_response: str,
    corrected_answer: typing.Optional[str],
) -> bool:
    """P2 标注闭环：点赞 + 修正文本 → 固化为精准回复命中表。

    纯点赞（无修正）不落表（同义反复无价值）；点踩永不落表（负样本
    走记忆温度抑制链路）；同问重复修正更新原条目（不堆积）。
    """
    if feedback != "like" or not (corrected_answer or "").strip():
        return False
    try:
        norm_q = user_input.strip()
        if not norm_q:
            return False
        existing = store._conn.execute(
            "SELECT id FROM annotations WHERE question_norm = ?",
            (__import__("neurova.core.annotation_store", fromlist=["normalize_query"]).normalize_query(norm_q),),
        ).fetchone()
        if existing:
            store.update_answer(existing["id"], corrected_answer.strip())
        else:
            store.add(question=norm_q, answer=corrected_answer.strip(), source="feedback")
        return True
    except Exception as e:  # noqa: BLE001 — 标注固化失败不阻断反馈主链路
        logger.warning("标注固化失败: %s", e)
        return False


@router.post("/chat/feedback")
async def post_chat_feedback(body: FeedbackRequest, request: Request):
    """点赞/点踩 agent 回复。

    持久化到该轮 assistant 消息 metadata（随 session 留存，供质量分析），
    并作用于该轮记忆温度形成质量闭环：like 强化（+10，更易召回）、
    dislike 抑制（-15，加速遗忘）。feedback=None 表示取消已有反馈。
    timestamp 为所在轮次的定位键（与删除轮次同一套双路定位规则）。
    """
    user_id = _get_user_id(request)
    repo = get_session_repository()
    target = _find_session_target(repo, body.session_id, user_id)
    agent_id = target.get("agent_id", "")

    ok = repo.update_message_metadata(
        agent_id=agent_id,
        session_id=body.session_id,
        timestamp=body.timestamp,
        metadata_patch={"feedback": body.feedback},
        role="assistant",
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")

    # 记忆温度反馈（best-effort，不阻断反馈持久化结果；取消反馈不做温度操作）
    if body.feedback:
        _apply_feedback_to_memory(repo, agent_id, body.session_id, body.timestamp, body.feedback)
        # P2 标注闭环：点赞 + 修正 → 精准回复命中表（best-effort）
        if body.corrected_answer is not None:
            try:
                round_data = repo.get_round(agent_id=agent_id, session_id=body.session_id, timestamp=body.timestamp)
                _round_user = (round_data or {}).get("user")
                _round_assistant = (round_data or {}).get("assistant")
                _user_text = _round_user.get("content", "") if isinstance(_round_user, dict) else ""
                _agent_text = _round_assistant.get("content", "") if isinstance(_round_assistant, dict) else ""
                from neurova.core.annotation_store import get_annotation_store

                _maybe_crystallize_annotation(
                    get_annotation_store(), body.feedback, _user_text, _agent_text, body.corrected_answer
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("标注闭环处理失败: %s", e)

    return {"code": 0, "message": "Feedback saved"}


class ForkSessionRequest(BaseModel):
    # 截取定位键：复制该时间戳（含）之前的全部历史到新会话；缺省=整个会话
    until_timestamp: typing.Optional[str] = None
    title: typing.Optional[str] = None


@router.post("/chat/sessions/{session_id}/fork")
async def fork_chat_session(session_id: str, body: ForkSessionRequest, request: Request):
    """会话分叉（ZCode fork 对齐）：按 until_timestamp 截取历史复制为新会话。

    双路定位（timestamp / metadata.client_timestamp）与删除轮次同一套规则；
    分叉出的新会话独立演进，原会话不动。agent 内存历史不注入（由新会话
    首轮对话按正常链路加载 session 历史）。
    """
    user_id = _get_user_id(request)
    repo = get_session_repository()
    target = _find_session_target(repo, session_id, user_id)
    agent_id = target.get("agent_id", "")

    history = repo.get_history(agent_id=agent_id, session_id=session_id)
    if body.until_timestamp:
        cut = None
        for idx, msg in enumerate(history):
            ts = msg.get("timestamp", "")
            meta_ts = (msg.get("metadata") or {}).get("client_timestamp", "")
            if ts == body.until_timestamp or (meta_ts and meta_ts == body.until_timestamp):
                cut = idx + 1  # 含该条
                break
        if cut is None:
            raise HTTPException(status_code=400, detail="until_timestamp not found in session history")
        copied = history[:cut]
    else:
        copied = list(history)

    fork_title = (body.title or "").strip() or f"{target.get('title', '新对话')} (分叉)"
    new_session_id = repo.create_session(agent_id=agent_id, user_id=user_id, title=fork_title)
    for msg in copied:
        repo.save_message(
            agent_id=agent_id,
            session_id=new_session_id,
            role=str(msg.get("role", "user")),
            content=str(msg.get("content", "")),
            metadata=(msg.get("metadata") or None) or None,
        )

    return {
        "code": 0,
        "message": "Session forked",
        "data": {
            "new_session_id": new_session_id,
            "copied_messages": len(copied),
            "title": fork_title,
        },
    }


class CheckpointRequest(BaseModel):
    session_id: str
    timestamp: str
    # True=设钩子；False=移除
    active: bool


@router.post("/chat/checkpoint")
async def set_chat_checkpoint(body: CheckpointRequest, request: Request):
    """消息钩子/检查点（ZCode checkpoint 对齐）：写消息 metadata.checkpoint。

    前端在消息操作条设/撤钩子；加载历史时读取 metadata 渲染锚点标记。
    复用 feedback 的双路定位契约。
    """
    user_id = _get_user_id(request)
    repo = get_session_repository()
    target = _find_session_target(repo, body.session_id, user_id)
    agent_id = target.get("agent_id", "")

    ok = repo.update_message_metadata(
        agent_id=agent_id,
        session_id=body.session_id,
        timestamp=body.timestamp,
        metadata_patch={"checkpoint": bool(body.active)},
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"code": 0, "message": "ok", "data": {"checkpoint": bool(body.active)}}


@router.get("/chat/feedback/stats")
async def get_feedback_stats(
    request: Request,
    agent_id: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
):
    """点赞/点踩统计（按 agent 聚合，供回复质量分析看板）。

    扫描最近 limit 个会话的 assistant 消息 metadata.feedback 聚合计数，
    并返回最近 20 条反馈明细（按时间倒序）。
    """
    user_id = _get_user_id(request)
    repo = get_session_repository()
    sessions = repo.list_sessions(agent_id=agent_id, user_id=user_id)[:limit]

    like = 0
    dislike = 0
    recent: typing.List[dict] = []
    for s in sessions:
        sid = s.get("session_id") or s.get("id", "")
        if not sid:
            continue
        try:
            msgs = repo.get_history(agent_id=agent_id or s.get("agent_id", ""), session_id=sid)
        except Exception as e:
            logger.warning("feedback stats 读取历史失败 (session=%s): %s", sid, e)
            continue
        for m in msgs:
            if not isinstance(m, dict) or m.get("role") != "assistant":
                continue
            fb = (m.get("metadata") or {}).get("feedback")
            if fb not in ("like", "dislike"):
                continue
            if fb == "like":
                like += 1
            else:
                dislike += 1
            recent.append(
                {
                    "session_id": sid,
                    "timestamp": m.get("timestamp", ""),
                    "content": (m.get("content") or "")[:100],
                    "feedback": fb,
                }
            )

    recent.sort(key=lambda r: r["timestamp"], reverse=True)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "agent_id": agent_id,
            "sessions_scanned": len(sessions),
            "total_feedback": like + dislike,
            "like": like,
            "dislike": dislike,
            "recent": recent[:20],
        },
    }


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


# ══════════════════════════════════════════════════════════════
# P2 标注闭环 — 精准回复命中表管理 API
# ══════════════════════════════════════════════════════════════


class AnnotationCreateRequest(BaseModel):
    question: str
    answer: str


class AnnotationUpdateRequest(BaseModel):
    answer: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/annotations")
async def list_annotations(
    request: Request,
    q: str = Query(default="", description="按问题/答案子串过滤"),
    limit: int = Query(default=100, ge=1, le=500),
):
    """精准回复命中表清单（管理页：按命中次数排序）。"""
    from neurova.core.annotation_store import get_annotation_store

    store = get_annotation_store()
    items = store.list_annotations(limit=limit)
    if q:
        ql = q.lower()
        items = [a for a in items if ql in (a.get("question") or "").lower() or ql in (a.get("answer") or "").lower()]
    return {"code": 0, "message": "ok", "data": {"items": items, "total": store.count()}}


@router.post("/annotations")
async def create_annotation(body: AnnotationCreateRequest, request: Request):
    """手工新增精准回复（不限于反馈链路沉淀）。"""
    if not body.question.strip() or not body.answer.strip():
        raise HTTPException(status_code=400, detail="question/answer 不能为空")
    from neurova.core.annotation_store import get_annotation_store

    ann_id = get_annotation_store().add(body.question.strip(), body.answer.strip(), source="manual")
    return {"code": 0, "message": "ok", "data": {"id": ann_id}}


@router.put("/annotations/{annotation_id}")
async def update_annotation(annotation_id: str, body: AnnotationUpdateRequest, request: Request):
    """更新答案 / 启停用（停用即下线该精准回复）。"""
    from neurova.core.annotation_store import get_annotation_store

    store = get_annotation_store()
    if store.get(annotation_id) is None:
        raise HTTPException(status_code=404, detail="标注不存在")
    if body.answer is not None:
        store.update_answer(annotation_id, body.answer)
    if body.enabled is not None:
        store.set_enabled(annotation_id, body.enabled)
    return {"code": 0, "message": "ok", "data": store.get(annotation_id)}


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, request: Request):
    from neurova.core.annotation_store import get_annotation_store

    if not get_annotation_store().delete(annotation_id):
        raise HTTPException(status_code=404, detail="标注不存在")
    return {"code": 0, "message": "ok"}


@router.get("/annotations/export")
async def export_training_set(request: Request):
    """重训练化集导出：JSONL（input/output 对）——供后续 SFT 微调集。"""
    from neurova.core.annotation_store import get_annotation_store

    lines = get_annotation_store().export_training_set()
    return {"code": 0, "message": "ok", "data": {"jsonl": "\n".join(lines), "count": len(lines)}}
