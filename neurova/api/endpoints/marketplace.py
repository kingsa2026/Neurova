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

from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin

logger = get_logger(__name__)

router = APIRouter()

_DEPRECATED = True
"""已废弃 — ADR 0013: 统一到 skill_pool_api.py。此端点调用 stub MarketImporter。"""

# 导入技能市场导入器
try:
    from neurova.skills.market_importer import ImportStatus, MarketImporter, MarketSkill, get_market_importer
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
    updated_at: Optional[Any] = None
    source: str = "local"  # 条目来源: local(管理员上架) / aliyun / xfyun(远端同步)


class SkillInstallRequest(BaseModel):
    """安装技能请求"""

    version: Optional[str] = None
    config: Dict[str, Any] = {}
    force: Optional[bool] = None


class MarketplaceSkillCreate(BaseModel):
    """上架技能请求(仅管理员)"""

    skill_id: str = Field(..., description="市场技能 ID")
    name: str = Field(..., description="技能名称")
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    category: str = "general"
    tags: List[str] = []
    download_url: str = ""
    rating: float = 0.0


class MarketplaceSkillUpdate(BaseModel):
    """更新技能请求(仅管理员); version 变化触发站内通知"""

    name: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    download_url: Optional[str] = None


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _default_skill_registry():
    """默认 Agent 工具注册表单例（懒导入避免循环依赖）"""
    from neurova.skill_system import get_skill_registry

    return get_skill_registry()


def _running_agent_registries():
    """运行中 Agents 的独立技能注册表（agent_core 各实例自建，非全局单例）"""
    regs: List[Any] = []
    try:
        from neurova.api.endpoints import get_app_state

        state = get_app_state() or {}
        for _aid, agent in (state.get("agents") or {}).items():
            if agent is None:
                continue
            reg = getattr(agent, "_skill_registry", None)
            if reg is not None and reg not in regs:
                regs.append(reg)
    except Exception as e:  # noqa: BLE001 — 运行态收集失败不阻断安装
        logger.warning("collect running agent registries failed: %s", e)
    return regs


def _convert_market_skill_to_api(skill: MarketSkill, installed: bool = False) -> MarketplaceSkill:
    """将MarketSkill转换为API响应格式"""
    if MarketSkill is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Market importer service not available"
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
        source=getattr(skill, "source", "local") or "local",
    )


