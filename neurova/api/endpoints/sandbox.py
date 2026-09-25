"""
沙箱 API v2.0.0 —— 一套值域，两种能力。

## 值域（唯一一份，前端 `Sandbox` 接口就是它的投影）

沙箱 session 只有**一套**形态与状态机：

| 字段 | 含义 |
|---|---|
| `id` | session id；`null` 是**保留 id**（无容器承载的思维沙箱面） |
| `name` / `image` / `timeout` | 创建参数（前端新建弹窗的三项） |
| `language` | 默认解释器（执行区下拉的当前值） |
| `steps` | 承载的执行/推理步骤（`steps_count` = `len(steps)`，不另存计数） |
| `status` | 有限枚举 `running / paused / committed / failed / timeout` |

两种能力**不是两套沙箱**，而是同一值域下的两种承载：

- **代码执行**：`POST /start` 带 `name`/`image`/`timeout` → 真 session（uuid），
  执行面 `POST /{id}/execute` 收 `{command, language}`，真解释器跑真代码；
- **思维沙箱**：`POST /start` 带 `agent_id`/`topic` → 挂在保留 id `null` 上
  （无容器承载），执行面 `POST /null/step` 收 `{input, context}`。
  `null` 不可删除、不可执行代码：它在值域里，但有一份限定能力面。

之所以此前是两套：前端页面描述代码执行沙箱、后端实现思维沙箱，
`/execute` 从未注册过路由（必 404）、`/start` 要 `agent_id`/`topic`（前端载荷必 422）、
`/commit` 强制结论 body（前端不传必 422）。同一个「沙箱」被定义了两份，
判据单源收口到本模块 + `neurova/sandbox/code_sandbox.py`（执行后端）。
"""

from __future__ import annotations

import asyncio
import datetime
import threading
import typing
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from neurova.api.auth import get_current_user, get_current_user_or_default
from neurova.api.endpoints import get_agent_instance
from neurova.core.logger import get_logger
from neurova.sandbox.code_sandbox import (
    CodeSandboxSession,
    SandboxLanguageError,
    SandboxBackendUnavailable,
    dockerAvailable,
    supportedLanguages,
)

logger = get_logger(__name__)

# P0 安全修复: 沙箱 commit 可写入 Agent 持久记忆，所有端点必须认证
router = APIRouter(dependencies=[Depends(get_current_user)])


# ── 值域常量（唯一一份）─────────────────────────────────

#: 保留 session id：思维沙箱面无容器承载，挂在它上面
THOUGHT_SESSION_ID = "null"

#: 状态有限枚举（前端 tag 三色映射的取值来源）
SANDBOX_STATUSES = ("running", "paused", "committed", "failed", "timeout")

#: 镜像白名单：用户选的镜像就是跑它的镜像，不收下再换一个跑
ALLOWED_IMAGES = (
    "python:3.11-slim",
    "python:3.12-slim",
    "node:20-slim",
    "node:22-slim",
)

#: 默认镜像（前端 placeholder 同值）
DEFAULT_IMAGE = "python:3.11-slim"

#: 语言覆盖：不声明时按镜像名推断
_IMAGE_DEFAULT_LANGUAGE = {
    "python:3.11-slim": "python",
    "python:3.12-slim": "python",
    "node:20-slim": "javascript",
    "node:22-slim": "javascript",
}

DEFAULT_TIMEOUT_SECONDS = 300
MIN_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 3600


# ── Models ─────────────────────────────────────────────


class SandboxStartRequest(BaseModel):
    """新建沙箱请求。

    两种能力共用**一个**请求体（一套值域）：
    - 传 `name`/`image`/`timeout` → 代码执行沙箱（真 session + 容器后端）；
    - 传 `agent_id`/`topic` → 思维沙箱（挂保留 id `null`）。
    只传描述字段而不传承载字段时，按代码执行沙箱起（镜像有默认值）。
    """

    # 代码执行面
    name: typing.Optional[str] = None
    image: typing.Optional[str] = None
    timeout: typing.Optional[int] = Field(default=None, ge=MIN_TIMEOUT_SECONDS, le=MAX_TIMEOUT_SECONDS)
    language: typing.Optional[str] = None
    backend: str = "auto"
    # 思维沙箱面
    agent_id: typing.Optional[str] = None
    topic: typing.Optional[str] = None
    description: str = ""
    max_steps: int = Field(default=10, ge=1, le=100)
    config: typing.Optional[dict] = None

    @field_validator("backend")
    @classmethod
    def _checkBackend(cls, value: str) -> str:
        if value not in ("auto", "docker"):
            raise ValueError("backend 只支持 'auto'（按可用性选择）或 'docker'（强制容器隔离）")
        return value


