"""构建批次的跨 surface 补偿日志（§12.13 残余风险）。

不做跨存储 2PC；每个 surface 各自事务提交，本模块记录「回到批次前」所需
的 undo 操作。`build_batch_compensate` 按逆序逐条执行，已补偿条目不重放。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.data_root import dataLanding
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_lock = threading.RLock()


def _journalDir() -> Path:
    override = os.environ.get("NEUROVA_BUILD_BATCH_JOURNAL_DIR", "")
    return Path(override) if override else Path(dataLanding("build_batches"))


def _batchPath(batchId: str) -> Path:
    safe = "".join(char for char in str(batchId) if char.isalnum() or char in "-_")
    return _journalDir() / f"{safe or 'unknown'}.json"


def _load(batchId: str) -> Dict[str, Any]:
    path = _batchPath(batchId)
    if not path.is_file():
        return {"batch_id": batchId, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"batch_id": batchId, "entries": []}
        data.setdefault("batch_id", batchId)
        data.setdefault("entries", [])
        return data
    except (OSError, ValueError) as exc:
        logger.warning("批次补偿日志读取失败 %s: %s", path, exc)
        return {"batch_id": batchId, "entries": []}


def _save(batchId: str, data: Dict[str, Any]) -> None:
    path = _batchPath(batchId)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def recordCompensation(
    batchId: str,
    *,
    surface: str,
    action: str,
    payload: Dict[str, Any],
    actor: str = "",
    dedupeKey: str = "",
) -> bool:
    """记录一条 undo；同 dedupeKey 已有未补偿条目时跳过（画布只存批次前快照）。"""
    batchId = str(batchId or "").strip()
    if not batchId:
        return False
    key = dedupeKey or "{}:{}:{}".format(
        surface,
        action,
        payload.get("canvas_id")
        or payload.get("node_type")
        or payload.get("workflow_id")
        or payload.get("draft_workflow_id")
        or "",
    )
    with _lock:
        data = _load(batchId)
        entries: List[Dict[str, Any]] = data.setdefault("entries", [])
        for entry in entries:
            if entry.get("dedupe_key") == key and not entry.get("compensated_at"):
                return False
        entries.append(
            {
                "surface": str(surface),
                "action": str(action),
                "payload": dict(payload or {}),
                "actor": str(actor or ""),
                "dedupe_key": key,
                "recorded_at": time.time(),
                "compensated_at": 0,
                "result": {},
            }
        )
        _save(batchId, data)
        return True


def listCompensations(batchId: str, *, includeCompensated: bool = True) -> List[Dict[str, Any]]:
    with _lock:
        entries = list(_load(str(batchId or "")).get("entries") or [])
    if includeCompensated:
        return entries
    return [entry for entry in entries if not entry.get("compensated_at")]


def markCompensated(batchId: str, index: int, result: Dict[str, Any]) -> None:
    with _lock:
        data = _load(batchId)
        entries: List[Dict[str, Any]] = data.get("entries") or []
        if 0 <= index < len(entries):
            entries[index]["compensated_at"] = time.time()
            entries[index]["result"] = dict(result or {})
            _save(batchId, data)


__all__ = [
    "recordCompensation",
    "listCompensations",
    "markCompensated",
]
