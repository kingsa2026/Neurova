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
from neurova.core.agent_run_ledger import (
    ENTRY_V1CHAT,
    ENTRY_V1CHAT_STREAM,
    AgentRunLedger,
    reportAdmissionOutcome,
    requestTurnAdmission,
    resumeTurnIdentity,
)

logger = get_logger(__name__)

router = APIRouter()


def turnPayloadForV1(body: Any, *, entry: str, sessionId: str) -> Dict[str, Any]:
    """parked 回合的待跑载荷（写侧）。字段名与读侧 `turnRequestFromPayload` 同源。"""
    return {
        "entry": entry,
        "message": body.message,
        "agent_id": body.agent_id,
        "session_id": sessionId,
        "model": body.model,
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
        "metadata": body.metadata or {},
    }


def turnRequestFromPayload(payload: Dict[str, Any]) -> Any:
    """按载荷重建**本入口自己的**请求模型（续跑按 entry 回到原入口，参数不丢）。"""
    fields = {
        key: payload.get(key)
        for key in ("message", "agent_id", "session_id", "model", "temperature", "max_tokens", "metadata")
    }
    cls = ChatStreamRequest if payload.get("entry") == ENTRY_V1CHAT_STREAM else ChatRequest
    return cls(**fields)


def preflightRejectionMessage(events) -> Optional[str]:
    """台账在晋升前就把这一轮挡下时（排队超时 / 等待期被取消）的诚实说明。

    非流式面没有事件流可发，只能把这些预检事件翻成一个如实的失败响应——
    不能继续跑完然后回 success（那是 §6-8 那族"依赖不满足仍报成功"的同形病灶）。
    """
    for event in events or []:
        if event.get("type") == "error":
            return str(event.get("message") or "排队等待超时")
        if event.get("type") == "stopped":
            return "该回合在排队期间被取消"
    return None


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


def _get_agent(agent_id: str = ""):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _user_can_access_agent(user_id: str, agent_id: str, role: str = "user") -> bool:
    """
    检查用户是否有权访问 Agent

    Wave H-W0：判定委托 agent_access 单源（admin 全量 / owner 匹配 /
    无主仅 admin）——列表/详情/写口/执行门同一口径，杜绝双实现漂移。
    """
    from neurova.api.agent_access import can_access_agent, resolve_agent_owner

    agent = _get_agent(agent_id)
    if not agent:
        return False
    return can_access_agent(user_id, role, resolve_agent_owner(agent_id, state_agent=agent))


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


async def _finishV1Turn(*, ledger: AgentRunLedger, admission, error: Optional[str]) -> None:
    """落终态 + 回填 pacing（两条 v1 入口共用，与网页那条走同一份台账实现）。

    挂起那一支直接返回：行已在 parked，这里再写终态就是把"等人续跑"抹成"已结束"。
    """
    if admission is not None and admission.parked:
        return
    ledger.settleResult({"error": error} if error else {})
    if admission is not None and admission.allowed:
        await reportAdmissionOutcome(admission, success=not error)


