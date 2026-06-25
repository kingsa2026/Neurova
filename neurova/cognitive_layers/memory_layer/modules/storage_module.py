"""
StorageModule — 存储管理模块

管理记忆的持久化存储，支持多种存储后端
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import threading
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class StorageModule:
    """
    存储管理模块

    统一管理记忆的存储操作，支持：
    - 记忆写入/读取/删除
    - 批量操作
    - 存储统计
    """

    def __init__(self, storage_backend: Optional[Any] = None):
        """
        Args:
            storage_backend: 存储后端实例
        """
        self._storage = storage_backend
        self._lock = threading.RLock()
        self._initialized = False
        self._write_count = 0
        self._read_count = 0

    @property
    def name(self) -> str:
        """模块名称"""
        return "storage_module"

    def init(self) -> bool:
        """初始化模块"""
        if self._initialized:
            return True

        try:
            if self._storage and hasattr(self._storage, "init"):
                self._storage.init()

            self._initialized = True
            logger.info("StorageModule initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize StorageModule: %s", e)
            return False

    def shutdown(self) -> None:
        """关闭模块"""
        if self._storage and hasattr(self._storage, "shutdown"):
            self._storage.shutdown()

        self._initialized = False
        logger.info("StorageModule shutdown")

    def store(self, memory_data: Dict[str, Any]) -> Optional[str]:
        """
        存储记忆

        Args:
            memory_data: 记忆数据

        Returns:
            记忆ID，失败返回 None
        """
        if not self._storage:
            logger.warning("Storage backend not configured")
            return None

        try:
            with self._lock:
                if hasattr(self._storage, "store"):
                    memory_id = self._storage.store(memory_data)
                elif hasattr(self._storage, "save"):
                    memory_id = self._storage.save(memory_data)
                else:
                    logger.error("Storage backend has no store/save method")
                    return None

                self._write_count += 1
                return memory_id

        except Exception as e:
            logger.error("Failed to store memory: %s", e)
            return None

    def retrieve(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        检索记忆

        Args:
            memory_id: 记忆ID

        Returns:
            记忆数据，不存在返回 None
        """
        if not self._storage:
            return None

        try:
            with self._lock:
                if hasattr(self._storage, "retrieve"):
                    data = self._storage.retrieve(memory_id)
                elif hasattr(self._storage, "get"):
                    data = self._storage.get(memory_id)
                else:
                    return None

                self._read_count += 1
                return data

        except Exception as e:
            logger.error("Failed to retrieve memory '%s': %s", memory_id, e)
            return None

    def delete(self, memory_id: str) -> bool:
        """删除记忆"""
        if not self._storage:
            return False

        try:
            with self._lock:
                if hasattr(self._storage, "delete"):
                    return self._storage.delete(memory_id)
                elif hasattr(self._storage, "remove"):
                    return self._storage.remove(memory_id)
            return False

        except Exception as e:
            logger.error("Failed to delete memory '%s': %s", memory_id, e)
            return False

    def search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """搜索记忆"""
        if not self._storage:
            return []

        try:
            with self._lock:
                if hasattr(self._storage, "search"):
                    results = self._storage.search(query, limit=limit, filters=filters)
                elif hasattr(self._storage, "find"):
                    results = self._storage.find(query, limit=limit)
                else:
                    results = []

                self._read_count += 1
                return results

        except Exception as e:
            logger.error("Failed to search memories: %s", e)
            return []

    def batch_store(self, memories: List[Dict[str, Any]]) -> List[Optional[str]]:
        """批量存储"""
        results = []
        for memory in memories:
            results.append(self.store(memory))
        return results

    def batch_retrieve(self, memory_ids: List[str]) -> List[Optional[Dict[str, Any]]]:
        """批量检索"""
        results = []
        for memory_id in memory_ids:
            results.append(self.retrieve(memory_id))
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            stats = {
                "initialized": self._initialized,
                "write_count": self._write_count,
                "read_count": self._read_count,
                "backend_type": type(self._storage).__name__ if self._storage else None,
            }

            # 获取后端统计
            if self._storage and hasattr(self._storage, "get_stats"):
                try:
                    stats["backend_stats"] = self._storage.get_stats()
                except Exception:
                    pass

            return stats

    def set_storage_backend(self, backend: Any) -> None:
        """设置存储后端"""
        with self._lock:
            self._storage = backend
