"""
技能池管理 API

提供以下端点:
- GET    /v1/skill-pool/public                   公共技能列表
- GET    /v1/skill-pool/public/{skill_id}        公共技能详情
- POST   /v1/skill-pool/public/{skill_id}/install 安装公共技能
- GET    /v1/skill-pool/private                  专属技能列表
- POST   /v1/skill-pool/private                  创建专属技能
- PUT    /v1/skill-pool/private/{skill_id}       更新专属技能
- DELETE /v1/skill-pool/private/{skill_id}       删除专属技能
- POST   /v1/skill-pool/private/{skill_id}/share 共享技能
- POST   /v1/skill-pool/private/{skill_id}/push  推送给Agent
- DELETE /v1/skill-pool/private/{skill_id}/push  取消推送
- GET    /v1/skill-pool/agent/{agent_id}/skills  Agent技能列表
- GET    /v1/skill-pool/me/skills                我的用户私库列表（Wave V）
- POST   /v1/skill-pool/me/skills                用户私库创建
- PUT    /v1/skill-pool/me/skills/{skill_id}     用户私库更新
- DELETE /v1/skill-pool/me/skills/{skill_id}     用户私库删除
- POST   /v1/skill-pool/me/skills/{id}/from-public 公共库自助安装到私库
- POST   /v1/skill-pool/transfers                发起 agent→user 流转提案
- GET    /v1/skill-pool/transfers                确认队列
- POST   /v1/skill-pool/transfers/{id}/accept    确认流转
- POST   /v1/skill-pool/transfers/{id}/reject    拒绝流转
"""

from neurova.core.logger import get_logger
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin
from neurova.skills.library_service import POOL_AGENT, POOL_PUBLIC, POOL_USER
from neurova.skills.skill_service import SkillService
from neurova.api.endpoints.marketplace import (
    MarketplaceSkillSubmit,
    SkillSubmissionReview,
    list_skill_submissions,
    review_skill_submission,
    submit_market_skill,
)
from neurova.api.endpoints._pydantic_compat import safe_model_dump

logger = get_logger(__name__)

# Wave F（2026-09-15 基线巡检存量债收口）：router 级登录鉴权——此前 /private
# CRUD、install-from-*、pending 审批面、agent/{id}/skills 全部裸奔，query
# agent_id 被当所有权凭据，任何未认证请求可读写他人 agent 技能。对齐
# /v1/agents 资源先例（登录即可操作，agent 是登录用户共享的运行时资产；
# 不建 agent-user 归属表）。admin-only 的提交审核面自带 require_admin 叠加。
router = APIRouter(dependencies=[Depends(get_current_user)])


