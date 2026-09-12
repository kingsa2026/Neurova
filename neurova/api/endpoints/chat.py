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
import asyncio
import json
from neurova.core.logger import get_logger
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as FastAPIPath, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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


# F-4 根修（台账 2026-09-11）：TTS 产物文件名白名单——tts_{session}_{ts}.wav
# 平名文件；拒路径分隔符/`..`/非 TTS 命名，内容端点据此防路径穿越。
_TTS_FILENAME_RE = re.compile(r"^tts_[A-Za-z0-9._-]+\.wav$")


def _tts_audio_http_url(audio_path: Optional[str], agent_id: str) -> Optional[str]:
    """本地 TTS 产物路径 → 鉴权内容端点 HTTP URL（F-4 根修，API 边界转换）。

    内部契约 audio_path 保持本地路径（artifacts_api 按路径注册本地产物依赖
    它），仅在把值交给 HTTP 客户端处转换；无产物返回 None（事件照旧不发）。
    """
    if not audio_path:
        return None
    return f"/api/v1/chat/tts-audio/{agent_id}/{Path(audio_path).name}"


@router.get("/tts-audio/{agent_id}/{filename}")
async def get_tts_audio(
    agent_id: str,
    filename: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """TTS 产物鉴权内容端点（attachment_dir 落盘音频的唯一 HTTP 取回路径）。

    登录态（get_current_user）+ agent 访问权（复用 _user_can_access_agent，
    与 chat 端点同语义）+ 文件名白名单（只服务 tts_*.wav 平名产物）；
    禁止无鉴权静态暴露。
    """
    user_id = current_user.get("user_id", "")
    role = current_user.get("role", "user")
    if not _user_can_access_agent(user_id, agent_id, role):
        raise HTTPException(
            status_code=403,
            detail="Permission denied: you don't have access to this Agent",
        )
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    if not _TTS_FILENAME_RE.fullmatch(filename):
        raise HTTPException(status_code=400, detail="Invalid TTS audio filename")
    attachment_dir = Path(getattr(agent.config, "attachment_dir", "") or "")
    if not str(attachment_dir):
        raise HTTPException(status_code=404, detail="TTS audio not found")
    audio_file = (attachment_dir / filename).resolve()
    if not audio_file.is_relative_to(attachment_dir.resolve()) or not audio_file.is_file():
        raise HTTPException(status_code=404, detail="TTS audio not found")
    return FileResponse(path=audio_file, media_type="audio/wav", filename=filename)


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
        # 隔离注入：服务端身份覆盖客户端自报（kb_builder 等技能据此归属知识条目）
        call_metadata["user_id"] = user_id
        # 角色透传：知识库检索链的 admin 全可见依赖 role（隔离语义与 API 层一致）
        call_metadata["role"] = role

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
                    "url": _tts_audio_http_url(audio_path, body.agent_id),
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

    # 审计 P0-C1/C4：真流式改造——原实现恒走"agent.chat() 全量返回再吐一块"
    # 的假流式（首字节延迟=全响应时长，且无心跳易被网关掐断）。现对齐
    # console.py /chat 的 emitter→队列模式：agent.chat(stream=True) 后台执行，
    # 管线 _call_loop_stream 产生的 content/reasoning 事件经 event_emitter →
    # 队列 → SSE 即时推送；空闲 15s 发 ": ping" 注释心跳保活。
    _EMIT_DONE = object()

    async def event_generator():
        """SSE 事件生成器（真流式）"""
        audio_url = None
        queue: asyncio.Queue = asyncio.Queue()

        def _emit(kind, data):
            # 管线在事件循环线程内同步回调；put_nowait 不阻塞主流程
            try:
                queue.put_nowait((kind, data))
            except Exception:  # noqa: BLE001 - 队列异常不拖垮聊天
                pass

        call_metadata = dict(body.metadata or {})
        call_metadata["event_emitter"] = _emit
        # 429 重试/切换倒计时事件转发（管线 retry_status → SSE retry）
        call_metadata["emit_status_events"] = True

        async def run_chat():
            try:
                return await agent.chat(
                    user_input=body.message,
                    stream=True,
                    session_id=body.session_id,
                    metadata=call_metadata,
                )
            finally:
                # 通知消费循环：本轮事件已全部产生
                queue.put_nowait(_EMIT_DONE)

        task = None
        try:
            # 发送开始事件
            yield f"event: start\ndata: {json.dumps({'request_id': request_id})}\n\n"

            task = asyncio.create_task(run_chat())
            # RES-P2-2：注册任务表（对齐 console.py）——带 session_id 的轮次
            # 可被 /console/chat/stop 真取消；完成后由 tracker 自动摘除
            if body.session_id:
                from neurova.core.task_tracker import get_task_tracker

                get_task_tracker().register_async_task(body.session_id, task, kind="chat")
            seen_content = False
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # 审计 P0-C4：空闲心跳（SSE 注释，前端解析器天然忽略）
                    yield ": ping\n\n"
                    continue
                if item is _EMIT_DONE:
                    break
                kind, data = item
                if kind == "content":
                    seen_content = True
                    yield f"event: message\ndata: {json.dumps({'content': str(data or '')})}\n\n"
                elif kind == "reasoning":
                    yield f"event: reasoning\ndata: {json.dumps({'content': str(data or '')})}\n\n"
                elif kind == "retry":
                    _retry = data if isinstance(data, dict) else {}
                    if _retry:
                        yield f"event: retry\ndata: {json.dumps({'type': 'retry', **_retry})}\n\n"

            # 整轮结束后取 chat() 返回值：TTS audio 产物 + 兜底文本
            response = await task
            reply_text = ""
            if isinstance(response, dict):
                reply_text = response.get("text", "")
                audio_url = _tts_audio_http_url(response.get("audio_path"), body.agent_id)
                if audio_url:
                    yield (
                        "event: audio\n"
                        f"data: {json.dumps({'type': 'audio', 'url': audio_url})}\n\n"
                    )
            else:
                reply_text = str(response)

            # 兜底：管线未产生任何 content 事件（命令回复/纯文本降级）时，
            # 用最终回复补发一条 message 事件，避免前端空白
            if not seen_content and reply_text:
                yield f"event: message\ndata: {json.dumps({'content': reply_text})}\n\n"

            # 发送完成事件（含 audio_url 兜底——前端 done case 消费）
            done_payload = {'request_id': request_id}
            if audio_url:
                done_payload['audio_url'] = audio_url
            yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # RES-P2-2：断连（GeneratorExit）/异常退出时取消孤儿生成任务——
            # 旧实现任由 run_chat 跑完全程（token 白烧、停止端点无效）。
            # 正常路径 task 已被 await 完成，此处为 no-op。
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:  # noqa: BLE001 — 收尸不外泄（含 CancelledError）
                    pass

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
async def add_attachment(
    request: Request,
    body: AttachmentRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """添加附件到对话（审计 A8：补齐鉴权——stub 期与兄弟端点同源）"""
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
