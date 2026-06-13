"""
数据库连接池

提供SQLite连接池管理，支持：
- 连接复用
- 线程安全
- 自动重连
- 连接超时
"""

import sqlite3
import threading
import logging
from typing import Optional
from contextlib import contextmanager
from queue import Queue, Empty, Full

logger = logging.getLogger(__name__)


class SQLiteConnectionPool:
    """SQLite连接池
    
    使用队列管理连接，支持线程安全的连接获取和释放。
    """
    
    def __init__(
        self,
        db_path: str,
        max_connections: int = 5,
        timeout: float = 30.0,
        check_same_thread: bool = False,
    ):
        """
        初始化连接池
        
        Args:
            db_path: 数据库文件路径
            max_connections: 最大连接数
            timeout: 连接获取超时时间（秒）
            check_same_thread: 是否检查线程一致性（SQLite默认True）
        """
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        self.check_same_thread = check_same_thread
        
        self._pool: Queue = Queue(maxsize=max_connections)
        self._lock = threading.RLock()
        self._created_count = 0
        
        logger.debug("连接池初始化: db=%s, max_conn=%d", db_path, max_connections)
    
    def _create_connection(self) -> sqlite3.Connection:
        """创建新的数据库连接"""
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=self.check_same_thread,
            timeout=self.timeout,
        )
        conn.row_factory = sqlite3.Row
        # 启用WAL模式提高并发性能
        conn.execute("PRAGMA journal_mode=WAL")
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    
    def get_connection(self) -> sqlite3.Connection:
        """
        获取数据库连接
        
        优先从池中获取空闲连接，如果没有则创建新连接。
        
        Returns:
            sqlite3.Connection: 数据库连接
        """
        try:
            # 尝试从池中获取连接
            conn = self._pool.get(timeout=self.timeout)
            # 验证连接是否有效
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.ProgrammingError:
                # 连接已关闭，创建新连接
                with self._lock:
                    self._created_count -= 1
        except Empty:
            pass
        
        # 创建新连接
        with self._lock:
            if self._created_count >= self.max_connections:
                logger.warning("连接池已满，等待可用连接")
                try:
                    conn = self._pool.get(timeout=self.timeout)
                    return conn
                except Empty:
                    raise RuntimeError("无法获取数据库连接：连接池超时")
            
            self._created_count += 1
        
        logger.debug("创建新连接: %s (总数: %d)", self.db_path, self._created_count)
        return self._create_connection()
    
    def return_connection(self, conn: sqlite3.Connection) -> None:
        """
        归还连接到连接池
        
        Args:
            conn: 要归还的连接
        """
        if conn is None:
            return
        
        try:
            # 验证连接是否有效
            conn.execute("SELECT 1")
            # 尝试放回池中
            self._pool.put_nowait(conn)
        except (sqlite3.ProgrammingError, Full):
            # 连接已关闭或池已满，关闭连接
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._created_count -= 1
    
    def close_all(self) -> None:
        """关闭所有连接"""
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Exception:
                    pass
            self._created_count = 0
        logger.debug("所有连接已关闭: %s", self.db_path)
    
    @contextmanager
    def connection(self):
        """
        上下文管理器，自动获取和归还连接
        
        Usage:
            with pool.connection() as conn:
                conn.execute("SELECT * FROM table")
        """
        conn = self.get_connection()
        try:
            yield conn
        finally:
            self.return_connection(conn)
    
    @property
    def pool_size(self) -> int:
        """当前池中空闲连接数"""
        return self._pool.qsize()
    
    @property
    def active_count(self) -> int:
        """当前活跃连接数"""
        return self._created_count - self.pool_size


# 全局连接池管理
_pools: dict = {}
_pools_lock = threading.Lock()


def get_connection_pool(
    db_path: str = "neurova_memory.db",
    max_connections: int = 5,
) -> SQLiteConnectionPool:
    """
    获取或创建数据库连接池
    
    Args:
        db_path: 数据库文件路径
        max_connections: 最大连接数
        
    Returns:
        SQLiteConnectionPool: 连接池实例
    """
    with _pools_lock:
        if db_path not in _pools:
            _pools[db_path] = SQLiteConnectionPool(
                db_path=db_path,
                max_connections=max_connections,
            )
            logger.info("创建连接池: %s (max_conn=%d)", db_path, max_connections)
        return _pools[db_path]


def close_all_pools() -> None:
    """关闭所有连接池"""
    with _pools_lock:
        for db_path, pool in _pools.items():
            pool.close_all()
        _pools.clear()
    logger.info("所有连接池已关闭")


@contextmanager
def get_db_connection(db_path: str = "neurova_memory.db"):
    """
    获取数据库连接的便捷函数
    
    Usage:
        with get_db_connection() as conn:
            conn.execute("SELECT * FROM table")
    """
    pool = get_connection_pool(db_path)
    with pool.connection() as conn:
        yield conn
