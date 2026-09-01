# -*- coding: utf-8 -*-
"""SQLite 版本化迁移（PRAGMA user_version，补课 1.2）。

替代"仅 IF NOT EXISTS"的无版本 schema 演进。规则：
- 版本号 int 严格递增，注册即排序；执行过的版本按 user_version 跳过
- 每条迁移独立事务：失败回滚并上抛（调用方决定启动失败/软降级）
- 注册表模块级——迁移内容写死在本文件，不读外部 SQL（防注入/防漂移）
- 接入面刻意最小：首批只挂记忆持久库（cognitive_storage_engine），
  其余库渐进接入
"""
import sqlite3
import threading
from typing import Callable, List, Tuple, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MigrationStep = Tuple[int, Union[str, Callable]]
_MIGRATIONS: List[MigrationStep] = []
_registry_lock = threading.RLock()


def register_migration(version: int, step: Union[str, Callable]) -> None:
    """注册迁移（版本号必须大于已注册最大版本；重复注册幂等忽略）。"""
    with _registry_lock:
        if any(v == version for v, _ in _MIGRATIONS):
            return
        _MIGRATIONS.append((version, step))
        _MIGRATIONS.sort(key=lambda t: t[0])


def migrate(conn, db_label: str = "db") -> List[int]:
    """执行未应用的迁移，返回本次应用的版本号列表。

    注意：sqlite3.executescript 会先隐式 COMMIT 当前事务再执行脚本，
    故 SQL 脚本型迁移无法包在显式事务里——其原子性由脚本自身
    （IF NOT EXISTS/幂等语句）保证；callable 迁移保持显式事务+回滚。
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    with _registry_lock:
        pending = [(v, s) for v, s in _MIGRATIONS if v > current]
    applied: List[int] = []
    for version, step in pending:
        if isinstance(step, str):
            try:
                conn.executescript(step)
                conn.execute("PRAGMA user_version = %d" % int(version))
                applied.append(version)
                logger.info("DB migration %s: user_version → %d", db_label, version)
            except Exception:
                logger.error("DB migration %s failed at v%d (script)", db_label, version)
                raise
        else:
            try:
                conn.execute("BEGIN")
                step(conn)
                conn.execute("PRAGMA user_version = %d" % int(version))
                conn.execute("COMMIT")
                applied.append(version)
                logger.info("DB migration %s: user_version → %d", db_label, version)
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                logger.error("DB migration %s failed at v%d (rolled back)", db_label, version)
                raise
    return applied


# v1：基线占位——既有表结构由 memory_layer/schema.py IF NOT EXISTS 管理，
# 本条仅确立版本起点，后续 schema 变更加 2/3/... 注册即可。
register_migration(1, "SELECT 1")
