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
    # P0-4/P2-15 声明面透传（前端徽标数据源）：条目带声明元数据时回传，
    # 无声明（远端源目录条目常态）为 None，前端不显示徽标
    permissions: Optional[Dict[str, Any]] = None
    sandbox_required: Optional[bool] = None


class SkillInstallRequest(BaseModel):
    """安装技能请求"""

    version: Optional[str] = None
    config: Dict[str, Any] = {}
    force: Optional[bool] = None
    # 目标 Agent（联邦注册落盘目标；缺省 default，兼容旧 /skill-pool 请求体）
    agent_id: Optional[str] = None


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


class MarketplaceSkillSubmit(BaseModel):
    """用户提交技能上架申请（进入待审，管理员审批后上架）

    Wave H-W3：kind=update 支持对已上架技能提交升级版本（版本号必须递增），
    不再恒 409 撞库。
    """

    skill_id: str = Field(..., description="市场技能 ID")
    name: str = Field(..., description="技能名称")
    description: str = ""
    version: str = "1.0.0"
    category: str = "general"
    tags: List[str] = []
    download_url: str = ""
    author: str = ""
    kind: str = Field(default="create", description="create=新上架 / update=升级已上架技能")
    # 闭环核验轮 V：用户私库技能发布公共库时携带源库条目 ID——materialize
    # 从该条目快照 tool_sequence/permissions 载荷进公共库（否则需求 3 的
    # "用户库→公共库"会丢失可执行体，公共副本退化为元目目录条目）。
    pool_skill_id: str = Field(default="", description="来源用户私库技能 ID（可空）")


class SkillSubmissionReview(BaseModel):
    """技能提交审批请求（仅管理员）"""

    approve: bool
    note: str = ""


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
        permissions=getattr(skill, "permissions", None),
        sandbox_required=getattr(skill, "sandbox_required", None),
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
                    service=SkillService(agent_id=body.agent_id or "default"),
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
            service=SkillService(agent_id=body.agent_id or "default"),
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
    agent_id: str = Query(default="default", description="目标 Agent ID（联邦注销落盘目标）"),
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
            service=SkillService(agent_id=agent_id),
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


