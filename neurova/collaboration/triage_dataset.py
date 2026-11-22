# -*- coding: utf-8 -*-
"""D-SB1/D-SB3 分诊训练数据集构建：真实会话窗口收割 + 规则/离线蒸馏弱标注。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md
§5.3 训练数据三级来源与 §8。本模块**只服务离线训练**（scripts/training/
train_neu_judge.py），不在任何运行链路上：

- D-SB3 真实训练数据源：从数据根的会话落盘文件
  （`<数据根>/<agent>/sessions/session_*.json`，role/content/timestamp
  与分诊窗口同构）收割对话窗口；
- D-SB1 离线 LLM 蒸馏：灰区窗口（规则弃权的 default_allow）可选用**既有
  LLM 分诊门**（`llm/triage.py` SmallBrainTriageGate）离线打弱标签——
  成本以 `distillLimit` 封顶、人工触发、运行时路径零改动；
- 标注优先级：规则高置信区（R0-R3）直接打标 → 灰区有蒸馏配额则问 LLM 门 →
  其余弃权不入训；人工复核改标（triage_skips.jsonl）在训练脚本侧优先。

纪律：纯函数无副作用（realGateTriageFn 的种子写入只发生在离线脚本进程）；
确定性（文件排序、无随机）；特征一律经 triage_rules.extractTriageFeatures
单源提取；不使用 built-in hash()。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from neurova.collaboration.triage_rules import evaluateTriage, extractTriageFeatures

MAX_WINDOW_EVENTS = 50


def harvestSessionWindows(
    dataRoot, maxWindows: int = 200, minMessages: int = 6
) -> List[Dict[str, Any]]:
    """从数据根收割真实会话窗口（D-SB3）。

    扫描 `<数据根>/<agent>/sessions/session_*.json`（仓内会话落盘格式，
    messages 元素含 role/content/timestamp），每个会话取末尾
    MAX_WINDOW_EVENTS 条消息作为一个窗口。短会话（<minMessages）与损坏
    文件跳过；按路径排序保证确定性；maxWindows 封顶。

    返回 [{"conversationId": "<agentDir>/<sessionId>", "events": [...]}]。
    """
    root = Path(dataRoot)
    windows: List[Dict[str, Any]] = []
    if not root.exists():
        return windows
    for path in sorted(root.glob("*/sessions/session_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 损坏文件跳过（离线收割不因脏数据中断）
            continue
        if not isinstance(payload, dict):
            continue
        rawMessages = payload.get("messages")
        if not isinstance(rawMessages, list) or len(rawMessages) < minMessages:
            continue
        events: List[Dict[str, Any]] = []
        for message in rawMessages[-MAX_WINDOW_EVENTS:]:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in ("user", "assistant"):
                continue
            content = message.get("content")
            events.append({
                "role": role,
                "content": content if isinstance(content, str) else "",
                "timestamp": message.get("timestamp"),
            })
        if len(events) < minMessages:
            continue
        agentDir = path.parent.parent.name
        sessionId = str(payload.get("session_id") or path.stem)
        windows.append({
            "conversationId": f"{agentDir}/{sessionId}",
            "events": events,
        })
        if len(windows) >= maxWindows:
            break
    return windows


def labelWindows(
    windows: List[Dict[str, Any]],
    distillLimit: int = 0,
    triageFn: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> Dict[str, Any]:
    """给窗口打弱标签（规则高置信区直标 + 灰区可选离线蒸馏）。

    - 规则 skip（R2/R3）→ label=0（not_actionable），labeler="rules"；
    - 规则高置信放行（no_events/human_last/human_in_window）→ label=1，labeler="rules"；
    - 灰区（default_allow）：有蒸馏配额且提供 triageFn 时调其裁决
      （labeler="llm_distill"，配额 -1）；triageFn 抛异常计 distillErrors、
      窗口弃权不入训；无配额/无 triageFn 计 grayUnlabeled 弃权。

    返回 {"labeled": [...], "grayUnlabeled": int, "distillUsed": int,
          "distillErrors": int}；labeled 元素含 conversationId/features
    （extractTriageFeatures 单源 11 键）/label/labeler/reason。
    """
    labeled: List[Dict[str, Any]] = []
    grayUnlabeled = 0
    distillUsed = 0
    distillErrors = 0
    remaining = int(distillLimit)
    for window in windows:
        events = window.get("events") or []
        verdict = evaluateTriage(events, "")
        features = extractTriageFeatures(events, "")
        conversationId = str(window.get("conversationId") or "")
        if verdict.action == "skip":
            labeled.append({
                "conversationId": conversationId,
                "features": features,
                "label": 0,
                "labeler": "rules",
                "reason": verdict.reason,
            })
            continue
        if verdict.reason != "default_allow":
            labeled.append({
                "conversationId": conversationId,
                "features": features,
                "label": 1,
                "labeler": "rules",
                "reason": verdict.reason,
            })
            continue
        # 灰区：默认弃权不入训；有配额且提供蒸馏裁决器时离线问 LLM 门
        if remaining <= 0 or triageFn is None:
            grayUnlabeled += 1
            continue
        try:
            actionable = bool(triageFn(window))
        except Exception:  # noqa: BLE001 - 蒸馏失败诚实计数，窗口弃权
            distillErrors += 1
            grayUnlabeled += 1
            continue
        remaining -= 1
        distillUsed += 1
        labeled.append({
            "conversationId": conversationId,
            "features": features,
            "label": 1 if actionable else 0,
            "labeler": "llm_distill",
            "reason": "distilled",
        })
    return {
        "labeled": labeled,
        "grayUnlabeled": grayUnlabeled,
        "distillUsed": distillUsed,
        "distillErrors": distillErrors,
    }


def realGateTriageFn(window: Dict[str, Any]) -> bool:
    """D-SB1 离线蒸馏适配器：把窗口灌进真实 SessionSyncManager，调**真分诊门**
    （`llm/triage.py` SmallBrainTriageGate，与运行时同一份实现）裁决。

    凭据缺失/门不可用 → TriageGateError 诚实上抛（调用方计 distillErrors、
    窗口弃权）；有凭据时返回门对窗口的 actionable 裁决。
    """
    from neurova.llm.triage import get_small_brain_triage_gate
    from neurova.sync.session_sync_manager import (
        get_session_sync_manager,
        EventType,
        SessionEvent,
    )

    conversationId = str(window.get("conversationId") or "")
    seedId = "distill::" + conversationId
    manager = get_session_sync_manager()
    session = manager.register_or_create_session(
        seedId, user_id="distill", agent_id="distill")
    for event in window.get("events") or []:
        eventType = EventType.USER_MESSAGE if event.get("role") == "user" else EventType.AGENT_REPLY
        timestamp = _parseTimestamp(event.get("timestamp"))
        session.add_event(SessionEvent(
            event_type=eventType,
            payload={"content": event.get("content") or ""},
            timestamp=timestamp,
        ))
    # triage_message 是协程：离线脚本无事件循环，用 asyncio.run 驱动真门
    result = asyncio.run(get_small_brain_triage_gate().triage_message(seedId))
    return bool(result.actionable)


def _parseTimestamp(value):
    """解析 ISO8601；naive 按 UTC 兜底；不可解析回当前时刻（种子序不变）。"""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return datetime.now(timezone.utc)
