# -*- coding: utf-8 -*-
"""评测报告：JSON 结构 + Markdown 渲染 + 原子落盘（temp+replace，与 rag_eval 同纪律）。

S1-1E：报告落盘位置即只读端点的数据源（`<数据根>/benchmark/multi_agent/*.json`），
本模块提供 list/load 只读面，不建第二套存储。
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def buildReport(results: List[dict], metrics: Dict[str, dict], comparison: dict,
                taskIsolatedMemory: bool = False) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # S1-1C：报告注明是否按任务隔离记忆（正式对比默认开启）
        "task_isolated_memory": bool(taskIsolatedMemory),
        "metrics": metrics,
        "comparison": comparison,
        "tasks": results,
    }


def renderMarkdown(report: dict) -> str:
    lines: List[str] = []
    lines.append("# 多 Agent 协作评测报告（multi-agent bench）")
    lines.append("")
    lines.append(f"> 生成时间：{report.get('generated_at', '')}")
    isolated = report.get("task_isolated_memory")
    if isolated is not None:
        lines.append(f"> 记忆隔离（taskIsolatedMemory）：{'开启' if isolated else '关闭'}")
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
    lines.append("| 模式 | 任务数 | 通过 | 成功率 | 均分 | 不可解(识别/总数) | 平均耗时(s) | Token | 步数 | 工具数 | 错误 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for mode, m in (report.get("metrics") or {}).items():
        unsolvable = "-"
        if m.get("unsolvable_total"):
            unsolvable = f"{m.get('unsolvable_identified', 0)}/{m['unsolvable_total']}"
        lines.append(
            f"| {mode} | {m['task_count']} | {m['passed_count']} | {m['success_rate']} "
            f"| {m['mean_score']} | {unsolvable} | {m.get('mean_elapsed_seconds')} "
            f"| {m.get('total_tokens')} | {m.get('total_steps', '-')} "
            f"| {m.get('total_tool_calls', '-')} | {m.get('error_count', 0)} |"
        )
    lines.append("")

    # P3-3：思考档位变量（effort_inference）——同任务集按档位拆开的成功率/均分
    effortRows = [(mode, m.get("by_effort") or {})
                  for mode, m in (report.get("metrics") or {}).items()
                  if m.get("by_effort")]
    if effortRows:
        lines.append("## 思考档位变量（effort_inference）")
        lines.append("")
        for mode, byEffort in effortRows:
            lines.append(f"**{mode}**")
            lines.append("")
            lines.append("| 档位 | 任务数 | 通过 | 成功率 | 均分 |")
            lines.append("|---|---|---|---|---|")
            for level, b in byEffort.items():
                lines.append(
                    f"| {level} | {b['task_count']} | {b['passed_count']} "
                    f"| {b['success_rate']} | {b['mean_score']} |"
                )
            lines.append("")

    lines.append("## 逐任务明细")
    lines.append("")
    lines.append("| 任务 | 模式 | 通过 | 得分 | 耗时(s) | Token | 步数 | 工具数 | 轨迹(工具) | 错误/拒绝 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for t in report.get("tasks") or []:
        err = t.get("error") or (f"rejected:{t.get('rejection_code')}" if t.get("rejected") else "")
        usage = t.get("usage") or {}
        trajectory = t.get("trajectory") or {}
        toolsUsed = trajectory.get("toolsUsed") or []
        lines.append(
            f"| {t.get('task_id')} | {t.get('mode')} | {t.get('passed')} | {t.get('score')} "
            f"| {t.get('elapsed_seconds')} | {usage.get('totalTokens', '-')} "
            f"| {usage.get('steps', '-')} | {usage.get('toolCalls', '-')} "
            f"| {'→'.join(str(x) for x in toolsUsed) if toolsUsed else '-'} | {err} |"
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


# ── S1-1E：报告落盘位置的只读面（runner 落盘 → 端点取回，不建新存储） ──


def defaultReportDir() -> Path:
    """多 agent 基线报告的统一落点：`<数据根>/benchmark/multi_agent/`。"""
    from neurova.core.data_root import get_data_root

    return get_data_root() / "benchmark" / "multi_agent"


def defaultReportPath(reportId: str = "") -> str:
    """新报告的默认落点；未给 id 时按 UTC 时间 + 短随机串生成（时间序可排序）。"""
    if not reportId:
        reportId = (
            datetime.now(timezone.utc).strftime("bench-%Y%m%dT%H%M%SZ")
            + "-" + uuid.uuid4().hex[:6]
        )
    return str(defaultReportDir() / f"{reportId}.json")


def listReports(directory: Optional[str] = None) -> List[dict]:
    """列出已落盘的基线报告（新→旧）。只读面：读不到/坏文件如实跳过。"""
    base = Path(directory) if directory else defaultReportDir()
    if not base.exists():
        return []
    items: List[dict] = []
    for file in sorted(base.glob("*.json"), key=lambda p: p.name, reverse=True):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 坏文件跳过，不阻断列表
            continue
        if not isinstance(data, dict):
            continue
        items.append({
            "report_id": file.stem,
            "generated_at": data.get("generated_at"),
            "task_isolated_memory": data.get("task_isolated_memory"),
            "task_count": len(data.get("tasks") or []),
            "metrics": data.get("metrics"),
            "comparison": data.get("comparison"),
        })
    return items


def loadReport(reportId: str, directory: Optional[str] = None) -> Optional[dict]:
    """按 id 取回单份基线报告全文；不存在返回 None。"""
    base = Path(directory) if directory else defaultReportDir()
    file = base / f"{Path(reportId).stem}.json"
    if not file.exists():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 坏文件如实返回 None
        return None
    return data if isinstance(data, dict) else None
