"""SQLite 存储自治理（资源治理 P2-5）。

借鉴参照系 ad 的存储治理形态（autovacuum 调优迁移 + 回收站定时 purge +
FTS outbox 死信），按本仓单机 SQLite 形态落成周期系统 job：

- `PRAGMA wal_checkpoint(TRUNCATE)`：把 WAL 收缩归档，防 WAL 无界增长；
- `PRAGMA optimize`：SQLite 官方推荐的廉价周期维护（按需 ANALYZE）；
- 结果计入 `neurova_db_maintenance_last_run_unixtime` gauge（可观测）。

注册走 app 启动装配（同 swarm_event_store_prune 范式）：每日一次。
"""

from __future__ import annotations

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def runDatabaseMaintenance(db_path: str = "") -> dict:
    """对指定库（缺省=数据根默认库）执行一轮自治理，返回统计。"""
    from neurova.core.connection_pool import get_connection_pool

    pool = get_connection_pool(db_path)
    with pool.connection() as conn:
        checkpointRow = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        conn.execute("PRAGMA optimize")
        conn.commit()
    stats = {
        "db": pool.db_path,
        "wal_busy": int(checkpointRow[0]) if checkpointRow else None,
        "wal_log_frames": int(checkpointRow[1]) if checkpointRow else None,
        "wal_checkpointed_frames": int(checkpointRow[2]) if checkpointRow else None,
    }
    try:
        from neurova.core.metrics import record_db_maintenance_run

        record_db_maintenance_run(pool.db_path)
    except Exception:  # noqa: BLE001 - 埋点失败不影响维护本身
        logger.debug("db maintenance metric failed", exc_info=True)
    logger.info(
        "SQLite 存储自治理完成: db=%s wal_checkpointed=%s",
        stats["db"], stats["wal_checkpointed_frames"],
    )
    return stats


def _maintenanceJobOnce() -> dict:
    """系统 job 包装：维护失败诚实记档（fail-soft，不拖垮调度器）。"""
    try:
        return runDatabaseMaintenance()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite 存储自治理失败: %s", exc)
        return {"ok": False, "error": str(exc)}


def registerDatabaseMaintenanceJob(scheduler) -> bool:
    """把存储自治理挂成每日系统 job（jobId=db_maintenance，幂等）。"""
    if scheduler is None or not hasattr(scheduler, "addSystemJob"):
        return False
    scheduler.addSystemJob(_maintenanceJobOnce, "db_maintenance", 86400)
    return True
