"""后台任务每日原子配额（资源治理 P1-2）。

借鉴参照系 ad 的后台频次治理形态（nightly topic 50/晚、classifier 200/日：
原子领取、存储不可用宁可不跑），按本仓单机 SQLite 形态落成：

- 原子性：BEGIN IMMEDIATE 串行化「读-判-增」，多连接并发领取不越限；
- fail-closed：配额存储不可用（连接坏/表坏/语句抛错）一律拒绝放行——
  后台任务少跑一轮可恢复，失控跑批不可恢复；
- 粒度：(配额名, UTC 日) 二元计数，跨日自然归零（主键 (name, day)）；
- 上限：环境变量注入（dailyLimitFromEnv），缺省由接线点给足量——正常
  节奏打不到顶，异常风暴（触发器死循环等）才触顶。

表结构走 db_migration 注册表（domain=background_quota，v1），共享库经
apply_domain_steps 幂等应用（不写 user_version，防多域互踩）。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS background_quotas (
    name TEXT NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (name, day)
);
"""

from neurova.core.db_migration import register_migration

# DDL 唯一事实源落注册表（教义第 6 条）；共享库经 apply_domain_steps 幂等应用。
register_migration(1, _SCHEMA_V1, domain="background_quota")


def _utcDay(day: str | None) -> str:
    if day:
        return str(day)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def ensureQuotaSchema(conn) -> None:
    """幂等应用配额表 DDL（每次调用都执行 CREATE IF NOT EXISTS，代价可忽略）。"""
    from neurova.core.db_migration import apply_domain_steps

    apply_domain_steps(conn, "background_quota")


def dailyLimitFromEnv(envName: str, default: int) -> int:
    """从环境变量读每日上限；缺失/垃圾值回落缺省，负值钳 0（=全拒）。"""
    raw = os.getenv(envName)
    if raw is None or not str(raw).strip():
        return max(0, int(default))
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return max(0, int(default))


def acquireDailyQuota(name: str, limit: int, *, day: str | None = None, conn=None) -> bool:
    """原子领取一个当日配额名额。

    Args:
        name: 配额名（如 "rsi_iteration" / "sleep_cycle"）
        limit: 当日上限；<=0 一律拒绝（0 = 本日不跑）
        day: UTC 日（缺省取当天；测试可注入固定日）
        conn: 显式 SQLite 连接；缺省走连接池默认库（数据根 neurova_memory.db）

    Returns:
        True=放行（已计数）；False=超额或配额存储不可用（fail-closed）。
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return False
    day = _utcDay(day)

    ownCtx = None
    if conn is None:
        from neurova.core.connection_pool import get_db_connection

        ownCtx = get_db_connection()
        conn = ownCtx.__enter__()
    try:
        ensureQuotaSchema(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT count FROM background_quotas WHERE name=? AND day=?", (name, day)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO background_quotas(name, day, count) VALUES(?,?,1)",
                    (name, day),
                )
                granted = True
            elif int(row[0]) < limit:
                conn.execute(
                    "UPDATE background_quotas SET count=count+1 WHERE name=? AND day=?",
                    (name, day),
                )
                granted = True
            else:
                granted = False
            conn.commit()
            return granted
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 - 回滚失败不再叠加掩真
                pass
            raise
    except Exception:  # noqa: BLE001 - fail-closed：存储任何形态的不可用都拒绝放行
        logger.warning("后台配额存储不可用，fail-closed 拒绝：name=%s", name, exc_info=True)
        return False
    finally:
        if ownCtx is not None:
            ownCtx.__exit__(None, None, None)
