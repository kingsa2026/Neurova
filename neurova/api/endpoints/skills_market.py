"""
技能市场接口 - Skills Market API

功能:
1. 技能列表 (GET /api/skills-market/skills)
2. 技能详情 (GET /api/skills-market/skills/{id})
3. 安装技能 (POST /api/skills-market/install)
4. 卸载技能 (DELETE /api/skills-market/skills/{id})
5. 技能分类 (GET /api/skills-market/categories)
"""

import datetime
import enum
from neurova.core.logger import get_logger
import typing

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()


# ── Enums ──────────────────────────────────────────────


class SkillCategory(str, enum.Enum):
    PRODUCTIVITY = "productivity"
    DEVELOPMENT = "development"
    DATA = "data"
    COMMUNICATION = "communication"
    AUTOMATION = "automation"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    SYSTEM = "system"
    OTHER = "other"


class SkillDifficulty(str, enum.Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


# ── Models ─────────────────────────────────────────────


class SkillInfo(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    category: SkillCategory = SkillCategory.OTHER
    difficulty: SkillDifficulty = SkillDifficulty.INTERMEDIATE
    tags: typing.List[str] = Field(default_factory=list)
    rating: float = 0.0
    rating_count: int = 0
    downloads: int = 0
    installed: bool = False
    featured: bool = False
    icon: str = ""
    created_at: str = ""


class SkillInstallRequest(BaseModel):
    skill_id: str
    agent_id: typing.Optional[str] = None


class SkillReview(BaseModel):
    user: str = "anonymous"
    rating: float = Field(ge=1.0, le=5.0)
    comment: str = ""


# ── In-memory store ────────────────────────────────────

_SKILLS_STORE: typing.Dict[str, dict] = {}
_INSTALLED_SKILLS: typing.Dict[str, set] = {}  # user_id -> {skill_ids}
_REVIEWS_STORE: typing.Dict[str, list] = {}  # skill_id -> [reviews]


def _init_sample_skills():
    """Initialize sample skills for demo purposes."""
    if _SKILLS_STORE:
        return
    samples = [
        {
            "id": "web-search",
            "name": "Web Search",
            "description": "Search the web for information",
            "author": "Neurova",
            "version": "1.2.0",
            "category": "data",
            "difficulty": "beginner",
            "tags": ["search", "web", "internet"],
            "rating": 4.5,
            "rating_count": 120,
            "downloads": 5000,
            "featured": True,
            "icon": "🔍",
        },
        {
            "id": "code-interpreter",
            "name": "Code Interpreter",
            "description": "Execute and analyze code snippets",
            "author": "Neurova",
            "version": "2.0.1",
            "category": "development",
            "difficulty": "intermediate",
            "tags": ["code", "python", "exec"],
            "rating": 4.8,
            "rating_count": 200,
            "downloads": 8000,
            "featured": True,
            "icon": "💻",
        },
        {
            "id": "file-manager",
            "name": "File Manager",
            "description": "Manage files and directories",
            "author": "Neurova",
            "version": "1.0.0",
            "category": "system",
            "difficulty": "beginner",
            "tags": ["file", "system", "io"],
            "rating": 4.2,
            "rating_count": 80,
            "downloads": 3000,
            "featured": False,
            "icon": "📁",
        },
        {
            "id": "data-analysis",
            "name": "Data Analysis",
            "description": "Analyze and visualize data",
            "author": "Neurova",
            "version": "1.5.0",
            "category": "analysis",
            "difficulty": "advanced",
            "tags": ["data", "analytics", "chart"],
            "rating": 4.6,
            "rating_count": 90,
            "downloads": 4000,
            "featured": True,
            "icon": "📊",
        },
        {
            "id": "email-sender",
            "name": "Email Sender",
            "description": "Send emails via SMTP",
            "author": "Community",
            "version": "1.1.0",
            "category": "communication",
            "difficulty": "intermediate",
            "tags": ["email", "smtp", "notify"],
            "rating": 4.0,
            "rating_count": 50,
            "downloads": 1500,
            "featured": False,
            "icon": "📧",
        },
        {
            "id": "task-scheduler",
            "name": "Task Scheduler",
            "description": "Schedule and manage recurring tasks",
            "author": "Neurova",
            "version": "1.3.0",
            "category": "automation",
            "difficulty": "intermediate",
            "tags": ["cron", "schedule", "automation"],
            "rating": 4.4,
            "rating_count": 70,
            "downloads": 2500,
            "featured": False,
            "icon": "⏰",
        },
    ]
    now = datetime.datetime.utcnow().isoformat()
    for s in samples:
        s["created_at"] = now
        _SKILLS_STORE[s["id"]] = s


_init_sample_skills()


def _get_user_id(request: Request) -> str:
    """Extract user ID from request state."""
    return getattr(request.state, "user_id", "anonymous")


# ── Endpoints ──────────────────────────────────────────


@router.get("/skills")
async def get_skills(
    request: Request,
    category: typing.Optional[str] = None,
    difficulty: typing.Optional[str] = None,
    q: typing.Optional[str] = None,
    sort: str = "rating",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """获取技能列表"""
    user_id = _get_user_id(request)
    installed = _INSTALLED_SKILLS.get(user_id, set())

    results = list(_SKILLS_STORE.values())

    if category:
        results = [s for s in results if s.get("category") == category]
    if difficulty:
        results = [s for s in results if s.get("difficulty") == difficulty]
    if q:
        q_lower = q.lower()
        results = [
            s
            for s in results
            if q_lower in s.get("name", "").lower()
            or q_lower in s.get("description", "").lower()
            or any(q_lower in t for t in s.get("tags", []))
        ]

    for s in results:
        s["installed"] = s["id"] in installed

    if sort == "rating":
        results.sort(key=lambda x: x.get("rating", 0), reverse=True)
    elif sort == "downloads":
        results.sort(key=lambda x: x.get("downloads", 0), reverse=True)
    elif sort == "name":
        results.sort(key=lambda x: x.get("name", ""))

    total = len(results)
    start = (page - 1) * size
    items = results[start : start + size]

    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/skills/{skill_id}")
async def get_skill_detail(skill_id: str, request: Request):
    """获取指定技能的详细信息"""
    user_id = _get_user_id(request)
    skill = _SKILLS_STORE.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    installed = _INSTALLED_SKILLS.get(user_id, set())
    result = {**skill, "installed": skill_id in installed, "reviews": _REVIEWS_STORE.get(skill_id, [])}

    return {"code": 0, "message": "success", "data": result}


@router.post("/install")
async def install_skill(body: SkillInstallRequest, request: Request):
    """安装指定的技能"""
    user_id = _get_user_id(request)
    skill_id = body.skill_id

    if skill_id not in _SKILLS_STORE:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    installed = _INSTALLED_SKILLS.setdefault(user_id, set())
    if skill_id in installed:
        return {"code": 0, "message": "Already installed", "data": {"skill_id": skill_id}}

    installed.add(skill_id)
    _SKILLS_STORE[skill_id]["downloads"] = _SKILLS_STORE[skill_id].get("downloads", 0) + 1

    logger.info("User %s installed skill %s", user_id, skill_id)
    return {"code": 0, "message": "Skill installed successfully", "data": {"skill_id": skill_id}}


@router.delete("/skills/{skill_id}")
async def uninstall_skill(skill_id: str, request: Request):
    """卸载指定的技能"""
    user_id = _get_user_id(request)
    installed = _INSTALLED_SKILLS.get(user_id, set())

    if skill_id not in installed:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not installed")

    installed.discard(skill_id)
    logger.info("User %s uninstalled skill %s", user_id, skill_id)
    return {"code": 0, "message": "Skill uninstalled successfully", "data": {"skill_id": skill_id}}


@router.get("/categories")
async def get_categories():
    """获取所有技能分类及统计信息"""
    category_stats: typing.Dict[str, int] = {}
    for skill in _SKILLS_STORE.values():
        cat = skill.get("category", "other")
        category_stats[cat] = category_stats.get(cat, 0) + 1

    categories = [{"id": c.value, "name": c.name, "count": category_stats.get(c.value, 0)} for c in SkillCategory]
    return {"code": 0, "message": "success", "data": {"categories": categories}}


@router.get("/featured")
async def get_featured_skills(request: Request):
    """获取精选推荐技能列表"""
    user_id = _get_user_id(request)
    installed = _INSTALLED_SKILLS.get(user_id, set())
    featured = [s for s in _SKILLS_STORE.values() if s.get("featured")]
    for s in featured:
        s["installed"] = s["id"] in installed
    return {"code": 0, "message": "success", "data": {"items": featured}}


@router.get("/installed")
async def get_installed_skills(request: Request):
    """获取当前用户已安装的技能列表"""
    user_id = _get_user_id(request)
    installed = _INSTALLED_SKILLS.get(user_id, set())
    items = [_SKILLS_STORE[sid] for sid in installed if sid in _SKILLS_STORE]
    return {"code": 0, "message": "success", "data": {"items": items, "total": len(items)}}


@router.post("/skills/{skill_id}/rate")
async def rate_skill(skill_id: str, body: SkillReview, request: Request):
    """对技能进行评分和评论"""
    if skill_id not in _SKILLS_STORE:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    reviews = _REVIEWS_STORE.setdefault(skill_id, [])
    review = {
        "user": body.user,
        "rating": body.rating,
        "comment": body.comment,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }
    reviews.append(review)

    skill = _SKILLS_STORE[skill_id]
    total_rating = sum(r["rating"] for r in reviews)
    skill["rating"] = round(total_rating / len(reviews), 2)
    skill["rating_count"] = len(reviews)

    return {
        "code": 0,
        "message": "Rating submitted",
        "data": {"skill_id": skill_id, "new_rating": skill["rating"], "rating_count": skill["rating_count"]},
    }
