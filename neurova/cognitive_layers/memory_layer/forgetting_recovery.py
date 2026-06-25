"""
遗忘恢复模块 - 提供从归档/删除状态恢复记忆的功能

功能:
- 归档记忆管理
- 删除记忆管理
- 从归档状态恢复记忆
- 从删除状态恢复记忆
- 恢复历史记录
"""

import datetime
from neurova.core.logger import get_logger
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


# ────── Enums ──────


class RecoveryStatus(Enum):
    """恢复状态"""

    SUCCESS = "success"  # 成功
    NOT_FOUND = "not_found"  # 未找到
    ALREADY_RECOVERED = "already_recovered"  # 已恢复
    PERMANENTLY_DELETED = "permanently_deleted"  # 已永久删除
    FAILED = "failed"  # 失败


# ────── Main Manager ──────


class ForgettingRecoveryManager:
    """
    遗忘恢复管理器

    提供从归档/删除状态恢复记忆的功能。
    """

    def __init__(self, storage_path: Optional[str] = None):
        """
        初始化遗忘恢复管理器

        Args:
            storage_path: 存储路径
        """
        self.storage_path = storage_path

        # 存储
        self._archived_memories: Dict[str, Dict[str, Any]] = {}
        self._deleted_memories: Dict[str, Dict[str, Any]] = {}
        self._recovery_history: List[Dict[str, Any]] = []

        logger.info("ForgettingRecoveryManager 初始化完成")

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

    def recover_from_archive(self, memory_id: str) -> tuple[RecoveryStatus, Optional[Dict[str, Any]]]:
        """
        从归档状态恢复记忆

        Args:
            memory_id: 记忆ID

        Returns:
            (恢复状态, 恢复的记忆数据)
        """
        if memory_id not in self._archived_memories:
            return RecoveryStatus.NOT_FOUND, None

        archive_record = self._archived_memories[memory_id]
        memory_data = archive_record["memory_data"]

        # 记录恢复历史
        now = datetime.datetime.now(datetime.timezone.utc)
        self._recovery_history.append(
            {
                "memory_id": memory_id,
                "recovered_from": "archive",
                "recovered_at": now.isoformat(),
                "original_reason": archive_record["reason"],
            }
        )

        # 从归档中移除
        del self._archived_memories[memory_id]

        logger.debug("从归档恢复记忆: %s", memory_id)

        return RecoveryStatus.SUCCESS, memory_data

    def recover_from_delete(self, memory_id: str) -> tuple[RecoveryStatus, Optional[Dict[str, Any]]]:
        """
        从删除状态恢复记忆

        Args:
            memory_id: 记忆ID

        Returns:
            (恢复状态, 恢复的记忆数据)
        """
        if memory_id not in self._deleted_memories:
            # 检查是否已永久删除
            # 这里简化处理，实际应该检查永久删除记录
            return RecoveryStatus.PERMANENTLY_DELETED, None

        delete_record = self._deleted_memories[memory_id]

        # 检查是否已永久删除
        if delete_record.get("permanent", False):
            return RecoveryStatus.PERMANENTLY_DELETED, None

        memory_data = delete_record["memory_data"]

        # 记录恢复历史
        now = datetime.datetime.now(datetime.timezone.utc)
        self._recovery_history.append(
            {
                "memory_id": memory_id,
                "recovered_from": "soft_delete",
                "recovered_at": now.isoformat(),
                "original_reason": delete_record["reason"],
            }
        )

        # 从软删除中移除
        del self._deleted_memories[memory_id]

        logger.debug("从软删除恢复记忆: %s", memory_id)

        return RecoveryStatus.SUCCESS, memory_data

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

    def permanently_delete(self, memory_id: str, from_archive: bool = False) -> bool:
        """
        永久删除记忆

        Args:
            memory_id: 记忆ID
            from_archive: 是否从归档中删除

        Returns:
            是否删除成功
        """
        if from_archive:
            if memory_id in self._archived_memories:
                del self._archived_memories[memory_id]
                logger.debug("永久删除归档记忆: %s", memory_id)
                return True
        else:
            if memory_id in self._deleted_memories:
                del self._deleted_memories[memory_id]
                logger.debug("永久删除软删除记忆: %s", memory_id)
                return True

        return False

    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

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
