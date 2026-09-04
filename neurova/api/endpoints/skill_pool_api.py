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
from neurova.api.endpoints.marketplace import (
    MarketplaceSkillSubmit,
    SkillSubmissionReview,
    list_skill_submissions,
    review_skill_submission,
    submit_market_skill,
)
from neurova.api.endpoints._pydantic_compat import safe_model_dump

logger = get_logger(__name__)
router = APIRouter()


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
    target_user_id: str = Field(..., description="目标用户 ID")


class SkillPush(BaseModel):
    agent_id: str = Field(default="default", description="Agent ID")


_public_skills: Dict[str, Dict[str, Any]] = {}
_private_skills: Dict[str, Dict[str, Any]] = {}

# s8: RLock 保护共享 dict 状态, 防 TOCTOU race (多线程部署时 create/update/delete
# 的 read-modify-write 临界区). RLock (非 Lock) 因 list 端点可能间接调用其他持锁方法.
_lock = threading.RLock()


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
async def install_public_skill(skill_id: str, agent_id: str = Query(default="default")):
    """安装公共技能到 Agent"""
    with _lock:
        skill = _public_skills.get(skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        return {"code": 0, "message": f"Skill '{skill_id}' installed to agent '{agent_id}'"}


@router.get("/private", response_model=List[SkillInfo])
async def list_private_skills(agent_id: str = Query(default="default")):
    """列出专属技能 (聚合多数据源)

    修复 (s2 P0 #1): 原仅读 _private_skills (API 内存状态), 导致通过
    POST /install-from-url 或 /install-from-zip 安装的技能 (SkillService 磁盘 manifest)
    在前端 SkillPoolPage 不可见 — split-brain.
    改为聚合:
      源1: _private_skills (POST /private 创建, 按 owner_id == agent_id 过滤)
      源2: SkillService(agent_id=agent_id).list_skills() (安装, 磁盘持久化)
    SkillRegistry 不纳入 /private (global 走 /public).

    修复 (s4 P1 #6): 参数名 user_id → agent_id, 对齐前端
    skill-pool.ts:53-55 的 getPrivateSkills(agentId) 发送 ?agent_id=xxx.

    修复 (s8): 加 _lock 保护 _private_skills 迭代, 防并发修改.
    """
    # 源1: API 内存状态 (按 owner_id 过滤), 在锁内复制避免迭代时被并发修改
    with _lock:
        result = [
            SkillInfo(**s)
            for s in _private_skills.values()
            if s.get("owner_id") == agent_id
        ]

    # 源2: SkillService 磁盘持久化技能 (锁外执行, 避免 I/O 阻塞持锁)
    try:
        from neurova.skills.skill_service import SkillService

        service = SkillService(agent_id=agent_id)
        for s in service.list_skills():
            result.append(
                SkillInfo(
                    skill_id=s.get("id", ""),
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    version=s.get("version", "1.0.0"),
                    enabled=s.get("enabled", True),
                    scope="private",
                    owner_id=agent_id,
                )
            )
    except Exception as e:
        # 优雅降级: 保留源1结果, 记录日志 (不静默吞)
        logger.exception(
            "list_private_skills: SkillService aggregation failed for agent_id=%s: %s",
            agent_id,
            e,
        )

    return result


@router.post("/private", response_model=SkillInfo)
async def create_private_skill(body: SkillCreate, agent_id: str = Query(default="default")):
    """创建专属技能

    s6 (WARTN 2): 参数名 user_id → agent_id, 与 list_private_skills 对齐.
    前端 skill-pool.ts 的 createSkill 不传此参数 (走默认 default), 故改名
    不破坏前端契约; 但同模块参数名一致后, 未来调用方传 ?agent_id=xxx
    创建→查询链路不再断裂.

    s8: 加 _lock 保护 _private_skills 写入.
    s9: 改用 safe_model_dump 替代 inline getattr fallback (统一 helper).
    """
    with _lock:
        sid = str(uuid.uuid4())
        now = time.time()
        skill = {
            "skill_id": sid,
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "scope": "private",
            "owner_id": agent_id,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
        _private_skills[sid] = skill
        return SkillInfo(**skill)


@router.put("/private/{skill_id}", response_model=SkillInfo)
async def update_private_skill(skill_id: str, body: SkillUpdate, agent_id: str = Query(default="default")):
    """更新专属技能

    s6 (WARTN 2): 参数名 user_id → agent_id, 与 list_private_skills 对齐.
    s6 附带修复: model_dump() 在 pydantic v1 下 AttributeError, 改用 safe_model_dump (s9 统一).
    s8: 加 _lock 保护 read-modify-write 临界区, 防 TOCTOU race.
    """
    with _lock:
        skill = _private_skills.get(skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        if skill.get("owner_id") != agent_id:
            raise HTTPException(status_code=403, detail="Permission denied")
        for k, v in safe_model_dump(body, exclude_none=True).items():
            skill[k] = v
        skill["updated_at"] = time.time()
        return SkillInfo(**skill)


@router.delete("/private/{skill_id}")
async def delete_private_skill(skill_id: str, agent_id: str = Query(default="default")):
    """删除专属技能

    s6 (WARTN 2): 参数名 user_id → agent_id, 与 list_private_skills 对齐.
    s8: 加 _lock 保护 _private_skills 删除.
    """
    with _lock:
        skill = _private_skills.get(skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        if skill.get("owner_id") != agent_id:
            raise HTTPException(status_code=403, detail="Permission denied")
        del _private_skills[skill_id]
        return {"code": 0, "message": "Skill deleted"}


@router.post("/private/{skill_id}/share")
async def share_private_skill(skill_id: str, body: SkillShare):
    """共享专属技能"""
    return {"code": 0, "message": f"Skill shared with {body.target_user_id}"}


@router.post("/private/{skill_id}/push")
async def push_skill_to_agent(skill_id: str, body: SkillPush):
    """推送技能到 Agent"""
    return {"code": 0, "message": f"Skill pushed to agent '{body.agent_id}'"}


@router.delete("/private/{skill_id}/push")
async def unpush_skill_from_agent(skill_id: str, agent_id: str = Query(default="default")):
    """取消推送"""
    return {"code": 0, "message": f"Skill unpushed from agent '{agent_id}'"}


@router.get("/agent/{agent_id}/skills", response_model=List[SkillInfo])
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


async def get_agent_skills(agent_id: str):
    """获取 Agent 的所有技能

    修复 (s1 P0 #7+#6): 原 `return []` 让前端 AgentSkillPage 永远显示空列表。
    改为调用 SkillService(agent_id).list_skills() 读取真实安装的技能。
    异常时记录 logger.exception 并优雅降级返回 [] (不静默吞)。
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
