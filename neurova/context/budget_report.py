"""常驻上下文预算报告（N6，只读）。

只测量、不改写：把系统提示里每一段的字符数与预算上限记下来，供
`GET /v1/context/budget` 读取。常驻面的编辑契约/自动改写不在本模块。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Mapping, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_ALWAYS_ON_CAP = 64_000

# 与现有分段预算同源：技能目录 8000、工具描述 18000、工作区文档 16KB。
SEGMENT_CAPS: Dict[str, int] = {
    "skill_catalog": 8_000,
    "tools": 18_000,
    "workspace_docs": 16 * 1024,
}

_reports: Dict[str, Dict[str, Any]] = {}
_lock = threading.RLock()


def buildAlwaysOnBudgetReport(
    segments: Mapping[str, str], *, system_cap: int = DEFAULT_ALWAYS_ON_CAP
) -> Dict[str, Any]:
    """按段统计常驻文本；超总预算或超分段预算都显式列出。"""
    items = []
    for name, text in (segments or {}).items():
        chars = len(text or "")
        cap = SEGMENT_CAPS.get(name)
        items.append(
            {
                "segment": name,
                "chars": chars,
                "cap": cap,
                "over_cap": bool(cap is not None and chars > cap),
            }
        )
    items.sort(key=lambda item: (-item["chars"], item["segment"]))
    total = sum(item["chars"] for item in items)
    return {
        "measured_at": time.time(),
        "total_chars": total,
        "system_cap": int(system_cap),
        "over_budget": total > int(system_cap),
        "over_segment_caps": [item["segment"] for item in items if item["over_cap"]],
        "segments": items,
    }


def recordContextBudget(
    agent_id: str,
    segments: Mapping[str, str],
    *,
    system_cap: int = DEFAULT_ALWAYS_ON_CAP,
) -> Dict[str, Any]:
    """记录最近一次系统提示的常驻分段；同 agent 后写覆盖先写。"""
    report = buildAlwaysOnBudgetReport(segments, system_cap=system_cap)
    report["agent_id"] = str(agent_id or "default")
    if report["over_budget"]:
        logger.warning(
            "常驻上下文超总预算: agent=%s total=%s cap=%s",
            report["agent_id"], report["total_chars"], report["system_cap"],
        )
    if report["over_segment_caps"]:
        logger.warning(
            "常驻上下文分段超预算: agent=%s segments=%s",
            report["agent_id"], ",".join(report["over_segment_caps"]),
        )
    with _lock:
        _reports[report["agent_id"]] = report
    return report


def getContextBudget(agent_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        report = _reports.get(str(agent_id or "default"))
        return dict(report) if report is not None else None


def resetContextBudget() -> None:
    with _lock:
        _reports.clear()
