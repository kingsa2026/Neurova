"""
Agent Builder v1.0.0 API 端点

隔离层级: 工具全局 + 产物用户层
"""

import datetime
from neurova.core.logger import get_logger
import typing
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


# ── Models ─────────────────────────────────────────────


class TemplateInfo(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    personality: str = ""
    system_prompt: str = ""
    tags: typing.List[str] = Field(default_factory=list)
    category: str = "general"


class BuildRequest(BaseModel):
    name: str
    template_id: typing.Optional[str] = None
    system_prompt: str = ""
    personality: str = ""
    model: typing.Optional[str] = None
    config: typing.Optional[dict] = None


class BuildResponse(BaseModel):
    agent_id: str
    name: str
    template_id: typing.Optional[str] = None
    status: str = "created"
    created_at: str = ""


class ValidateRequest(BaseModel):
    name: str = ""
    system_prompt: str = ""
    personality: str = ""
    config: typing.Optional[dict] = None


# ── In-memory store ────────────────────────────────────

_TEMPLATES: typing.List[dict] = [
    {
        "id": "assistant",
        "name": "General Assistant",
        "description": "A helpful general-purpose assistant",
        "personality": "Helpful, friendly, and knowledgeable",
        "system_prompt": "You are a helpful assistant.",
        "tags": ["general", "assistant"],
        "category": "general",
    },
    {
        "id": "coder",
        "name": "Code Expert",
        "description": "Specialized in programming and software development",
        "personality": "Technical, precise, and detail-oriented",
        "system_prompt": "You are an expert software developer.",
        "tags": ["coding", "development"],
        "category": "technical",
    },
    {
        "id": "researcher",
        "name": "Research Analyst",
        "description": "Focused on research and data analysis",
        "personality": "Analytical, thorough, and evidence-based",
        "system_prompt": "You are a research analyst.",
        "tags": ["research", "analysis"],
        "category": "analytical",
    },
    {
        "id": "creative",
        "name": "Creative Writer",
        "description": "Specialized in creative writing and content creation",
        "personality": "Imaginative, expressive, and eloquent",
        "system_prompt": "You are a creative writer.",
        "tags": ["writing", "creative"],
        "category": "creative",
    },
    {
        "id": "teacher",
        "name": "Educator",
        "description": "Focused on teaching and explaining concepts",
        "personality": "Patient, clear, and encouraging",
        "system_prompt": "You are an educator who explains concepts clearly.",
        "tags": ["education", "teaching"],
        "category": "education",
    },
]

_BUILT_AGENTS: typing.Dict[str, dict] = {}


# ── Endpoints ──────────────────────────────────────────


@router.get("/templates")
async def list_templates():
    """列出所有预定义的人格模板"""
    return {"code": 0, "message": "success", "data": {"templates": _TEMPLATES, "total": len(_TEMPLATES)}}


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """获取指定模板的详情"""
    template = next((t for t in _TEMPLATES if t["id"] == template_id), None)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return {"code": 0, "message": "success", "data": template}


@router.post("/validate")
async def validate_config(body: ValidateRequest):
    """校验 Agent 配置（不创建实例）"""
    errors = []
    if not body.name and not body.system_prompt and not body.personality:
        errors.append("At least one of name, system_prompt, or personality must be provided")
    if body.name and len(body.name) > 100:
        errors.append("Name must be <= 100 characters")
    if body.system_prompt and len(body.system_prompt) > 10000:
        errors.append("System prompt must be <= 10000 characters")

    return {
        "code": 0,
        "message": "Validation complete",
        "data": {"valid": len(errors) == 0, "errors": errors},
    }


@router.post("/build")
async def build_agent(body: BuildRequest, request):
    """创建 Agent 实例"""
    user_id = getattr(request.state, "user_id", "anonymous")
    agent_id = str(uuid.uuid4())[:12]
    now = datetime.datetime.utcnow().isoformat()

    # Resolve template
    template = None
    if body.template_id:
        template = next((t for t in _TEMPLATES if t["id"] == body.template_id), None)
        if not template:
            raise HTTPException(status_code=404, detail=f"Template '{body.template_id}' not found")

    system_prompt = body.system_prompt or (template["system_prompt"] if template else "You are a helpful assistant.")
    personality = body.personality or (template["personality"] if template else "")

    # Try to create real agent
    agent_created = False
    try:
        from neurova.api.endpoints import get_agent_instance

        existing = get_agent_instance()
        if existing:
            agent_created = True
    except Exception:
        pass

    agent_data = {
        "agent_id": agent_id,
        "name": body.name,
        "user_id": user_id,
        "template_id": body.template_id,
        "system_prompt": system_prompt,
        "personality": personality,
        "model": body.model,
        "config": body.config or {},
        "status": "active" if agent_created else "configured",
        "created_at": now,
    }
    _BUILT_AGENTS[agent_id] = agent_data

    logger.info("Agent built: %s for user %s", agent_id, user_id)
    return {"code": 0, "message": "Agent built successfully", "data": agent_data}


@router.get("/agents")
async def list_built_agents(request):
    """列出用户创建的 Agent"""
    user_id = getattr(request.state, "user_id", "anonymous")
    agents = [a for a in _BUILT_AGENTS.values() if a.get("user_id") == user_id]
    return {"code": 0, "message": "success", "data": {"agents": agents, "total": len(agents)}}