def _parkedResponse(
    runId: str,
    reason: str,
    *,
    agentId: str,
    sessionId: str,
    requestId: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """挂起按它本来的样子回：`message` 不是 success，但请求确实被受理并留了凭据。"""
    return {
        "code": 0,
        "message": "parked",
        "data": {
            "status": "parked",
            "run_id": runId,
            "reason": reason,
            "park_details": dict(details or {}),
            "agent_id": agentId,
            "session_id": sessionId,
            "resume_via": f"/api/v1/console/chat/resume?run_id={runId}",
        },
        "request_id": requestId,
    }


def _failure(code: int, message: str, requestId: str, httpStatus: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=httpStatus,
        content={"code": code, "message": message, "request_id": requestId},
    )


@router.post("")
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    resume_run_id: str = "",
):
    """普通对话

    `resume_run_id` 只由续跑端点在服务端填入（不是请求体字段），它让重跑复用台账原行，
    并以**原回合属主**的身份执行。
    """
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

    sessionId = body.session_id or ""
    if resume_run_id:
        from neurova.core import agent_run_store as _ars

        row = await asyncio.to_thread(_ars.get_agent_run_store().get, resume_run_id) or {}
        # 续跑执行身份＝原回合属主（推导单源在 core，四入口共用这一份）
        user_id, ownerAgentId = resumeTurnIdentity(row, user_id, body.agent_id)
        body.agent_id = ownerAgentId or body.agent_id

    ledger = AgentRunLedger(
        sessionId, user_id, body.agent_id, body.message, run_id=resume_run_id or None
    )
    # 没有 session_id 的调用方在这一律不记账：凭空造一个共享泳道会让这些请求互相
    # 排队（今天它们根本不排队），那是接线造出来的新阻塞面。代价是这类请求
    # 挂起时无处落库，只能如实回 503（见下）。
    preflight = await ledger.acquire() if sessionId else []
    rejected = preflightRejectionMessage(preflight)
    if rejected:
        return _failure(4009, rejected, request_id, httpStatus=409)

    admission = None
    turnError: Optional[str] = None
    try:
        # Bug V2-3 修复:不强制传 {"history": []} 给 agent。
        # 原代码 `body.metadata if "history" in body.metadata else {"history": []}`
        # 在调用方未传 history 键时,丢掉 metadata 中其他字段(voice_context 等),
        # 且强制空历史导致 LLM 缺对话上下文,工具参数指代不清("搜一下他"不知道"他"是谁)。
        # 现在不强制注入,让 chat_pipeline 自行从 session 恢复历史。
        call_metadata = body.metadata or {}
        # 隔离注入：服务端身份覆盖客户端自报（kb_builder 等技能据此归属知识条目）
        call_metadata["user_id"] = user_id
        # 请求级属主（§6-121 (b) 的乙案）：**在请求边界写一次**，不再由管线中途补写。
        # 原先 `ChatPipeline._execute_steps` 每次回合都按 metadata 里的 user_id 再写一遍这条
        # 通道，于是渠道路径里"会话属主"（router 写的 owner）在回合内被换成"发送者"——
        # `mem_core.save_to_session` 只读这条通道，渠道会话因此不再落进属主的控制台。
        # 两边取的是同一个 `user_id`（上面那行），同源、单点、无第二写方。
        from neurova.core.identity_context import set_request_user_id

        set_request_user_id(user_id)
        # 角色透传：知识库检索链的 admin 全可见依赖 role（隔离语义与 API 层一致）
        call_metadata["role"] = role
        call_metadata["tenant_id"] = str(current_user.get("tenant_id") or "default")

        # P2-8 §6-46：这条公开 API 与网页面共用同一份模型额度，也就必须问同一道闸
        admission = await requestTurnAdmission(
            ledger=ledger,
            agentId=body.agent_id,
            modelName=body.model or "",
            sessionId=sessionId,
            userInput=body.message,
            payload=turnPayloadForV1(body, entry=ENTRY_V1CHAT, sessionId=sessionId),
        )
        if not admission.allowed:
            if admission.parked:
                return _parkedResponse(
                    admission.runId, admission.parkReason,
                    agentId=body.agent_id, sessionId=sessionId, requestId=request_id,
                    details=admission.outcome.details if admission.outcome else None,
                )
            turnError = (
                "让位闸判定挂起（原因 %s），但无法落库成可续跑的挂起行（请求缺 session_id"
                " 或台账未开），本轮已中止" % (admission.parkReason or "unspecified")
            )
            return _failure(4008, turnError, request_id, httpStatus=503)

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
        turnError = str(e)
        return JSONResponse(
            status_code=500,
            content={
                "code": 5000,
                "message": f"Chat failed: {str(e)}",
                "request_id": request_id,
            },
        )
    finally:
        await _finishV1Turn(ledger=ledger, admission=admission, error=turnError)


