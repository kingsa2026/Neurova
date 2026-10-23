"""知识条目生命周期判定（唯一实现）。

判定只回答两个问题：条目是否被归档、是否已过 valid_until。
不在这里自动删除、不改写数据——归档/恢复走条目的显式更新通道，
物理擦除仍走 `purge_knowledge`。
"""
from __future__ import annotations

import datetime
from typing import Any, Optional

ACTIVE = "active"
ARCHIVED = "archived"
LIFECYCLE_STATUSES = (ACTIVE, ARCHIVED)
_UTC = datetime.timezone.utc


def normalizeLifecycleStatus(value: Any) -> str:
    status = str(value or ACTIVE).strip().lower()
    if status not in LIFECYCLE_STATUSES:
        raise ValueError(
            "未知 lifecycle_status: %r（有效值: %s）"
            % (value, " / ".join(LIFECYCLE_STATUSES))
        )
    return status


def parseValidUntil(value: Any) -> Optional[datetime.datetime]:
    """解析 valid_until；支持 ISO 字符串与 epoch 秒。坏值返回 None（不隐藏条目）。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(float(value), tz=_UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        stamp = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_UTC)
    return stamp.astimezone(_UTC)


def isExpired(item: dict, now: Optional[datetime.datetime] = None) -> bool:
    until = parseValidUntil((item or {}).get("valid_until"))
    if until is None:
        return False
    moment = now or datetime.datetime.now(_UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_UTC)
    return until <= moment.astimezone(_UTC)


def isRetrievable(item: dict, now: Optional[datetime.datetime] = None) -> bool:
    """active 且未过期；归档优先于过期。坏 status 按 archived 处理（失败方向是不展示）。"""
    try:
        status = normalizeLifecycleStatus((item or {}).get("lifecycle_status"))
    except ValueError:
        return False
    if status != ACTIVE:
        return False
    return not isExpired(item, now)
