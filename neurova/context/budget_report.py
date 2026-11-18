"""常驻上下文预算报告（N6，只读）。

只测量、不改写：把系统提示里每一段的字符数与预算上限记下来，供
`GET /v1/context/budget` 读取。常驻面的编辑契约/自动改写不在本模块。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

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


# ════════════════════════════════════════════════════════════════
# SC-6：折叠后 N 轮召回率（折叠事件 × 抽屉命中 的关联账本与聚合读数）
#
# 单源关联账本（对照文档 §8.3 SC-6）：折叠侧（orchestrator 折叠提交点）记
# 区间指纹（covers hash，与归档侧 `_windowChunkHash` 同源），召回侧
# （semantic_drawer 取水命中）记命中指纹，两边都写**这一本账**；
# 聚合面 `foldRecallReadout` 出"折叠后 N 轮内区间被召回比率"。
#
# 覆盖面说明（诚实边界）：抽屉埋点覆盖被动注入（build_context 的 pool.draw）
# 与主动检索（pool_search → pool.search）两条召回路径；recall_history /
# recall_context_span 直取台账/索引、不经抽屉，其命中不在本账本内——
# 比率因此是**下界**（分母不受影响，分子可能少计）。
#
# 跨重启（fail-open，尽力而为）：账本是进程内的；重启后折叠分母经时间线
# 重放恢复（`restoreFoldIntervals`，编排层 S6' 建槽时调用，回合未知记 0），
# 重启后的召回照常记账。空账/缺账一律返回合法零形状，不抛错。
# ════════════════════════════════════════════════════════════════

#: 折叠后召回观察窗（N 轮）：折叠后第 1..N 个回合内命中该区间记为"及时召回"。
#: 折早了该比率会抬高（折叠时机质量的量化指标，池形态独有）。
FOLD_RECALL_WINDOW_TURNS = 8

#: 回合轴的无身份回落键（与折叠缓存键 `_resolve_window_cache_key` 的回落同形）。
_FOLD_RECALL_DEFAULT_SCOPE = "direct"

_foldRecallLock = threading.RLock()
#: sessionKey -> [{turn, foldSeq, hashes}]，按折叠提交顺序追加
_foldEvents: Dict[str, List[Dict[str, Any]]] = {}
#: sessionKey -> [{turn, hash}]，按召回发生顺序追加
_recallHits: Dict[str, List[Dict[str, Any]]] = {}
#: sessionKey -> 当前回合序（编排层每轮 build_context 推进一次）
_turnCounters: Dict[str, int] = {}
#: sessionKey -> 时间线重放恢复的折叠区间（回合未知，按 0 计）
_restoredFolds: Dict[str, set] = {}

#: 单会话账本容量上限（防长驻进程无界增长；超限丢最旧）
_MAX_FOLD_EVENTS_PER_SESSION = 1000
_MAX_RECALL_HITS_PER_SESSION = 20000


def foldRecallWindowTurns() -> int:
    """召回观察窗 N（env `NEUROVA_FOLD_RECALL_WINDOW_TURNS` 可覆盖，钳 [1,1000]）。"""
    try:
        value = int(os.environ.get("NEUROVA_FOLD_RECALL_WINDOW_TURNS", str(FOLD_RECALL_WINDOW_TURNS)))
    except (TypeError, ValueError):
        value = FOLD_RECALL_WINDOW_TURNS
    return min(1000, max(1, value))


def noteContextTurn(sessionKey: Optional[str]) -> int:
    """推进会话的回合轴（编排层每轮 build_context 调用一次）。

    折叠事件与召回命中都以本回合序记帐，聚合面据此判"N 轮内"。
    返回推进后的回合序（从 1 起）。
    """
    key = str(sessionKey or _FOLD_RECALL_DEFAULT_SCOPE)
    with _foldRecallLock:
        _turnCounters[key] = int(_turnCounters.get(key, 0)) + 1
        return _turnCounters[key]


def currentContextTurn(sessionKey: Optional[str]) -> int:
    """当前回合序（未推进过为 0）。"""
    key = str(sessionKey or _FOLD_RECALL_DEFAULT_SCOPE)
    with _foldRecallLock:
        return int(_turnCounters.get(key, 0))


def recordFoldIntervals(
    sessionKey: Optional[str],
    hashes: Iterable[str],
    *,
    foldSeq: Optional[int] = None,
    turn: Optional[int] = None,
) -> None:
    """折叠侧记账：一次折叠提交所覆盖的区间指纹集（covers hash）。

    `turn` 缺省取当前回合序；`foldSeq` 为折叠代际（可解释性用）。
    空 hashes 不记账（防抖/零覆盖轮不留空事件）。
    """
    key = str(sessionKey or _FOLD_RECALL_DEFAULT_SCOPE)
    cleaned = [str(h) for h in (hashes or []) if h]
    if not cleaned:
        return
    with _foldRecallLock:
        resolvedTurn = int(currentContextTurn(key)) if turn is None else int(turn)
        _foldEvents.setdefault(key, []).append(
            {"turn": resolvedTurn, "foldSeq": foldSeq, "hashes": cleaned}
        )
        events = _foldEvents[key]
        if len(events) > _MAX_FOLD_EVENTS_PER_SESSION:
            del events[: len(events) - _MAX_FOLD_EVENTS_PER_SESSION]


def restoreFoldIntervals(sessionKey: Optional[str], hashes: Iterable[str]) -> None:
    """跨重启恢复：时间线重放（S6' 建槽）恢复折叠分母。

    重放侧回合未知，按 0 计（重启后的命中相对它必然是"折叠后"）；
    重复重放按 hash 集合合并（槽位重建/淘汰重放幂等）。
    """
    key = str(sessionKey or _FOLD_RECALL_DEFAULT_SCOPE)
    cleaned = {str(h) for h in (hashes or []) if h}
    if not cleaned:
        return
    with _foldRecallLock:
        _restoredFolds.setdefault(key, set()).update(cleaned)


def recordRecallHits(
    sessionKey: Optional[str],
    hashes: Iterable[str],
    *,
    turn: Optional[int] = None,
) -> None:
    """召回侧记账：本轮取水命中的条目指纹（与折叠 covers 同一 hash 空间）。"""
    key = str(sessionKey or _FOLD_RECALL_DEFAULT_SCOPE)
    cleaned = [str(h) for h in (hashes or []) if h]
    if not cleaned:
        return
    with _foldRecallLock:
        resolvedTurn = int(currentContextTurn(key)) if turn is None else int(turn)
        hits = _recallHits.setdefault(key, [])
        for h in cleaned:
            hits.append({"turn": resolvedTurn, "hash": h})
        if len(hits) > _MAX_RECALL_HITS_PER_SESSION:
            del hits[: len(hits) - _MAX_RECALL_HITS_PER_SESSION]


def _aggregateFoldRecall(
    events: List[Dict[str, Any]],
    hits: List[Dict[str, Any]],
    restored: set,
    windowTurns: int,
) -> Dict[str, Any]:
    """聚合判据（纯函数，单源）：分子/分母/逐事件明细。

    - 分母 = 去重后被折叠区间 hash 数（事件 ∪ 重放恢复）；
    - 分子 = 其中在折叠后第 1..N 轮内被召回的区间数
      （折叠**当轮**命中不计：ht <= ft 排除——当轮防召回由
      `_last_folded_hashes` 在视图层管辖，这里口径一致）；
    - 重放恢复的折叠回合未知记 0：重启后第 t 轮命中即 Δt=t，t<=N 计入
      （尽力而为的近似，不谎报精确）。
    """
    foldTurnByHash: Dict[str, int] = {}
    for event in events:
        turn = int(event.get("turn") or 0)
        for h in event.get("hashes") or []:
            if h and h not in foldTurnByHash:
                foldTurnByHash[h] = turn
    for h in restored or set():
        if h and h not in foldTurnByHash:
            foldTurnByHash[h] = 0
    hitTurnByHash: Dict[str, int] = {}
    for hit in hits:
        h = hit.get("hash")
        turn = int(hit.get("turn") or 0)
        if h and (h not in hitTurnByHash or turn < hitTurnByHash[h]):
            hitTurnByHash[h] = turn

    numerator = 0
    for h, foldTurn in foldTurnByHash.items():
        hitTurn = hitTurnByHash.get(h)
        if hitTurn is None:
            continue
        if hitTurn <= foldTurn:
            continue
        if hitTurn - foldTurn <= windowTurns:
            numerator += 1
    denominator = len(foldTurnByHash)
    return {
        "denominator": denominator,
        "numerator": numerator,
        "unrecalled": denominator - numerator,
        "recall_rate": round(numerator / denominator, 4) if denominator else 0.0,
        "_foldTurnByHash": foldTurnByHash,
        "_hitTurnByHash": hitTurnByHash,
    }


def foldRecallReadout(sessionKey: Optional[str] = None) -> Dict[str, Any]:
    """聚合读数：折叠后 N 轮内区间被召回比率。

    - `sessionKey` 给定：返回该会话读数，附逐折叠事件明细 `per_event`
      （fold_seq / 回合 / 折叠条数 / 窗内召回数），分子分母可解释；
    - `sessionKey=None`：聚合全部会话，附 `sessions` 分会话切片。

    fail-open：任何意外失败返回合法零形状（读数面不抛错）。
    """
    empty = {
        "window_turns": foldRecallWindowTurns(),
        "fold_events": 0,
        "denominator": 0,
        "numerator": 0,
        "unrecalled": 0,
        "recall_rate": 0.0,
    }
    try:
        windowTurns = foldRecallWindowTurns()
        with _foldRecallLock:
            if sessionKey is not None:
                key = str(sessionKey or _FOLD_RECALL_DEFAULT_SCOPE)
                events = [dict(e, hashes=list(e.get("hashes") or [])) for e in _foldEvents.get(key, [])]
                hits = [dict(h) for h in _recallHits.get(key, [])]
                restored = set(_restoredFolds.get(key, set()))
            else:
                events = [
                    dict(e, hashes=list(e.get("hashes") or []))
                    for key in _foldEvents
                    for e in _foldEvents.get(key, [])
                ]
                hits = [dict(h) for key in _recallHits for h in _recallHits.get(key, [])]
                restored = set()
                for key in _restoredFolds:
                    restored |= set(_restoredFolds.get(key, set()))
        aggregate = _aggregateFoldRecall(events, hits, restored, windowTurns)
        aggregate.pop("_foldTurnByHash", None)
        hitTurnByHash = aggregate.pop("_hitTurnByHash")
        readout = {"window_turns": windowTurns, "fold_events": len(events), **aggregate}
        if sessionKey is not None:
            perEvent = []
            for event in events:
                eventTurn = int(event.get("turn") or 0)
                eventHashes = [h for h in event.get("hashes") or [] if h]
                hitTurns = {}
                for h in eventHashes:
                    hitTurn = hitTurnByHash.get(h)
                    if hitTurn is not None and hitTurn > eventTurn and hitTurn - eventTurn <= windowTurns:
                        hitTurns[h] = hitTurn
                perEvent.append(
                    {
                        "fold_seq": event.get("foldSeq"),
                        "turn": eventTurn,
                        "folded": len(eventHashes),
                        "recalled_in_window": len(hitTurns),
                        "hit_turns": hitTurns,
                    }
                )
            readout["per_event"] = perEvent
        else:
            # 分会话切片按原始账本逐键聚合（读数总账 = 各会话之和的口径）
            sessions: Dict[str, Dict[str, Any]] = {}
            allKeys = set(_foldEvents) | set(_restoredFolds)
            for key in sorted(allKeys):
                with _foldRecallLock:
                    kEvents = [
                        dict(e, hashes=list(e.get("hashes") or []))
                        for e in _foldEvents.get(key, [])
                    ]
                    kHits = [dict(h) for h in _recallHits.get(key, [])]
                    kRestored = set(_restoredFolds.get(key, set()))
                kAgg = _aggregateFoldRecall(kEvents, kHits, kRestored, windowTurns)
                kAgg.pop("_foldTurnByHash", None)
                kAgg.pop("_hitTurnByHash", None)
                sessions[key] = {
                    "fold_events": len(kEvents),
                    **kAgg,
                }
            readout["sessions"] = sessions
        return readout
    except Exception as exc:  # noqa: BLE001 - 读数面 fail-open
        logger.warning("折叠后召回率读数失败（返回零形状）: %s", exc)
        return dict(empty, last_error=f"{type(exc).__name__}: {exc}")


def resetFoldRecallLedger() -> None:
    """清空折叠后召回率账本（测试/运维用；不影响折叠与召回行为）。"""
    with _foldRecallLock:
        _foldEvents.clear()
        _recallHits.clear()
        _turnCounters.clear()
        _restoredFolds.clear()