@router.post("/stream")
async def chat_stream(
    request: Request,
    body: ChatStreamRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    resume_run_id: str = "",
):
    """流式对话 SSE

    `resume_run_id` 只由续跑端点在服务端填入：复用台账原行，并按原回合属主身份执行。
    """
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

    sessionId = body.session_id or ""
    if resume_run_id:
        from neurova.core import agent_run_store as _ars

        row = await asyncio.to_thread(_ars.get_agent_run_store().get, resume_run_id) or {}
        user_id, ownerAgentId = resumeTurnIdentity(row, user_id, body.agent_id)
        body.agent_id = ownerAgentId or body.agent_id

    ledger = AgentRunLedger(
        sessionId, user_id, body.agent_id, body.message, run_id=resume_run_id or None
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
        admission = None
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
        # 会话属主（裁定甲，§6-153）：流式此前不写 `user_id`，于是 `mem_core.save_to_session`
        # 取到空属主，而 `session_manager.py:1650` 的过滤是「空属主不过滤」⇒ **每个登录用户
        # 的控制台都能看见别人的流式会话标题**。写在 `event_generator` 内、`create_task` 之前：
        # task 在创建时复制当前上下文，放在端点顶部反而不保证被 `run_chat` 那条 task 看到。
        call_metadata["user_id"] = user_id
        call_metadata["tenant_id"] = str(current_user.get("tenant_id") or "default")
        from neurova.core.identity_context import set_request_user_id

        set_request_user_id(user_id)

        async def _gateWaitNotice(*, attempt: int, waitSeconds: float, reason: str) -> None:
            # 等待预算（默认 10×20s）远超租约 90s：每次入睡前强制续租，并把进度
            # 转成既有 retry 事件（不新造状态面）
            await ledger.heartbeat(force=True)
            _emit("retry", {
                "type": "retry",
                "phase": "yield_wait",
                "source": "glance_yield",
                "retry": attempt,
                "wait_seconds": round(float(waitSeconds), 2),
                "reason": reason,
                "model": body.model or "",
            })

        async def run_chat():
            nonlocal admission
            turnSucceeded = False
            try:
                admission = await requestTurnAdmission(
                    ledger=ledger,
                    agentId=body.agent_id,
                    modelName=body.model or "",
                    sessionId=sessionId,
                    userInput=body.message,
                    payload=turnPayloadForV1(body, entry=ENTRY_V1CHAT_STREAM, sessionId=sessionId),
                    onWait=_gateWaitNotice,
                )
                if not admission.allowed:
                    if admission.parked:
                        return {
                            "parked": True,
                            "park_reason": admission.parkReason,
                            "run_id": admission.runId,
                            "attempts": admission.attempts,
                            "waited_seconds": round(admission.waitedSeconds, 2),
                            "park_details": dict(
                                admission.outcome.details if admission.outcome else {}
                            ),
                        }
                    return {
                        "error": (
                            "让位闸判定挂起（原因 %s），但无法落库成可续跑的挂起行"
                            "（请求缺 session_id 或台账未开），本轮已中止"
                            % (admission.parkReason or "unspecified")
                        )
                    }
                response = await agent.chat(
                    user_input=body.message,
                    stream=True,
                    session_id=body.session_id,
                    metadata=call_metadata,
                )
                turnSucceeded = True
                return response
            finally:
                if admission is not None and admission.allowed and not admission.parked:
                    try:
                        await reportAdmissionOutcome(admission, success=turnSucceeded)
                    except Exception:  # noqa: BLE001 - 统计回执不翻案本轮结果
                        logger.warning("让位闸回执失败（不影响本轮结果）", exc_info=True)
                # 通知消费循环：本轮事件已全部产生
                queue.put_nowait(_EMIT_DONE)

        task = None
        try:
            # 发送开始事件
            yield f"event: start\ndata: {json.dumps({'request_id': request_id})}\n\n"

            # P2-8 §6-46：先落库再执行；排队进度/超时/被取消都以同一条 SSE 上的
            # 具名事件如实透出（rejected 时台账已补发收尾事件）
            for event in await ledger.acquire():
                yield (
                    f"event: {event.get('type')}\n"
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                )
            if ledger.rejected:
                return

            task = asyncio.create_task(run_chat())
            # RES-P2-2：注册任务表（对齐 console.py）——带 session_id 的轮次
            # 可被 /console/chat/stop 真取消；完成后由 tracker 自动摘除
            if body.session_id:
                from neurova.core.task_tracker import get_task_tracker

                get_task_tracker().register_async_task(body.session_id, task, kind="chat")
            # 台账终态单点收敛：task 完成回调（生成器早退/断线也不丢终态）
            ledger.attach(task)
            seen_content = False
            while True:
                # 台账心跳（内部 5s 节流；空闲 15s 的 ping 分支会顺带把它推动）
                await ledger.heartbeat()
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
                elif kind == "upstream_status":
                    # 上游静默：结构化透传，前端按 i18n 组装（与 retry 同一族控制事件）
                    _st = data if isinstance(data, dict) else {}
                    if _st:
                        yield (
                            "event: upstream_status\n"
                            f"data: {json.dumps({'type': 'upstream_status', **_st})}\n\n"
                        )

            # 整轮结束后取 chat() 返回值：TTS audio 产物 + 兜底文本
            response = await task
            reply_text = ""
            if isinstance(response, dict) and response.get("parked"):
                # P2-8：闸判挂起且已落库——这一轮没跑，流以 parked+done 收尾
                parkedPayload = {k: v for k, v in response.items() if k != "parked"}
                parkedPayload["type"] = "parked"
                yield f"event: parked\ndata: {json.dumps(parkedPayload, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: {json.dumps({'type': 'done', 'request_id': request_id})}\n\n"
                return
            if isinstance(response, dict) and response.get("error"):
                # 没落库的"挂起"没有续跑入口，只能如实报失败，不能静默 done
                errPayload = {"type": "error", "error": response["error"]}
                yield f"event: error\ndata: {json.dumps(errPayload, ensure_ascii=False)}\n\n"
                yield f"event: done\ndata: {json.dumps({'type': 'done', 'request_id': request_id})}\n\n"
                return
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
# Agent 类无 get_sessions 方法,只有 session_manager 属性)
# - POST /sessions(与 console.py /chat/sessions POST 重复)
# - PUT /sessions/{session_id}(纯 stub,注释明确说"我们没有实际的会话存储")
# - DELETE /sessions/{session_id}(纯 stub,注释明确说"我们没有实际的会话存储")
# 前端只用 /api/v1/console/chat/sessions(console.py 路由,已通过 SessionRepository 接入真实存储)。
# 


@router.get("/history")
async def get_chat_history(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    session_id: str = Query(..., description="会话 ID（必填：缺键只能回空表，那是把'没给键'伪装成'没有历史'）"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """读取会话历史。

    原实现调的是 agent 上那两个**从未被定义过**的会话历史方法（那两个名字全仓只
    出现在原来的四行里，来源是 `7835c367` 的 pyc 骨架恢复），`hasattr` 恒 False，
    于是对任何人都恒回 `{"history": []}`：门挂着、数据恒空的空转端点。
    现接上仓内**唯一**那份有数据、有归属校验的实现（与
    `console.py` 的 `GET /chat/history` 同一条链，教义第 7 条选定那份）。

    归属键换成**会话属主**而不是"agent 可达"：调用者传的 `agent_id` 本来就不参与
    取数，拿它当门只会把"自己的会话读不到"（非 default agent 的属主先撞 403）
    和"别人的会话能不能读"（agent 可达就放行，`session_id` 从不比对）同时留下。
    """
    request_id = _get_request_id(request)
    from neurova.api.endpoints.console import _find_session_target, _get_user_id
    from neurova.session_repository import get_session_repository

    user_id = _get_user_id(request, current_user)
    repo = get_session_repository()
    target = _find_session_target(repo, session_id, user_id)
    messages = repo.get_history(
        agent_id=str(target.get("agent_id", "")), session_id=session_id
    )
    if limit:
        messages = messages[-limit:]

    return {
        "code": 0,
        "message": "success",
        "data": {
            "history": messages,
            "agent_id": str(target.get("agent_id", "")),
            "session_id": session_id,
        },
        "request_id": request_id,
    }


@router.delete("/history")
async def clear_chat_history(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    session_id: str = Query(..., description="会话 ID"),
):
    """清空对话历史——**显式 501**，不再谎报成功。

    原实现用 `hasattr` 探一个从未定义的 agent 方法，探测恒 False，于是每次都回
    `{"code": 0, "message": "History cleared"}` 而什么都没清：§6-8「依赖缺失却报
    成功」那一族，处置形态沿用仓内先例（`212d855c` 把 `/v1/health/recover` 的假成功
    收成显式 501）。

    为什么不顺手接一个"真清"：`session_repository` 只有 `delete_session`（整条会话
    没了）与 `delete_round`（单轮），**没有**"清空一个会话的持久消息"这一格；只清
    agent 内存历史又会被 `_restore_session_history` 从文件复活——
    `console.py:_sync_agent_history_from_session` 的存在就是那条 bug 的实证。补这个
    primitive 是新增一条不可逆写路径且当前零调用方，属产品裁决（已登记台账）。

    身份仍在能力判定**之前**：陌生人拿到 403 而不是 501，否则 501 会替他确认
    "这条会话存在"（与 `console.py` 的 `/chat/resume` 同一纪律）。
    """
    request_id = _get_request_id(request)
    from neurova.api.endpoints.console import _find_session_target, _get_user_id
    from neurova.session_repository import get_session_repository

    user_id = _get_user_id(request, current_user)
    _find_session_target(get_session_repository(), session_id, user_id)

    raise HTTPException(
        status_code=501,
        detail=(
            "清空会话持久消息在本仓没有落点（session_repository 只有 delete_session / "
            "delete_round）；整条会话删除请走 DELETE /api/v1/console/chat/sessions/"
            "{session_id}"
        ),
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
