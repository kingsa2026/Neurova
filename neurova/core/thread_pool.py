"""
线程池管理器

提供全局共享的线程池实例，避免每次操作都创建新的 ThreadPoolExecutor
（创建/销毁线程是纯开销，且无上限派生会失控）。

用法：
    from neurova.core.thread_pool import get_thread_pool

    pool = get_thread_pool()                      # 默认共享池
    pool = get_thread_pool("asr-consent", 1)      # 具名共享池（1 worker）

具名池按 name 隔离 busy 面（长任务不会饿死其他调用方的短任务），
但同一 name 的调用方共享同一个池实例与同一组线程——这才是"共享单例"
的意义。max_workers 在该 name 首次注册时确定，后续同 name 传入不同值
只记 debug 日志并复用（避免两个调用方互相改对方池的大小）。

P0-2：暴露线程数 / 队列深度 / max_workers 快照（iter_pools），
供 core/metrics.py 的 observe_pools() 转成 prometheus gauge。
"""

from neurova.core.logger import get_logger
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Tuple

logger = get_logger(__name__)

# 默认池名（未指定 name 的调用方共用）
DEFAULT_POOL_NAME = "default"


class ThreadPoolManager:
    """线程池管理器

    提供全局共享的线程池实例，支持：
    - 线程安全的线程池获取（按 name 隔离）
    - 可配置的最大工作线程数（首次注册生效）
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
            max_workers: 默认池的最大工作线程数，None 使用 ThreadPoolExecutor 默认值
        """
        if self._initialized:
            return

        self._max_workers = max_workers
        # name -> (pool, max_workers)
        self._pools: Dict[str, Tuple[ThreadPoolExecutor, Optional[int]]] = {}
        self._pool_lock = threading.Lock()
        self._initialized = True

        logger.debug("ThreadPoolManager 初始化: max_workers=%s", max_workers)

    def _create_pool(self, name: str, max_workers: Optional[int]) -> ThreadPoolExecutor:
        """创建具名线程池（线程名前缀带池名，便于线程栈排查）。"""
        pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=f"neurova-{name}" if name != DEFAULT_POOL_NAME else "neurova-pool",
        )
        logger.debug("创建共享线程池: name=%s max_workers=%s", name, max_workers)
        return pool

    def get_pool(
        self, name: str = DEFAULT_POOL_NAME, max_workers: Optional[int] = None
    ) -> ThreadPoolExecutor:
        """获取（必要时创建）具名共享池。"""
        with self._pool_lock:
            existing = self._pools.get(name)
            if existing is not None:
                pool, registered_workers = existing
                if (
                    max_workers is not None
                    and registered_workers is not None
                    and max_workers != registered_workers
                ):
                    logger.debug(
                        "共享线程池 %s 已按 max_workers=%s 注册，忽略本次请求的 %s",
                        name,
                        registered_workers,
                        max_workers,
                    )
                return pool
            effective = max_workers if max_workers is not None else self._max_workers
            pool = self._create_pool(name, effective)
            self._pools[name] = (pool, effective)
            return pool

    @property
    def pool(self) -> ThreadPoolExecutor:
        """默认共享池（向后兼容旧调用）。"""
        return self.get_pool()

    @property
    def pool_name(self) -> str:
        """默认池标识（指标 label 用，向后兼容旧调用）。"""
        return DEFAULT_POOL_NAME

    def shutdown(self, wait: bool = True) -> None:
        """关闭全部共享池。"""
        with self._pool_lock:
            pools = list(self._pools.items())
            self._pools.clear()
        for name, (pool, _workers) in pools:
            try:
                pool.shutdown(wait=wait)
                logger.debug("共享线程池已关闭: name=%s", name)
            except Exception as e:  # noqa: BLE001 - 关闭期故障不阻断其余池收尾
                logger.warning("关闭共享线程池 %s 失败: %s", name, e)


# 全局线程池管理器实例
_manager: Optional[ThreadPoolManager] = None
_manager_lock = threading.Lock()


def get_thread_pool_manager(max_workers: Optional[int] = None) -> ThreadPoolManager:
    """
    获取全局线程池管理器

    Args:
        max_workers: 默认池的最大工作线程数（仅管理器首次创建时生效）

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


def get_thread_pool(
    max_workers: Optional[int] = None, name: str = DEFAULT_POOL_NAME
) -> ThreadPoolExecutor:
    """
    获取共享线程池（同一 name 返回同一实例，不随调用创建新池）

    Args:
        max_workers: 最大工作线程数（该 name 首次注册时生效）
        name: 池名。不同用途建议用不同 name（长任务不饿死短任务）

    Returns:
        ThreadPoolExecutor: 共享线程池实例
    """
    manager = get_thread_pool_manager(max_workers)
    return manager.get_pool(name=name, max_workers=max_workers)


def iter_pools():
    """遍历当前已创建的线程池（metrics 快照用）。

    返回 (name, pool) 列表；未创建即"未使用"，**不触发懒加载**——不应因
    抓指标而建池。

    具名多池形态为 name -> (pool, max_workers)；防御性地也接受裸 pool 条目，
    使观测面不因内部结构微调而丢指标。
    """
    manager = _manager
    if manager is None:
        return []

    named = getattr(manager, "_pools", None)
    if isinstance(named, dict) and named:
        snapshot = list(named.items())
        out = []
        for name, entry in snapshot:
            # 具名多池形态为 name -> (pool, max_workers)；防御性地也接受裸 pool
            pool = entry[0] if isinstance(entry, tuple) else entry
            if pool is not None:
                out.append((str(name), pool))
        return out

    # 具名多池已是唯一实现，缺 _pools 视为未创建
    return []


def shutdown_thread_pool(wait: bool = True) -> None:
    """关闭全部共享线程池（测试/停机收口）"""
    global _manager
    if _manager is not None:
        _manager.shutdown(wait)
        _manager = None
