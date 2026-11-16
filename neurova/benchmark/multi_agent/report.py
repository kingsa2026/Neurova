# -*- coding: utf-8 -*-
"""评测报告：JSON 结构 + Markdown 渲染 + 原子落盘（temp+replace，与 rag_eval 同纪律）。"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def buildReport(results: List[dict], metrics: Dict[str, dict], comparison: dict) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "comparison": comparison,
        "tasks": results,
    }


def renderMarkdown(report: dict) -> str:
    lines: List[str] = []
    lines.append("# 多 Agent 协作评测报告（multi-agent bench）")
    lines.append("")
    lines.append(f"> 生成时间：{report.get('generated_at', '')}")
    lines.append("")

    comparison = report.get("comparison") or {}
    if comparison.get("available"):
        lines.append("## 开销与收益对照（swarm − solo）")
        lines.append("")
        lines.append("| 指标 | 差值 |")
        lines.append("|---|---|")
        lines.append(f"| 成功率差 | {comparison.get('success_rate_delta')} |")
        lines.append(f"| 均分差 | {comparison.get('mean_score_delta')} |")
        lines.append(f"| 平均耗时差 (s) | {comparison.get('elapsed_delta_seconds')} |")
        lines.append(f"| Token 倍数 | {comparison.get('token_multiplier')} |")
        lines.append("")

    lines.append("## 分模式聚合")
    lines.append("")
    lines.append("| 模式 | 任务数 | 通过 | 成功率 | 均分 | 不可解(识别/总数) | 平均耗时(s) | Token | 错误 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for mode, m in (report.get("metrics") or {}).items():
        unsolvable = "-"
        if m.get("unsolvable_total"):
            unsolvable = f"{m.get('unsolvable_identified', 0)}/{m['unsolvable_total']}"
        lines.append(
            f"| {mode} | {m['task_count']} | {m['passed_count']} | {m['success_rate']} "
            f"| {m['mean_score']} | {unsolvable} | {m.get('mean_elapsed_seconds')} "
            f"| {m.get('total_tokens')} | {m.get('error_count', 0)} |"
        )
    lines.append("")

    lines.append("## 逐任务明细")
    lines.append("")
    lines.append("| 任务 | 模式 | 通过 | 得分 | 耗时(s) | 错误/拒绝 |")
    lines.append("|---|---|---|---|---|---|")
    for t in report.get("tasks") or []:
        err = t.get("error") or (f"rejected:{t.get('rejection_code')}" if t.get("rejected") else "")
        lines.append(
            f"| {t.get('task_id')} | {t.get('mode')} | {t.get('passed')} | {t.get('score')} "
            f"| {t.get('elapsed_seconds')} | {err} |"
        )
    lines.append("")
    return "\n".join(lines)


def saveReport(report: dict, path: str) -> str:
    """JSON 原子落盘（temp + os.replace），返回落点。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + target.name, dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return str(target)
