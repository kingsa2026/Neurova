# -*- coding: utf-8 -*-
"""H-4 蜂群 run 级事件归档（JSONL 追加账本）+ 因果链 + per-run 全序 seq（F2）。

每个子代理 run 一份追加式事件账本，落 `<数据根>/swarm_runs/<subagentId>.events.jsonl`；
事件带 `event_id` 与 `causation_id`（指向同 run 内紧邻前一事，链头为空）——排查时
从任一事回溯整条链。`seq` 为该账本文件内从 1 起的单调序号（chunk/tool_call/
permission/terminal 同账本同 seq，先后可判定；写入在全局锁内，文件序＝seq 序）。
`lineage`（F5 谱系：tenant/team/agentPath/trace）非空时随事件入档。
与信封同纪律：**正文不进账本**（task 只留截断摘要，报告/错误全文在 member 会话
与主链路）。fail-open：归档故障绝不阻断蜂群主流程（调用方兜）。
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()

# per-路径 seq 计数缓存（F2 全序）：键 = 账本文件绝对路径字符串。
# 首次遇到该路径时回扫文件取既有最大 seq 续起；此后进程内自增。
# 读写都只在 _LOCK 内发生，文件追加序与 seq 序天然一致。
_SEQ_CACHE: Dict[str, int] = {}


def _eventsPath(subagentId: str):
    from neurova.core.data_root import dataPath

    safe = "".join(ch for ch in str(subagentId or "") if ch.isalnum() or ch in "._-")
    if not safe:
        raise ValueError("subagent_id 非法，拒绝落盘")
    return Path(dataPath("swarm_runs")) / f"{safe}.events.jsonl"


def scanMaxLedgerSeq(path: Path) -> int:
    """回扫一份 JSONL 账本，取既有记录里的最大 seq（无 seq 行/坏行容错）。

    纯读取、无共享可变态：events 与 frames 两条账本各自持锁调它，
    计数互不干扰（seq 按文件路径区分，天然独立单调）。
    """
    max_seq = 0
    if not path.exists():
        return max_seq
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                try:
                    seq = int(record.get("seq", -1))
                except (TypeError, ValueError):
                    continue
                if seq > max_seq:
                    max_seq = seq
    except OSError as exc:
        logger.debug("账本 seq 回扫失败（按空账本续起）: %s", exc)
    return max_seq


def _nextSeqLocked(path: Path) -> int:
    """取该路径下一个 seq。**必须在持有 _LOCK 时调用**；首次遇路径回扫文件。"""
    key = str(path)
    if key not in _SEQ_CACHE:
        _SEQ_CACHE[key] = scanMaxLedgerSeq(path)
    _SEQ_CACHE[key] += 1
    return _SEQ_CACHE[key]


def appendRunEvent(
    subagentId: str, eventType: str,
    payload: Optional[Dict[str, Any]] = None, causationId: str = "",
    lineage: Optional[Dict[str, Any]] = None,
) -> str:
    """追加一条 run 事件，返回 event_id（调用方据以串因果链）。

    ``lineage``（F5 谱系：tenant/team/agentPath/trace）非空时入档。
    """
    eventId = f"evt_{uuid.uuid4().hex[:12]}"
    record = {
        "event_id": eventId,
        "type": str(eventType or ""),
        "subagent_id": str(subagentId or ""),
        "causation_id": str(causationId or ""),
        "payload": payload or {},
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    if lineage:
        record["lineage"] = dict(lineage)
    path = _eventsPath(subagentId)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        record["seq"] = _nextSeqLocked(path)
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
