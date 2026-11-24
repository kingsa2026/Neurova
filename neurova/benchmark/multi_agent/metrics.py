# -*- coding: utf-8 -*-
"""指标聚合：成功率 / 均分 / 不可解题识别 / 开销对照。纯函数，输入 runner 的事实记录。"""
from __future__ import annotations

from typing import Dict, List


def aggregate(results: List[dict]) -> Dict[str, dict]:
    """按模式聚合。逐条 result 由 runner 产出（见 BenchRunner.runTask）。"""
    by_mode: Dict[str, List[dict]] = {}
    for r in results:
        by_mode.setdefault(r.get("mode", "unknown"), []).append(r)

    out: Dict[str, dict] = {}
    for mode, items in by_mode.items():
        total = len(items)
        # P0-② 器械故障≠任务失败：failure_class 标记的行（派发/判据异常）没有
        # 质量证据，不进成功率与均分的分母；单列 infra_failed 计数保持可见。
        # agent 返回体 error / 治理拒绝是实测结局，仍算量出来的行。
        judged = [r for r in items if not r.get("failure_class")]
        passed = sum(1 for r in judged if r.get("passed"))
        scores = [float(r.get("score") or 0.0) for r in judged]
        unsolvable = [r for r in items if r.get("unsolvable")]
        unsolvable_ok = sum(1 for r in unsolvable if r.get("passed"))
        elapsed = [float(r["elapsed_seconds"]) for r in items if r.get("elapsed_seconds") is not None]
        # S1-1A：usage 列优先（runner 回传的规范键）；无 usage 的旧记录回退 legacy tokens
        def _usageNum(r: dict, key: str) -> float:
            usage = r.get("usage") or {}
            value = usage.get(key)
            return float(value) if isinstance(value, (int, float)) else 0.0

        promptTokens = [ _usageNum(r, "promptTokens") for r in items ]
        completionTokens = [ _usageNum(r, "completionTokens") for r in items ]
        steps = [ _usageNum(r, "steps") for r in items ]
        toolCalls = [ _usageNum(r, "toolCalls") for r in items ]
        tokens = [
            float((r.get("usage") or {}).get("totalTokens") or r.get("tokens") or 0.0)
            for r in items
        ]
        # P3-3：按思考档位（effort_inference）分档聚合——同任务集在不同档位下的表现变量
        # （只聚合量出来的行，器械故障不冒充某档位的 0 分）
        byEffort: Dict[str, dict] = {}
        for r in judged:
            bucket = byEffort.setdefault(str(r.get("effort") or "unknown"),
                                         {"task_count": 0, "passed_count": 0, "_scores": []})
            bucket["task_count"] += 1
            if r.get("passed"):
                bucket["passed_count"] += 1
            bucket["_scores"].append(float(r.get("score") or 0.0))
        effortOut: Dict[str, dict] = {}
        for level in sorted(byEffort):
            b = byEffort[level]
            effortOut[level] = {
                "task_count": b["task_count"],
                "passed_count": b["passed_count"],
                "success_rate": round(b["passed_count"] / b["task_count"], 4),
                "mean_score": round(sum(b["_scores"]) / len(b["_scores"]), 2),
            }
        out[mode] = {
            "task_count": total,
            "passed_count": passed,
            "success_rate": round(passed / len(judged), 4) if judged else 0.0,
            "mean_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
            "infra_failed": total - len(judged),
            "unsolvable_total": len(unsolvable),
            "unsolvable_identified": unsolvable_ok,
            "unsolvable_identified_rate": round(unsolvable_ok / len(unsolvable), 4) if unsolvable else None,
            "mean_elapsed_seconds": round(sum(elapsed) / len(elapsed), 3) if elapsed else None,
            "total_tokens": sum(tokens) if tokens else None,
            # S1-1A：usage/轨迹效率聚合列（报告与只读端点共用这份口径）
            "total_prompt_tokens": int(sum(promptTokens)),
            "total_completion_tokens": int(sum(completionTokens)),
            "total_steps": int(sum(steps)),
            "total_tool_calls": int(sum(toolCalls)),
            "mean_steps": round(sum(steps) / len(steps), 2) if steps else None,
            "mean_tool_calls": round(sum(toolCalls) / len(toolCalls), 2) if toolCalls else None,
            "error_count": sum(1 for r in items if r.get("error")),
            "by_effort": effortOut,
        }
    return out


def compare(results: List[dict]) -> dict:
    """swarm 相对 solo 的开销对照（同任务集）。缺任一模式则返回空差异。"""
    by_mode = aggregate(results)
    solo, swarm = by_mode.get("solo"), by_mode.get("swarm")
    if not solo or not swarm:
        return {"available": False}
    elapsed_delta = None
    if solo.get("mean_elapsed_seconds") is not None and swarm.get("mean_elapsed_seconds") is not None:
        elapsed_delta = round(swarm["mean_elapsed_seconds"] - solo["mean_elapsed_seconds"], 3)
    token_multiplier = None
    if solo.get("total_tokens") and swarm.get("total_tokens"):
        token_multiplier = round(swarm["total_tokens"] / max(solo["total_tokens"], 1), 3)
    return {
        "available": True,
        "success_rate_delta": round(swarm["success_rate"] - solo["success_rate"], 4),
        "mean_score_delta": round(swarm["mean_score"] - solo["mean_score"], 2),
        "elapsed_delta_seconds": elapsed_delta,
        "token_multiplier": token_multiplier,
    }
