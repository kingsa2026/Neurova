# -*- coding: utf-8 -*-
"""技能库 cold/warm A/B 评测 harness。

回答的问题
已有 simulated/文本进化 A/B，但"库级 cold/warm"对照此前没有。）

输出/reward/验收目标打包成"反馈技能"注入，等价于带答案重放，见
 §2.11）：

1. 执行面只见任务：executor 签名 (task_input, *, skills_enabled, seed)，
   seed 只允许 sanitize_warm_seed 白名单字段（任务输入/成功工具序列/
   无答案摘要），verifier/reward/expected/acceptance 等键即抛 SeedLeakError；
2. 评分面才见预期：expected 仅用于打分，绝不进 executor 参数；
3. 如实报告 fixed/broken 双矩阵——warm 退化不得被聚合数字吞掉；
4. 冻结变量：双臂同任务集同 executor 同判定，唯一开关=skills_enabled。

用法（离线评测/回归门）：

    report = await run_cold_warm_ab(cases, my_executor)
    # {"cold_pass_rate": .5, "warm_pass_rate": .75, "delta": .25,
    #  "fixed": [...], "broken": [...], "n": 4}

真实接线（评测 runner 注入 agent 执行器 + 技能库开关）由调用方组装；
本模块只提供方法论正确的 harness 与泄漏门。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

__all__ = [
    "SeedLeakError",
    "sanitize_warm_seed",
    "build_seed_from_successful_run",
    "collect_warm_seeds_from_patterns",
    "make_agent_ab_executor",
    "run_cold_warm_ab",
]

# warm 种子白名单（仅"怎么做的"，禁"答案是什么"）
_SEED_ALLOWED_KEYS = frozenset({"task_input", "tool_sequence", "summary"})
# 答案形态键黑名单（子串命中即拒，宁严勿漏）
_SEED_LEAK_MARKERS = (
    "verifier",
    "reward",
    "expected",
    "acceptance",
    "test_stdout",
    "ground_truth",
    "answer",
    "target_value",
)


class SeedLeakError(ValueError):
    """warm 种子携带答案形态字段（会把 A/B 变成带答案重放）。"""


def sanitize_warm_seed(seed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """白名单过滤 + 黑名单拒收。None 原样返回；未知键丢弃；泄漏键抛错。"""
    if seed is None:
        return None
    if not isinstance(seed, dict):
        raise SeedLeakError(f"warm 种子必须是 dict，实际 {type(seed).__name__}")
    for key in seed:
        low = str(key).lower()
        if any(m in low for m in _SEED_LEAK_MARKERS):
            raise SeedLeakError(f"warm 种子含答案形态键 {key!r}（A/B 可信度红线）")
    return {k: v for k, v in seed.items() if k in _SEED_ALLOWED_KEYS}


def build_seed_from_successful_run(run_record: Dict[str, Any]) -> Dict[str, Any]:
    """从成功执行记录构造最小 warm 种子（只留输入+工具序列，剥答案）。"""
    if not isinstance(run_record, dict) or not run_record.get("success"):
        raise ValueError("warm 种子只能来自成功执行记录")
    seed: Dict[str, Any] = {"task_input": str(run_record.get("task_input", ""))}
    seq = run_record.get("tool_sequence")
    if isinstance(seq, list):
        seed["tool_sequence"] = [str(t) for t in seq]
    summary = run_record.get("summary")
    if isinstance(summary, str):
        seed["summary"] = summary
    return sanitize_warm_seed(seed)


def collect_warm_seeds_from_patterns(patterns: List[Any], min_independent_successes: int = 2) -> List[Dict[str, Any]]:
    """从 AutoSkillBuilder 的 ToolPattern 物化 warm 种子集（P2-4 replay 接线）。

 采集纪律：
    - 只取**成功证据**：pattern.source_evidence 中 "s" 源数 ≥ min_independent_successes
      （单源自证不入种子——回声室红线）；
    - 字段白名单：task_input←上下文关键词（非答案）、tool_sequence←成功序列、
      summary=模式统计摘要；全程经 sanitize_warm_seed，verifier/reward 形态键
      结构上不可能混入。
    """
    seeds: List[Dict[str, Any]] = []
    for p in patterns or []:
        evidence = getattr(p, "source_evidence", None) or {}
        independent = sum(1 for v in evidence.values() if v == "s")
        if independent < max(1, int(min_independent_successes)):
            continue
        seq = [str(t) for t in (getattr(p, "tool_sequence", None) or [])]
        if len(seq) < 2:
            continue
        keywords = " ".join(str(k) for k in (getattr(p, "context_keywords", None) or [])[:6])
        seed = build_seed_from_successful_run(
            {
                "task_input": keywords or seq[0],
                "tool_sequence": seq,
                "success": True,
                "summary": f"跨 {independent} 个独立任务复现的成功序列",
            }
        )
        seeds.append(seed)
    return seeds


def make_agent_ab_executor(agent, *, sender: str = "ab-eval"):
    """把真实 Agent 包成 run_cold_warm_ab 的 executor（P2-4 replay 接线）。

    cold 臂 = turn 级 skills_off 上下文（tool schema 与技能目录同时缺席，
    见 orchestrator Wave E 守卫）；warm 臂 = 正常，可带白名单种子（仅工具
    序列/无答案摘要，经 sanitize 门）。每臂独立设置/复位 ContextVar，
    同进程可安全交替。expected/verifier 不经过本函数——泄漏红线由 harness
    调用方与本适配器的签名共同保证。
    """
    from neurova.core import turn_context

    async def _run(task_input: str, *, skills_enabled: bool, seed: Optional[Dict[str, Any]] = None) -> str:
        text = str(task_input or "")
        if skills_enabled and seed and seed.get("tool_sequence"):
            text += "\n\n（历史成功路径参考：" + " → ".join(seed["tool_sequence"]) + "）"
        token = turn_context.set_turn_skills_off(not skills_enabled)
        try:
            result = await agent.process_message(text, sender=sender)
            return str(getattr(result, "response", None) or result)
        finally:
            turn_context.reset_turn_skills_off(token)

    return _run


async def run_cold_warm_ab(
    cases: List[Dict[str, Any]],
    executor: Callable[..., Awaitable[str]],
) -> Dict[str, Any]:
    """双臂对照：cold=skills_enabled False / warm=True（可带白名单种子）。

    case: {"task_input": str, "expected": str, "warm_seed"?: dict}
    判定：executor 返回包含 expected（大小写不敏感子串）记 pass。
    """
    if not cases:
        return {"cold_pass_rate": 0.0, "warm_pass_rate": 0.0, "delta": 0.0,
                "fixed": [], "broken": [], "n": 0}

    seeds = [sanitize_warm_seed(c.get("warm_seed")) for c in cases]

    async def _arm(enabled: bool) -> List[bool]:
        outcomes: List[bool] = []
        for case, seed in zip(cases, seeds):
            result = await executor(
                str(case.get("task_input", "")),
                skills_enabled=enabled,
                seed=seed if enabled else None,
            )
            expected = str(case.get("expected", ""))
            outcomes.append(bool(expected) and expected.lower() in str(result).lower())
        return outcomes

    cold = await _arm(False)
    warm = await _arm(True)
    n = len(cases)
    fixed = [c.get("task_input") for c, cc, wc in zip(cases, cold, warm) if wc and not cc]
    broken = [c.get("task_input") for c, cc, wc in zip(cases, cold, warm) if cc and not wc]
    return {
        "cold_pass_rate": sum(cold) / n,
        "warm_pass_rate": sum(warm) / n,
        "delta": (sum(warm) - sum(cold)) / n,
        "fixed": fixed,
        "broken": broken,
        "n": n,
    }
