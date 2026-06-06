from __future__ import annotations

"""
技能市场接口 - Marketplace Endpoint

功能:
1. 获取技能列表 (GET /api/v1/marketplace/skills)
2. 获取技能详情 (GET /api/v1/marketplace/skills/{id})
3. 安装技能 (POST /api/v1/marketplace/skills/{id}/install)
4. 卸载技能 (DELETE /api/v1/marketplace/skills/{id}/install)
5. 获取已安装技能 (GET /api/v1/marketplace/installed)
"""

import logging
import time
import typing
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# 导入技能市场导入器
try:
    from neurova.skills.market_importer import get_market_importer, MarketImporter, MarketSkill, ImportStatus
except ImportError:
    logger.warning("Market importer service not available")
    get_market_importer = None
    MarketImporter = None
    MarketSkill = None
    ImportStatus = None


class MarketplaceSkill(BaseModel):
    """市场技能"""
    skill_id: str
    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    category: str = "general"
    tags: List[str] = []
    downloads: int = 0
    rating: float = 0.0
    installed: bool = False
    price: float = 0.0
    download_url: str = ""
    updated_at: Optional[str] = None


class SkillInstallRequest(BaseModel):
    """安装技能请求"""
    version: Optional[str] = None
    config: Dict[str, Any] = {}


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _convert_market_skill_to_api(skill: MarketSkill, installed: bool = False) -> MarketplaceSkill:
    """将MarketSkill转换为API响应格式"""
    if MarketSkill is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market importer service not available"
        )
    
    return MarketplaceSkill(
        skill_id=skill.skill_id,
        name=skill.name,
        description=skill.description,
        author=skill.author,
        version=skill.version,
        category=skill.category,
        tags=skill.tags,
        downloads=skill.downloads,
        rating=skill.rating,
        installed=installed,
        price=0.0,  # 默认价格为0，可从metadata扩展
        download_url=skill.download_url,
        updated_at=skill.updated_at,
    )


@router.get("/skills", response_model=List[MarketplaceSkill])
async def get_marketplace_skills(
    request: Request,
    category: Optional[str] = Query(default=None, description="分类筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取市场技能列表"""
    try:
        if get_market_importer is None:
            logger.warning("Market importer service not available")
            return []
        
        # 获取市场导入器
        importer = get_market_importer()
        
        # 搜索技能
        skills = importer.search_skills(
            query=search or "",
            category=category,
            tags=None,  # 标签筛选可后续扩展
        )
        
        # 获取已安装技能列表
        installed_skills = importer.list_installed()
        installed_ids = {item["skill_id"] for item in installed_skills}
        
        # 转换为API格式并过滤
        result = []
        for skill in skills[offset:offset + limit]:
            installed = skill.skill_id in installed_ids
            result.append(_convert_market_skill_to_api(skill, installed))
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to get marketplace skills: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get marketplace skills: {str(e)}"
        )


@router.get("/skills/{skill_id}", response_model=MarketplaceSkill)
async def get_marketplace_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
):
    """获取市场技能详情"""
    try:
        if get_market_importer is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Market importer service not available"
            )
        
        # 获取市场导入器
        importer = get_market_importer()
        
        # 搜索技能（使用skill_id作为查询）
        skills = importer.search_skills(query=skill_id)
        
        # 查找匹配的技能
        target_skill = None
        for skill in skills:
            if skill.skill_id == skill_id:
                target_skill = skill
                break
        
        if not target_skill:
            # 尝试按名称搜索
            skills = importer.search_skills(query=skill_id)
            for skill in skills:
                if skill.name.lower() == skill_id.lower():
                    target_skill = skill
                    break
        
        if not target_skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' not found"
            )
        
        # 检查是否已安装
        installed_skills = importer.list_installed()
        installed_ids = {item["skill_id"] for item in installed_skills}
        installed = target_skill.skill_id in installed_ids
        
        return _convert_market_skill_to_api(target_skill, installed)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get skill details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get skill details: {str(e)}"
        )