class SkillInfo(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    scope: str = "public"
    owner_id: str = ""
    enabled: bool = True
    created_at: float = 0
    updated_at: float = 0
    # Wave F：共享标志（落 manifest config.shared，列表回显供前端徽标）
    shared: bool = False
    # 生命周期与用量（前端状态徽标数据源；C11 遥测延伸）
    usage: Dict[str, Any] = Field(default_factory=dict)


class SkillCreate(BaseModel):
    name: str = Field(..., description="技能名称")
    description: str = Field(default="", description="描述")
    category: str = Field(default="general", description="分类")
    config: Dict[str, Any] = Field(default_factory=dict, description="技能配置")


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    # 闭环核验轮 V5：行级启停（消费方 call_skill/注册表读条目 enabled，
    # 旧前端把开关塞进 config.enabled 是静默空操作——本字段为唯一真通道）
    enabled: Optional[bool] = None


class SkillShare(BaseModel):
    target_user_id: str = Field(default="", description="目标用户 ID（可空=公开共享标记）")


class SkillPush(BaseModel):
    agent_id: str = Field(default="default", description="Agent ID")


# Wave H-W3：原 `_public_skills` 僵尸内存 dict（无人填充、恒空）随 /public
# 端点真人化删除——公共库唯一事实源=library_service pool=public manifest。
# s8: RLock 保留给模块内其余共享态防护（测试契约依赖其存在且可重入）。
_lock = threading.RLock()


def _pool_service(agent_id: str) -> SkillService:
    """private 链统一服务入口。

    Wave V 单源化：经 library_service.get_library("agent", …) 取**同进程单例**
    ——端点读写与 transfers 落库/轮级 flush（同样走 get_library）共用实例，
    消解跨实例 manifest 内存态互踩（孤岛吸收纪律）。
    （延迟解析保持：测试 monkeypatch skill_service.SkillService 类或本函数
    皆可生效。）
    """
    from neurova.skills import library_service as _lib

    return _lib.get_library(POOL_AGENT, agent_id)


# s5: 已删除 _get_spm() (死代码, 零调用方)。SkillPoolManager 孤岛本体亦于
# 2026-09-15 整模块退役（三层技能库设计吸收其 pool_type/owner 词汇，
#）；private 链唯一事实源=SkillService。


@router.get("/public", response_model=List[SkillInfo])
async def list_public_skills(category: Optional[str] = Query(default=None)):
    """列出公共技能 —— Wave H-W3 真人化：读公共库 manifest（library_service
    pool=public，approve 物化链写入），原 `_public_skills` 僵尸 dict 退位。"""
    from neurova.skills import library_service as _lib

    rows: List[SkillInfo] = []
    try:
        for sid, info in _lib.get_library(POOL_PUBLIC).iter_skills():
            if not info.get("enabled", True):
                continue
            manifest = info.get("manifest") or {}
            cfg = manifest.get("config") or {}
            cat = str(cfg.get("category") or "general")
            if category and cat != category:
                continue
            rows.append(
                SkillInfo(
                    skill_id=sid,
                    name=str(info.get("name") or sid),
                    description=str(info.get("description") or ""),
                    version=str(info.get("version") or "1.0.0"),
                    category=cat,
                    scope="public",
                    owner_id="",
                    enabled=True,
                    usage=info.get("usage") or {},
                )
            )
    except Exception as e:
        logger.exception("list_public_skills 读公共库失败: %s", e)
    return rows


@router.get("/public/{skill_id}", response_model=SkillInfo)
async def get_public_skill(skill_id: str):
    """获取公共技能详情（公共库 manifest 单源）"""
    from neurova.skills import library_service as _lib

    info = None
    try:
        info = _lib.get_library(POOL_PUBLIC).get_skill_info(skill_id)
    except Exception as e:
        logger.exception("get_public_skill 读公共库失败 %s: %s", skill_id, e)
    if not info:
        raise HTTPException(status_code=404, detail="Skill not found")
    cfg = (info.get("manifest") or {}).get("config") or {}
    return SkillInfo(
        skill_id=skill_id,
        name=str(info.get("name") or skill_id),
        description=str(info.get("description") or ""),
        version=str(info.get("version") or "1.0.0"),
        category=str(cfg.get("category") or "general"),
        scope="public",
        owner_id="",
        enabled=bool(info.get("enabled", True)),
        usage=info.get("usage") or {},
    )


@router.post("/public/{skill_id}/install")
@router.post("/{skill_id}/install")
async def install_public_skill(
    request: Request,
    skill_id: str,
    agent_id: str = Query(default="default"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """安装公共技能 — ADR 0013: 委托 marketplace canonical 安装链。

    修复 (2026-09-09): 原实现查无人填充的内存 dict _public_skills（僵尸），
    前端 SkillMarketPage/AgentSkillPage/SkillPoolPage 安装恒 404（调用的
    /{skill_id}/install 路由此前根本不存在）。现统一走 catalog → 下载导入
    → 联邦注册（技能页 manifest + 工具注册表）真实链路，agent_id 透传。
    """
    from neurova.api.endpoints.marketplace import SkillInstallRequest, install_skill

    return await install_skill(request, skill_id, SkillInstallRequest(agent_id=agent_id), current_user)


@router.get("/private", response_model=List[SkillInfo])
async def list_private_skills(agent_id: str = Query(default="default")):
    """列出专属技能——Wave F 起单源：SkillService manifest（磁盘持久）。

    历史（s2 修复曾聚合两源治 split-brain）记录于本模块头部；Wave F 把
    create 侧也落到磁盘后聚合逻辑删除——单源不存在漂移。s4 参数名对齐
    前端 ?agent_id=xxx 契约保持不变。
    """
    result: List[SkillInfo] = []
    try:
        service = _pool_service(agent_id)
        for sid, info in service.iter_skills():
            manifest = info.get("manifest") or {}
            cfg = manifest.get("config") or {}
            result.append(
                SkillInfo(
                    skill_id=sid,
                    name=str(info.get("name") or sid),
                    description=str(info.get("description") or ""),
                    version=str(info.get("version") or "1.0.0"),
                    enabled=bool(info.get("enabled", True)),
                    scope="private",
                    owner_id=agent_id,
                    category=str(cfg.get("category") or "general"),
                    shared=bool(cfg.get("shared")),
                    usage=info.get("usage") or {},
                )
            )
    except Exception as e:
        # 优雅降级：磁盘读失败记录日志返回空（不静默吞）
        logger.exception("list_private_skills failed for agent_id=%s: %s", agent_id, e)
    return result


@router.post("/private", response_model=SkillInfo)
async def create_private_skill(body: SkillCreate, agent_id: str = Query(default="default")):
    """创建专属技能——Wave F 落盘化（原内存 dict 重启即丢）。

    manifest 条目 source 走 register_auto_skill 通道（origin auto），但归属
    视图按 agent_id 隔离；config 携带用户侧 category/description 语义。
    """
    sid = str(uuid.uuid4())[:8]
    now = time.time()
    service = _pool_service(agent_id)
    ok = service.register_auto_skill(
        sid,
        name=body.name,
        description=body.description,
        config={**(body.config or {}), "category": body.category},
        manifest_source="user",
    )
    if not ok:
        raise HTTPException(status_code=409, detail="技能创建失败（同名或存储故障）")
    return SkillInfo(
        skill_id=sid,
        name=body.name,
        description=body.description,
        category=body.category,
        scope="private",
        owner_id=agent_id,
        enabled=True,
        created_at=now,
        updated_at=now,
    )


@router.put("/private/{skill_id}", response_model=SkillInfo)
async def update_private_skill(skill_id: str, body: SkillUpdate, agent_id: str = Query(default="default")):
    """更新专属技能（磁盘 manifest 单源；跨 agent 视图查无 → 404）。"""
    service = _pool_service(agent_id)
    info = service.get_skill_info(skill_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    patch = safe_model_dump(body, exclude_none=True)
    enabled = patch.pop("enabled", None)
    merged_cfg = dict((info.get("manifest") or {}).get("config") or {})
    if "category" in patch:
        merged_cfg["category"] = patch.pop("category")
    if "config" in patch:
        merged_cfg.update(patch.pop("config") or {})
    ok = service.update_auto_skill(
        skill_id,
        version=None,
        config=merged_cfg or None,
        name=patch.get("name"),
        description=patch.get("description"),
    )
    if not ok:
        raise HTTPException(status_code=500, detail="更新落盘失败")
    # V5 行级启停真通道（config.enabled 从不触发行级 enabled）
    if enabled is not None:
        (service.enable_skill if enabled else service.disable_skill)(skill_id)
    fresh = service.get_skill_info(skill_id) or info
    cfg = (fresh.get("manifest") or {}).get("config") or {}
    return SkillInfo(
        skill_id=skill_id,
        name=str(fresh.get("name") or skill_id),
        description=str(fresh.get("description") or ""),
        version=str(fresh.get("version") or "1.0.0"),
        enabled=bool(fresh.get("enabled", True)),
        scope="private",
        owner_id=agent_id,
        category=str(cfg.get("category") or "general"),
        shared=bool(cfg.get("shared")),
        usage=fresh.get("usage") or {},
    )


@router.delete("/private/{skill_id}")
async def delete_private_skill(skill_id: str, agent_id: str = Query(default="default")):
    """删除专属技能（manifest 条目移除；纯元数据条目无文件可删即仅清账）。"""
    service = _pool_service(agent_id)
    if service.get_skill_info(skill_id) is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    result = service.uninstall_skill(skill_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "删除失败"))
    return {"code": 0, "message": "Skill deleted"}


@router.post("/private/{skill_id}/share")
async def share_private_skill(
    skill_id: str, body: SkillShare = Body(default=SkillShare()), agent_id: str = Query(default="default")
):
    """共享专属技能——Wave F 真实现：config.shared/shared_with 落盘。

    原实现恒返回成功不持久（前端不传 body 时还恒 422）。桌面多用户语义下
    "共享"=池内对该 agent 视图外的成员可见标记，真实分发通道随后续
    多用户需求另立项。
    """
    service = _pool_service(agent_id)
    info = service.get_skill_info(skill_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    cfg = dict((info.get("manifest") or {}).get("config") or {})
    cfg["shared"] = True
    target = str(body.target_user_id or "")
    if target:
        lst = [x for x in (cfg.get("shared_with") or []) if isinstance(x, str)]
        if target not in lst:
            lst.append(target)
        cfg["shared_with"] = lst
    if not service.update_auto_skill(skill_id, config=cfg):
        raise HTTPException(status_code=500, detail="共享状态落盘失败")
    return {"code": 0, "message": f"Skill shared with {target or 'pool members'}"}


@router.post("/private/{skill_id}/push")
async def push_skill_to_agent(skill_id: str, body: SkillPush, agent_id: str = Query(default="default")):
    """推送技能到 Agent——Wave F 真实现：条目复制到目标 agent manifest（幂等）。

    目标视图与源视图相同（前端 pushToPool 即此形态）→ 幂等成功语义：
    "技能已在池视图内"，不再假报跨 agent 推送。
    """
    if not body.agent_id:
        raise HTTPException(status_code=400, detail="目标 agent 无效")
    if body.agent_id == agent_id:
        if _pool_service(agent_id).get_skill_info(skill_id) is None:
            raise HTTPException(status_code=404, detail=f"源技能不存在: {skill_id}")
        return {"code": 0, "message": "Skill already present in target view"}
    src = _pool_service(agent_id).get_skill_info(skill_id)
    if src is None:
        raise HTTPException(status_code=404, detail=f"源技能不存在: {skill_id}")
    dst = _pool_service(body.agent_id)
    if dst.get_skill_info(skill_id) is not None:
        return {"code": 0, "message": f"Skill already pushed to agent '{body.agent_id}'"}
    cfg = dict((src.get("manifest") or {}).get("config") or {})
    if not dst.register_auto_skill(
        skill_id,
        name=str(src.get("name") or skill_id),
        description=str(src.get("description") or ""),
        version=str(src.get("version") or "1.0.0"),
        config=cfg,
        manifest_source=str((src.get("manifest") or {}).get("source") or "user"),
    ):
        raise HTTPException(status_code=500, detail="推送落盘失败")
    return {"code": 0, "message": f"Skill pushed to agent '{body.agent_id}'"}


@router.delete("/private/{skill_id}/push")
async def unpush_skill_from_agent(skill_id: str, agent_id: str = Query(default="default")):
    """取消推送——从指定 agent（query agent_id 即目标）移除条目。"""
    service = _pool_service(agent_id)
    if service.get_skill_info(skill_id) is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    result = service.uninstall_skill(skill_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "取消推送失败"))
    return {"code": 0, "message": f"Skill unpushed from agent '{agent_id}'"}


@router.post("/private/{skill_id}/execute")
async def execute_private_skill(skill_id: str, body: Dict[str, Any] = Body(default_factory=dict)):
    """闭环核验轮 V5：AgentSkillPage 执行按钮此前恒 404（路由缺失，
    前端 executeSkill 调的 POST /private/{id}/execute 后端从未实现）。
    执行走 SkillService.call_skill 咽喉（行级 enabled 闸 + 入口 .py 动态加载）。"""
    agent_id = str(body.get("agent_id") or "default")
    service = _pool_service(agent_id)
    if service.get_skill_info(skill_id) is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    args = body.get("arguments") or {}
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="arguments 须为对象")
    return {"code": 0, "data": service.call_skill(skill_id, **args)}


# ── Wave V 用户私库真人面（三层技能库"我的技能"页签）─────────
# 前端私有页签原调 /private?agent_id=_all——落幽灵桶 data/agents/_all；
# 三层语义下该页签=当前账号用户私库（pool=user、ukey=u:{user_id}）。
# from-public=「市场安装落用户库」定案在本页的自助落地（apply_transfer
# 副本+血缘），不动 marketplace 既有 agent 安装面（其他页语义零变化）。


def _account_key(current_user: Dict[str, Any]) -> str:
    return f"u:{current_user.get('user_id') or ''}"


@router.get("/me/skills", response_model=List[SkillInfo])
async def list_my_skills(current_user: Dict[str, Any] = Depends(get_current_user)):
    """当前账号用户私库列表。"""
    from neurova.skills import library_service as _lib

    acct = _account_key(current_user)
    rows: List[SkillInfo] = []
    try:
        for sid, info in _lib.get_library(POOL_USER, acct).iter_skills():
            manifest = info.get("manifest") or {}
            cfg = manifest.get("config") or {}
            rows.append(
                SkillInfo(
                    skill_id=sid,
                    name=str(info.get("name") or sid),
                    description=str(info.get("description") or ""),
                    version=str(info.get("version") or "1.0.0"),
                    category=str(cfg.get("category") or "general"),
                    scope="user",
                    owner_id=acct,
                    enabled=bool(info.get("enabled", True)),
                    shared=bool(cfg.get("shared")),
                    usage=info.get("usage") or {},
                )
            )
    except Exception as e:
        logger.exception("list_my_skills 读用户库失败: %s", e)
    return rows


@router.post("/me/skills", response_model=SkillInfo)
async def create_my_skill(body: SkillCreate, current_user: Dict[str, Any] = Depends(get_current_user)):
    """用户私库创建技能（uuid8 sid，与 agent 库命名空间天然不撞）。"""
    from neurova.skills import library_service as _lib

    acct = _account_key(current_user)
    sid = str(uuid.uuid4())[:8]
    now = time.time()
    ok = _lib.get_library(POOL_USER, acct).register_auto_skill(
        sid,
        name=body.name,
        description=body.description,
        config={**(body.config or {}), "category": body.category},
        manifest_source="user",
        pool_type="user",
        owner_user_id=acct,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="技能创建失败（同名或存储故障）")
    return SkillInfo(
        skill_id=sid,
        name=body.name,
        description=body.description,
        category=body.category,
        scope="user",
        owner_id=acct,
        enabled=True,
        created_at=now,
        updated_at=now,
    )


@router.put("/me/skills/{skill_id}", response_model=SkillInfo)
async def update_my_skill(
    skill_id: str, body: SkillUpdate, current_user: Dict[str, Any] = Depends(get_current_user)
):
    """用户私库更新（跨账号视图查无 → 404，防枚举同口径）。"""
    from neurova.skills import library_service as _lib

    svc = _lib.get_library(POOL_USER, _account_key(current_user))
    info = svc.get_skill_info(skill_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    patch = safe_model_dump(body, exclude_none=True)
    enabled = patch.pop("enabled", None)
    merged_cfg = dict((info.get("manifest") or {}).get("config") or {})
    if "category" in patch:
        merged_cfg["category"] = patch.pop("category")
    if "config" in patch:
        merged_cfg.update(patch.pop("config") or {})
    ok = svc.update_auto_skill(
        skill_id,
        version=None,
        config=merged_cfg or None,
        name=patch.get("name"),
        description=patch.get("description"),
    )
    if not ok:
        raise HTTPException(status_code=500, detail="更新落盘失败")
    if enabled is not None:
        (svc.enable_skill if enabled else svc.disable_skill)(skill_id)
    fresh = svc.get_skill_info(skill_id) or info
    cfg = (fresh.get("manifest") or {}).get("config") or {}
    return SkillInfo(
        skill_id=skill_id,
        name=str(fresh.get("name") or skill_id),
        description=str(fresh.get("description") or ""),
        version=str(fresh.get("version") or "1.0.0"),
        enabled=bool(fresh.get("enabled", True)),
        scope="user",
        owner_id=_account_key(current_user),
        category=str(cfg.get("category") or "general"),
        shared=bool(cfg.get("shared")),
        usage=fresh.get("usage") or {},
    )


@router.delete("/me/skills/{skill_id}")
async def delete_my_skill(skill_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """用户私库删除（本地技能删除无确认队列通道=属主自决；transfers 队列只管跨库）。"""
    from neurova.skills import library_service as _lib

    svc = _lib.get_library(POOL_USER, _account_key(current_user))
    if svc.get_skill_info(skill_id) is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    result = svc.uninstall_skill(skill_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "删除失败"))
    return {"code": 0, "message": "Skill deleted"}


@router.post("/me/skills/{skill_id}/from-public")
async def install_public_skill_to_mine(skill_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """公共库→我的私库自助安装：apply_transfer 副本+血缘（公共升级广播
    据此可达，需求 5 闭环）；本地同名无血缘顶替 → 409。"""
    from neurova.skills import library_service as _lib

    acct = _account_key(current_user)
    pub = _lib.get_library(POOL_PUBLIC)
    if pub.get_skill_info(skill_id) is None:
        raise HTTPException(status_code=404, detail="公共库无此技能")
    r = _lib.apply_transfer(POOL_USER, acct, POOL_PUBLIC, "", skill_id, actor=acct)
    if not r.get("ok"):
        raise HTTPException(status_code=409, detail=r.get("error") or "安装失败")
    return {"code": 0, "message": "installed", "data": {"applied": r.get("action")}}


@router.get("/agent/{agent_id}/pending-skills")
async def list_pending_skills(agent_id: str):
    """C10 审批面：列出待审自动技能（评审闸开启时的配套生态）。

    pending 数据在 Agent 的 skill_packer（AutoSkillBuilder）实例上；
    Agent 未就绪返回空列表（闸关时恒空）。
    """
    try:
        from neurova.api.endpoints.governance import _get_agent

        agent = _get_agent()
        packer = getattr(agent, "skill_packer", None) if agent is not None else None
        if packer is None or not hasattr(packer, "list_pending_templates"):
            return []
        return packer.list_pending_templates()
    except Exception as e:
        logger.exception("list_pending_skills failed for agent_id=%s: %s", agent_id, e)
        return []


@router.post("/agent/{agent_id}/pending-skills/{template_id}/approve")
async def approve_pending_skill(agent_id: str, template_id: str):
    """C10 审批面：批准待审模板（激活后下轮 pattern_mining 注册进 Registry）。"""
    from neurova.api.endpoints.governance import _get_agent

    agent = _get_agent()
    packer = getattr(agent, "skill_packer", None) if agent is not None else None
    if packer is None or not hasattr(packer, "approve_template"):
        raise HTTPException(status_code=503, detail="Agent 未就绪或评审闸未开启")
    ok = packer.approve_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"待审模板不存在: {template_id}")
    return {"code": 0, "data": {"approved": True, "template_id": template_id}}


@router.post("/agent/{agent_id}/pending-skills/{template_id}/reject")
async def reject_pending_skill(agent_id: str, template_id: str):
    """C10 审批面：拒绝并删除待审模板。"""
    from neurova.api.endpoints.governance import _get_agent

    agent = _get_agent()
    packer = getattr(agent, "skill_packer", None) if agent is not None else None
    if packer is None or not hasattr(packer, "reject_template"):
        raise HTTPException(status_code=503, detail="Agent 未就绪或评审闸未开启")
    ok = packer.reject_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"待审模板不存在: {template_id}")
    return {"code": 0, "data": {"rejected": True, "template_id": template_id}}


# ── C10 治理收紧（2026-09-12）：经验记录待审面 ──


@router.get("/agent/{agent_id}/pending-experiences")
async def list_pending_experiences(agent_id: str):
    """C10 审批面：列出待审的自动化 applied 经验记录（评审闸开启时非空）。"""
    try:
        from neurova.evolution.skill_experience import get_skill_experience_store

        items = get_skill_experience_store().list_pending_experiences()
        return [
            {
                "record_id": r.record_id,
                "skill_id": r.skill_id,
                "source": r.source,
                "content": r.content,
                "context": r.context,
                "created_at": r.created_at,
            }
            for r in items
        ]
    except Exception as e:
        logger.exception("list_pending_experiences failed: %s", e)
        return []


@router.post("/agent/{agent_id}/pending-experiences/{record_id}/approve")
async def approve_pending_experience(agent_id: str, record_id: str):
    """批准待审经验：注入技能描述（立即生效）并计入重建阈值。"""
    from neurova.api.endpoints.governance import _get_agent
    from neurova.evolution.skill_experience import get_skill_experience_store

    agent = _get_agent()
    registry = getattr(agent, "_skill_registry", None) if agent is not None else None
    ok = get_skill_experience_store().approve_experience(record_id, registry=registry)
    if not ok:
        raise HTTPException(status_code=404, detail=f"待审经验不存在: {record_id}")
    return {"code": 0, "data": {"approved": True, "record_id": record_id}}


@router.post("/agent/{agent_id}/pending-experiences/{record_id}/reject")
async def reject_pending_experience(agent_id: str, record_id: str):
    """拒绝待审经验：直接丢弃。"""
    from neurova.evolution.skill_experience import get_skill_experience_store

    ok = get_skill_experience_store().reject_experience(record_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"待审经验不存在: {record_id}")
    return {"code": 0, "data": {"rejected": True, "record_id": record_id}}


@router.get("/agent/{agent_id}/skills", response_model=List[SkillInfo])
async def get_agent_skills(agent_id: str):
    """获取 Agent 的所有技能

    修复 (s1 P0 #7+#6): 原 `return []` 让前端 AgentSkillPage 永远显示空列表。
    改为调用 SkillService(agent_id).list_skills() 读取真实安装的技能。
    异常时记录 logger.exception 并优雅降级返回 [] (不静默吞)。

    路由断裂修复 (核验 2026-09-13): 本函数一度**无任何装饰器**(被堆叠在
    /agent/{agent_id}/skills 上的 pending-skills 路由顶替),技能页实际拿到
    的是待审模板列表——装饰器已分离,路径重新挂回本函数。
    """
    try:
        service = _pool_service(agent_id)
        skills = service.list_skills()
        return [
            SkillInfo(
                skill_id=s.get("id", ""),
                name=s.get("name", ""),
                description=s.get("description", ""),
                usage=s.get("usage") or {},
                version=s.get("version", "1.0.0"),
                enabled=s.get("enabled", True),
                scope="agent",
                owner_id=agent_id,
            )
            for s in skills
        ]
    except Exception as e:
        logger.exception("get_agent_skills failed for agent_id=%s: %s", agent_id, e)
        return []


@router.post("/install-from-url")
async def install_from_url(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)):
    """从 URL 安装技能。V 轮落库路由：target=agent（默认，现状 default 库）/
    me（当前账号用户私库——与技能库页「从 URL 导入」的"我的库"语义对齐）。"""
    body = await request.json()
    url = body.get("url", "")
    version = body.get("version")
    if not url:
        return {"success": False, "error": "URL is required"}
    try:
        service, _pool, _owner = _install_target(body.get("target"), current_user)
        skill_id = url.split("/")[-1].replace(".zip", "") or None
        result = service.install_skill(
            skill_path=url, skill_id=skill_id, pool_type=_pool, owner_user_id=_owner
        )
        return {"success": True, "url": url, "version": version, "result": result}
    except ValueError as bad:
        return {"success": False, "error": str(bad)}
    except Exception as e:
        logger.exception("install_from_url failed: %s", e)
        return {"success": False, "error": str(e)}


def _install_target(target, current_user: Dict[str, Any]):
    """导入落点解析（V 轮）：空/agent=(default agent 库, 现状语义零变化)；
    me=(当前账号用户私库, pool 落款 user)。返回 (service, pool, owner)。"""
    if str(target or "").lower() == "me":
        from neurova.skills import library_service as _lib

        acct = _account_key(current_user)
        return _lib.get_library(POOL_USER, acct), POOL_USER, acct
    return _pool_service("default"), POOL_AGENT, "default"


@router.post("/install-from-zip")
async def install_from_zip(
    file: UploadFile = File(...),
    target: str = Form(default=""),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """从 ZIP 安装技能。target 语义同 install-from-url（V 轮）。"""
    import os
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, file.filename or "skill.zip")
            content = await file.read()
            with open(zip_path, "wb") as f:
                f.write(content)
            service = _install_target_service(target, current_user)
            skill_id = (file.filename or "skill").replace(".zip", "") or None
            result = service.install_skill(
                skill_path=zip_path,
                skill_id=skill_id,
                pool_type=POOL_USER if str(target or "").lower() == "me" else POOL_AGENT,
                owner_user_id=_account_key(current_user) if str(target or "").lower() == "me" else "default",
            )
            return {"success": True, "message": "Skill installed from ZIP", "result": result}
    except ValueError as bad:
        raise HTTPException(status_code=400, detail=str(bad))
    except Exception as e:
        logger.exception("install_from_zip failed: %s", e)
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 技能提交-审核三连(canonical /v1/skill-pool 域,ADR 0013)
#
# 2026-09-03 线上 404:提交/审核后端实现曾寄生在 /v1/marketplace(废弃域),
# 前端按 canonical 前缀 /skill-pool/* 接线导致三连全部 404。
# 修复:在此委托 marketplace 的同源 handler —— 共享 submissions 存储、
# 通知与鉴权;迁移后 marketplace 旧前缀仍然可用,存量兼容。
# ---------------------------------------------------------------------------
@router.post("/skills/submit")
async def submit_skill_for_review(
    body: MarketplaceSkillSubmit,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """用户提交技能上架申请(登录用户):进入待审批并通知管理员。"""
    return await submit_market_skill(body, current_user)


@router.get("/skill-submissions")
async def skill_submissions_list(
    review_status: str = Query(
        default="pending", description="筛选状态: pending/approved/rejected/all"
    ),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """提交审批列表(仅管理员)。"""
    return await list_skill_submissions(review_status=review_status, admin=admin)


@router.post("/skill-submissions/{submission_id}/review")
async def skill_submission_review(
    submission_id: str,
    body: SkillSubmissionReview,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """审批技能提交(仅管理员):approve 写入市场目录,reject 不上架。"""
    return await review_skill_submission(submission_id=submission_id, body=body, admin=admin)


# ---------------------------------------------------------------------------
# Wave H-W4 技能流转（三层库跨库提案：确认制推送 / 升级广播）
#
# 语义（用户拍板）：agent→user 初推与升级均需**用户确认**（agent 自主产物
# 不得直写用户域）；user→public 走 /skills/submit 审批流（不在此域）；
# public→user/agent 升级广播由 marketplace 物化链写入本 store 的 upgrade 卡。
# ---------------------------------------------------------------------------


class SkillTransferCreate(BaseModel):
    transfer_type: str = Field(..., description="agent_to_user")
    skill_id: str
    src_pool: str = POOL_AGENT
    src_owner: str = ""
    note: str = ""


class SkillTransferDecision(BaseModel):
    note: str = ""


@router.post("/transfers")
async def create_skill_transfer(
    body: SkillTransferCreate, current_user: Dict[str, Any] = Depends(get_current_user)
):
    """发起跨库流转提案（当前仅 agent→user；落 pending + 通知确认人）。"""
    from neurova.skills import library_service as _lib
    from neurova.skills.skill_transfers import (
        TT_AGENT_TO_USER,
        get_skill_transfer_store,
    )

    if body.transfer_type != TT_AGENT_TO_USER:
        raise HTTPException(
            status_code=400,
            detail=(
                "该方向请走对应通道：user→public 用 /skill-pool/skills/submit"
                "（管理员审批）；public→私库升级由系统广播确认卡"
            ),
        )
    dst_owner = _account_key(current_user)
    try:
        src_entry = _lib.get_library(body.src_pool, body.src_owner).get_skill_info(body.skill_id)
    except ValueError as bad:
        raise HTTPException(status_code=400, detail=str(bad))
    if src_entry is None:
        raise HTTPException(status_code=404, detail=f"源技能不存在: {body.skill_id}")

    tkey = f"{TT_AGENT_TO_USER}:{body.src_pool}:{body.src_owner}->{dst_owner}:{body.skill_id}"
    entry = get_skill_transfer_store().create(
        {
            "transfer_type": TT_AGENT_TO_USER,
            "skill_id": body.skill_id,
            "src_pool": body.src_pool,
            "src_owner": body.src_owner,
            "dst_pool": POOL_USER,
            "dst_owner": dst_owner,
            "confirm_owner": dst_owner,
            "kind": "initial",
            "version": str(src_entry.get("version") or ""),
            "name": str(src_entry.get("name") or body.skill_id),
            "transfer_key": tkey,
            "note": body.note,
        }
    )
    try:
        from neurova.api.endpoints.notifications import notify_user

        notify_user(
            str(current_user.get("user_id") or ""),
            title="技能推送待确认",
            message=f"Agent『{body.src_owner}』向你推送技能「{entry['name']}」v{entry['version']}，等待确认",
            notification_type="skill_transfer",
            data={
                "transfer_id": entry["transfer_id"],
                "skill_id": body.skill_id,
                "action": "skill_transfer",
            },
        )
    except Exception:  # noqa: BLE001 - 通知失败不吞提案
        logger.debug("流转通知发送失败", exc_info=True)
    return {"code": 0, "message": "submitted", "data": entry}


@router.get("/transfers")
async def list_skill_transfers(
    status_filter: str = Query(default="pending", alias="status"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """确认队列：本人归属的卡片；admin 全量。"""
    from neurova.skills.skill_transfers import get_skill_transfer_store

    store = get_skill_transfer_store()
    if str(current_user.get("role") or "") == "admin":
        items = store.list(status=None if status_filter == "all" else status_filter)
    else:
        items = store.list(
            status=None if status_filter == "all" else status_filter,
            confirm_owner=_account_key(current_user),
        )
    return {"code": 0, "message": "success", "data": {"items": items, "total": len(items)}}


def _decide_transfer(transfer_id: str, current_user: Dict[str, Any], approve: bool, note: str = ""):
    from neurova.skills.library_service import apply_transfer
    from neurova.skills.skill_transfers import STATUS_ACCEPTED, STATUS_REJECTED, get_skill_transfer_store

    store = get_skill_transfer_store()
    row = store.get(transfer_id)
    if not row:
        raise HTTPException(status_code=404, detail="流转不存在")
    actor_key = _account_key(current_user)
    if str(current_user.get("role") or "") != "admin" and actor_key != str(row.get("confirm_owner") or ""):
        raise HTTPException(status_code=403, detail="仅技能归属人可确认")
    if row.get("status") != "pending":
        raise HTTPException(status_code=409, detail="该流转已处理")

    if approve:
        result = apply_transfer(
            row["dst_pool"], row["dst_owner"], row["src_pool"], row["src_owner"],
            row["skill_id"], actor_key,
            # 卡快照版本优先（防卡片在途源侧回滚推旧版）
            override_version=str(row.get("version") or ""),
        )
        if not result.get("ok"):
            raise HTTPException(status_code=409, detail=result.get("error") or "流转应用失败")
        updated = store.set_status(transfer_id, STATUS_ACCEPTED, decided_by=actor_key, note=note)
        return {"code": 0, "message": "accepted", "data": {"transfer": updated, "applied": result.get("action")}}
    updated = store.set_status(transfer_id, STATUS_REJECTED, decided_by=actor_key, note=note)
    return {"code": 0, "message": "rejected", "data": {"transfer": updated}}


@router.post("/transfers/{transfer_id}/accept")
async def accept_skill_transfer(
    transfer_id: str,
    body: Optional[SkillTransferDecision] = Body(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """确认流转：apply_transfer 落副本/原地升级（账本保留）。"""
    return _decide_transfer(transfer_id, current_user, True, (body.note if body else ""))


@router.post("/transfers/{transfer_id}/reject")
async def reject_skill_transfer(
    transfer_id: str,
    body: Optional[SkillTransferDecision] = Body(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """拒绝流转：仅记账不动库。"""
    return _decide_transfer(transfer_id, current_user, False, (body.note if body else ""))
