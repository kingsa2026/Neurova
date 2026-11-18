# -*- coding: utf-8 -*-
"""H-4 蜂群 run 级事件归档（JSONL 追加账本）+ 因果链（对照评测改进项）。

每个子代理 run 一份追加式事件账本，落 `<数据根>/swarm_runs/<subagentId>.events.jsonl`；
事件带 `event_id` 与 `causation_id`（指向同 run 内紧邻前一事，链头为空）——排查时
从任一事回溯整条链。与信封同纪律：**正文不进账本**（task 只留截断摘要，报告/错误
全文在 member 会话与主链路）。fail-open：归档故障绝不阻断蜂群主流程（调用方兜）。
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()


def _eventsPath(subagentId: str):
    from pathlib import Path

    from neurova.core.data_root import dataPath

    safe = "".join(ch for ch in str(subagentId or "") if ch.isalnum() or ch in "._-")
    if not safe:
        raise ValueError("subagent_id 非法，拒绝落盘")
    return Path(dataPath("swarm_runs")) / f"{safe}.events.jsonl"


def appendRunEvent(
    subagentId: str, eventType: str,
    payload: Optional[Dict[str, Any]] = None, causationId: str = "",
) -> str:
    """追加一条 run 事件，返回 event_id（调用方据以串因果链）。"""
    eventId = f"evt_{uuid.uuid4().hex[:12]}"
    record = {
        "event_id": eventId,
        "type": str(eventType or ""),
        "subagent_id": str(subagentId or ""),
        "causation_id": str(causationId or ""),
        "payload": payload or {},
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _eventsPath(subagentId)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return eventId


def readRunEvents(subagentId: str) -> List[Dict[str, Any]]:
    """读一份 run 的全部事件（测试与排查用；坏行跳过不致命）。"""
    try:
        path = _eventsPath(subagentId)
    except ValueError:
        return []
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("跳过损坏事件行: %s", line[:80])
    return out