class ExecuteRequest(BaseModel):
    """代码执行请求（前端 `ExecutePayload` 的字段来源）。"""

    command: str = Field(min_length=1)
    language: typing.Optional[str] = None
    timeout: typing.Optional[float] = Field(default=None, gt=0)


class SandboxCommitRequest(BaseModel):
    """提交请求。`conclusion` 可选——前端 `commitSandbox(id)` 不带 body。"""

    conclusion: typing.Optional[str] = None
    save_to_memory: bool = True
    tags: typing.List[str] = Field(default_factory=list)


class StepRequest(BaseModel):
    input: str
    context: typing.Optional[str] = None


# ── 账户内的 session 存储 ──────────────────────────────

_SESSIONS: typing.Dict[str, dict] = {}  # session_id -> session data
_SESSIONS_LOCK = threading.RLock()


def reset_execution_sandboxes() -> None:
    """清空全部代码执行沙箱（测试隔离出口；同时释放容器后端）。"""
    with _SESSIONS_LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    for session in sessions:
        carrier = session.get("carrier")
        if isinstance(carrier, CodeSandboxSession):
            carrier.close()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _publicView(session: dict) -> dict:
    """磁盘态 → 前端 `Sandbox` 接口的字段投影（唯一一处）。"""
    return {
        "id": session["id"],
        "name": session["name"],
        "status": session["status"],
        "image": session["image"],
        "language": session["language"],
        "timeout": session["timeout"],
        "steps_count": len(session["steps"]),
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "agent_id": session.get("agent_id"),
        "topic": session.get("topic"),
    }


def _requireSession(sandbox_id: str) -> dict:
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(sandbox_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    return session


def _thoughtSession() -> dict:
    """保留的思维沙箱 session：无容器承载，随需自举。"""
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(THOUGHT_SESSION_ID)
        if session is None:
            now = _now()
            session = {
                "id": THOUGHT_SESSION_ID,
                "name": "思维沙箱",
                "image": None,
                "language": None,
                "timeout": None,
                "backend": None,
                "status": "running",
                "agent_id": None,
                "topic": None,
                "description": "",
                "max_steps": 10,
                "steps": [],
                "created_at": now,
                "updated_at": now,
                "carrier": None,
            }
            _SESSIONS[THOUGHT_SESSION_ID] = session
        return session


# ── Endpoints ──────────────────────────────────────────


@router.get("")
async def list_all_sandboxes(status: typing.Optional[str] = None):
    """列出所有沙箱"""
    with _SESSIONS_LOCK:
        results = [_publicView(s) for s in _SESSIONS.values()]
    if status:
        results = [s for s in results if s["status"] == status]
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"code": 0, "message": "success", "data": {"sandboxes": results, "total": len(results)}}


@router.get("/agent/{agent_id}")
async def list_sandboxes(agent_id: str, status: typing.Optional[str] = None):
    """列出某 Agent 的所有沙箱"""
    with _SESSIONS_LOCK:
        results = [_publicView(s) for s in _SESSIONS.values() if s.get("agent_id") == agent_id]
    if status:
        results = [s for s in results if s["status"] == status]
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"code": 0, "message": "success", "data": {"sandboxes": results, "total": len(results)}}


@router.post("/start")
async def start_sandbox(body: SandboxStartRequest):
    """开启沙箱。

    带 `agent_id`/`topic` → 思维沙箱（保留 id `null`，无容器承载）；
    否则 → 代码执行沙箱（真 session，镜像白名单校验）。
    """
    if body.agent_id or body.topic:
        return _startThoughtCapability(body)

    image = body.image or DEFAULT_IMAGE
    if image not in ALLOWED_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"镜像 '{image}' 不在白名单内；可选：{list(ALLOWED_IMAGES)}",
        )
    language = body.language or _IMAGE_DEFAULT_LANGUAGE[image]
    if language not in supportedLanguages():
        raise HTTPException(
            status_code=400,
            detail=f"语言 '{language}' 不支持；可选：{supportedLanguages()}",
        )
    if body.backend == "docker" and not dockerAvailable():
        raise HTTPException(
            status_code=503,
            detail="请求 backend=docker 但 Docker 不可用——不静默降级成裸跑，"
                   "请先启动 Docker 守护进程或改用 backend=auto",
        )

    if body.timeout is not None and not (MIN_TIMEOUT_SECONDS <= body.timeout <= MAX_TIMEOUT_SECONDS):
        raise HTTPException(
            status_code=400,
            detail=f"timeout 须在 [{MIN_TIMEOUT_SECONDS}, {MAX_TIMEOUT_SECONDS}] 秒内",
        )

    sandbox_id = uuid.uuid4().hex[:12]
    now = _now()
    session = {
        "id": sandbox_id,
        "name": body.name or f"code-{sandbox_id}",
        "image": image,
        "language": language,
        "timeout": body.timeout if body.timeout is not None else DEFAULT_TIMEOUT_SECONDS,
        "backend": body.backend,
        "status": "running",
        "agent_id": None,
        "topic": None,
        "description": body.description,
        "max_steps": body.max_steps,
        "steps": [],
        "created_at": now,
        "updated_at": now,
        "carrier": None,
    }
    with _SESSIONS_LOCK:
        _SESSIONS[sandbox_id] = session
    return {"code": 0, "message": "Sandbox started", "data": _publicView(session)}


