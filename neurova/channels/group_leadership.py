"""群领导选举（Group Leadership Election）—— 渠道外部群唯一 responder 仲裁。

见 docs/superpowers/specs/2026-09-19-group-leadership-election-design.md。

同一外部群 `(channel_type, chat_id)` 可能挂多个我方 agent；本模块以**进程内租约**选出
唯一 leader，同一时刻仅 leader 可代表我方应答，leader 静默到期后由到达的候选接管，
消除重复应答与 bot 互聊回声。默认关闭、fail-open（异常/缺配置一律放行，绝不吞人类）。
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

GroupKey = Tuple[str, str]  # (channel_type, chat_id)

DEFAULT_LEASE_TTL_SECONDS = 90


@dataclass
class LeaderRecord:
    agent_id: str
    expires_at: float  # time.monotonic 基准


class GroupLeadershipArbiter:
    """进程内群领导仲裁器（由工厂管理单例；本类本身可独立实例化用于测试）。"""

    def __init__(self) -> None:
        self._leaders: Dict[GroupKey, LeaderRecord] = {}
        self._lock = threading.Lock()

    def may_respond(
        self,
        group_key: GroupKey,
        agent_id: str,
        *,
        now: Optional[float] = None,
        ttl: Optional[float] = None,
    ) -> bool:
        """本 agent 此刻是否可代表该群应答。leader 命中即续租；无/过期则申领。"""
        if not agent_id or not (isinstance(group_key, tuple) and len(group_key) == 2):
            # 输入不完整 → 不设限（放行，安全侧）
            return True
        now = time.monotonic() if now is None else now
        lease_ttl = DEFAULT_LEASE_TTL_SECONDS if ttl is None else float(ttl or DEFAULT_LEASE_TTL_SECONDS)
        with self._lock:
            self._evict_stale_locked(now)
            rec = self._leaders.get(group_key)
            if rec is None or now >= rec.expires_at or rec.agent_id == agent_id:
                self._leaders[group_key] = LeaderRecord(agent_id=agent_id, expires_at=now + lease_ttl)
                return True
            return False

    def current_leader(self, group_key: GroupKey, now: Optional[float] = None) -> Optional[str]:
        """当前 leader；无记录或已过期返回 None。now 可注入（测试同钟）。"""
        now = time.monotonic() if now is None else now
        with self._lock:
            rec = self._leaders.get(group_key)
            if rec is None or now >= rec.expires_at:
                return None
            return rec.agent_id

    def _evict_stale(self, now: float) -> None:
        with self._lock:
            self._evict_stale_locked(now)

    def _evict_stale_locked(self, now: float) -> None:
        """回收远早于 now 的过期记录，防群数量增长导致无界内存。调用方须持锁。"""
        # 宽限：仅清理过期超过一个 TTL 周期的记录，避免边界抖动。
        stale = [
            k
            for k, r in self._leaders.items()
            if now - r.expires_at > DEFAULT_LEASE_TTL_SECONDS
        ]
        for k in stale:
            self._leaders.pop(k, None)


_arbiter: Optional[GroupLeadershipArbiter] = None
_arbiter_lock = threading.Lock()


def get_group_leadership_arbiter() -> GroupLeadershipArbiter:
    global _arbiter
    if _arbiter is None:
        with _arbiter_lock:
            if _arbiter is None:
                _arbiter = GroupLeadershipArbiter()
    return _arbiter


def reset_group_leadership_arbiter() -> None:
    global _arbiter
    with _arbiter_lock:
        _arbiter = None


def get_group_leadership_config(path: "Optional[Path]" = None) -> Tuple[bool, int]:
    """读群领导选举参数：优先系统设置 routing 分区，env 作运维逃生门（最优先）。默认关。"""
    try:
        from neurova.core.app_settings import load_app_settings

        routing = load_app_settings(path).get("routing") or {}
    except Exception:  # noqa: BLE001 - 读设置失败 → 默认关（放行）
        routing = {}

    enabled = bool(routing.get("group_leadership_enabled", False))
    try:
        ttl = int(routing.get("group_lease_ttl_seconds", DEFAULT_LEASE_TTL_SECONDS) or DEFAULT_LEASE_TTL_SECONDS)
    except (TypeError, ValueError):
        ttl = DEFAULT_LEASE_TTL_SECONDS

    env = (os.environ.get("NEUROVA_GROUP_LEADERSHIP") or "").strip().lower()
    if env in ("on", "1", "true", "yes"):
        enabled = True
    elif env in ("off", "0", "false", "no"):
        enabled = False
    return enabled, ttl


__all__ = [
    "GroupLeadershipArbiter",
    "LeaderRecord",
    "get_group_leadership_arbiter",
    "reset_group_leadership_arbiter",
    "get_group_leadership_config",
    "DEFAULT_LEASE_TTL_SECONDS",
]
