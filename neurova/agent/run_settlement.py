# -*- coding: utf-8 -*-
"""run 自动结算（参照系 ac 借鉴 A5）：闲置/完成后自动收敛，九重护栏一票否决。

本模块是**纯逻辑**：不做 IO、不持全局态；结算动作经 ``settle_fn`` 回调注入，
真实落账（走 ``transitionRun`` 状态机）、关终端、释放进程池由接线方提供。

判定顺序（``evaluateSettlement``）：
1. status 已是 ``settled`` → 拒绝，原因 ``already_settled``（幂等短路）；
2. 护栏命中表 ``guards`` 按 ``ALL_GUARDS`` 固定顺序取**首个命中**者一票否决；
3. 闲置时长 ``now_ts - last_activity_at >= idle_days * 86400``（含边界）→ 结算；
4. 否则 → 拒绝，原因 ``idle_not_reached``。

配置（``readSettleSettings``）：自动结算默认**关**（D-C 拍板），idle 阈值默认
3 天；非法值（含非正数、非有限值）一律回落缺省——本模块不打印，回落时由
调用方记日志。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

SETTLE_IDLE_DAYS_DEFAULT = 3.0
SETTLE_ENV_ENABLED = "NEUROVA_SWARM_AUTO_SETTLE"  # 默认 off（D-C 拍板）
SETTLE_ENV_IDLE_DAYS = "NEUROVA_SWARM_SETTLE_IDLE_DAYS"  # 默认 3.0

# 护栏键（guards dict 的键；True=命中=挡结算）
G_ACTIVE_RUN = "active_run"
G_PENDING_APPROVAL = "pending_approval"
G_PINNED = "pinned"
G_EXPLICIT_OVERRIDE = "explicit_override"
G_QUEUED_TURN = "queued_turn"
G_SNOOZED = "snoozed"
G_BACKGROUND_WORK = "background_work"
G_GRACE_PERIOD = "grace_period"

SETTLED_STATUS = "settled"
REASON_ALREADY_SETTLED = "already_settled"
REASON_IDLE_NOT_REACHED = "idle_not_reached"

# 固定优先级：首个命中者即拒绝原因；already_settled 垫底（status 命中时已先行短路）。
ALL_GUARDS = (
    G_ACTIVE_RUN,
    G_PENDING_APPROVAL,
    G_PINNED,
    G_EXPLICIT_OVERRIDE,
    G_QUEUED_TURN,
    G_SNOOZED,
    G_BACKGROUND_WORK,
    G_GRACE_PERIOD,
    REASON_ALREADY_SETTLED,
)

_SECONDS_PER_DAY = 86400.0
_ENABLED_TRUTHY = frozenset({"1", "true", "yes", "on"})


@dataclass
class SettlementCandidate:
    """sweep 评估对象：调用方从 run 现场收集状态与护栏命中表。"""

    subagent_id: str
    status: str  # 当前 run 状态（如 completed/failed/settled/running…）
    last_activity_at: float  # 最近活动时间（epoch 秒）
    guards: Dict[str, bool]  # 护栏命中表（缺的键按 False）


def readSettleSettings(env: Optional[Dict[str, str]] = None) -> Tuple[bool, float]:
    """读 ``(enabled, idle_days)``：env 缺省读 ``os.environ``。

    enabled 默认 False（开关缺省关）；idle_days 默认 3.0，非法值回落缺省，
    回落不由本模块记日志，由调用方负责。
    """
    source = os.environ if env is None else env
    enabled = _parseEnabled(source.get(SETTLE_ENV_ENABLED))
    idle_days = _parseIdleDays(source.get(SETTLE_ENV_IDLE_DAYS))
    return enabled, idle_days


def _parseEnabled(raw: Optional[str]) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in _ENABLED_TRUTHY


def _parseIdleDays(raw: Optional[str]) -> float:
    if raw is None:
        return SETTLE_IDLE_DAYS_DEFAULT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return SETTLE_IDLE_DAYS_DEFAULT
    if not math.isfinite(value) or value <= 0:
        return SETTLE_IDLE_DAYS_DEFAULT
    return value


def evaluateSettlement(
    candidate: SettlementCandidate, *, now_ts: float, idle_days: float
) -> Tuple[bool, str]:
    """单候选判定，返回 ``(should_settle, reason)``。

    - status 已是 ``settled`` → ``(False, "already_settled")``；
    - 任一护栏命中 → ``(False, 该护栏键)``（按 ``ALL_GUARDS`` 固定顺序取首个）；
    - 闲置时长 ``>= idle_days*86400`` → ``(True, "")``；
    - 否则 → ``(False, "idle_not_reached")``。
    """
    if candidate.status == SETTLED_STATUS:
        return False, REASON_ALREADY_SETTLED
    for guard in ALL_GUARDS:
        if candidate.guards.get(guard):
            return False, guard
    idle_seconds = now_ts - candidate.last_activity_at
    if idle_seconds >= idle_days * _SECONDS_PER_DAY:
        return True, ""
    return False, REASON_IDLE_NOT_REACHED


def sweep(
    candidates: List[SettlementCandidate],
    *,
    now_ts: float,
    idle_days: float,
    settle_fn: Callable[[str], Any],
) -> Dict[str, Any]:
    """批量评估+执行：对通过者调 ``settle_fn(subagent_id)``（同步回调）。

    单个回调异常计入 ``failed``，不中断其余候选。返回
    ``{"settled": [id...], "skipped": [[id, reason]...], "failed": [[id, error]...]}``。
    """
    settled: List[str] = []
    skipped: List[List[str]] = []
    failed: List[List[str]] = []
    for candidate in candidates:
        should_settle, reason = evaluateSettlement(
            candidate, now_ts=now_ts, idle_days=idle_days
        )
        if not should_settle:
            skipped.append([candidate.subagent_id, reason])
            continue
        try:
            settle_fn(candidate.subagent_id)
        except Exception as exc:  # 单个结算动作失败不中断本轮 sweep
            failed.append([candidate.subagent_id, f"{type(exc).__name__}: {exc}"])
            continue
        settled.append(candidate.subagent_id)
    return {"settled": settled, "skipped": skipped, "failed": failed}
