"""
技能市场 API

提供以下端点:
- GET    /v1/skill-market/markets           列出支持的市场
- POST   /v1/skill-market/search            搜索技能
- POST   /v1/skill-market/install           从 URL 安装
- POST   /v1/skill-market/install/zip       从 ZIP 安装
- GET    /v1/skill-market/installed          已安装列表
"""

import logging
import os
import tempfile
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchSkillRequest(BaseModel):
    query: str = Field(..., description="搜索关键词")
    market: Optional[str] = Field(default=None, description="指定市场")
    category: Optional[str] = Field(default=None, description="分类筛选")
    limit: int = Field(default=20, le=100)


class InstallSkillRequest(BaseModel):
    url: str = Field(..., description="技能 URL")
    version: Optional[str] = Field(default=None, description="指定版本")


class MarketplaceSkill(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    downloads: int = 0
    rating: float = 0.0
    market: str = ""
    category: str = ""


_installed_skills: List[Dict[str, Any]] = []


@router.get("/markets")
async def list_markets():
    """列出支持的技能市场"""
    return {
        "code": 0,
        "data": {
            "markets": [
                {"id": "neurova-hub", "name": "Neurova Hub", "url": "https://hub.neurova.ai"},
                {"id": "github", "name": "GitHub", "url": "https://github.com"},
            ]
        },
    }


@router.post("/search")
async def search_skills(body: SearchSkillRequest):
    """搜索技能市场"""
    # 模拟搜索结果
    results = [
        MarketplaceSkill(
            skill_id="skill_weather",
            name="Weather Skill",
            description="Get weather information",
            author="neurova",
            version="1.0.0",
            downloads=1500,
            rating=4.5,
            market="neurova-hub",
        ),
        MarketplaceSkill(
            skill_id="skill_translate",
            name="Translation Skill",
            description="Translate text",
            author="community",
            version="2.1.0",
            downloads=3200,
            rating=4.8,
            market="neurova-hub",
        ),
    ]
    if body.query:
        results = [
            r for r in results if body.query.lower() in r.name.lower() or body.query.lower() in r.description.lower()
        ]
    return {"code": 0, "data": {"skills": [r.model_dump() for r in results[: body.limit]]}}


@router.post("/install")
async def install_skill_from_market(body: InstallSkillRequest):
    """从市场安装技能"""
    _installed_skills.append(
        {"skill_id": body.url.split("/")[-1], "source_url": body.url, "version": body.version or "latest"}
    )
    return {"code": 0, "message": "Skill installed", "data": {"url": body.url}}


@router.post("/install/zip")
async def install_skill_from_zip(file: UploadFile = File(...)):
    """从 ZIP 文件安装"""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, file.filename or "skill.zip")
        content = await file.read()
        with open(zip_path, "wb") as f:
            f.write(content)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(os.path.join(tmpdir, "extracted"))
    return {"code": 0, "message": "Skill installed from ZIP"}


@router.get("/installed")
async def list_installed_skills():
    """列出已安装技能"""
    return {"code": 0, "data": {"skills": _installed_skills}}