def _startThoughtCapability(body: SandboxStartRequest) -> dict:
    """思维沙箱面：落在保留 id `null` 上，收敛 `max_steps` 与 topic。"""
    if not (body.agent_id and body.topic):
        raise HTTPException(
            status_code=422,
            detail="思维沙箱需要同时给 agent_id 与 topic；只给其一是半截请求",
        )
    session = _thoughtSession()
    with _SESSIONS_LOCK:
        session.update(
            {
                "agent_id": body.agent_id,
                "topic": body.topic,
                "description": body.description,
                "max_steps": body.max_steps,
                "status": "running",
                "updated_at": _now(),
            }
        )
    return {"code": 0, "message": "Thought sandbox ready", "data": _publicView(session)}


@router.get("/{sandbox_id}")
async def get_sandbox_status(sandbox_id: str):
    """查询沙箱状态"""
    session = _thoughtSession() if sandbox_id == THOUGHT_SESSION_ID else _requireSession(sandbox_id)
    return {"code": 0, "message": "success", "data": _publicView(session)}


@router.post("/{sandbox_id}/execute")
async def execute_in_session(sandbox_id: str, body: ExecuteRequest):
    """在代码执行沙箱中真跑一段代码（前端 `/execute` 的唯一对应路由）。"""
    session = _thoughtSession() if sandbox_id == THOUGHT_SESSION_ID else _requireSession(sandbox_id)
    if sandbox_id == THOUGHT_SESSION_ID:
        raise HTTPException(
            status_code=400,
            detail="思维沙箱（id='null'）无容器承载，不提供代码执行；"
                   "如要跑代码请用 POST /start 建一个代码执行沙箱",
        )
    if session["status"] != "running":
        raise HTTPException(
            status_code=400,
            detail=f"Sandbox is {session['status']}, not running",
        )

    language = body.language or session["language"]
    if language not in supportedLanguages():
        raise HTTPException(
            status_code=400,
            detail=f"语言 '{language}' 不支持；可选：{supportedLanguages()}",
        )
    timeout = float(body.timeout) if body.timeout else float(session["timeout"])

    carrier = session.get("carrier")
    if not isinstance(carrier, CodeSandboxSession):
        carrier = CodeSandboxSession(
            image=session["image"],
            backend=session.get("backend", "auto"),
        )
        session["carrier"] = carrier

    try:
        outcome = await asyncio.to_thread(
            carrier.execute, body.command, language, timeout
        )
    except SandboxLanguageError:
        raise
    except SandboxBackendUnavailable as exc:
        session["status"] = "failed"
        session["updated_at"] = _now()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    step = {
        "step": len(session["steps"]) + 1,
        "language": language,
        "command": body.command,
        "exit_code": outcome["exit_code"],
        "stdout": outcome["stdout"],
        "stderr": outcome["stderr"],
        "backend": outcome["backend"],
        "enforced": outcome["enforced"],
        "timed_out": outcome["timed_out"],
        "duration_ms": outcome["duration_ms"],
        "timestamp": _now(),
    }
    with _SESSIONS_LOCK:
        session["steps"].append(step)
        session["language"] = language
        if outcome["timed_out"]:
            session["status"] = "timeout"
        session["updated_at"] = _now()

    return {
        "code": 0,
        "message": "Executed",
        "data": {
            "sandbox_id": sandbox_id,
            "output": outcome["stdout"] or outcome["stderr"],
            "stdout": outcome["stdout"],
            "stderr": outcome["stderr"],
            "exit_code": outcome["exit_code"],
            "backend": outcome["backend"],
            "enforced": outcome["enforced"],
            "timed_out": outcome["timed_out"],
            "duration_ms": outcome["duration_ms"],
            "steps_count": len(session["steps"]),
        },
    }


