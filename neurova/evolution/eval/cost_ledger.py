"""每任务成本账 + Cost-of-Pass 读数 + 进化成本软门（HN1/HC1，2026-11-13）。

来历：HarnessPro 对照（docs/08-research/harnesspro_vs_neurova_cost_aware_
harness_rsi_comparison_2026-11-13.md）断点 HN1——本仓成本只记账不进目标：
`usage_accounting` 记到「调用/模型/用户」粒度，`runner.cost_*` 是文本长度
代理（P1-5），执行/判分的真实 token/费用没有按任务落账，提案面没有成本门。

本模块补三件事（不与 P1-5 的长度代理竞争——那是「文本膨胀」判据，这是
「执行花费」账目，两回事各占一格）：

1. **每任务成本账**：runner 在每次单例评测（执行+判分）前后取进程级
   usage 快照差分，按臂（baseline/candidate/probe/anchor/heldout/…）落账。
   快照差分与 `agent_turns_tokens`（E1）同口径：进程级、并发 LLM 活动会
   并入（单机部署形态的已知边界，如实声明）。
2. **CoP（Cost-of-Pass）**：臂总成本 / 通过数（score ≥ pass_score 且未
   失败）。零通过 ⇒ None 不是 0——0 会被读成「免费通过」；无 usage 事件 ⇒
   state="no_usage_events"——0 是「没量到」不是「没花钱」。
3. **成本软门**：候选臂成本相对基线臂涨幅超阈值 ⇒ 提案
   `requires_manual_review=True`（不自动应用、也不拒绝——钱的事人说了算）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: 结果面里每任务明细的外露上限（审计面防膨胀；总数另计 tasks_total）
_MAX_TASK_ROWS = 20


def usageSnapshot() -> Dict[str, Any]:
    """进程级 usage 快照：{"tokens": int, "cost_usd": float}。

    单源取 `core.usage_accounting`（全部 LLM 调用方共用的那本账）。
    独立成模块级函数是为了让 runner 以模块属性访问（可测试注入假快照），
    不是第二本账。
    """
    from neurova.core.usage_accounting import get_usage_accounting

    snap = get_usage_accounting().snapshot()
    return {
        "tokens": int(snap["total"]["total_tokens"] or 0),
        "cost_usd": float(snap.get("total_cost") or 0.0),
    }


def usageDelta(before: Dict[str, Any], after: Dict[str, Any]) -> tuple:
    """两次快照的差分 → (tokens, cost_usd)。负差分（记账面被清/换进程）
    按 0 处理，不产假成本（与 `tokensDelta` 同一纪律）。"""
    try:
        tokens = int(after["tokens"]) - int(before["tokens"])
    except (TypeError, ValueError, KeyError):
        tokens = 0
    try:
        cost = float(after["cost_usd"]) - float(before["cost_usd"])
    except (TypeError, ValueError, KeyError):
        cost = 0.0
    return (tokens if tokens > 0 else 0), (cost if cost > 0.0 else 0.0)


@dataclass
class TaskCostRecord:
    """一次单例评测（执行+判分）的任务级成本记录。"""

    task_input: str
    arm: str
    tokens: int
    cost_usd: float
    score: float
    failed: bool
    passed: bool


class EvalCostLedger:
    """一轮进化运行的任务级成本账（run 作用域，每轮 run() 重建）。

    线程安全不设防：runner 的评测链是单事件循环内串行/asyncio.gather——
    add() 只在 `_score_example` 收尾处调用，与 usage 快照同任务上下文；
    跨线程并发写账不是本类的运行形态（与 runner 的 eval_errors 计数同假设）。
    """

    def __init__(self, pass_score: float = 0.5):
        self._pass_score = float(pass_score)
        self._records: List[TaskCostRecord] = []

    def add(self, *, task_input: str, arm: str, tokens: int, cost_usd: float,
            score: float, failed: bool) -> None:
        passed = (not failed) and float(score) >= self._pass_score
        self._records.append(
            TaskCostRecord(task_input=str(task_input), arm=str(arm or "unlabeled"),
                           tokens=int(tokens), cost_usd=float(cost_usd),
                           score=float(score), failed=bool(failed), passed=passed))

    def _armSummary(self, records: List[TaskCostRecord]) -> Dict[str, Any]:
        tokens = sum(r.tokens for r in records)
        cost = sum(r.cost_usd for r in records)
        passed = sum(1 for r in records if r.passed)
        tasks = len(records)
        summary: Dict[str, Any] = {
            "tasks": tasks,
            "tokens": tokens,
            "cost_usd": round(cost, 6),
            "passed": passed,
            "cost_per_case_tokens": round(tokens / tasks, 2) if tasks else 0.0,
            "cost_per_case_usd": round(cost / tasks, 6) if tasks else 0.0,
            # CoP：分母是「通过」不是「评测数」；零通过 ⇒ None（无定义），
            # 不是 0——0 会被读成「免费通过」。
            "cop_tokens": round(tokens / passed, 2) if passed else None,
            "cop_usd": round(cost / passed, 6) if passed else None,
        }
        return summary

    def summarize(self) -> Dict[str, Any]:
        arms: Dict[str, List[TaskCostRecord]] = {}
        for r in self._records:
            arms.setdefault(r.arm, []).append(r)
        summaries = {arm: self._armSummary(rows) for arm, rows in sorted(arms.items())}
        total_tokens = sum(s["tokens"] for s in summaries.values())
        measured = any(
            s["tokens"] > 0 or s["cost_usd"] > 0 for s in summaries.values())
        return {
            "state": "measured" if measured else "no_usage_events",
            "pass_score": self._pass_score,
            "arms": summaries,
            "tasks_total": len(self._records),
            "tasks": [
                {
                    "task_input": r.task_input[:80],
                    "arm": r.arm,
                    "tokens": r.tokens,
                    "cost_usd": round(r.cost_usd, 6),
                    "score": round(r.score, 4),
                    "failed": r.failed,
                    "passed": r.passed,
                }
                for r in self._records[:_MAX_TASK_ROWS]
            ],
        }


def costSoftGateVerdict(cost_summary: Optional[Dict[str, Any]], *,
                        ratio_threshold: float, enabled: bool = True) -> Dict[str, Any]:
    """成本软门的**唯一**判定实现（service 提案面消费，不在此自动应用/拒绝）。

    - disabled / 未量到（no_usage_events、基线零成本）⇒ 诚实不判，不冒充通过；
    - 候选臂成本相对基线臂涨幅 > ratio_threshold ⇒ manual_review（人工复核）；
    - 否则 within_budget。
    """
    if not enabled:
        return {"state": "disabled"}
    summary = cost_summary or {}
    if summary.get("state") != "measured":
        return {"state": "unmeasured", "reason": str(summary.get("state") or "no_usage_events")}
    arms = summary.get("arms") or {}
    base_usd = float((arms.get("baseline") or {}).get("cost_usd") or 0.0)
    cand_usd = float((arms.get("candidate") or {}).get("cost_usd") or 0.0)
    if base_usd <= 0.0:
        return {"state": "unmeasured", "reason": "baseline_cost_zero"}
    ratio = (cand_usd - base_usd) / base_usd
    if ratio > float(ratio_threshold):
        return {
            "state": "manual_review",
            "ratio": round(ratio, 4),
            "threshold": float(ratio_threshold),
            "baseline_usd": round(base_usd, 6),
            "candidate_usd": round(cand_usd, 6),
        }
    return {"state": "within_budget", "ratio": round(ratio, 4),
            "threshold": float(ratio_threshold)}


def deploymentCostDelta(cost_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """V6 部署形态成本差（VideoEvolve 对照 2026-11-14）：胜者相对基线臂的
    **每任务执行成本差**（tokens/费用），给审批人看「采纳后每任务多花多少」——
    开发搜索的花费（成本账自身）与部署形态的花费（本读数）分开计量，对应
    论文「进化后调用数 0.996→1.963」的披露纪律。

    - 未量到（no_usage_events / 缺任一臂）⇒ state=unmeasured + 原因，不冒充 0；
    - measured ⇒ 每任务 tokens/费用差 + 相对比例（基线零成本 ⇒ None，不产
      无穷大）+ CoP 两列（每任务「通过成本」的两侧对照）。

    唯一实现点：提案面与详情面都取这里，不各算一遍。
    """
    summary = cost_summary or {}
    arms = summary.get("arms") or {}
    base = arms.get("baseline") or {}
    cand = arms.get("candidate") or {}
    if summary.get("state") != "measured" or not base or not cand:
        return {"state": "unmeasured",
                "reason": str(summary.get("state") or "no_usage_events")}
    base_usd = float(base.get("cost_per_case_usd") or 0.0)
    cand_usd = float(cand.get("cost_per_case_usd") or 0.0)
    base_tokens = float(base.get("cost_per_case_tokens") or 0.0)
    cand_tokens = float(cand.get("cost_per_case_tokens") or 0.0)
    return {
        "state": "measured",
        "baseline_per_case_usd": round(base_usd, 6),
        "candidate_per_case_usd": round(cand_usd, 6),
        "delta_per_case_usd": round(cand_usd - base_usd, 6),
        # 基线零成本时比例无定义 ⇒ None（不是 0 也不是 inf）
        "delta_ratio": (round((cand_usd - base_usd) / base_usd, 4)
                        if base_usd > 0 else None),
        "baseline_per_case_tokens": round(base_tokens, 2),
        "candidate_per_case_tokens": round(cand_tokens, 2),
        "delta_per_case_tokens": round(cand_tokens - base_tokens, 2),
        "baseline_cop_usd": base.get("cop_usd"),
        "candidate_cop_usd": cand.get("cop_usd"),
    }
