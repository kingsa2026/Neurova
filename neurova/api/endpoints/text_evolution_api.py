"""文本进化与技能生命周期 API。

挂在 /api/v1/evolution 下(经 endpoints/__init__.py 的 register_endpoint_routers
统一注册)。鉴权口径对齐项目既有实践(记忆搜索设置页同型):
  读 = 登录用户;写(改设置/触发扫描/批准提案) = admin。

端点:
  GET   /settings                      进化设置
  PUT   /settings                      更新进化设置(admin)
  GET   /skills/{agent_id}/usage       技能生命周期与用量汇总
  POST  /skills/{agent_id}/sweep       立即执行一次生命周期扫描(admin)
  POST  /skills/{agent_id}/evolve      对指定技能跑一次文本进化(admin)
  POST  /skills/{agent_id}/ab          双臂试评:基线 vs 候选正文对照(admin)
  GET   /skills/{agent_id}/proposals   进化提案列表(pending/approved/rejected)
  POST  /skills/{agent_id}/proposals/{proposal_id}/approve   批准→写回技能(admin)
  POST  /skills/{agent_id}/proposals/{proposal_id}/reject    拒绝(admin)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter()
_admin_dep = require_admin()


# ── 设置 ──


class SettingsPatch(BaseModel):
    text_evolution: Optional[bool] = None
    lifecycle_sweep: Optional[bool] = None
    lifecycle_interval_hours: Optional[int] = Field(default=None, ge=1, le=24 * 30)
    judge_model: Optional[str] = None
    optimizer_model: Optional[str] = None


@router.get("/settings")
async def get_evolution_settings(user: Dict[str, Any] = Depends(get_current_user)):
    from neurova.evolution.evolution_settings import load_settings

    return {"code": 0, "data": load_settings().__dict__}


@router.put("/settings", dependencies=[Depends(_admin_dep)])
async def update_evolution_settings(
    body: SettingsPatch, user: Dict[str, Any] = Depends(get_current_user)
):
    from neurova.evolution.evolution_settings import update_settings

    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        settings = update_settings(**patch)
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"设置字段非法: {e}") from e
    return {"code": 0, "data": settings.__dict__}


# ── 生命周期 ──


def _skill_service(agent_id: str):
    from neurova.skills.skill_service import SkillService

    return SkillService(agent_id=agent_id)


@router.get("/skills/{agent_id}/usage")
async def get_lifecycle_usage(agent_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """技能生命周期汇总:按状态分组 + 扫描状态(不暴露技能正文)。"""
    try:
        svc = _skill_service(agent_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"技能服务不可用: {e}") from e
    by_state = {"active": [], "stale": [], "archived": []}
    items = []
    for skill_id, info in svc.iter_skills():
        usage = info.get("usage") if isinstance(info, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        state = str(usage.get("state") or "active")
        by_state.setdefault(state, [])
        by_state[state].append(skill_id)
        items.append(
            {
                "skill_id": skill_id,
                "state": state,
                "pinned": bool(usage.get("pinned")),
                "created_by": str(usage.get("created_by") or "user"),
                "use_count": int(usage.get("use_count") or 0),
                "last_activity_at_ms": int(usage.get("last_activity_at_ms") or 0),
            }
        )
    return {"code": 0, "data": {"counts": {k: len(v) for k, v in by_state.items()}, "skills": items}}


@router.post("/skills/{agent_id}/sweep", dependencies=[Depends(_admin_dep)])
async def run_lifecycle_sweep(agent_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """手动立即扫描(admin):绕过间隔闸,直接 apply_transitions。"""
    from neurova.evolution.skill_lifecycle import apply_transitions

    try:
        svc = _skill_service(agent_id)
        counts = apply_transitions(svc)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"生命周期扫描失败: {e}") from e
    return {"code": 0, "data": counts}


class PinRequest(BaseModel):
    pinned: bool


@router.post("/skills/{agent_id}/{skill_id}/pin", dependencies=[Depends(_admin_dep)])
async def pin_or_unpin_skill(
    agent_id: str, skill_id: str, body: PinRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """钉住/解钉(pinned 技能绕开生命周期自动迁移)。"""
    try:
        svc = _skill_service(agent_id)
        if not svc.set_skill_pinned(skill_id, body.pinned):
            raise HTTPException(status_code=404, detail=f"技能不存在: {skill_id}")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"钉住操作失败: {e}") from e
    return {"code": 0, "data": {"pinned": bool(body.pinned)}}


# ── 文本进化 ──


class EvolveRequest(BaseModel):
    skill_id: str
    iterations: Optional[int] = Field(default=None, ge=1, le=50)
    dataset_source: str = Field(default="auto", pattern="^(auto|golden|mined|synthetic)$")


@router.post("/skills/{agent_id}/evolve", dependencies=[Depends(_admin_dep)])
async def evolve_skill(body: EvolveRequest, agent_id: str,
                       user: Dict[str, Any] = Depends(get_current_user)):
    """对指定技能跑一次进化;产出 pending 提案(绝不自动应用)。"""
    from neurova.evolution.eval.config import EvolutionConfig
    from neurova.evolution.eval.service import SkillEvolutionService

    svc = _skill_service(agent_id)
    info = svc.get_skill_info(body.skill_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"技能不存在: {body.skill_id}")
    cfg = dict((info.get("manifest") or {}).get("config") or {})
    skill_text = str(cfg.get("context_template") or info.get("description") or "")
    if not skill_text.strip():
        raise HTTPException(status_code=422, detail="技能正文为空,无进化对象")

    settings = _load_settings_safe()
    from neurova.evolution.eval.dataset import EvalDataset
    from neurova.evolution.eval.synthetic import SyntheticDatasetBuilder

    service = SkillEvolutionService(agent_id)
    config = EvolutionConfig(
        judge_model=settings.judge_model, optimizer_model=settings.optimizer_model
    )
    dataset: Optional[EvalDataset] = None
    if body.dataset_source == "auto":
        dataset = await service.build_dataset(body.skill_id, skill_text)
    elif body.dataset_source == "synthetic":
        dataset = await SyntheticDatasetBuilder(config).generate(skill_text, "skill")
    # golden/mined: build_dataset 内部按源取(空则报错)
    if body.dataset_source in ("golden", "mined"):
        dataset = await service.build_dataset(
            body.skill_id, skill_text, source=body.dataset_source
        )
    if not dataset or not dataset.all_examples:
        raise HTTPException(
            status_code=422,
            detail=f"无可用评测集(source={body.dataset_source});先 golden/mined/synthetic 准备用例",
        )

    result, proposal = await service.evolve(
        skill_id=body.skill_id, skill_text=skill_text,
        dataset=dataset, iterations=body.iterations, config=config,
    )
    return {
        "code": 0,
        "data": {
            **result.to_dict(),
            "proposal": proposal.to_dict() if proposal else None,
        },
    }


class ABRequest(BaseModel):
    skill_id: str
    candidate_text: str = Field(min_length=1)
    dataset_source: str = Field(default="auto", pattern="^(auto|golden|mined|synthetic)$")
    # 执行面开关：默认 False=模拟面（单轮 chat，零工具零上下文）。真轨迹臂会把候选正文
    # 经轮级覆盖槽送进一次真实 agent 回合，成本约 2 臂×任务数 个回合，且必须显式开。
    real_trajectory: bool = False


@router.post("/skills/{agent_id}/ab", dependencies=[Depends(_admin_dep)])
async def ab_compare_texts(body: ABRequest, agent_id: str,
                           user: Dict[str, Any] = Depends(get_current_user)):
    """双臂试评(admin)：基线正文 vs 候选正文，同任务集同判分器对照。

    任务集优先 heldout（P0-2 真留出集，未被搜索消耗）。**只读评测**——
    不产提案、不写技能、不入台账；审批人在 decide 前对候选做干净集核验。
    """
    from neurova.evolution.eval.config import EvolutionConfig
    from neurova.evolution.eval.service import SkillEvolutionService

    svc = _skill_service(agent_id)
    info = svc.get_skill_info(body.skill_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"技能不存在: {body.skill_id}")
    if not body.candidate_text.strip():
        raise HTTPException(status_code=422, detail="candidate_text 不能为空白")
    cfg = dict((info.get("manifest") or {}).get("config") or {})
    skill_text = str(cfg.get("context_template") or info.get("description") or "")
    if not skill_text.strip():
        raise HTTPException(status_code=422, detail="技能正文为空,无双臂基线")
    if body.candidate_text.strip() == skill_text.strip():
        raise HTTPException(status_code=422, detail="候选正文与基线相同,无双臂差异")

    settings = _load_settings_safe()
    from neurova.evolution.eval.dataset import EvalDataset
    from neurova.evolution.eval.synthetic import SyntheticDatasetBuilder

    service = SkillEvolutionService(agent_id)
    config = EvolutionConfig(
        judge_model=settings.judge_model, optimizer_model=settings.optimizer_model
    )
    dataset: Optional[EvalDataset] = None
    if body.dataset_source == "auto":
        dataset = await service.build_dataset(body.skill_id, skill_text)
    elif body.dataset_source == "synthetic":
        dataset = await SyntheticDatasetBuilder(config).generate(skill_text, "skill")
    if body.dataset_source in ("golden", "mined"):
        dataset = await service.build_dataset(
            body.skill_id, skill_text, source=body.dataset_source
        )
    if not dataset or not dataset.all_examples:
        raise HTTPException(
            status_code=422,
            detail=f"无可用评测集(source={body.dataset_source});先 golden/mined/synthetic 准备用例",
        )

    report = await service.ab_compare(
        baseline_text=skill_text, candidate_text=body.candidate_text,
        dataset=dataset, config=config, agent=_textArmExecutorFor(agent_id, info, body),
    )
    # 来源标注不在这里重算：service 已按"真正拿去执行的那个对象"定好。端点自己
    # 再推一遍就会分叉（实测：注入真臂后被这里改标成 simulated，标注反而成了谎）。
    return {"code": 0, "data": report}


def _textArmExecutorFor(agent_id: str, info: Dict[str, Any], body: ABRequest):
    """按请求把双臂切到真 agent 轨迹；**不在此判执行器类型**，只负责装配与诚实失败。

    三条口径：
    · 拿不到 agent ⇒ 409 点名原因并给出回退项，绝不静默降级成模拟面（教义第 2 条）；
    · 技能名组不出 `$mention` ⇒ 422——那种情况下两臂会拿到同一份仓内正文，
      比出一个看起来正常的假 0 差；
    · `real_trajectory=false` ⇒ 返回 None，由 service 的装配接缝回落模拟面，
      并在报告里如实标注来源（`executor_kind`）。
    """
    if not body.real_trajectory:
        return None

    from neurova.api.endpoints import get_agent_instance
    from neurova.evolution.eval.ab_library import TextArmAgentExecutor

    agent = get_agent_instance(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=409,
            detail=(f"agent「{agent_id}」不在线，无法跑真轨迹双臂；"
                    "如需继续请用 real_trajectory=false 走模拟面（报告会标注来源）"),
        )
    try:
        return TextArmAgentExecutor(agent, skill_name=str(info.get("name") or body.skill_id))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _load_settings_safe():
    from neurova.evolution.evolution_settings import load_settings

    return load_settings()


@router.get("/skills/{agent_id}/proposals")
async def list_evolution_proposals(
    agent_id: str, status: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if status and status not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=422, detail="status 取值: pending|approved|rejected")
    from neurova.evolution.eval.service import SkillEvolutionService

    items = SkillEvolutionService(agent_id).list_proposals(status=status)
    # 列表面不夹带正文(可能很大),详情接口再给全文
    rows = [
        {
            "proposal_id": p.get("proposal_id"),
            "skill_id": p.get("skill_id"),
            "status": p.get("status"),
            "holdout_before": p.get("holdout_before"),
            "holdout_after": p.get("holdout_after"),
            "iterations_run": p.get("iterations_run"),
            "created_at": p.get("created_at"),
            "decided_at": p.get("decided_at"),
            # M-C 读数：这条验收证据跑在哪个基座上（空串 = 未记，含本批之前落盘的全部旧记录）
            "model_under_test": p.get("model_under_test") or "",
        }
        for p in items
    ]
    from neurova.evolution.eval.service import modelCoverageReadout

    # 形状纪律：`data` 是前端已在消费的列表，改成 dict 会打破既有契约——
    # 覆盖读数作**同级新增键**，老调用者读 data 不受影响。
    return {
        "code": 0,
        "data": rows,
        "model_coverage": modelCoverageReadout(items),
    }


@router.get("/skills/{agent_id}/proposals/{proposal_id}")
async def get_evolution_proposal_detail(agent_id: str, proposal_id: str,
                                        user: Dict[str, Any] = Depends(get_current_user)):
    """提案详情：正文 + 那次进化的审计运行（§6-95 后半给 `runs/*.json` 接上的读者）。

    刻意走这条**既有**详情面而不是新建端点：审批人点开提案时本来就要取一次详情，
    运行记录挂在这里等于"决策时看得见证据"，而不是再多一个没人调的通道
    （台账 §6-111 记的就是"落了零消费者的读数"那种形态）。
    一条如实边界：**被门拒掉的候选不产提案**，所以这条读路径天然只覆盖"出了提案的那些
    运行"；「门逐条拦了谁」那一半仍无出口（属另一裁，见台账 §6-95 后半）。
    """
    from neurova.evolution.eval.service import SkillEvolutionService

    service = SkillEvolutionService(agent_id)
    for p in service.list_proposals():
        if p.get("proposal_id") == proposal_id:
            runState, runPayload = service.runLookup(str(p.get("run_id") or ""))
            return {"code": 0, "data": {
                **p,
                "evolution_run": runPayload,
                "evolution_run_status": runState,
            }}
    raise HTTPException(status_code=404, detail=f"提案不存在: {proposal_id}")


@router.post("/skills/{agent_id}/proposals/{proposal_id}/approve", dependencies=[Depends(_admin_dep)])
async def approve_evolution_proposal(agent_id: str, proposal_id: str,
                                     user: Dict[str, Any] = Depends(get_current_user)):
    """批准 → 进化文本写回技能正文(唯一变更点)。

    审批人取认证身份传入（§6-2 阶段①）：决策可归因，缺失即 400。
    """
    from neurova.evolution.eval.service import SkillEvolutionService

    try:
        ok = SkillEvolutionService(agent_id).decide(
            proposal_id, approve=True,
            approver=str(user.get("username") or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="提案不存在或已处理")
    return {"code": 0, "data": {"approved": True}}


@router.post("/skills/{agent_id}/proposals/{proposal_id}/reject", dependencies=[Depends(_admin_dep)])
async def reject_evolution_proposal(agent_id: str, proposal_id: str,
                                    user: Dict[str, Any] = Depends(get_current_user)):
    from neurova.evolution.eval.service import SkillEvolutionService

    ok = SkillEvolutionService(agent_id).decide(
        proposal_id, approve=False,
        approver=str(user.get("username") or ""))
    if not ok:
        raise HTTPException(status_code=404, detail="提案不存在或已处理")
    return {"code": 0, "data": {"rejected": True}}
