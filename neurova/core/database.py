"""
数据库连接管理

提供统一的数据库连接接口，支持连接池。
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import sqlite3
from typing import Optional
from contextlib import contextmanager

from neurova.core.connection_pool import get_connection_pool, get_db_connection, close_all_pools

logger = get_logger(__name__)

# 默认数据库路径
DEFAULT_DB_PATH = "neurova_memory.db"


def get_db_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    获取数据库连接（兼容旧接口）
    
    注意：推荐使用 get_db_connection() 上下文管理器。
    
    Args:
        db_path: 数据库文件路径
        
    Returns:
        sqlite3.Connection: 数据库连接
    """
    path = db_path or DEFAULT_DB_PATH
    pool = get_connection_pool(path)
    return pool.get_connection()


def return_db_conn(conn: sqlite3.Connection) -> None:
    """
    归还数据库连接（兼容旧接口）

    注意：推荐使用 get_db_connection() 上下文管理器。

    P1-4：按**归属**归还。原实现逐个池尝试 return_connection，而任意有效连接
    都能通过池的 SELECT 1 校验 —— 第一个池就会把别的库的连接收下（跨库串用）。
    现要求池先认领（SQLiteConnectionPool.owns），无池认领则关闭，避免泄漏。

    Args:
        conn: 要归还的连接
    """
    if conn is None:
        return

    for pool in _get_all_pools():
        try:
            if pool.owns(conn) and pool.return_connection(conn):
                return
        except Exception:
            continue

    # 没有池认领（池已关闭 / 该连接非池创建）：直接关闭
    try:
        conn.close()
    except Exception:
        pass


def get_short_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """借出一条池化短连接（P1-4 迁移入口）。

    "短连接"= 借出 → 一次操作 → 归还（见 ADR 0014）。调用方**必须**成对归还：
    `release_short_connection(conn)`，否则漏满 max_connections 后取连接会阻塞
    到 timeout。

    `:memory:` / 空路径不进池：池化对内存库无意义（池里那条连接持有的是
    另一个空库，借出者看到的是空 schema）。
    """
    path = db_path or DEFAULT_DB_PATH
    if not path or str(path).startswith(":memory:"):
        return _bare_connection(path)
    pool = get_connection_pool(str(path))
    return pool.get_connection()


def release_short_connection(conn: sqlite3.Connection) -> None:
    """归还短连接（与 get_short_connection 配对）。"""
    return_db_conn(conn)


def _bare_connection(db_path: str) -> sqlite3.Connection:
    """非池化裸连接（仅 :memory: / 空路径走这里）。

    刻意不开 foreign_keys —— 与迁移前的裸连接行为一致：迁移只改"连接来源"，
    不顺手改约束语义（行为变化须单独评估，否则迁移点会静默变更写入校验）。
    """
    conn = sqlite3.connect(db_path or ":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _get_all_pools():
    """获取所有连接池（内部方法）

    返回快照列表：直接返回 _pools.values() 视图时，并发新建池会让迭代中
    的 return_db_conn 撞 "dictionary changed size during iteration"。
    """
    from neurova.core.connection_pool import iter_pools

    return [pool for _, pool in iter_pools()]


@contextmanager
def short_connection(db_path: Optional[str] = None):
    """借出池化短连接，**不改事务语义**（P1-4 迁移用的最简形态）。

    与 `get_short_connection()` 的差别只有"自动归还"：进出块不 commit、不
    rollback，由调用方显式控制事务。适合原本就是"自己 commit"的调用点。

    注意：块内遗留的未提交事务会在归还时被池回滚（P0-2 的归还语义），
    所以需要"成功即提交"的调用点必须用 `short_transaction()`。
    """
    conn = get_short_connection(db_path)
    try:
        yield conn
    finally:
        release_short_connection(conn)


@contextmanager
def short_transaction(db_path: Optional[str] = None):
    """借出池化短连接 + 事务语义，替代裸 `with sqlite3.connect(...) as conn:`。

    保留 sqlite3.Connection 上下文管理器原有的**成功提交 / 异常回滚**语义，
    并补上原写法缺失的"关闭/归还"（`with conn` 不关闭连接——迁移前每次调用
    都漏一条，长跑进程句柄数线性增长；池化后漏归还则漏满并发上限即阻塞）。
    """
    conn = get_short_connection(db_path)
    try:
        yield conn
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 - 回滚失败不影响原异常传播
            pass
        raise
    finally:
        release_short_connection(conn)


@contextmanager
def database_connection(db_path: Optional[str] = None):
    """
    数据库连接上下文管理器
    
    自动获取和归还连接，推荐使用方式。
    
    Usage:
        with database_connection() as conn:
            conn.execute("SELECT * FROM table")
    
    Args:
        db_path: 数据库文件路径
    """
    path = db_path or DEFAULT_DB_PATH
    with get_db_connection(path) as conn:
        yield conn


def close_db_conn():
    """关闭所有数据库连接"""
    close_all_pools()
    logger.info("所有数据库连接已关闭")


# 兼容旧代码的全局连接（已废弃，仅用于向后兼容）
_db_conn: Optional[sqlite3.Connection] = None


def _get_db_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """获取数据库连接（旧接口，已废弃）"""
    import warnings
    warnings.warn(
        "_get_db_conn() is deprecated, use get_db_connection() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return get_db_conn(db_path)
