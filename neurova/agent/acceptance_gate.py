# -*- coding: utf-8 -*-
"""蜂群子代理终态验收门（P1-2，评测报告 G-3）。

论文依据（arXiv:2610.33048）：验收门 a_t(g) = C_g^t(z) ∧ R_t(g)——
产出/证据达标 **且** 评审通过才构成"可被下游采用的结果"；失败/取消单元的 a 恒 0
（终态关闭本身不构成合格输入）。消融实证：去贡献规格 −4.27、去监督评审 −12.82。

本模块只做**验收**（C_g^t）；监督评审相位（R_t(g)）在 P1-3 落地。判定器单源复用
`goal_verifier.verifyGoalCompletion`（禁工具子会话，与单 agent loop 出口同一份）。

启用策略（2026-11-17 用户裁定）：
- 系统设置 `advanced.swarm_acceptance_enabled`（默认 **关**＝零行为漂移），
  前端设置面板「高级」卡可视开关；
- env `NEUROVA_SWARM_ACCEPTANCE=on/off` 显式值最优先（运维逃生门）；
- spawn 时显式带 `acceptanceCriteria` 的任务**绕过开关单独生效**（数据齐备即验收）。

回炉纪律：判定不达标 → 把 missing 逐条作为修正指令回炉重做一次（复用同一条 run
与 member 会话，历史自然衔接）；再不达标 → run 置 failed（cause=acceptance_failed），
其产出不作为合格结果回流。判定器不可用（通道故障/解析失败）→ **诚实降级**：
run 照常 completed 但 acceptance 记录 skipped 原因，绝不静默放行也绝不误杀。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from neurova.core.logger import get_logger
from neurova.core.app_settings import get_advanced_settings
from neurova.agent.loop_goal import normalizeGoal
from neurova.agent.goal_verifier import verifyGoalCompletion

logger = get_logger(__name__)

#: 部署级逃生门：显式 on/off 压过设置面板的值
ACCEPTANCE_ENV = "NEUROVA_SWARM_ACCEPTANCE"
#: 设置面板的键（advanced section，见 app_settings.ADVANCED_DEFAULTS）
SETTING_KEY = "swarm_acceptance_enabled"
#: 自动回炉轮数（首次产出 + 1 次修正机会；总 chat 调用 ≤ 2）
MAX_REWORK_ROUNDS = 1

#: 判定通道注入形态：llmChat(messages) → 含 .content 的响应（见 sub_session 纪律）
VerifyChannel = Callable[[Any], Awaitable[Any]]


@dataclass
class GateResult:
    """验收门的产出事实。failedReason 非 None → run 必须置 failed（验收不通过）。"""

    report: str
    info: Optional[dict]  # 写入 SubAgentRun.acceptance / to_dict 的记录
    failedReason: Optional[str] = None
    cause: str = ""


def acceptanceEnabled() -> bool:
    """设置面板开关（advanced.swarm_acceptance_enabled，默认关）；env 显式 on/off 最优先。"""
    raw = (os.environ.get(ACCEPTANCE_ENV) or "").strip().lower()
    if raw in ("on", "1", "true", "yes"):
        return True
    if raw in ("off", "0", "false", "no"):
        return False
    try:
        return bool(get_advanced_settings().get(SETTING_KEY, False))
    except Exception:  # noqa: BLE001 - 设置不可读回落默认关（不因设置故障放行或误杀）
        return False


def _criteriaOf(run: Any) -> list:
    unit = getattr(run, "task_unit", None) or {}
    criteria = unit.get("acceptanceCriteria") or []
    return [str(c).strip() for c in criteria if str(c or "").strip()]


def gateActiveFor(run: Any) -> bool:
    """该 run 是否过验收门：设置开 → 全部蜂群任务；设置关 → 仅显式带验收条件的任务。"""
    if _criteriaOf(run):
        return True
    return acceptanceEnabled()


def gateGoalFor(run: Any):
    """验收目标：task_unit.goal（缺省退回原始 task 文本），成功条目 = acceptanceCriteria。"""
    unit = getattr(run, "task_unit", None) or {}
    statement = str(unit.get("goal") or getattr(run, "task", "") or "").strip()
    return normalizeGoal({"statement": statement, "successCriteria": _criteriaOf(run)})


def revisionInstructions(basePrompt: str, verdict: dict) -> str:
    """把 judge 的 missing 逐条转成修正指令（可执行、可核对，不写模糊批语）。"""
    missing = verdict.get("missing") or []
    lines = [str(basePrompt), "", "【验收打回】上一轮产出未通过验收判定，请逐条补齐后重新提交完整产出："]
    for idx, item in enumerate(missing, 1):
        lines.append(f"{idx}. {item}")
    if verdict.get("explanation"):
        lines.append(f"（判定意见：{verdict['explanation']}）")
    lines.append("补齐后重新给出**完整**产出（不要只交差异部分）。")
    return "\n".join(lines)


async def runAcceptanceLoop(
    run: Any,
    chatFn: Callable[[str], Awaitable[str]],
    verifyChannel: VerifyChannel,
    firstReport: str,
) -> GateResult:
    """验收主循环：判定 → 不达标带 missing 回炉一次 → 再判定。

    chatFn(text) = member 的完整 agent 管线（带流式/会话/预算，由调用方闭包提供）；
    verifyChannel = agent.llm_client.chat（goal_verifier 的受限判定通道）。
    """
    if not gateActiveFor(run):
        return GateResult(report=firstReport, info=None)
    goal = gateGoalFor(run)
    if goal is None:
        return GateResult(report=firstReport, info={"skipped": "no_goal"})

    report = firstReport
    rounds = 0
    while True:
        verdict = await verifyGoalCompletion(verifyChannel, goal, evidence=report)
        if not verdict.get("parse_ok", False):
            # 判定不可用：诚实降级（记录原因，不静默放行、不凭空续跑）
            logger.warning(
                "Swarm: 验收判定不可用（%s），run %s 诚实放行并标注",
                str(verdict.get("raw", ""))[:120], getattr(run, "subagent_id", "?"),
            )
            return GateResult(
                report=report,
                info={"achieved": None, "skipped": "judge_unavailable",
                      "detail": str(verdict.get("raw", ""))[:200], "rounds": rounds},
            )
        if verdict.get("achieved"):
            return GateResult(
                report=report,
                info={**verdict, "rounds": rounds, "reworked": rounds > 0},
            )
        if rounds >= MAX_REWORK_ROUNDS:
            missing = verdict.get("missing") or []
            detail = "；".join(missing) if missing else str(verdict.get("explanation") or "未达标")
            return GateResult(
                report=report,
                info={**verdict, "rounds": rounds, "reworked": rounds > 0},
                failedReason=f"acceptance_failed（验收门判定未达标：{detail}）",
                cause="acceptance_failed",
            )
        rounds += 1
        logger.info(
            "Swarm: 验收未达标，回炉第 %d 次（run %s）：%s",
            rounds, getattr(run, "subagent_id", "?"), "；".join(verdict.get("missing") or []),
        )
        report = await chatFn(revisionInstructions(
            renderBase(run), verdict,
        ))


def renderBase(run: Any) -> str:
    """回炉提示词的基底 = 原始任务 + 任务书（与首次派生同源，不丢结构化字段）。"""
    from neurova.agent.task_unit import renderTaskUnitPrompt

    return renderTaskUnitPrompt(getattr(run, "task", ""), getattr(run, "task_unit", None))
