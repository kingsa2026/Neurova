# -*- coding: utf-8 -*-
"""设备通知事件入库（2026-11-23 计划卡 A5 推送路径）。

手机端 NotificationListener 采集的通知经 device:event 帧推到后端，按设备
分文件落 JSONL（数据根 `device_notifications/<pairing_id>.jsonl`，保留最近
500 行）；REST 读面（属主 JWT）供面板与 agent 拉取。记忆沉淀（D6）另案，
不在本模块范围。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

from neurova.core.data_root import dataPath
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_MAX_LINES = 500
_lock = threading.Lock()

__all__ = ["recordDeviceEvents", "readDeviceEvents", "resetForTests"]


def _safeId(pairingId: str) -> str:
    return "".join(ch for ch in str(pairingId or "") if ch.isalnum() or ch in "._-")


def _pathFor(pairingId: str):
    from pathlib import Path

    return Path(dataPath("device_notifications")) / f"{_safeId(pairingId)}.jsonl"


def recordDeviceEvents(pairingId: str, userId: str, items: Any) -> int:
    """落一批通知事件；返回入库条数。非列表/无有效项返回 0（不抛——通知
    采集是旁路数据面，绝不影响 WS 主循环）。"""
    if not isinstance(items, list):
        return 0
    valid: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        package = str(item.get("package") or "")
        if not package:
            continue
        valid.append({
            "package": package,
            "title": str(item.get("title") or ""),
            "text": str(item.get("text") or ""),
            "posted_at": item.get("posted_at"),
        })
    if not valid:
        return 0
    now = time.time()
    try:
        with _lock:
            path = _pathFor(pairingId)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                for item in valid:
                    row = {
                        "pairing_id": pairingId,
                        "user_id": userId,
                        "received_at": now,
                        "item": item,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            _trim(path)
    except Exception as e:  # noqa: BLE001 - 入库失败只告警
        logger.warning("通知事件入库失败: %s", e)
        return 0
    return len(valid)


def readDeviceEvents(pairingId: str, limit: int = 50) -> List[Dict[str, Any]]:
    """按设备读最近通知事件（旧→新，最多 limit 条）。"""
    path = _pathFor(pairingId)
    if not path.exists():
        return []
    bounded = max(1, min(int(limit), 500))
    try:
        with _lock:
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
    except Exception as e:  # noqa: BLE001
        logger.warning("通知事件读取失败: %s", e)
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-bounded:]:
        try:
            rows.append(json.loads(line))
        except Exception:  # noqa: BLE001 - 坏行跳过
            continue
    return rows


def _trim(path) -> None:
    """超上限重写保留尾部（有界账本，对齐 mobile_ws_events 老化语义）。"""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
        if len(lines) <= _MAX_LINES:
            return
        with open(path, "w", encoding="utf-8") as handle:
            handle.writelines(lines[-_MAX_LINES:])
    except Exception as e:  # noqa: BLE001
        logger.debug("通知事件账本裁剪失败: %s", e)


def resetForTests() -> None:
    """测试隔离占位：数据根注入即完成隔离（无进程内缓存）。"""
    return None