def _broadcast_public_upgrade(skill_id: str, version: str, name: str) -> int:
    """Wave H-W4（需求 5）：公共库技能升级 → 向持有派生副本的用户/agent 私库
    广播**确认型**升级卡（skill_transfers），副本迭代权在归属人。

    扫描三库目录找 `config.transferred_from.pool == public` 且 skill_id 匹配的
    条目；agent 库副本的确认人=其属主账号（agent_config.json.owner_user_id），
    无属主回退 admin。幂等键保证同一版本只一张 pending 卡。失败仅告警。
    """
    created = 0
    try:
        import json as _json

        from neurova.skills import library_service as _lib
        from neurova.skills.skill_transfers import (
            TT_PUBLIC_TO_AGENT,
            TT_PUBLIC_TO_USER,
            get_skill_transfer_store,
        )

        base = _lib._BASE_DIR
        targets = []  # (pool, owner_dir_token, confirm_owner, entry)
        for pool, sub, resolver in (
            (_lib.POOL_USER, "users", _lib.from_dir_token),
            (_lib.POOL_AGENT, "agents", None),
        ):
            root = base / sub
            if not root.exists():
                continue
            for d in root.iterdir():
                mf = d / "skills" / "manifest.json"
                if not d.is_dir() or not mf.exists():
                    continue
                try:
                    entries = _json.loads(mf.read_text(encoding="utf-8"))
                except Exception:
                    continue
                row = entries.get(skill_id) if isinstance(entries, dict) else None
                if not row:
                    continue
                tf = ((row.get("manifest") or {}).get("config") or {}).get("transferred_from") or {}
                if tf.get("pool") != _lib.POOL_PUBLIC or str(tf.get("skill_id") or "") != skill_id:
                    continue
                owner_key = resolver(d.name) if resolver else d.name
                if pool == "user":
                    confirm = owner_key  # u:7
                else:
                    acfg = d / "agent_config.json"
                    acct = ""
                    try:
                        if acfg.exists():
                            acct = str(_json.loads(acfg.read_text(encoding="utf-8")).get("owner_user_id") or "")
                    except Exception:
                        acct = ""
                    confirm = f"u:{acct}" if acct else "admin"
                targets.append((pool, owner_key, confirm, row))

        store = get_skill_transfer_store()
        for pool, owner_key, confirm, row in targets:
            cur_ver = str(row.get("version") or "")
            try:
                from neurova.api.endpoints.skill_version_api import compare_versions

                if cur_ver and compare_versions(str(version), cur_ver) <= 0:
                    continue  # 副本不比公共版新才推
            except Exception:
                pass
            ttype = TT_PUBLIC_TO_USER if pool == "user" else TT_PUBLIC_TO_AGENT
            entry = store.create(
                {
                    "transfer_type": ttype,
                    "skill_id": skill_id,
                    "src_pool": _lib.POOL_PUBLIC,
                    "src_owner": "",
                    "dst_pool": pool,
                    "dst_owner": owner_key,
                    "confirm_owner": confirm,
                    "kind": "upgrade",
                    "version": str(version or ""),
                    "name": str(name or skill_id),
                    "transfer_key": f"{ttype}:public->{pool}:{owner_key}:{skill_id}@{version}",
                }
            )
            created += 1
            if str(confirm or "").startswith("u:"):
                try:
                    from neurova.api.endpoints.notifications import notify_user

                    notify_user(
                        confirm.split(":", 1)[1],
                        title="公共技能升级待确认",
                        message=f"公共库技能「{name or skill_id}」升级到 v{version}，确认后将同步你的副本",
                        notification_type="skill_transfer",
                        data={
                            "transfer_id": entry["transfer_id"],
                            "skill_id": skill_id,
                            "action": "skill_transfer",
                        },
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("升级广播通知失败（不阻断）", exc_info=True)
    except Exception:  # noqa: BLE001 - 广播失败不阻断审批物化
        logger.warning("公共库升级广播失败（skill=%s）", skill_id, exc_info=True)
    return created


def _materialize_public_entry(submission: Dict[str, Any], kind: str) -> None:
    """Wave H-W3：审批通过后把社区技能物化进公共库 manifest。

    公共库（library_service pool=public）是轮级装配视图的第三层来源。
    create=登记（pool_type=public、source=community）；update=**原地版本
    bump**（update_auto_skill 语义：修订链追加 + trust/usage 账本保留——
    不走 install_skill 重建，绕开 force 重装清零坑）。失败仅告警不阻断
    审批（catalog 仍为市场权威面）。
    """
    try:
        from neurova.skills import library_service as _lib

        pub = _lib.get_library(_lib.POOL_PUBLIC)
        sid = str(submission.get("skill_id") or "")
        if not sid:
            return
        version = str(submission.get("version") or "1.0.0")
        fields = {
            "name": str(submission.get("name") or sid),
            "description": str(submission.get("description") or ""),
            "category": str(submission.get("category") or "general"),
            "tags": list(submission.get("tags") or []),
            "download_url": str(submission.get("download_url") or ""),
        }
        # V 轮：随单可执行载荷快照透传（用户私库来源提交的 tool_sequence/permissions）
        payload_cfg = submission.get("config") or {}
        _carry = {k: payload_cfg[k] for k in ("tool_sequence", "permissions") if payload_cfg.get(k)}
        existing = pub.get_skill_info(sid)
        if existing is None:
            pub.register_auto_skill(
                sid,
                name=fields["name"],
                description=fields["description"],
                version=version,
                config={
                    "category": fields["category"],
                    "tags": fields["tags"],
                    "download_url": fields["download_url"],
                    **_carry,
                },
                manifest_source="community",
                pool_type=_lib.POOL_PUBLIC,
                owner_user_id="",
            )
        else:
            cfg = dict((existing.get("manifest") or {}).get("config") or {})
            cfg.update(
                {
                    "category": fields["category"],
                    "tags": fields["tags"],
                    "download_url": fields["download_url"],
                    "submitted_by": str(submission.get("submitted_by") or ""),
                    **_carry,
                }
            )
            pub.update_auto_skill(
                sid,
                version=version,
                config=cfg,
                name=fields["name"],
                description=fields["description"],
            )
            # Wave H-W4：公共升级 → 派生副本确认卡（需求 5，"用户确认升级后迭代"）
            _broadcast_public_upgrade(sid, version, fields["name"])
    except Exception:  # noqa: BLE001 - 物化失败不阻断审批主链
        logger.warning("公共库物化失败（skill=%s）", submission.get("skill_id"), exc_info=True)


def _notify_market_update(entry: Dict[str, Any], old_version: str) -> int:
    """版本变更站内通知: 优先所有注册用户, 兜底 default。

    通知类型 market_update; data 携带 skill_id/latest_version 供前端
    "市场界面更新提示"读取。
    """
    from neurova.api.endpoints.notifications import notify_all_users

    name = entry.get("name") or entry.get("skill_id", "")
    count = notify_all_users(
        title=f"市场技能更新: {name}",
        message=f"「{name}」已更新到 v{entry.get('version')} (v{old_version} → v{entry.get('version')})",
        notification_type="market_update",
        data={
            "skill_id": entry.get("skill_id", ""),
            "latest_version": entry.get("version"),
            "name": name,
        },
    )
    logger.info("market skill %s update notified to %d user(s)", entry.get("skill_id"), count)
    return count


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


@router.post("/skills/submit")
async def submit_market_skill(
    body: MarketplaceSkillSubmit,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """用户提交技能上架申请（登录用户）：进入待审批并通知管理员审核

    提交存独立存储（submissions.json），审批通过才写入市场目录。
    """
    try:
        from neurova.api.endpoints.notifications import notify_admins
        from neurova.skills.market_store import get_market_store
        from neurova.skills.market_submissions import get_market_submission_store

        store = get_market_store()
        # Wave H-W3 升级提交单型：kind=update 对已上架技能提新版本（不再恒
        # 409），版本号必须严格高于当前上架版；kind=create 撞库护栏不变。
        kind = str(getattr(body, "kind", "create") or "create").strip().lower()
        if kind not in ("create", "update"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"未知提交类型 kind={kind!r}（支持 create/update）",
            )
        existing_entry = store.get(body.skill_id)
        if kind == "update":
            if existing_entry is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill '{body.skill_id}' not found in marketplace（升级目标须已上架）",
                )
            from neurova.api.endpoints.skill_version_api import compare_versions

            if compare_versions(
                str(body.version or "1.0.0"), str(existing_entry.get("version") or "0.0.0")
            ) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"升级版本必须高于当前上架版 {existing_entry.get('version')}",
                )
        elif existing_entry is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Skill '{body.skill_id}' already exists in marketplace",
            )

        # V 轮：来源=本人用户私库条目 → 服务端快照可执行载荷（白名单键，
        # 不信任前端回传；materialize 落公共库时透传，需求 3 全链保可执行）。
        # 必须在证据门**之前**：名称/描述以库内条目为权威覆写，门扫最终文本。
        snapshot_cfg: Dict[str, Any] = {}
        pool_sid = str(getattr(body, "pool_skill_id", "") or "").strip()
        if pool_sid:
            from neurova.skills import library_service as _lib

            acct = f"u:{current_user.get('user_id') or ''}"
            try:
                src = _lib.get_library(_lib.POOL_USER, acct).get_skill_info(pool_sid)
            except ValueError as bad:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(bad))
            if src is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"用户私库无此技能: {pool_sid}",
                )
            _src_cfg = (src.get("manifest") or {}).get("config") or {}
            snapshot_cfg = {
                k: _src_cfg[k]
                for k in ("tool_sequence", "permissions")
                if k in _src_cfg
            }
            body.name = str(src.get("name") or body.name)
            body.description = str(src.get("description") or body.description)
            body.version = str(src.get("version") or body.version)

        # P2-1 提交证据门：文本注入扫描 +
        # 密钥脱敏 + 本地同源 provisional 拒上架。人工 admin 审批保留，二者
        # 叠加=机器拦底、人裁质量。
        from neurova.skills.skill_install_gate import evaluate_submission_gate

        local_trust_state = None
        try:
            from neurova.skills.skill_service import SkillService

            info = SkillService(agent_id="default").get_skill_info(body.skill_id) or {}
            local_trust_state = ((info.get("identity") or {}).get("trust") or {}).get("state")
        except Exception:  # noqa: BLE001 - 本地查不到=纯市场申请，交文本门
            pass
        verdict = evaluate_submission_gate(
            {
                "skill_id": body.skill_id,
                "name": body.name,
                "description": body.description,
                "category": body.category,
                "tags": " ".join(body.tags or []),
                "download_url": body.download_url or "",
                "author": body.author or "",
            },
            local_trust_state,
        )
        if verdict["blocked"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="；".join(verdict["errors"]) or "提交内容未过证据门",
            )

        submissions = get_market_submission_store()
        if any(
            s.get("skill_id") == body.skill_id and s.get("status") == "pending"
            for s in submissions.list_all("pending")
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Skill '{body.skill_id}' already has a pending submission",
            )

        entry = submissions.create(
            {
                "skill_id": body.skill_id,
                "name": body.name,
                "description": body.description,
                "version": body.version,
                "category": body.category,
                "tags": body.tags,
                "download_url": body.download_url,
                "author": body.author or str(current_user.get("username", "")),
                "submitted_by": str(current_user.get("user_id", "")),
                "submitted_by_name": str(current_user.get("username", "")),
                # Wave H-W3：升级提交单型随单存档（review 分流依据）
                "kind": kind,
                # V 轮：可执行载荷快照（无则空 dict，物化侧按键透传）
                "config": snapshot_cfg,
            }
        )

        notify_admins(
            title="技能提交待审核",
            message=(
                f"用户 {current_user.get('username', '')} 提交技能「{body.name}」"
                f"(v{body.version}) 申请上架，等待审核"
            ),
            notification_type="skill_review",
            data={"skill_id": body.skill_id, "submission_id": entry["id"], "name": body.name},
        )
        return {
            "code": 0,
            "message": f"Skill '{body.skill_id}' submitted for review",
            "data": entry,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to submit market skill: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to submit skill: {str(e)}"
        )