@router.get("/skills", response_model=None)
async def get_marketplace_skills(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
    category: Optional[str] = Query(default=None, description="分类筛选"),
    search: Optional[str] = Query(default=None, description="搜索关键词"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    source: Optional[str] = Query(default=None, description="来源筛选: local(管理员上架) / aliyun / xfyun"),
    with_total: bool = Query(default=False, description="返回 {items,total} 信封（分页用）；默认裸数组兼容旧契约"),
):
    """获取市场技能列表 — 登录用户可读

    source+with_total 供前端来源 Tab 分页；不带 with_total 时保持裸数组旧契约。
    """
    try:
        if get_market_importer is None:
            logger.warning("Market importer service not available")
            return {"items": [], "total": 0} if with_total else []

        # 获取市场导入器
        importer = get_market_importer()

        # 搜索技能（source 过滤在 importer 内做，local 匹配无 source 字段的种子）
        skills = importer.search_skills(
            query=search or "",
            category=category,
            tags=None,  # 标签筛选可后续扩展
            source=source,
        )

        # 获取已安装技能列表
        installed_skills = importer.list_installed()
        installed_ids = {item["skill_id"] for item in installed_skills}

        total = len(skills)
        # 转换为API格式并分页切片
        result = []
        for skill in skills[offset : offset + limit]:
            installed = skill.skill_id in installed_ids
            result.append(_convert_market_skill_to_api(skill, installed))

        if with_total:
            return {"items": result, "total": total}
        return result

    except Exception as e:
        logger.exception("Failed to get marketplace skills: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get marketplace skills: {str(e)}"
        )


@router.get("/skills/{skill_id}", response_model=MarketplaceSkill)
async def get_marketplace_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取市场技能详情 — 登录用户可读"""
    try:
        if get_market_importer is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Market importer service not available"
            )

        # 获取市场导入器
        importer = get_market_importer()

        # 精确匹配: 直接查 catalog(stop-words/子串匹配会漏 uuid 形 id),
        # 找不到再回退模糊搜索(兼容旧行为)
        target_skill = None
        try:
            from neurova.skills.market_store import get_market_store

            entry = get_market_store().get(skill_id)
            if entry:
                target_skill = MarketSkill(
                    skill_id=entry.get("skill_id", ""),
                    name=entry.get("name", entry.get("skill_id", "")),
                    version=entry.get("version", "1.0.0"),
                    description=entry.get("description", ""),
                    author=entry.get("author", ""),
                    download_url=entry.get("download_url", ""),
                    category=entry.get("category", "general"),
                    tags=list(entry.get("tags") or []),
                    rating=float(entry.get("rating", 0.0)),
                    downloads=int(entry.get("downloads", 0)),
                    updated_at=entry.get("updated_at"),
                    source=entry.get("source", "local"),
                )
        except Exception:
            logger.warning("market store lookup failed, fallback to search", exc_info=True)

        if not target_skill:
            # 搜索技能（使用skill_id作为查询）
            skills = importer.search_skills(query=skill_id)

            # 查找匹配的技能
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found")

        # 检查是否已安装
        installed_skills = importer.list_installed()
        installed_ids = {item["skill_id"] for item in installed_skills}
        installed = target_skill.skill_id in installed_ids

        return _convert_market_skill_to_api(target_skill, installed)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get skill details: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get skill details: {str(e)}"
        )


@router.post("/skills/{skill_id}/install")
async def install_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
    body: SkillInstallRequest = SkillInstallRequest(),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """安装技能 — 登录用户可操作"""
    request_id = _get_request_id(request)

    try:
        if get_market_importer is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Market importer service not available"
            )

        # 获取市场导入器
        importer = get_market_importer()

        # 精确匹配再模糊回退(与详情端点一致; catalog 为唯一数据源)
        target_skill = None
        try:
            from neurova.skills.market_store import get_market_store
            from neurova.skills.market_importer import MarketSkill as _MS

            entry = get_market_store().get(skill_id)
            if entry:
                target_skill = _MS(
                    skill_id=entry.get("skill_id", ""),
                    name=entry.get("name", entry.get("skill_id", "")),
                    version=entry.get("version", "1.0.0"),
                    description=entry.get("description", ""),
                    author=entry.get("author", ""),
                    download_url=entry.get("download_url", ""),
                    category=entry.get("category", "general"),
                    tags=list(entry.get("tags") or []),
                    rating=float(entry.get("rating", 0.0)),
                    downloads=int(entry.get("downloads", 0)),
                    updated_at=entry.get("updated_at"),
                    source=entry.get("source", "local"),
                )
        except Exception:
            logger.warning("market store lookup failed, fallback to search", exc_info=True)

        if not target_skill:
            # 先搜索技能获取下载URL
            skills = importer.search_skills(query=skill_id)
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
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found in marketplace"
            )

        # 检查是否已安装
        installed_skills = importer.list_installed()
        installed_ids = {item["skill_id"] for item in installed_skills}

        if target_skill.skill_id in installed_ids:
            if not body.force:
                # 幂等补链: 旧版本安装未注册进 agent 技能页/工具集, 补一次联邦注册
                from neurova.skills.market_registry import link_market_skill_to_agent
                from neurova.skills.skill_service import SkillService

                link_market_skill_to_agent(
                    skill_id=target_skill.skill_id,
                    name=target_skill.name,
                    description=target_skill.description,
                    version=target_skill.version,
                    service=SkillService(agent_id="default"),
                    registry=_default_skill_registry(),
                    extra_registries=_running_agent_registries(),
                    market_skills_dir=importer._skills_dir,
                )
                return {
                    "code": 0,
                    "message": f"Skill '{skill_id}' is already installed",
                    "data": {"skill_id": target_skill.skill_id, "already_installed": True},
                    "request_id": request_id,
                }
            logger.info("force reinstall skill '%s'", skill_id)

        # 安装技能
        task = importer.import_skill(
            skill_id=target_skill.skill_id,
            version=body.version,
            force=bool(body.force),
        )

        # 检查导入状态
        if ImportStatus and task.status == ImportStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to install skill '{skill_id}': {task.error_message}",
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

        # 联邦注册: agent 技能页(manifest) + 工具注册表(可执行) 同时打通
        from neurova.skills.market_registry import link_market_skill_to_agent
        from neurova.skills.skill_service import SkillService

        link_market_skill_to_agent(
            skill_id=target_skill.skill_id,
            name=target_skill.name,
            description=target_skill.description,
            version=target_skill.version,
            service=SkillService(agent_id="default"),
            registry=_default_skill_registry(),
            extra_registries=_running_agent_registries(),
            market_skills_dir=importer._skills_dir,
        )

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
        logger.exception("Failed to install skill: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to install skill: {str(e)}"
        )


@router.delete("/skills/{skill_id}/install")
async def uninstall_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """卸载技能 — 登录用户可操作"""
    request_id = _get_request_id(request)

    try:
        if get_market_importer is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Market importer service not available"
            )

        # 获取市场导入器
        importer = get_market_importer()

        # 检查技能是否已安装
        installed_skills = importer.list_installed()
        installed_ids = {item["skill_id"] for item in installed_skills}

        if skill_id not in installed_ids:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' is not installed")

        # 卸载技能
        success = importer.uninstall_skill(skill_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to uninstall skill '{skill_id}'"
            )

        # 联邦注销: agent 技能页 + 工具注册表(全局+运行中 Agent) 同步移除
        from neurova.skills.market_registry import unlink_market_skill_from_agent
        from neurova.skills.skill_service import SkillService

        unlink_market_skill_from_agent(
            skill_id,
            service=SkillService(agent_id="default"),
            registry=_default_skill_registry(),
        )
        for reg in _running_agent_registries():
            reg.unregister(skill_id)

        return {
            "code": 0,
            "message": f"Skill '{skill_id}' uninstalled successfully",
            "data": {"skill_id": skill_id},
            "request_id": request_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to uninstall skill: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to uninstall skill: {str(e)}"
        )


@router.get("/installed", response_model=List[MarketplaceSkill])
async def get_installed_skills(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取已安装技能 — 登录用户可读"""
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
        logger.exception("Failed to get installed skills: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get installed skills: {str(e)}"
        )


# ---------------------------------------------------------------------------
# 市场管理端点（仅管理员）：上架 / 更新版本(站内通知) / 下架
# ---------------------------------------------------------------------------


def _notify_market_update(entry: Dict[str, Any], old_version: str) -> int:
    """版本变更站内通知: 优先所有注册用户, 兜底 default。

    通知类型 market_update; data 携带 skill_id/latest_version 供前端
    "市场界面更新提示"读取。
    """
    from neurova.api.endpoints.notifications import get_notification_manager

    manager = get_notification_manager()
    name = entry.get("name") or entry.get("skill_id", "")
    target_ids: List[str] = []
    try:
        from neurova.api.endpoints.enhanced_users_api import _users_store

        target_ids = [str(uid) for uid in (_users_store or {}).keys()]
    except Exception as e:  # noqa: BLE001
        logger.warning("enumerate users for market notify failed: %s", e)
    if not target_ids:
        target_ids = ["default"]
    title = f"市场技能更新: {name}"
    message = f"「{name}」已更新到 v{entry.get('version')} (v{old_version} → v{entry.get('version')})"
    for uid in target_ids:
        manager.add_notification(
            user_id=uid,
            title=title,
            message=message,
            notification_type="market_update",
            data={
                "skill_id": entry.get("skill_id", ""),
                "latest_version": entry.get("version"),
                "name": name,
            },
        )
    logger.info("market skill %s update notified to %d user(s)", entry.get("skill_id"), len(target_ids))
    return len(target_ids)


@router.post("/skills")
async def create_market_skill(
    body: MarketplaceSkillCreate,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """上架市场技能 — 仅管理员"""
    try:
        from neurova.skills.market_store import get_market_store

        store = get_market_store()
        try:
            entry = store.create(body.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        return {
            "code": 0,
            "message": f"Skill '{body.skill_id}' published",
            "data": entry,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to create market skill: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to publish skill: {str(e)}"
        )


@router.put("/skills/{skill_id}")
async def update_market_skill(
    skill_id: str = Path(..., description="技能ID"),
    body: MarketplaceSkillUpdate = MarketplaceSkillUpdate(),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新技能(元数据/版本) — 仅管理员; 版本变更时向用户推送市场更新通知"""
    try:
        from neurova.skills.market_store import get_market_store

        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        store = get_market_store()
        before = store.get(skill_id) or {}
        result = store.update(skill_id, patch)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found")
        if result["version_changed"]:
            _notify_market_update(result["entry"], old_version=str(before.get("version", "?")))
        return {
            "code": 0,
            "message": f"Skill '{skill_id}' updated",
            "data": result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update market skill: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update skill: {str(e)}"
        )


@router.delete("/skills/{skill_id}")
async def delete_market_skill(
    skill_id: str = Path(..., description="技能ID"),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """下架市场技能 — 仅管理员"""
    try:
        from neurova.skills.market_store import get_market_store

        removed = get_market_store().remove(skill_id)
        if not removed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found")
        return {
            "code": 0,
            "message": f"Skill '{skill_id}' removed from marketplace",
            "data": {"skill_id": skill_id},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete market skill: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove skill: {str(e)}"
        )


@router.post("/sync")
async def sync_market_sources(
    source: str = Query(default="all", description="远端市场源: aliyun / xfyun / all"),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """同步远端市场源条目到本地 Catalog — 仅管理员

    数据流: 远端列表 API → 映射为带 source 标记的 catalog entry → upsert 进
    MarketStore。浏览/搜索/安装/联邦注册复用既有链路；admin 本地改动字段
    (rating 等) 不被远端覆盖。上游失败降级为 errors 计数不阻断其他源。
    """
    try:
        from neurova.skills import market_sources
        from neurova.skills.market_store import get_market_store

        if source == "all":
            keys = [s.key for s in market_sources.list_sources()]
        else:
            try:
                market_sources.get_source(source)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown source '{source}'. available: aliyun, xfyun, all",
                )
            keys = [source]

        store = get_market_store()
        results = [market_sources.sync_source(key, store) for key in keys]
        totals = {
            "created": sum(r["created"] for r in results),
            "updated": sum(r["updated"] for r in results),
            "removed": sum(r["removed"] for r in results),
            "errors": sum(r["errors"] for r in results),
        }
        return {
            "code": 0,
            "message": f"Synced {len(keys)} source(s): +{totals['created']} ~{totals['updated']} -{totals['removed']}",
            "data": {"results": results, "totals": totals},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to sync market sources: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to sync market sources: {str(e)}"
        )
