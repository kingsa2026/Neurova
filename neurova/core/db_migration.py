# -*- coding: utf-8 -*-
"""SQLite 版本化迁移（PRAGMA user_version，补课 1.2 + Yuxi 对比 P0-4）。

替代"仅 IF NOT EXISTS"的无版本 schema 演进。规则：
- **版本按 domain 隔离**（2026-09-13 根治）：每库一个版本域，A 域的 v2
  不会套到 B 库头上（旧全局单链缺陷）；注册即排序、执行过的版本按
  user_version 跳过
- **防降级**：库的 user_version 高于本域已注册最大版本 → SchemaVersionError
  （对位 Yuxi require_current_schema / OpenClaw "user_version 高于当前版本
  拒绝打开"——新代码写过 schema 后回滚旧代码继续跑只会制造脏写）
- 未注册域 → ValueError：接入纪律显式化，不静默放过拼错的域名
- 每条 callable 迁移独立事务：失败回滚并上抛（调用方决定启动失败/软降级）
- 注册表模块级——迁移内容写死在代码，不读外部 SQL（防注入/防漂移）
- 接入面渐进：已登记 memory（基线 v1）；channel_ingress/agent_runs 随
  各自模块登记；其余库接入时在模块内 register_migration(domain=...) 即可
"""
import sqlite3
import threading
from typing import Callable, Dict, List, Tuple, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MigrationStep = Tuple[int, Union[str, Callable]]
# domain -> 已排序迁移链（旧实现为全局单链，2026-09-13 P0-4 改域隔离）
_DOMAIN_MIGRATIONS: Dict[str, List[MigrationStep]] = {}
_registry_lock = threading.RLock()


class SchemaVersionError(RuntimeError):
    """库 schema 版本高于代码已知版本（降级运行防护，拒绝打开继续跑）。"""


def register_migration(
    version: int, step: Union[str, Callable], domain: str = "memory"
) -> None:
    """注册迁移到指定版本域（版本号必须大于该域已注册最大版本；重复注册幂等忽略）。"""
    with _registry_lock:
        steps = _DOMAIN_MIGRATIONS.setdefault(domain, [])
        if any(v == version for v, _ in steps):
            return
        if steps and version <= steps[-1][0]:
            raise ValueError(
                f"迁移版本必须严格递增：domain={domain!r} 已注册至 v{steps[-1][0]}，拒绝 v{version}"
            )
        steps.append((version, step))
        steps.sort(key=lambda t: t[0])


def registered_domains() -> List[str]:
    with _registry_lock:
        return sorted(_DOMAIN_MIGRATIONS)


def schema_version(conn) -> int:
    """读取库的 user_version（调用方须已确定 domain）。"""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn, domain: str = "memory") -> List[int]:
    """对指定版本域执行未应用的迁移，返回本次应用的版本号列表。

    Raises:
        ValueError: 域未注册（接入纪律：先 register_migration 再 migrate）
        SchemaVersionError: 库版本高于域内已注册最大版本（防降级）

    注意：sqlite3.executescript 会先隐式 COMMIT 当前事务再执行脚本，
    故 SQL 脚本型迁移无法包在显式事务里——其原子性由脚本自身
    （IF NOT EXISTS/幂等语句）保证；callable 迁移保持显式事务+回滚。
    """
    with _registry_lock:
        if domain not in _DOMAIN_MIGRATIONS:
            raise ValueError(
                f"未注册的 schema 版本域: {domain!r}（已注册: {registered_domains()}；"
                "接入新库须先 register_migration(version, step, domain=...))"
            )
        steps = list(_DOMAIN_MIGRATIONS[domain])
    current = schema_version(conn)
    max_registered = steps[-1][0] if steps else 0
    if current > max_registered:
        raise SchemaVersionError(
            f"domain={domain!r} 库 user_version={current} 高于代码已知最大版本 "
            f"{max_registered}——疑似旧代码打开新 schema 库，拒绝降级运行"
        )
    pending = [(v, s) for v, s in steps if v > current]
    applied: List[int] = []
    for version, step in pending:
        if isinstance(step, str):
            try:
                conn.executescript(step)
                conn.execute("PRAGMA user_version = %d" % int(version))
                applied.append(version)
                logger.info("DB migration %s: user_version → %d", domain, version)
            except Exception:
                logger.error("DB migration %s failed at v%d (script)", domain, version)
                raise
        else:
            try:
                conn.execute("BEGIN")
                step(conn)
                conn.execute("PRAGMA user_version = %d" % int(version))
                conn.execute("COMMIT")
                applied.append(version)
                logger.info("DB migration %s: user_version → %d", domain, version)
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                logger.error("DB migration %s failed at v%d (rolled back)", domain, version)
                raise
    return applied


# v1：基线占位——既有表结构由 memory_layer/schema.py IF NOT EXISTS 管理，
# 本条仅确立版本起点，后续 schema 变更加 2/3/... 注册即可。
register_migration(1, "SELECT 1", domain="memory")
