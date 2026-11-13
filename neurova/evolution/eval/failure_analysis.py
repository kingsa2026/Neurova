"""轨迹联合诊断消费层（R4，2026-11-13）。

来历：HarnessPro 对照（docs/08-research/harnesspro_vs_neurova_cost_aware_
harness_rsi_comparison_2026-11-13.md）§10.2 R4——tool_trace/环节证据/判分
反馈都已采集，但缺一层「聚合成结构化诊断 → 喂变异器」的消费者（HarnessPro
Trajectory Analyzer 的形态；采集与消费之间断链）。

本模块把一轮评测的失败证据聚合为**结构化诊断条目**：

- 按**归一化失败模式**分组（反馈首行去数字/路径/空白后作键——同因不同
  参数算同一类，避免「第 1 行失败/第 42 行失败」被拆成两类）；
- 每条：次数、占比、最差分、例证任务（≤3）、环节证据并集（capability
  gap kinds）、原始模式首行；
- 排序确定性：次数降序 → 模式名字典序；
- `diagnosisDigest` 渲染成变异器提示里的「联合诊断」段（紧凑、有界）。

纯函数、零 LLM/IO；失败证据已在 runner 侧脱敏（`_redact_eval_error`），
这里只做分组与排版，不新增外泄面。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

#: 诊断条目上限（变异器提示预算有界；超出按排序截断）
_MAX_ENTRIES = 5
#: 每条诊断的例证任务上限
_MAX_EXAMPLES = 3
#: 模式键的归一化长度
_PATTERN_CHARS = 80


def _patternKey(feedback: str) -> str:
    """失败模式归一化键：反馈首行、去数字、去路径片段、压缩空白。"""
    first_line = str(feedback or "").splitlines()[0] if str(feedback or "") else ""
    lowered = first_line.strip().lower()
    no_digits = re.sub(r"\d+", "N", lowered)
    no_paths = re.sub(r"[\w\-./\\]+\.(py|json|txt|md|log)\b", "FILE", no_digits)
    compressed = re.sub(r"\s+", " ", no_paths)
    return compressed[:_PATTERN_CHARS] if compressed else "(无反馈)"


def buildDiagnosis(failures: List[Any], *, max_entries: int = _MAX_ENTRIES) -> List[Dict[str, Any]]:
    """把失败证据聚合成结构化诊断条目（确定性：同输入同输出）。"""
    if not failures:
        return []
    groups: Dict[str, Dict[str, Any]] = {}
    total = len(failures)
    for failure in failures:
        key = _patternKey(getattr(failure, "feedback", ""))
        group = groups.setdefault(key, {
            "pattern": str(getattr(failure, "feedback", "") or "").splitlines()[0]
            if str(getattr(failure, "feedback", "") or "") else "(无反馈)",
            "key": key,
            "count": 0,
            "worst_score": None,
            "tasks": [],
            "env_kinds": set(),
        })
        group["count"] += 1
        score = getattr(failure, "score", None)
        if isinstance(score, (int, float)) and (
                group["worst_score"] is None or score < group["worst_score"]):
            group["worst_score"] = float(score)
        task = str(getattr(failure, "task_input", "") or "")
        if task and len(group["tasks"]) < _MAX_EXAMPLES:
            group["tasks"].append(task[:60])
        for kind in (getattr(failure, "environments", None) or []):
            if str(kind or "").strip():
                group["env_kinds"].add(str(kind))
    entries = []
    for group in groups.values():
        entries.append({
            "pattern": group["pattern"][:120],
            "count": group["count"],
            "share": round(group["count"] / total, 3) if total else 0.0,
            "worst_score": (round(group["worst_score"], 4)
                            if group["worst_score"] is not None else None),
            "tasks": group["tasks"],
            "env_kinds": sorted(group["env_kinds"]),
        })
    entries.sort(key=lambda e: (-e["count"], e["pattern"]))
    return entries[:max(1, int(max_entries))]


def diagnosisDigest(entries: List[Dict[str, Any]]) -> str:
    """诊断条目 → 变异器提示里的「联合诊断」段（紧凑文本；空 ⇒ 空串）。"""
    if not entries:
        return ""
    lines: List[str] = []
    for index, entry in enumerate(entries):
        parts = [f"模式{index + 1}: {entry['pattern']}",
                 f"出现 {entry['count']} 次（占比 {entry['share']:.0%}）"]
        if entry.get("worst_score") is not None:
            parts.append(f"最差分 {entry['worst_score']}")
        if entry.get("tasks"):
            parts.append("例证: " + "；".join(entry["tasks"]))
        if entry.get("env_kinds"):
            parts.append("环节证据: " + "/".join(entry["env_kinds"]))
        lines.append(" - " + "；".join(parts))
    return "\n".join(lines)
