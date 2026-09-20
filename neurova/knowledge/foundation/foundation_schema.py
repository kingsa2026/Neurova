"""`knowledge_foundation` 版本域的单主注册处。

为什么要有这个文件：`db_migration.register_migration` 要求同一版本域内版本号**按注册序
严格递增**，而一个 SQLite 文件只有一个 `user_version` 整数——所以"一个库文件 = 一个版本域
= 一个注册顺序"。本域的迁移本来分散在 `knowledge_facts`（v1–v3）与 `narratives`（v4）里，
加进 v5 之后两条注册序一定会互撞（实测在导入期直接 ValueError）。

规矩：**往本域加迁移只改这个文件**，SQL 仍由各自的模块持有；版本号只增不减，
已发布的版本号与其 SQL 文本永不改写（零停机迁移纪律）。
"""

from __future__ import annotations

from typing import List

from neurova.core.db_migration import migrate as applyMigrations, register_migration

from .knowledge_facts import (
    _SCHEMA,
    _SCHEMA_V2,
    _SCHEMA_V3,
    _SCHEMA_V5,
)
from .narratives import NARRATIVE_DOMAIN, _SCHEMA_V4

_STEPS: List[tuple] = [
    (1, _SCHEMA),
    (2, _SCHEMA_V2),
    (3, _SCHEMA_V3),
    (4, _SCHEMA_V4),
    (5, _SCHEMA_V5),
]

_registered = False


def ensureRegistered() -> None:
    """按版本号升序注册整条链。重复调用幂等（注册表本身也挡重复版本）。"""
    global _registered
    if _registered:
        return
    for version, step in sorted(_STEPS, key=lambda t: t[0]):
        register_migration(version, step, domain=NARRATIVE_DOMAIN)
    _registered = True


def applyTo(conn) -> List[int]:
    """把链应用到给定连接上（各存储构造时调用）。"""
    ensureRegistered()
    return applyMigrations(conn, NARRATIVE_DOMAIN)
