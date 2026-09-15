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
"""

from neurova.core.logger import get_logger
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin
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


class SkillShare(BaseModel):
    target_user_id: str = Field(default="", description="目标用户 ID（可空=公开共享标记）")


class SkillPush(BaseModel):
    agent_id: str = Field(default="default", description="Agent ID")


_public_skills: Dict[str, Dict[str, Any]] = {}

# Wave F：_private_skills 内存 dict 已废除（双轨合一）——private 技能的唯一
# 事实源是 SkillService manifest（data/agents/{agent_id}/skills/manifest.json，
# 自带 RLock + 原子写 + usage 遥测）。原内存轨 create 重启即丢、与磁盘
# manifest 互不可见（split-brain 的另一半）。
# s8: RLock 仍保护 _public_skills（公共演示轨，读写方均在锁内）。
_lock = threading.RLock()


def _pool_service(agent_id: str) -> SkillService:
    """private 链统一服务入口。

    经模块属性延迟解析类（非 from-import 快照）——保证测试 monkeypatch
    neurova.skills.skill_service.SkillService 对端点生效，也避免旧 s2 时代
    靠打桩类隔离落盘的契约回归为"真写 data/ 污染"。
    """
    from neurova.skills import skill_service as _ss_mod

    return _ss_mod.SkillService(agent_id=agent_id)


# s5: 已删除 _get_spm() (死代码, 零调用方).
# s2/s4 修复后 list_private_skills 直接调用 SkillService, 不再需要 SkillPoolManager 桥接.


@router.get("/public", response_model=List[SkillInfo])
async def list_public_skills(category: Optional[str] = Query(default=None)):
    """列出公共技能"""
    with _lock:
        skills = [s for s in _public_skills.values() if s.get("scope") == "public"]
        if category:
            skills = [s for s in skills if s.get("category") == category]
        return [SkillInfo(**s) for s in skills]


@router.get("/public/{skill_id}", response_model=SkillInfo)
async def get_public_skill(skill_id: str):
    """获取公共技能详情"""
    with _lock:
        skill = _public_skills.get(skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        return SkillInfo(**skill)


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

    历史（s2 修复曾聚合"内存 dict + 磁盘"两源治 split-brain）；Wave F 把
    create 侧也落到磁盘后，聚合逻辑删除——单源不存在漂移。s4 参数名对齐
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
async def share_private_skill(skill_id: str, body: SkillShare, agent_id: str = Query(default="default")):
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
    """推送技能到 Agent——Wave F 真实现：条目复制到目标 agent manifest（幂等）。"""
    if not body.agent_id or body.agent_id == agent_id:
        raise HTTPException(status_code=400, detail="目标 agent 无效（需不同于源视图）")
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
        from neurova.skills.skill_service import SkillService

        service = SkillService(agent_id=agent_id)
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
async def install_from_url(request: Request):
    """从 URL 安装技能到技能池"""
    body = await request.json()
    url = body.get("url", "")
    version = body.get("version")
    if not url:
        return {"success": False, "error": "URL is required"}
    try:
        from neurova.skills.skill_service import SkillService

        service = SkillService(agent_id="default")
        skill_id = url.split("/")[-1].replace(".zip", "") or None
        result = service.install_skill(skill_path=url, skill_id=skill_id)
        return {"success": True, "url": url, "version": version, "result": result}
    except Exception as e:
        logger.exception("install_from_url failed: %s", e)
        return {"success": False, "error": str(e)}


@router.post("/install-from-zip")
async def install_from_zip(file: UploadFile = File(...)):
    """从 ZIP 文件安装技能到技能池"""
    import os
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, file.filename or "skill.zip")
            content = await file.read()
            with open(zip_path, "wb") as f:
                f.write(content)
            from neurova.skills.skill_service import SkillService

            service = SkillService(agent_id="default")
            skill_id = (file.filename or "skill").replace(".zip", "") or None
            result = service.install_skill(skill_path=zip_path, skill_id=skill_id)
            return {"success": True, "message": "Skill installed from ZIP", "result": result}
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
