"""
线程池管理器

提供全局线程池实例，避免每次操作都创建新的 ThreadPoolExecutor。
"""

from neurova.core.logger import get_logger
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = get_logger(__name__)


class ThreadPoolManager:
    """线程池管理器
    
    提供全局共享的线程池实例，支持：
    - 线程安全的线程池获取
    - 可配置的最大工作线程数
    - 懒加载初始化
    """
    
    _instance: Optional["ThreadPoolManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, max_workers: Optional[int] = None):
        """
        初始化线程池管理器
        
        Args:
            max_workers: 最大工作线程数，None 使用默认值
        """
        if self._initialized:
            return
        
        self._max_workers = max_workers
        self._pool: Optional[ThreadPoolExecutor] = None
        self._pool_lock = threading.Lock()
        self._initialized = True
        
        logger.debug("ThreadPoolManager 初始化: max_workers=%s", max_workers)
    
    def _create_pool(self) -> ThreadPoolExecutor:
        """创建线程池"""
        pool = ThreadPoolExecutor(max_workers=self._max_workers)
        logger.debug("创建线程池: max_workers=%s", self._max_workers)
        return pool
    
    @property
    def pool(self) -> ThreadPoolExecutor:
        """获取线程池实例"""
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    self._pool = self._create_pool()
        return self._pool
    
    def shutdown(self, wait: bool = True):
        """关闭线程池"""
        if self._pool is not None:
            with self._pool_lock:
                if self._pool is not None:
                    self._pool.shutdown(wait=wait)
                    self._pool = None
                    logger.debug("线程池已关闭")


# 全局线程池管理器实例
_manager: Optional[ThreadPoolManager] = None
_manager_lock = threading.Lock()


def get_thread_pool_manager(max_workers: Optional[int] = None) -> ThreadPoolManager:
    """
    获取全局线程池管理器
    
    Args:
        max_workers: 最大工作线程数
        
    Returns:
        ThreadPoolManager: 线程池管理器实例
    """
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ThreadPoolManager()
                if max_workers is not None:
                    _manager._max_workers = max_workers
    return _manager


def get_thread_pool(max_workers: Optional[int] = None) -> ThreadPoolExecutor:
    """
    获取全局线程池
    
    Args:
        max_workers: 最大工作线程数
        
    Returns:
        ThreadPoolExecutor: 线程池实例
    """
    manager = get_thread_pool_manager(max_workers)
    return manager.pool


def shutdown_thread_pool(wait: bool = True):
    """关闭全局线程池"""
    global _manager
    if _manager is not None:
        _manager.shutdown(wait)
        _manager = None
