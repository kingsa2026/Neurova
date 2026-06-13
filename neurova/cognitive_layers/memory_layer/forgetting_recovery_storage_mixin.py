"""
Forgetting Recovery Storage Mixin - 遗忘恢复存储功能

提供归档、删除和恢复记忆的存储功能。
"""

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ForgettingRecoveryStorageMixin:
    """
    遗忘恢复存储 Mixin

    提供归档、删除和恢复记忆的存储功能。
    """

    def __init__(self):
        """初始化遗忘恢复存储"""
        self._archived_memories: Dict[str, Dict[str, Any]] = {}
        self._deleted_memories: Dict[str, Dict[str, Any]] = {}
        self._recovery_history: List[Dict[str, Any]] = []
        logger.info("ForgettingRecoveryStorageMixin 初始化完成")

    def archive_memory(
        self,
        memory_id: str,
        memory_data: Dict[str, Any],
        reason: str = "forgotten",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        归档记忆

        Args:
            memory_id: 记忆ID
            memory_data: 记忆数据
            reason: 归档原因
            metadata: 可选的元数据

        Returns:
            归档记录
        """
        now = datetime.datetime.now(datetime.timezone.utc)

        archive_record = {
            "id": str(uuid.uuid4()),
            "memory_id": memory_id,
            "memory_data": memory_data,
            "reason": reason,
            "metadata": metadata or {},
            "archived_at": now.isoformat(),
            "status": "archived",
        }

        self._archived_memories[memory_id] = archive_record
        logger.debug("归档记忆: %s (原因: %s)", memory_id, reason)

        return archive_record

    def delete_memory(
        self,
        memory_id: str,
        memory_data: Dict[str, Any],
        reason: str = "explicit_delete",
        permanent: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        删除记忆

        Args:
            memory_id: 记忆ID
            memory_data: 记忆数据
            reason: 删除原因
            permanent: 是否永久删除
            metadata: 可选的元数据

        Returns:
            删除记录
        """
        now = datetime.datetime.now(datetime.timezone.utc)

        delete_record = {
            "id": str(uuid.uuid4()),
            "memory_id": memory_id,
            "memory_data": memory_data,
            "reason": reason,
            "permanent": permanent,
            "metadata": metadata or {},
            "deleted_at": now.isoformat(),
            "status": "deleted" if permanent else "soft_deleted",
        }

        if permanent:
            # 永久删除，不保留恢复能力
            logger.debug("永久删除记忆: %s", memory_id)
        else:
            # 软删除，保留恢复能力
            self._deleted_memories[memory_id] = delete_record
            logger.debug("软删除记忆: %s", memory_id)

        return delete_record

    def recover_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        恢复记忆

        Args:
            memory_id: 记忆ID

        Returns:
            恢复的记忆数据，如果无法恢复返回None
        """
        now = datetime.datetime.now(datetime.timezone.utc)

        # 首先检查归档的记忆
        if memory_id in self._archived_memories:
            archive_record = self._archived_memories[memory_id]
            memory_data = archive_record["memory_data"]

            # 记录恢复历史
            self._recovery_history.append(
                {
                    "memory_id": memory_id,
                    "recovered_from": "archive",
                    "recovered_at": now.isoformat(),
                    "original_archive_reason": archive_record["reason"],
                }
            )

            # 从归档中移除
            del self._archived_memories[memory_id]

            logger.debug("从归档恢复记忆: %s", memory_id)
            return memory_data

        # 检查软删除的记忆
        if memory_id in self._deleted_memories:
            delete_record = self._deleted_memories[memory_id]
            memory_data = delete_record["memory_data"]

            # 记录恢复历史
            self._recovery_history.append(
                {
                    "memory_id": memory_id,
                    "recovered_from": "soft_delete",
                    "recovered_at": now.isoformat(),
                    "original_delete_reason": delete_record["reason"],
                }
            )

            # 从软删除中移除
            del self._deleted_memories[memory_id]

            logger.debug("从软删除恢复记忆: %s", memory_id)
            return memory_data

        return None

    def get_archived_memories(
        self,
        reason: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        获取归档记忆

        Args:
            reason: 按原因过滤
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            归档记忆列表
        """
        archives = list(self._archived_memories.values())

        # 按原因过滤
        if reason:
            archives = [a for a in archives if a["reason"] == reason]

        # 按归档时间排序
        archives.sort(key=lambda x: x["archived_at"], reverse=True)

        return archives[offset : offset + limit]

    def get_deleted_memories(
        self,
        reason: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        获取软删除记忆

        Args:
            reason: 按原因过滤
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            软删除记忆列表
        """
        deleted = list(self._deleted_memories.values())

        # 按原因过滤
        if reason:
            deleted = [d for d in deleted if d["reason"] == reason]

        # 按删除时间排序
        deleted.sort(key=lambda x: x["deleted_at"], reverse=True)

        return deleted[offset : offset + limit]

    def get_recovery_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取恢复历史

        Args:
            limit: 返回数量限制

        Returns:
            恢复历史列表
        """
        history = sorted(self._recovery_history, key=lambda x: x["recovered_at"], reverse=True)
        return history[:limit]

    def search_archived_memories(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        搜索归档记忆

        Args:
            query: 搜索查询
            limit: 返回数量限制

        Returns:
            匹配的归档记忆
        """
        query_lower = query.lower()
        results = []

        for archive in self._archived_memories.values():
            # 在记忆数据中搜索
            memory_data = archive["memory_data"]
            content = memory_data.get("content", "")

            if query_lower in content.lower():
                results.append(archive)

        # 按归档时间排序
        results.sort(key=lambda x: x["archived_at"], reverse=True)

        return results[:limit]

    def get_forgetting_statistics(self) -> Dict[str, Any]:
        """
        获取遗忘统计信息

        Returns:
            统计信息字典
        """
        archived = list(self._archived_memories.values())
        deleted = list(self._deleted_memories.values())

        # 归档原因分布
        archive_reason_dist: Dict[str, int] = {}
        for archive in archived:
            reason = archive["reason"]
            archive_reason_dist[reason] = archive_reason_dist.get(reason, 0) + 1

        # 删除原因分布
        delete_reason_dist: Dict[str, int] = {}
        for delete in deleted:
            reason = delete["reason"]
            delete_reason_dist[reason] = delete_reason_dist.get(reason, 0) + 1

        # 恢复统计
        recovery_count = len(self._recovery_history)
        recovery_from_archive = sum(1 for r in self._recovery_history if r["recovered_from"] == "archive")
        recovery_from_delete = sum(1 for r in self._recovery_history if r["recovered_from"] == "soft_delete")

        return {
            "archived_count": len(archived),
            "deleted_count": len(deleted),
            "total_forgettable": len(archived) + len(deleted),
            "archive_reason_distribution": archive_reason_dist,
            "delete_reason_distribution": delete_reason_dist,
            "recovery_count": recovery_count,
            "recovery_from_archive": recovery_from_archive,
            "recovery_from_soft_delete": recovery_from_delete,
            "recovery_rate": recovery_count / (len(archived) + len(deleted)) if (archived or deleted) else 0.0,
        }

    def cleanup_old_archives(self, days: int = 30) -> int:
        """
        清理旧的归档记忆

        Args:
            days: 保留天数

        Returns:
            清理的记忆数量
        """
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        cutoff_str = cutoff.isoformat()

        to_delete = []
        for memory_id, archive in self._archived_memories.items():
            if archive["archived_at"] < cutoff_str:
                to_delete.append(memory_id)

        for memory_id in to_delete:
            del self._archived_memories[memory_id]

        if to_delete:
            logger.debug("清理 %s 个超过 %s 天的归档记忆", len(to_delete), days)

        return len(to_delete)

    def clear_all(self) -> Dict[str, int]:
        """
        清空所有存储

        Returns:
            清空的数量统计
        """
        archived_count = len(self._archived_memories)
        deleted_count = len(self._deleted_memories)
        history_count = len(self._recovery_history)

        self._archived_memories.clear()
        self._deleted_memories.clear()
        self._recovery_history.clear()

        logger.debug("清空所有存储: 归档 %s, 删除 %s, 历史 %s", archived_count, deleted_count, history_count)

        return {
            "archived_cleared": archived_count,
            "deleted_cleared": deleted_count,
            "history_cleared": history_count,
        }
