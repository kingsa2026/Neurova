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
    
    Args:
        conn: 要归还的连接
    """
    if conn is None:
        return
    
    # 查找对应的连接池并归还
    for pool in _get_all_pools():
        try:
            pool.return_connection(conn)
            return
        except Exception:
            continue
    
    # 如果找不到池，直接关闭
    try:
        conn.close()
    except Exception:
        pass


def _get_all_pools():
    """获取所有连接池（内部方法）"""
    from neurova.core.connection_pool import _pools
    return _pools.values()


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
