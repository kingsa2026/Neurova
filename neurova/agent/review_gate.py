# -*- coding: utf-8 -*-
"""蜂群监督评审相位（P1-3，评测报告 G-5）。

论文依据（AutoSwarm arXiv:2610.33048）：监督评审 R_t(g) 是验收门 a_t(g)=C∧R 的第二个
乘数——**集成前**由监督方按验收条件把关。消融实证：去掉监督评审 −12.82 分（最大单项）。

形态（2026-11-17 用户裁定）：rubric 子会话——单源复用 `review.py` 的 P0-P3 结构化评审
（与 /review 命令同一套判据），不引入异构第二模型。

触发条件：spawn 时 task_unit.reviewMode = "supervisor"（显式 opt-in，默认 none 不评审）。
时序：验收门（P1-2）通过后、终态 completed 之前；run 进入 in_review 相位（占派生槽，
看门狗继续守护）。评审不通过 → findings 逐条作为修正指令回炉一次；仍不通过 →
failed（cause=review_failed）。评审器不可用（通道故障/解析失败）→ 诚实降级：
completed + review.skipped=reviewer_unavailable，绝不静默放行也绝不误杀。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from neurova.core.logger import get_logger
from neurova.agent.review import run_review

logger = get_logger(__name__)

#: 评审回炉轮数（首次评审 + 1 次修正机会）
MAX_REVIEW_ROUNDS = 1


@dataclass
class ReviewResult:
    report: str
    info: Optional[dict]
    failedReason: Optional[str] = None
    cause: str = ""


def reviewNeededFor(run: Any) -> bool:
    unit = getattr(run, "task_unit", None) or {}
    return str(unit.get("reviewMode") or "none").strip().lower() == "supervisor"


def _focusOf(run: Any) -> str:
    unit = getattr(run, "task_unit", None) or {}
    criteria = [str(c).strip() for c in (unit.get("acceptanceCriteria") or []) if str(c or "").strip()]
    if not criteria:
        return ""
    return "按任务验收条件逐条核对：" + "；".join(criteria)


def reviewRevisionInstructions(basePrompt: str, verdict: dict) -> str:
    """把评审 findings 逐条转成修正指令（优先级 + 位置 + 问题），要求重新提交完整产出。"""
    lines = [str(basePrompt), "", "【评审打回】上一轮产出未通过监督评审，请按以下发现逐条修正后重新提交完整产出："]
    for idx, finding in enumerate(verdict.get("findings") or [], 1):
        title = str(finding.get("title") or "").strip()
        body = str(finding.get("body") or "").strip()
        priority = str(finding.get("priority") or "").strip()
        location = str(finding.get("code_location") or "").strip()
        piece = f"{idx}. [{priority or 'P2'}] {title}"
        if location:
            piece += f"（{location}）"
        if body:
            piece += f"：{body}"
        lines.append(piece)
    if verdict.get("overall_explanation"):
        lines.append(f"（评审总评：{verdict['overall_explanation']}）")
    lines.append("修正后重新给出**完整**产出（不要只交差异部分）。")
    return "\n".join(lines)


async def runReviewLoop(
    run: Any,
    chatFn: Callable[[str], Awaitable[str]],
    verifyChannel: Callable[[Any], Awaitable[Any]],
    firstReport: str,
) -> ReviewResult:
    """评审主循环：评审 → 不通过带 findings 回炉一次 → 再评审。

    setPhase 由调用方注入（swarm._run_member 里把 run.status 切到 in_review/running），
    让 status 工具/前端在评审期间能看到真实相位。
    """
    if not reviewNeededFor(run):
        return ReviewResult(report=firstReport, info=None)

    # 惰性导入：swarm 的相位常量是唯一出处；本模块被 swarm 导入，函数内取用避免环。
    from neurova.agent.swarm import SUBAGENT_IN_REVIEW, SUBAGENT_RUNNING

    report = firstReport
    rounds = 0
    while True:
        run.status = SUBAGENT_IN_REVIEW
        try:
            verdict = await run_review(
                verifyChannel,
                review_target=report,
                focus=_focusOf(run),
            )
        except Exception as exc:  # noqa: BLE001 - 评审通道故障=评审不可用，诚实降级不误杀
            logger.warning(
                "Swarm: 评审子会话通道故障（%s），run %s 诚实放行并标注",
                str(exc)[:120], getattr(run, "subagent_id", "?"),
            )
            run.status = SUBAGENT_RUNNING
            return ReviewResult(
                report=report,
                info={"passed": None, "skipped": "reviewer_unavailable",
                      "detail": str(exc)[:200], "rounds": rounds},
            )
        if not verdict.get("parse_ok", False):
            logger.warning(
                "Swarm: 评审子会话不可用（%s），run %s 诚实放行并标注",
                str(verdict.get("raw", ""))[:120], getattr(run, "subagent_id", "?"),
            )
            run.status = SUBAGENT_RUNNING
            return ReviewResult(
                report=report,
                info={"passed": None, "skipped": "reviewer_unavailable",
                      "detail": str(verdict.get("raw", ""))[:200], "rounds": rounds},
            )
        if str(verdict.get("overall_correctness")) == "correct":
            run.status = SUBAGENT_RUNNING
            return ReviewResult(
                report=report,
                info={**verdict, "passed": True, "rounds": rounds, "reworked": rounds > 0},
            )
        if rounds >= MAX_REVIEW_ROUNDS:
            findings = verdict.get("findings") or []
            titles = "；".join(str(f.get("title") or "") for f in findings[:5]) or "评审未通过"
            run.status = SUBAGENT_RUNNING
            return ReviewResult(
                report=report,
                info={**verdict, "passed": False, "rounds": rounds, "reworked": rounds > 1},
                failedReason=f"review_failed（监督评审未通过：{titles}）",
                cause="review_failed",
            )
        rounds += 1
        logger.info(
            "Swarm: 评审未通过，回炉第 %d 次（run %s）",
            rounds, getattr(run, "subagent_id", "?"),
        )
        run.status = SUBAGENT_RUNNING
        report = await chatFn(reviewRevisionInstructions(renderBase(run), verdict))


def renderBase(run: Any) -> str:
    """回炉提示词的基底 = 原始任务 + 任务书（与首次派生同源）。"""
    from neurova.agent.task_unit import renderTaskUnitPrompt

    return renderTaskUnitPrompt(getattr(run, "task", ""), getattr(run, "task_unit", None))