@router.get("/skill-submissions")
async def list_skill_submissions(
    review_status: str = Query(default="pending", description="筛选状态: pending/approved/rejected/all"),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """提交审批列表（仅管理员）"""
    try:
        from neurova.skills.market_submissions import get_market_submission_store

        status_filter = None if review_status == "all" else review_status
        items = get_market_submission_store().list_all(status_filter)
        return {"code": 0, "message": "success", "data": {"items": items, "total": len(items)}}
    except Exception as e:
        logger.exception("Failed to list skill submissions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list skill submissions: {str(e)}",
        )


@router.post("/skill-submissions/{submission_id}/review")
async def review_skill_submission(
    submission_id: str,
    body: SkillSubmissionReview,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """审批技能提交（仅管理员）：approve→写入市场目录；reject→不上架。

    审批结果回执提交者。
    """
    try:
        from neurova.api.endpoints.notifications import notify_user
        from neurova.skills.market_submissions import get_market_submission_store
        from neurova.skills.market_store import get_market_store

        submissions = get_market_submission_store()
        submission = submissions.get(submission_id)
        if not submission:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Submission '{submission_id}' not found",
            )
        if submission.get("status") != "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Submission '{submission_id}' already reviewed",
            )

        reviewed_by = str(admin.get("user_id", ""))
        if body.approve:
            market = get_market_store()
            kind = str(submission.get("kind") or "create")
            entry_payload = {
                "skill_id": submission["skill_id"],
                "name": submission.get("name", ""),
                "description": submission.get("description", ""),
                "version": submission.get("version", "1.0.0"),
                "category": submission.get("category", "general"),
                "tags": submission.get("tags", []),
                "download_url": submission.get("download_url", ""),
                "author": submission.get("author", ""),
                "source": "community",
                # 孤岛吸收 #归属：catalog 带提交者，公共库可回溯"这是谁上架的"
                "owner_user_id": str(submission.get("submitted_by") or ""),
            }
            if kind == "update":
                result = market.update(submission["skill_id"], entry_payload)
                if result is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Skill '{submission['skill_id']}' vanished before approval",
                    )
                if result.get("version_changed"):
                    _notify_market_update(result["entry"], old_version=str(
                        (submission.get("version") or "?")))
            else:
                if market.get(submission["skill_id"]) is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Skill '{submission['skill_id']}' already exists in marketplace",
                    )
                market.create(entry_payload)

            # Wave H-W3 公共库物化：装配视图第三层的真实来源（update 走原地
            # 合并保账本；create 登记）。失败不阻断审批（catalog 已是权威面）。
            _materialize_public_entry(submission, kind)

        result = submissions.set_status(
            submission_id,
            "approved" if body.approve else "rejected",
            reviewed_by=reviewed_by,
            note=body.note,
        )

        submitter = str(submission.get("submitted_by") or "")
        if submitter:
            name = submission.get("name", "")
            if body.approve:
                msg = f"你提交的技能「{name}」已通过审核并上架市场"
            else:
                msg = f"你提交的技能「{name}」未通过审核" + (f"：{body.note}" if body.note else "")
            notify_user(
                submitter,
                title="技能审核结果",
                message=msg,
                notification_type="skill_review_result",
                data={
                    "skill_id": submission.get("skill_id", ""),
                    "submission_id": submission_id,
                    "approve": bool(body.approve),
                },
            )
        return {"code": 0, "message": "reviewed", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to review skill submission: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to review skill submission: {str(e)}",
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
