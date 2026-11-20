# -*- coding: utf-8 -*-
"""neuacp 帧账本：一手事实流（JSONL 追加）+ 游标回放（设计文档 §3.2，拍板 D-A）。

与 H-4 治理账本（``swarm_event_log``）同目录、独立文件：
``<数据根>/swarm_runs/<subagentId>.frames.jsonl``。两流分工见设计文档 §4：
治理账本承载生命周期/治理投影（正文不进）；本账本承载**原生帧**（ACP JSON-RPC
消息 / plugin NDJSON 行解析出的 dict），脱敏后全量留痕、永不合成/推断，
供审计回放、时序判定与契约测试共用。

record 形态：``{"seq", "subagent_id", "direction", "frame", "lineage", "occurred_at"}``。
``seq`` 与 events 账本**各自独立**单调（流内全序，跨流不比较）；``frame`` 写盘前
必经 :func:`redactFrame`（拍板 D-A：留正文、脱敏前置）。

本模块**可抛异常**（参数非法/写盘失败原样上抛）；fail-open 由调用钩子负责
（acp_client/plugin_executor 的帧钩子全部 try/except，绝不阻断泵/发送）。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.agent.neuacp.redaction import redactFrame
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()

# per-路径 seq 计数缓存（与 events 账本各自独立；键 = frames 文件绝对路径）。
# 首次遇到该路径时回扫文件取既有最大 seq 续起；读写只在 _LOCK 内，保序优先。
_SEQ_CACHE: Dict[str, int] = {}

_DIRECTIONS = ("in", "out", "observed")


def _framesPath(subagentId: str) -> Path:
    """与 swarm_event_log._eventsPath 同规则：只留字母数字与 ``._-``，净化后为空即拒。"""
    from neurova.core.data_root import dataPath

    safe = "".join(ch for ch in str(subagentId or "") if ch.isalnum() or ch in "._-")
    if not safe:
        raise ValueError("subagent_id 非法，拒绝落盘")
    return Path(dataPath("swarm_runs")) / f"{safe}.frames.jsonl"


def appendFrame(
    subagentId: str, direction: str, frame: dict,
    *, lineage: Optional[Dict[str, Any]] = None,
) -> int:
    """落一帧进账本，返回本帧 seq。写盘前必经脱敏；参数非法原样抛 ValueError。"""
    key = str(subagentId or "").strip()
    if not key:
        raise ValueError("subagent_id 不能为空")
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction 非法：{direction!r}（只接受 in/out/observed）")
    path = _framesPath(key)
    record: Dict[str, Any] = {
        "subagent_id": key,
        "direction": direction,
        # 写盘前必经脱敏（拍板 D-A）：结构级字段名 + 值级单源，原帧不被修改
        "frame": redactFrame(frame if isinstance(frame, dict) else {}),
        "lineage": dict(lineage) if lineage else None,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        cache_key = str(path)
        if cache_key not in _SEQ_CACHE:
            from neurova.agent.swarm_event_log import scanMaxLedgerSeq

            _SEQ_CACHE[cache_key] = scanMaxLedgerSeq(path)
        _SEQ_CACHE[cache_key] += 1
        record["seq"] = _SEQ_CACHE[cache_key]
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record["seq"]


def readFrames(subagentId: str, afterSeq: int = 0, limit: int = 1000) -> List[Dict[str, Any]]:
    """按 seq 游标回放：返回 ``seq > afterSeq`` 的前 ``limit`` 条（文件序）。

    坏行跳过不致命；subagent_id 非法或文件不存在返回空列表（读侧宽容）。
    """
    try:
        path = _framesPath(subagentId)
    except ValueError:
        return []
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if len(out) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("跳过损坏帧行: %s", line[:80])
                continue
            if not isinstance(record, dict):
                continue
            try:
                seq = int(record.get("seq", -1))
            except (TypeError, ValueError):
                continue
            if seq > afterSeq:
                out.append(record)
    return out
