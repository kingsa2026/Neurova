# -*- coding: utf-8 -*-
"""RSI 迭代结果摘要 —— 响应面/推送面的单一事实源。

为什么需要这层收口：

- ``RSIOrchestrator.run_iteration()`` 返回的是完整迭代快照
  （feedback_signals / optimizations / applied_results / metrics ...），
  体积大、且不适合进对话响应。
- PostChatPipeline 的 RSI 步骤已后台化（Issue #55 P0 尾延迟），原始 dict
  不再随响应回传。
- 但"上一轮 RSI 迭代到底做了什么"仍是调用方要的观测面（响应面、运营面板）。
  此前 ``process()["rsi_result"]`` 恒为 None，而 ``NegativeScreenPusher.push_rsi_result`` 读的是
  ``iteration/improvements/convergence_score/status``——与 orchestrator 真实
  输出（``convergence/applied_count/gain/phase_advanced``）名字全不匹配，
  且 ``convergence`` 是 dict（``dict * 100`` 直接 TypeError）：一旦接线即报错。
  （该推送口因生产零调用方已于工单 012 删除；本模块的字段口径是它留下的教训。）

本模块只做两件事，字段名一律对齐 orchestrator 真实输出：

1. :func:`summarize_rsi_result` —— raw dict → 响应面摘要（九个字段，
   含度量证据状态、有证据用例数、缺席闭环系统名单、晋升判据结论与落盘状态）。
2. :func:`record_rsi_summary` / :func:`get_latest_rsi_summary` —— 按
   (agent, session) 记录**最近一次已完成**的迭代摘要。

关于"最近一次"而不是"本轮"：RSI 在后台 task 里跑，响应构建时本轮结果通常还
没产出。所以响应里给的是最近一次已完成摘要（``turn`` 标明归属轮次、
``stale`` 标明是否非本轮），而不是阻塞等待（会把尾延迟加回来）或编造数据。

存储默认**进程内**;§6-4(2026-10-06)起支持**挂载持久化**:摘要随记录追加
进 jsonl 审计流(env ``NEUROVA_EVOLUTION_RSI_SUMMARIES`` 重定位,默认
``data/evolution/rsi_summaries.jsonl``),``attach_persistence`` 在启动时
按 (agent, session) 恢复最新摘要——重启后到下一次 RSI 迭代前响应面不再为空。
同一审计流还接收每轮迭代的**规范指标快照**(时序留痕)。落盘失败只记日志,
内存读数不受影响(观测面故障不阻断进化);未挂载时零 IO(与
PersistedStateMixin 同约定)。
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 响应面摘要的字段集合（唯一契约，测试与推送面都引用它）
RSI_SUMMARY_FIELDS: Tuple[str, ...] = (
    "status", "applied_count", "gain", "phase_advanced", "phase_persisted",
    "measure_state", "evidenced_cases", "placeholder_systems", "phase_verdict",
)

_UNKNOWN_STATUS = "unknown"

# 度量证据状态（工单 008 交付项 5）：与收敛结论正交，说的是"这个数字有没有依据"。
MEASURE_STATE_MEASURED = "measured"
MEASURE_STATE_BLIND = "measurement_blind"
MEASURE_STATE_NOT_ATTEMPTED = "not_attempted"
MEASURE_STATE_UNKNOWN = "unknown"
MEASURE_STATES: Tuple[str, ...] = (
    MEASURE_STATE_MEASURED, MEASURE_STATE_BLIND,
    MEASURE_STATE_NOT_ATTEMPTED, MEASURE_STATE_UNKNOWN,
)

# 会话级摘要表的有界上限：只保最近 N 个 (agent, session)，防长进程无界增长
_MAX_TRACKED_SESSIONS = 1024

# 审计流压实阈值:超过 _COMPACT_MAX 行时只保留最近 _COMPACT_KEEP 行
_COMPACT_MAX = 2000
_COMPACT_KEEP = 1000

_summaries: "OrderedDict[Tuple[str, str], Dict[str, Any]]" = OrderedDict()
_lock = threading.RLock()
_persist_path: Optional[Path] = None

ENV_SUMMARIES_PATH = "NEUROVA_EVOLUTION_RSI_SUMMARIES"


def default_rsi_summaries_path() -> Path:
    """审计流默认落点(env 可重定位;测试用 env 指到临时目录)。"""
    from neurova.core.data_root import get_data_root

    return Path(os.environ.get(
        ENV_SUMMARIES_PATH, get_data_root() / "evolution" / "rsi_summaries.jsonl"))


def _append_record(payload: Dict[str, Any]) -> bool:
    """追加一行进审计流;未挂载零 IO,失败只记日志(观测面故障不阻断进化)。"""
    if _persist_path is None:
        return False
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with open(_persist_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except OSError as e:
        logger.debug("RSI 观测审计流写入失败(%s): %s", _persist_path, e)
        return False


def _compact_if_needed(target: Path) -> None:
    """审计流有界:超过 _COMPACT_MAX 行时原子重写为最近 _COMPACT_KEEP 行。"""
    if not target.exists():
        return
    text = target.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= _COMPACT_MAX:
        return
    kept = lines[-_COMPACT_KEEP:]
    tmp = target.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def _restore(target: Path) -> None:
    """从审计流恢复摘要:同一 (agent, session) 文件序在后者胜。坏行跳过。"""
    if not target.exists():
        return
    restored: "OrderedDict[Tuple[str, str], Dict[str, Any]]" = OrderedDict()
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("type") not in (None, "summary"):
            continue
        summary = record.get("summary")
        if not isinstance(summary, dict):
            continue
        key = (str(record.get("agent_id") or "default"),
               str(record.get("session_id") or "default"))
        restored[key] = {"summary": summary, "turn": record.get("turn")}
        while len(restored) >= _MAX_TRACKED_SESSIONS:
            for stale in list(restored)[: _MAX_TRACKED_SESSIONS // 2]:
                restored.pop(stale, None)
    with _lock:
        _summaries.clear()
        _summaries.update(restored)


def attach_persistence(path: Optional[Path] = None) -> bool:
    """挂载观测审计流并恢复历史摘要(启动时调用;重复挂载 = 重新恢复)。"""
    global _persist_path
    target = Path(path) if path is not None else default_rsi_summaries_path()
    try:
        _compact_if_needed(target)
        _restore(target)
    except OSError as e:
        logger.warning("RSI 摘要持久化挂载失败,保持内存模式: %s", e)
        return False
    _persist_path = target
    return True


def detach_persistence() -> None:
    """摘除挂载(测试/隔离用);内存表不受影响。"""
    global _persist_path
    _persist_path = None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def convergence_status(result: Mapping[str, Any]) -> str:
    """从迭代结果里取收敛状态。

    ``run_iteration()`` 的 ``convergence`` 是 dict（``{"status": ...}``）；
    历史/其它调用方也可能给扁平 ``status``/``convergence_status``。三者兼容，
    取不到时返回 ``"unknown"``——绝不拿 dict 当数字用。
    """
    convergence = result.get("convergence")
    status = convergence.get("status") if isinstance(convergence, Mapping) else None
    if not status:
        status = result.get("status") or result.get("convergence_status")
    return str(status) if status else _UNKNOWN_STATUS


def measurement_evidence(result: Mapping[str, Any]) -> Dict[str, Any]:
    """本轮测量到底有没有依据（工单 008 交付项 5）。

    只有 gain 时"没有改善空间"和"量不出来"是同一个数字，而两者的处置相反：
    前者降频巡检即可，后者要去修测量。所以响应面必须带出评测集自报的分母。

    没有前后测量结果 = 本轮根本没跑自动执行（观察期/手动期），
    此时报 `not_attempted` 而不是"0 例"——后者会把"没测"冒充成"测了且全blind"。
    """
    outcomes = result.get("eval")
    after = outcomes.get("after") if isinstance(outcomes, Mapping) else None
    if not isinstance(after, Mapping):
        return {"measure_state": MEASURE_STATE_NOT_ATTEMPTED, "evidenced_cases": None}
    state = after.get("state")
    cases = after.get("evidenced_cases")
    return {
        "measure_state": str(state) if state else MEASURE_STATE_UNKNOWN,
        "evidenced_cases": cases if isinstance(cases, int) else None,
    }


def _placeholder_systems(result: Mapping[str, Any]) -> Optional[List[str]]:
    """缺席闭环系统的名单（工单 018 第 4 项）。

    `None` 表示这份快照没带该信息，**不等于**"一个都没缺席"——
    把未知读成"一切正常"正是本批要消灭的那类兜底。
    """
    names = result.get("placeholder_systems")
    if not isinstance(names, (list, tuple)):
        return None
    return sorted(str(name) for name in names)


def phase_verdict_evidence(result: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """本轮晋升判据的结论与依据（工单 016 把它接到响应面）。

    为什么必须有出口：`phase_advanced=False` 有两种相反的成因——"缺证据所以不敢推进"
    （去把证据跑出来）与"有证据且证据否决"（停下来查质量）。只报布尔值就是把两者
    压成同一个数字，与工单 008 在 gain=0 上拆掉的那个假象同形。三态契约
    （`docs/CONTEXT.md`）要求 `unevidenced` 出现在观测面，不能只活在日志里。

    `None` 表示这份快照没带判据（历史形态/第三方编排器），**不等于**"判据通过"。
    """
    verdict = result.get("phase_verdict")
    if not isinstance(verdict, Mapping) or not verdict.get("state"):
        return None
    return {"state": str(verdict["state"]), "reason": str(verdict.get("reason") or "")}


def summarize_rsi_result(result: Any) -> Optional[Dict[str, Any]]:
    """把 RSI 迭代结果压成响应面摘要（字段名对齐 orchestrator 真实输出）。

    形态不符（None / 非 Mapping / 空 dict）时返回 None，不造默认值——
    不存在的迭代不该冒充"跑了一轮没优化"。
    """
    if not isinstance(result, Mapping) or not result:
        return None
    summary = {
        "status": convergence_status(result),
        "applied_count": _as_int(result.get("applied_count", 0)),
        "gain": _as_float(result.get("gain", 0.0)),
        "phase_advanced": bool(result.get("phase_advanced", False)),
        # 工单 005：只报 `phase_advanced` 会把"内存已晋升、盘上没晋升"读成已存活
        "phase_persisted": bool(result.get("phase_persisted", False)),
    }
    summary.update(measurement_evidence(result))
    summary["placeholder_systems"] = _placeholder_systems(result)
    summary["phase_verdict"] = phase_verdict_evidence(result)
    return summary


def _key(agent_id: Any, session_id: Any) -> Tuple[str, str]:
    return (str(agent_id or "default"), str(session_id or "default"))


def record_rsi_summary(
    agent_id: Any,
    session_id: Any,
    result: Any,
    turn: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """记录一次已完成 RSI 迭代的摘要（result 为 run_iteration 原始返回）。

    Returns:
        落库的摘要（含 ``turn``）；形态不符时返回 None 且不写入。
    """
    summary = summarize_rsi_result(result)
    if summary is None:
        return None

    key = _key(agent_id, session_id)
    with _lock:
        if key not in _summaries and len(_summaries) >= _MAX_TRACKED_SESSIONS:
            # 插入序淘汰最旧一半（dict 保序）——与 turn_context 的会话表同策略
            for stale in list(_summaries)[: _MAX_TRACKED_SESSIONS // 2]:
                _summaries.pop(stale, None)
        _summaries[key] = {"summary": summary, "turn": _as_int(turn) if turn is not None else None}
        # §6-4:摘要随记录追加进审计流(未挂载零 IO;失败 soft)
        _append_record({
            "type": "summary",
            "agent_id": key[0],
            "session_id": key[1],
            "turn": _summaries[key]["turn"],
            "summary": summary,
            "ts": round(time.time(), 3),
        })
        return dict(_summaries[key])


def get_latest_rsi_summary(
    agent_id: Any,
    session_id: Any,
    current_turn: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """取该会话最近一次已完成的 RSI 摘要（从未有过迭代时返回 None）。

    ``current_turn`` 给出时附带 ``stale`` 标记：True 表示该摘要不是本轮的
    （RSI 仍在后台，或本轮 RSI 被跳过）。判不出轮次时不虚报。
    """
    with _lock:
        record = _summaries.get(_key(agent_id, session_id))
        if record is None:
            return None
        record = dict(record)

    payload = dict(record["summary"])
    payload["turn"] = record.get("turn")
    recorded_turn = record.get("turn")
    payload["stale"] = bool(
        current_turn is not None and recorded_turn is not None and recorded_turn != current_turn
    )
    return payload


def record_metrics_snapshot(metrics: Any, agent_id: Any = None) -> bool:
    """把规范指标快照追加进观测审计流(§6-4 时序留痕)。

    未挂载返回 False(零 IO);落盘失败 soft(False + 日志)。
    """
    if not isinstance(metrics, Mapping):
        return False
    return _append_record({
        "type": "metrics",
        "agent_id": str(agent_id or "default"),
        "metrics": dict(metrics),
        "ts": round(time.time(), 3),
    })


def clear_rsi_summaries() -> None:
    """清空摘要表（测试/setup-teardown 用）。"""
    with _lock:
        _summaries.clear()


__all__ = [
    "RSI_SUMMARY_FIELDS",
    "MEASURE_STATES",
    "convergence_status",
    "measurement_evidence",
    "phase_verdict_evidence",
    "summarize_rsi_result",
    "record_rsi_summary",
    "get_latest_rsi_summary",
    "record_metrics_snapshot",
    "attach_persistence",
    "detach_persistence",
    "default_rsi_summaries_path",
    "clear_rsi_summaries",
]
