# -*- coding: utf-8 -*-
"""SB-5 分诊 skip 样本回流（训练数据闭环）。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md
§5.3 训练数据三级来源第 2 级（人工标注回流）与 §8-SB-5。

职责：把分诊门 skip 掉的回合按特征快照落成 JSONL 样本
（`<数据根>/triage_skips.jsonl`），供 admin 复核改标（/coordination/
triage/skip-samples）后进入下一轮 NeuJudge 训练集。

纪律：
- 落盘是**遥测旁路**：`recordSkipSample` 对任何失败只 warning + 返回
  False，绝不外抛、绝不影响闸决策（调用方另计 `triage_feedback_errors`）；
- 线程安全：模块级 `threading.Lock` 串行化追加与重写；
- 文件损坏（坏行）读取时跳过不炸；relabel 用同目录临时文件 +
  `os.replace` 原子重写，不残留半截文件。

记录契约（一行一 JSON 对象，键序即写入序）：
{"sample_id": uuid4hex, "recorded_at": ISO8601, "conversation_id",
 "mode": "shadow"|"enforce", "source": "rules"|"model", "rule", "p",
 "features", "label": "not_actionable", "relabeled": false, "relabel_note": ""}
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.data_root import get_data_root
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 样本文件名（落在数据根下）。
SKIP_SAMPLES_FILENAME = "triage_skips.jsonl"

#: 复核标签全集（admin 改标面与端点 422 判定的单源）。
VALID_LABELS = ("actionable", "not_actionable")

#: skip 样本初始标签：分诊门的先验是"这一轮不值得响应"。
DEFAULT_LABEL = "not_actionable"

_lock = threading.Lock()


def _samplesPath() -> Path:
    """样本文件落点（调用时解析数据根——注入对延迟装配生效）。"""
    return get_data_root() / SKIP_SAMPLES_FILENAME


def _nowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compactWindow(events: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """窗口快照压缩：末尾 ≤10 条事件、单条内容 ≤120 字符（golden case 与
    admin 复核用；省空间且不含全量上下文）。"""
    compact: List[Dict[str, Any]] = []
    for event in (events or [])[-10:]:
        if not isinstance(event, dict):
            continue
        compact.append({
            "role": str(event.get("role") or ""),
            "content": str(event.get("content") or "")[:120],
            "timestamp": event.get("timestamp"),
        })
    return compact


def recordSkipSample(
    *,
    conversationId: str,
    source: str,
    rule: str,
    p: Optional[float] = None,
    features: Optional[Dict[str, Any]] = None,
    mode: str,
    window: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """追加一条 skip 样本；成功 True；任何失败 warning + False（绝不外抛）。

    `source`："rules"（规则 R2/R3 命中）或 "model"（灰区 NeuJudge p<SKIP_P）；
    `rule`：规则源为命中规则名；模型源为路由到模型的规则层裁决（default_allow）；
    `mode`："shadow" 或 "enforce"（shadow 也入样本，靠该字段区分）；
    `window`：skip 时刻的会话事件快照（压缩后落盘，供 golden case 与复核）。
    """
    record: Dict[str, Any] = {
        "sample_id": uuid.uuid4().hex,
        "recorded_at": _nowIso(),
        "conversation_id": str(conversationId or ""),
        "mode": str(mode or ""),
        "source": str(source or ""),
        "rule": str(rule or ""),
        "p": float(p) if p is not None else None,
        "features": dict(features or {}),
        "window": _compactWindow(window),
        "label": DEFAULT_LABEL,
        "relabeled": False,
        "relabel_note": "",
    }
    try:
        path = _samplesPath()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with _lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return True
    except Exception:  # noqa: BLE001 - 遥测 fail-soft：点名留痕，不炸闸决策
        logger.warning(
            "分诊 skip 样本落盘失败：conversation=%s", conversationId, exc_info=True
        )
        return False


def _readRecords(path: Path) -> List[Dict[str, Any]]:
    """读全部记录；坏行（非 JSON 对象）跳过不炸。"""
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def listSkipSamples(limit: int = 100) -> List[Dict[str, Any]]:
    """列出样本，最新在前，最多 limit 条。"""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 100
    if limit <= 0:
        return []
    with _lock:
        records = _readRecords(_samplesPath())
    return list(reversed(records[-limit:]))


def relabelSample(sampleId: str, newLabel: str, note: str = "") -> bool:
    """复核改标一条样本并原子重写文件。

    命中返回 True；找不到返回 False；`newLabel` 非法抛 ValueError
    （端点据以回 422，与"未找到 404"区分）。
    """
    if newLabel not in VALID_LABELS:
        raise ValueError(f"label 必须是 {VALID_LABELS} 之一，得到 {newLabel!r}")

    path = _samplesPath()
    with _lock:
        if not path.exists():
            return False
        lines = path.read_text(encoding="utf-8").splitlines()
        hitIndex = -1
        for idx, line in enumerate(lines):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed.get("sample_id") == sampleId:
                hitIndex = idx
                break
        if hitIndex < 0:
            return False
        try:
            target = json.loads(lines[hitIndex])
        except json.JSONDecodeError:
            return False
        target["label"] = newLabel
        target["relabeled"] = True
        target["relabel_note"] = str(note or "")
        lines[hitIndex] = json.dumps(target, ensure_ascii=False)
        # 原子重写：同目录临时文件 + os.replace（锁内串行，崩溃不留半截文件）。
        tmpPath = path.with_name(f"{path.name}.relabel-{uuid.uuid4().hex}.tmp")
        try:
            with tmpPath.open("w", encoding="utf-8") as fh:
                for line in lines:
                    fh.write(line + "\n")
            os.replace(tmpPath, path)
        except Exception:
            try:
                tmpPath.unlink()
            except OSError:
                pass
            raise
    return True


def _parseTimestamp(value) -> "datetime | None":
    """解析 ISO8601 时间戳；不可解析返回 None。naive 值按 UTC 兜底（样本库
    与 SessionSyncManager 事件都产 aware UTC，此处只为防手写数据混入 naive）。"""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def falseRescueStats(windowMinutes: float = 5.0, limit: int = 200) -> Dict[str, Any]:
    """误杀率统计（计划 §7 晋升判据的数据来源）。

    误杀定义：会话被分诊门 skip（或 shadow would-skip）后，`windowMinutes`
    分钟内出现人类新消息——说明被静音的是人类关心的内容，阈值需要回调。

    纯读：样本库（listSkipSamples）+ SessionSyncManager 现役事件窗口，
    不写任何状态；无样本时分母为零按 rate=0.0 处理，不外抛。
    """
    samples = [s for s in listSkipSamples(limit=limit)
               if s.get("mode") in ("shadow", "enforce")]
    if not samples:
        return {"samples": 0, "falseKills": 0, "falseRescueRate": 0.0,
                "windowMinutes": windowMinutes}
    from neurova.sync.session_sync_manager import get_session_sync_manager

    manager = get_session_sync_manager()
    windowSeconds = windowMinutes * 60.0
    falseKills = 0
    for sample in samples:
        conversationId = str(sample.get("conversation_id") or "")
        recordedAt = _parseTimestamp(sample.get("recorded_at"))
        if not conversationId or recordedAt is None:
            continue
        for event in manager.get_messages(conversationId, 50):
            if event.get("role") != "user":
                continue
            eventTs = _parseTimestamp(event.get("timestamp"))
            if eventTs is None:
                continue
            deltaSeconds = (eventTs - recordedAt).total_seconds()
            if 0.0 <= deltaSeconds <= windowSeconds:
                falseKills += 1
                break
    return {
        "samples": len(samples),
        "falseKills": falseKills,
        "falseRescueRate": round(falseKills / len(samples), 4),
        "windowMinutes": windowMinutes,
    }