@router.post("/{sandbox_id}/step")
async def execute_step(sandbox_id: str, body: StepRequest):
    """思维沙箱中执行一步思考（保留 id `null` 的限定能力面）。"""
    session = _thoughtSession() if sandbox_id == THOUGHT_SESSION_ID else _requireSession(sandbox_id)
    if sandbox_id != THOUGHT_SESSION_ID:
        raise HTTPException(
            status_code=400,
            detail=f"Sandbox '{sandbox_id}' 是代码执行沙箱（执行面 /execute）；"
                   "思维步进只服务于保留 session 'null'",
        )
    if session["status"] != "running":
        raise HTTPException(status_code=400, detail=f"Sandbox is {session['status']}, not running")
    if len(session["steps"]) >= session["max_steps"]:
        raise HTTPException(status_code=400, detail="Maximum steps reached. Please commit or destroy.")

    # Try to use agent for real thinking
    thought = f"Step {len(session['steps']) + 1}: Analyzing '{body.input}'"
    try:
        agent = get_agent_instance()
        if agent:
            prompt = f"[Sandbox: {session['topic']}]\nStep {len(session['steps']) + 1}\nInput: {body.input}"
            if body.context:
                prompt += f"\nContext: {body.context}"
            # S7 修复 (B-2 #10): 不注入 {"history": []},让 agent.chat() 从 session 恢复历史.
            result = await agent.chat(prompt)
            thought = result if isinstance(result, str) else str(result)
    except Exception as e:  # noqa: BLE001
        logger.warning("沙箱步骤中 Agent 思考失败，使用占位思考: %s", e)

    step_data = {
        "step": len(session["steps"]) + 1,
        "input": body.input,
        "context": body.context,
        "thought": thought,
        "timestamp": _now(),
    }
    with _SESSIONS_LOCK:
        session["steps"].append(step_data)
        session["updated_at"] = _now()

    return {
        "code": 0,
        "message": "Step executed",
        "data": {
            "step": step_data,
            "remaining_steps": session["max_steps"] - len(session["steps"]),
        },
    }


@router.post("/{sandbox_id}/commit")
async def commit_sandbox(
    sandbox_id: str,
    body: typing.Optional[SandboxCommitRequest] = Body(default=None),
):
    """提交沙箱状态（结论可写记忆），然后冻结执行。前端不带 body。"""
    session = _requireSession(sandbox_id)
    request = body or SandboxCommitRequest()

    conclusion = request.conclusion
    if conclusion is None:
        # 无结论时用最后一步的产物作结论——不臆造，也不落空
        conclusion = _lastOutcomeAsConclusion(session)

    with _SESSIONS_LOCK:
        session["status"] = "committed"
        session["conclusion"] = conclusion
        session["updated_at"] = _now()

    saved = False
    if request.save_to_memory and conclusion:
        saved = _persistConclusion(session, conclusion, request.tags)

    return {
        "code": 0,
        "message": "Sandbox committed",
        "data": {
            "sandbox_id": sandbox_id,
            "conclusion": conclusion,
            "steps_count": len(session["steps"]),
            "saved_to_memory": saved,
        },
    }


def _lastOutcomeAsConclusion(session: dict) -> str:
    """取最后一步的实际产物作结论（思维步取 thought，代码步取 stdout/stderr）。"""
    if not session["steps"]:
        return ""
    last = session["steps"][-1]
    if last.get("thought"):
        return str(last["thought"])
    tail = (last.get("stdout") or "").strip() or (last.get("stderr") or "").strip()
    return tail[-2000:]


def _persistConclusion(session: dict, conclusion: str, tags: typing.List[str]) -> bool:
    """把结论写进持久记忆；返回是否真的写入（不谎报 saved_to_memory）。"""
    try:
        agent = get_agent_instance()
    except Exception as e:  # noqa: BLE001 - agent 未装配属正常态
        logger.warning("沙箱提交：agent 未装配，跳过记忆写入: %s", e)
        return False
    if not agent or not hasattr(agent, "memory_manager"):
        return False
    manager = agent.memory_manager
    if not hasattr(manager, "remember"):
        return False
    content = f"[Sandbox Conclusion] {conclusion}"
    try:
        manager.remember(
            content,
            tags=list(tags) + ["sandbox", "conclusion"],
            metadata={"sandbox_id": session["id"], "sandbox_kind": session.get("image") or "thought"},
        )
    except TypeError:
        # 老签名不接受 tags/metadata：仍以内容落库，不吞掉这条结论
        manager.remember(content)
    return True


@router.delete("/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str):
    """销毁沙箱（丢弃中间过程）"""
    if sandbox_id == THOUGHT_SESSION_ID:
        raise HTTPException(
            status_code=400,
            detail="'null' 是保留 session（思维沙箱面），不可销毁",
        )
    with _SESSIONS_LOCK:
        session = _SESSIONS.pop(sandbox_id, None)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    carrier = session.get("carrier")
    if isinstance(carrier, CodeSandboxSession):
        carrier.close()
    return {"code": 0, "message": "Sandbox destroyed", "data": {"sandbox_id": sandbox_id}}
