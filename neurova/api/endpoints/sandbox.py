"""
Sandbox API 端点 v1.0.0 — 思维沙箱管理
"""

import datetime
import typing
import uuid

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from pydantic import BaseModel
from pydantic import Field

from neurova.api.endpoints import get_agent_instance

router = APIRouter()


# ── Models ─────────────────────────────────────────────

class SandboxStartRequest(BaseModel):
    agent_id: str
    topic: str
    description: str = ""
    max_steps: int = Field(default=10, ge=1, le=100)
    config: typing.Optional[dict] = None


class SandboxCommitRequest(BaseModel):
    conclusion: str
    save_to_memory: bool = True
    tags: typing.List[str] = Field(default_factory=list)


class StepRequest(BaseModel):
    input: str
    context: typing.Optional[str] = None


# ── In-memory store ────────────────────────────────────

_SANDBOXES: typing.Dict[str, dict] = {}  # sandbox_id -> sandbox data


# ── Endpoints ──────────────────────────────────────────

@router.post("/start")
async def start_thought_sandbox(body: SandboxStartRequest):
    """为 Agent 开启思维沙箱"""
    sandbox_id = str(uuid.uuid4())[:12]
    now = datetime.datetime.utcnow().isoformat()

    sandbox = {
        "sandbox_id": sandbox_id,
        "agent_id": body.agent_id,
        "topic": body.topic,
        "description": body.description,
        "status": "active",
        "max_steps": body.max_steps,
        "current_step": 0,
        "steps": [],
        "conclusion": None,
        "config": body.config or {},
        "created_at": now,
        "updated_at": now,
    }
    _SANDBOXES[sandbox_id] = sandbox

    return {"code": 0, "message": "Sandbox started", "data": sandbox}


@router.get("/{sandbox_id}")
async def get_sandbox_status(sandbox_id: str):
    """查询沙箱状态"""
    sandbox = _SANDBOXES.get(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    return {"code": 0, "message": "success", "data": sandbox}


@router.post("/{sandbox_id}/step")
async def execute_step(sandbox_id: str, body: StepRequest):
    """沙箱中执行一步思考"""
    sandbox = _SANDBOXES.get(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    if sandbox["status"] != "active":
        raise HTTPException(status_code=400, detail=f"Sandbox is {sandbox['status']}, not active")
    if sandbox["current_step"] >= sandbox["max_steps"]:
        raise HTTPException(status_code=400, detail="Maximum steps reached. Please commit or destroy.")

    # Try to use agent for real thinking
    thought = f"Step {sandbox['current_step'] + 1}: Analyzing '{body.input}'"
    try:
        agent = get_agent_instance()
        if agent:
            prompt = f"[Sandbox: {sandbox['topic']}]\nStep {sandbox['current_step'] + 1}\nInput: {body.input}"
            if body.context:
                prompt += f"\nContext: {body.context}"
            result = await agent.chat(prompt)
            thought = result if isinstance(result, str) else str(result)
    except Exception:
        pass

    step_data = {
        "step": sandbox["current_step"] + 1,
        "input": body.input,
        "context": body.context,
        "thought": thought,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }
    sandbox["steps"].append(step_data)
    sandbox["current_step"] += 1
    sandbox["updated_at"] = datetime.datetime.utcnow().isoformat()

    return {"code": 0, "message": "Step executed", "data": {"step": step_data, "remaining_steps": sandbox["max_steps"] - sandbox["current_step"]}}


@router.post("/{sandbox_id}/commit")
async def commit_sandbox(sandbox_id: str, body: SandboxCommitRequest):
    """提交结论（写入持久化记忆），然后销毁"""
    sandbox = _SANDBOXES.get(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")

    sandbox["status"] = "committed"
    sandbox["conclusion"] = body.conclusion
    sandbox["updated_at"] = datetime.datetime.utcnow().isoformat()

    # Try to save to memory
    if body.save_to_memory:
        try:
            agent = get_agent_instance()
            if agent and hasattr(agent, "memory_manager"):
                memory_content = f"[Sandbox Conclusion] Topic: {sandbox['topic']}\nConclusion: {body.conclusion}"
                if hasattr(agent.memory_manager, "remember"):
                    await agent.memory_manager.remember(memory_content, tags=body.tags + ["sandbox", "conclusion"])
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to save sandbox to memory: %s", e)

    return {
        "code": 0, "message": "Sandbox committed",
        "data": {"sandbox_id": sandbox_id, "conclusion": body.conclusion, "steps_count": len(sandbox["steps"]), "saved_to_memory": body.save_to_memory},
    }


@router.delete("/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str):
    """销毁沙箱（丢弃中间过程）"""
    sandbox = _SANDBOXES.pop(sandbox_id, None)
    if not sandbox:
        raise HTTPException(status_code=404, detail=f"Sandbox '{sandbox_id}' not found")
    return {"code": 0, "message": "Sandbox destroyed", "data": {"sandbox_id": sandbox_id}}


@router.get("/agent/{agent_id}")
async def list_sandboxes(agent_id: str, status: typing.Optional[str] = None):
    """列出某 Agent 的所有沙箱"""
    results = [s for s in _SANDBOXES.values() if s.get("agent_id") == agent_id]
    if status:
        results = [s for s in results if s.get("status") == status]
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"code": 0, "message": "success", "data": {"sandboxes": results, "total": len(results)}}
