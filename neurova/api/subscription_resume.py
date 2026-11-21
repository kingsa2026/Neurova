# -*- coding: utf-8 -*-
"""多端订阅自适应：断线重连续传决策 / 重连退避 / 帧去重的**单源**（批三 D3）。

PC、鸿蒙、安卓三端的订阅恢复语义必须一致，本模块是仓内唯一出处：
- :func:`resolveResumeMode` / :func:`resolveResume`：客户端带游标重连时，服务端
  判定"按游标增量重放"还是"降级全量快照"。判据与全局事件库
  ``swarm_event_store.replayThrough`` 的降级语义同构（绝不部分回放）：
  * 游标有效且落在可回放窗口与预算内 → ``replay``；
  * 游标过旧（早于保留窗口下界，``(cursor, head]`` 区间内已有帧被修剪）→
    ``snapshot``——增量必不完整，诚实要求快照；
  * 游标领先服务端头（非法，疑似跨实例切换或本地状态错位）→ ``snapshot``，
    决策里带诚实标注；
  * 重放字节预算已耗尽 / 已降级 → ``snapshot``；
  * 缺游标（首连）或游标非法（负数）→ ``snapshot``（首连走快照是正常路径）。
- :func:`reconnectBackoff`：三端统一的重连退避公式 ``min(base_s * 2^n, cap_s)``
  （缺省 ±20% 抖动）。**客户端应按服务端下发的该语义实现**（本函数即语义
  出处）；``jitter_fn`` 可注入以便确定性测试或接入平台随机源。
- :func:`dedupBySequence`：重放帧与实时帧衔接处按 ``seq`` 去重保序。

依赖仅标准库 + ``ws_stream_budget.ReplayByteBudget``（预算判据），可独立测试。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, List, Optional

from neurova.api.ws_stream_budget import ReplayByteBudget

__all__ = [
    "RESUME_MODE_REPLAY",
    "RESUME_MODE_SNAPSHOT",
    "RECONNECT_BACKOFF_BASE_S",
    "RECONNECT_BACKOFF_CAP_S",
    "RECONNECT_BACKOFF_JITTER_FRACTION",
    "ResumeDecision",
    "resolveResume",
    "resolveResumeMode",
    "reconnectBackoff",
    "dedupBySequence",
]

#: 按游标增量重放
RESUME_MODE_REPLAY = "replay"
#: 降级全量快照（游标过旧 / 非法 / 预算耗尽 / 首连）
RESUME_MODE_SNAPSHOT = "snapshot"

#: 三端统一重连退避参数（reconnectBackoff 的缺省语义单源；
#: connection_runtime.describeForClients 下发给三端的就是这三个值，不另抄）
RECONNECT_BACKOFF_BASE_S = 0.5
RECONNECT_BACKOFF_CAP_S = 30.0
#: 缺省抖动幅度：最终时延在封顶后基础值上乘 ``[1-j, 1+j]`` 均匀分布
RECONNECT_BACKOFF_JITTER_FRACTION = 0.2


@dataclass(frozen=True)
class ResumeDecision:
    """续传决策：模式 + 机器可读原因 + 面向日志/下发的诚实标注。"""

    mode: str  #: "replay" | "snapshot"
    reason: str  #: 机器可读原因（cursor_in_window / cursor_pruned / cursor_ahead_of_head / cursor_invalid / no_cursor / budget_exhausted）
    note: str = ""  #: 诚实标注（中文，供日志与对账；replay 时为空）


def resolveResume(
    cursor_seq: Optional[int],
    head_seq: Optional[int],
    *,
    min_available_seq: Optional[int] = None,
    budget: Optional[ReplayByteBudget] = None,
) -> ResumeDecision:
    """续传决策完整形态（含诚实标注）。判据见模块 docstring。

    ``min_available_seq``：仍可回放窗口的下界（更早的帧已被修剪）。
    判 ``snapshot`` 的过旧条件是 ``cursor < min_available_seq - 1``——即
    ``(cursor, head]`` 区间内确有已修剪空洞；``cursor == min_available_seq - 1``
    时回放恰好从窗口首帧无缝开始，仍判 ``replay``（与事件库
    ``pruned_through`` 边界语义一致：边界上的游标可无缝续传）。
    """
    cursor = None if cursor_seq is None else int(cursor_seq)
    head = 0 if head_seq is None else int(head_seq)

    if cursor is None:
        return ResumeDecision(
            RESUME_MODE_SNAPSHOT, "no_cursor", "客户端未携带游标（首连），按全量快照恢复"
        )
    if cursor < 0:
        return ResumeDecision(
            RESUME_MODE_SNAPSHOT, "cursor_invalid", f"游标 {cursor} 非法（负数），按全量快照恢复"
        )
    if cursor > head:
        return ResumeDecision(
            RESUME_MODE_SNAPSHOT,
            "cursor_ahead_of_head",
            f"客户端游标 {cursor} 领先服务端头 {head}（非法，疑似跨实例切换或状态错位），"
            "丢弃游标按全量快照恢复",
        )
    if min_available_seq is not None and cursor < int(min_available_seq) - 1:
        return ResumeDecision(
            RESUME_MODE_SNAPSHOT,
            "cursor_pruned",
            f"游标 {cursor} 早于可回放窗口下界 {int(min_available_seq)}（区间内已有帧被修剪），"
            "增量必不完整，按全量快照恢复",
        )
    if budget is not None and (budget.downgraded or budget.remaining() <= 0):
        return ResumeDecision(
            RESUME_MODE_SNAPSHOT,
            "budget_exhausted",
            "重放字节预算已耗尽，按全量快照恢复（回放过程中每帧仍需继续记账，"
            "再次突破预算同样降级）",
        )
    return ResumeDecision(RESUME_MODE_REPLAY, "cursor_in_window", "")


def resolveResumeMode(
    cursor_seq: Optional[int],
    head_seq: Optional[int],
    *,
    min_available_seq: Optional[int] = None,
    budget: Optional[ReplayByteBudget] = None,
) -> str:
    """续传决策的简形式：只返回 ``"replay"`` 或 ``"snapshot"``。"""
    return resolveResume(
        cursor_seq, head_seq, min_available_seq=min_available_seq, budget=budget
    ).mode


def reconnectBackoff(
    attempt: int,
    *,
    base_s: float = RECONNECT_BACKOFF_BASE_S,
    cap_s: float = RECONNECT_BACKOFF_CAP_S,
    jitter_fn=None,
) -> float:
    """三端统一的重连退避：``min(base_s * 2^attempt, cap_s)``，缺省 ±20% 抖动。

    - ``attempt`` 负数按 0 处理；封顶在抖动**之前**生效（结果至多 ``cap_s * 1.2``）；
    - ``jitter_fn(delay_s) -> float`` 可注入：收到封顶后的基础时延，返回最终时延
      （确定性测试传 ``lambda d: d``；平台可接自己的随机源）；
    - 缺省抖动 ``±RECONNECT_BACKOFF_JITTER_FRACTION``（±20%）。

    本函数是 PC / 鸿蒙 / 安卓三端重连退避的**语义单源**：客户端 SDK 按此处
    公式实现，服务端在下发的续传/重连说明里引用同一语义，不再各自手抄。
    """
    n = max(0, int(attempt))
    raw = min(float(base_s) * (2 ** n), float(cap_s))
    if jitter_fn is not None:
        return float(jitter_fn(raw))
    j = RECONNECT_BACKOFF_JITTER_FRACTION
    return raw * random.uniform(1 - j, 1 + j)


def dedupBySequence(frames: Optional[List[Any]]) -> List[Any]:
    """按 ``seq`` 去重保序（重放 + 实时衔接处不重复）。

    只对带 ``seq`` 的 dict 帧去重（保留首次出现）；缺 ``seq`` 的帧（连接级
    心跳/控制帧）无法判定重复，原样保留。
    """
    seen = set()
    out: List[Any] = []
    for frame in frames or []:
        seq = frame.get("seq") if isinstance(frame, dict) else None
        if seq is None:
            out.append(frame)
            continue
        if seq in seen:
            continue
        seen.add(seq)
        out.append(frame)
    return out