@router.post("/skills/{skill_id}/install")
async def install_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
    body: SkillInstallRequest = SkillInstallRequest(),
):
    """安装技能"""
    request_id = _get_request_id(request)
    
    try:
        if get_market_importer is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Market importer service not available"
            )
        
        # 获取市场导入器
        importer = get_market_importer()
        
        # 先搜索技能获取下载URL
        skills = importer.search_skills(query=skill_id)
        target_skill = None
        for skill in skills:
            if skill.skill_id == skill_id:
                target_skill = skill
                break
        
        if not target_skill:
            # 尝试按名称搜索
            skills = importer.search_skills(query=skill_id)
            for skill in skills:
                if skill.name.lower() == skill_id.lower():
                    target_skill = skill
                    break
        
        if not target_skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' not found in marketplace"
            )
        
        # 检查是否已安装
        installed_skills = importer.list_installed()
        installed_ids = {item["skill_id"] for item in installed_skills}
        
        if target_skill.skill_id in installed_ids:
            return {
                "code": 0,
                "message": f"Skill '{skill_id}' is already installed",
                "data": {"skill_id": target_skill.skill_id, "already_installed": True},
                "request_id": request_id,
            }
        
        # 安装技能
        task = importer.import_skill(
            skill_id=target_skill.skill_id,
            version=body.version,
        )
        
        # 检查导入状态
        if ImportStatus and task.status == ImportStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to install skill '{skill_id}': {task.error_message}"
            )
        
        # 如果导入还在进行中，返回进行中状态
        if ImportStatus and task.status != ImportStatus.COMPLETED:
            return {
                "code": 0,
                "message": f"Skill '{skill_id}' installation started",
                "data": {
                    "skill_id": target_skill.skill_id,
                    "status": task.status.value,
                    "task_id": task.skill_id,
                },
                "request_id": request_id,
            }
        
        return {
            "code": 0,
            "message": f"Skill '{skill_id}' installed successfully",
            "data": {
                "skill_id": target_skill.skill_id,
                "version": body.version or target_skill.version,
            },
            "request_id": request_id,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to install skill: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to install skill: {str(e)}"
        )


@router.delete("/skills/{skill_id}/install")
async def uninstall_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
):
    """卸载技能"""
    request_id = _get_request_id(request)
    
    try:
        if get_market_importer is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Market importer service not available"
            )
        
        # 获取市场导入器
        importer = get_market_importer()
        
        # 检查技能是否已安装
        installed_skills = importer.list_installed()
        installed_ids = {item["skill_id"] for item in installed_skills}
        
        if skill_id not in installed_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' is not installed"
            )
        
        # 卸载技能
        success = importer.uninstall_skill(skill_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to uninstall skill '{skill_id}'"
            )
        
        return {
            "code": 0,
            "message": f"Skill '{skill_id}' uninstalled successfully",
            "data": {"skill_id": skill_id},
            "request_id": request_id,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to uninstall skill: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to uninstall skill: {str(e)}"
        )


@router.get("/installed", response_model=List[MarketplaceSkill])
async def get_installed_skills(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取已安装技能"""
    try:
        if get_market_importer is None:
            logger.warning("Market importer service not available")
            return []
        
        # 获取市场导入器
        importer = get_market_importer()
        
        # 获取已安装技能列表
        installed_skills = importer.list_installed()
        
        # 转换为API格式
        result = []
        for item in installed_skills[:limit]:
            # 创建基础MarketplaceSkill（没有完整市场信息）
            skill = MarketplaceSkill(
                skill_id=item["skill_id"],
                name=item["skill_id"],  # 使用skill_id作为名称
                description="Installed skill",
                author="Unknown",
                version=item["version"],
                category="installed",
                tags=[],
                downloads=0,
                rating=0.0,
                installed=True,
                price=0.0,
                download_url="",
                updated_at=None,
            )
            result.append(skill)
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to get installed skills: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get installed skills: {str(e)}"
        )
