"""
版本控制与演进 - 记忆版本快照、演变追踪、版本回滚
"""

from __future__ import annotations

import datetime
import json
from neurova.core.logger import get_logger
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class VersionType(str, Enum):
    """版本类型"""

    SNAPSHOT = "snapshot"  # 完整快照
    DELTA = "delta"  # 增量更新
    ROLLBACK = "rollback"  # 回滚点
    MERGE = "merge"  # 合并点


@dataclass
class MemoryVersion:
    """记忆版本"""

    version_id: str
    memory_id: str
    version_type: VersionType
    timestamp: datetime.datetime
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_version_id: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None
    author: str = "system"
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "version_id": self.version_id,
            "memory_id": self.memory_id,
            "version_type": self.version_type.value,
            "timestamp": self.timestamp.isoformat(),
            "content": self.content,
            "metadata": self.metadata,
            "author": self.author,
            "description": self.description,
        }
        if self.parent_version_id:
            result["parent_version_id"] = self.parent_version_id
        if self.changes:
            result["changes"] = self.changes
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryVersion":
        """从字典创建"""
        return cls(
            version_id=data["version_id"],
            memory_id=data["memory_id"],
            version_type=VersionType(data["version_type"]),
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            content=data["content"],
            metadata=data.get("metadata", {}),
            parent_version_id=data.get("parent_version_id"),
            changes=data.get("changes"),
            author=data.get("author", "system"),
            description=data.get("description", ""),
        )


@dataclass
class VersionDiff:
    """版本差异"""

    version_id_1: str
    version_id_2: str
    content_diff: str
    metadata_diff: Dict[str, Any] = field(default_factory=dict)
    timestamp_diff_seconds: float = 0.0
    changes_summary: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "version_id_1": self.version_id_1,
            "version_id_2": self.version_id_2,
            "content_diff": self.content_diff,
            "metadata_diff": self.metadata_diff,
            "timestamp_diff_seconds": self.timestamp_diff_seconds,
            "changes_summary": self.changes_summary,
        }


class MemoryVersionControl:
    """记忆版本控制

    提供记忆的版本快照、演变追踪、版本回滚功能。
    """

    def __init__(
        self,
        storage: Any = None,
        max_versions_per_memory: int = 100,
        max_total_versions: int = 10000,
    ):
        """初始化版本控制

        Args:
            storage: 存储引擎
            max_versions_per_memory: 每个记忆的最大版本数
            max_total_versions: 总最大版本数
        """
        self._storage = storage
        self._max_versions_per_memory = max_versions_per_memory
        self._max_total_versions = max_total_versions

        # 版本索引
        self._versions: Dict[str, List[MemoryVersion]] = defaultdict(list)  # memory_id -> versions
        self._version_index: Dict[str, MemoryVersion] = {}  # version_id -> version

        # 线程安全
        self._lock = threading.RLock()

        # 统计信息
        self._stats = {
            "total_versions": 0,
            "total_snapshots": 0,
            "total_rollbacks": 0,
            "total_merges": 0,
        }

        # 初始化版本表
        self._init_version_table()

        logger.info("MemoryVersionControl 初始化完成")

    def _init_version_table(self) -> None:
        """初始化版本表"""
        if self._storage is None:
            return

        try:
            # 创建版本表（如果不存在）
            if hasattr(self._storage, "execute"):
                self._storage.execute("""
                    CREATE TABLE IF NOT EXISTS memory_versions (
                        version_id TEXT PRIMARY KEY,
                        memory_id TEXT NOT NULL,
                        version_type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        content TEXT NOT NULL,
                        metadata TEXT,
                        parent_version_id TEXT,
                        changes TEXT,
                        author TEXT,
                        description TEXT
                    )
                """)

                # 创建索引
                self._storage.execute("""
                    CREATE INDEX IF NOT EXISTS idx_memory_versions_memory_id 
                    ON memory_versions(memory_id)
                """)

                self._storage.execute("""
                    CREATE INDEX IF NOT EXISTS idx_memory_versions_timestamp 
                    ON memory_versions(timestamp)
                """)

                # 加载现有版本
                self._load_versions()

        except Exception as e:
            logger.warning("初始化版本表失败: %s", e)

    def _load_versions(self) -> None:
        """加载现有版本"""
        if self._storage is None:
            return

        try:
            if hasattr(self._storage, "fetch_all"):
                rows = self._storage.fetch_all("SELECT * FROM memory_versions ORDER BY timestamp DESC")

                for row in rows:
                    version = self._row_to_version(row)
                    if version:
                        self._versions[version.memory_id].append(version)
                        self._version_index[version.version_id] = version
                        self._stats["total_versions"] += 1

                logger.info("加载了 %s 个版本", self._stats['total_versions'])
        except Exception as e:
            logger.warning("加载版本失败: %s", e)

    def _row_to_version(self, row: Any) -> Optional[MemoryVersion]:
        """将数据库行转换为版本对象

        Args:
            row: 数据库行

        Returns:
            版本对象
        """
        try:
            if isinstance(row, dict):
                return MemoryVersion.from_dict(row)
            elif isinstance(row, (tuple, list)):
                # 假设列顺序：version_id, memory_id, version_type, timestamp, content, metadata, parent_version_id, changes, author, description
                return MemoryVersion(
                    version_id=row[0],
                    memory_id=row[1],
                    version_type=VersionType(row[2]),
                    timestamp=datetime.datetime.fromisoformat(row[3]),
                    content=row[4],
                    metadata=json.loads(row[5]) if row[5] else {},
                    parent_version_id=row[6],
                    changes=json.loads(row[7]) if row[7] else None,
                    author=row[8] or "system",
                    description=row[9] or "",
                )
            return None
        except Exception as e:
            logger.warning("转换版本行失败: %s", e)
            return None

    def _save_version(self, version: MemoryVersion) -> None:
        """保存版本到存储

        Args:
            version: 版本对象
        """
        if self._storage is None:
            return

        try:
            if hasattr(self._storage, "execute"):
                self._storage.execute(
                    """
                    INSERT OR REPLACE INTO memory_versions 
                    (version_id, memory_id, version_type, timestamp, content, metadata, parent_version_id, changes, author, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version.version_id,
                        version.memory_id,
                        version.version_type.value,
                        version.timestamp.isoformat(),
                        version.content,
                        json.dumps(version.metadata),
                        version.parent_version_id,
                        json.dumps(version.changes) if version.changes else None,
                        version.author,
                        version.description,
                    ),
                )
        except Exception as e:
            logger.warning("保存版本失败: %s", e)

    def create_snapshot(
        self,
        memory_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        author: str = "system",
        description: str = "",
    ) -> MemoryVersion:
        """创建快照

        Args:
            memory_id: 记忆ID
            content: 记忆内容
            metadata: 附加元数据
            author: 作者
            description: 描述

        Returns:
            创建的版本
        """
        with self._lock:
            # 生成版本ID
            version_id = f"v_{memory_id}_{int(time.time() * 1000)}"

            # 获取父版本
            parent_version_id = None
            if memory_id in self._versions and self._versions[memory_id]:
                parent_version_id = self._versions[memory_id][-1].version_id

            # 创建版本
            version = MemoryVersion(
                version_id=version_id,
                memory_id=memory_id,
                version_type=VersionType.SNAPSHOT,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                content=content,
                metadata=metadata or {},
                parent_version_id=parent_version_id,
                author=author,
                description=description,
            )

            # 添加到索引
            self._versions[memory_id].append(version)
            self._version_index[version_id] = version

            # 限制版本数量
            self._cleanup_old_versions(memory_id)

            # 保存到存储
            self._save_version(version)

            # 更新统计
            self._stats["total_versions"] += 1
            self._stats["total_snapshots"] += 1

            logger.debug("创建快照: %s for memory %s", version_id, memory_id)
            return version

    def _cleanup_old_versions(self, memory_id: str) -> None:
        """清理旧版本

        Args:
            memory_id: 记忆ID
        """
        versions = self._versions[memory_id]

        # 限制每个记忆的版本数
        if len(versions) > self._max_versions_per_memory:
            # 保留最新的版本
            removed = versions[: -self._max_versions_per_memory]
            versions[:] = versions[-self._max_versions_per_memory :]

            # 从索引中移除
            for v in removed:
                if v.version_id in self._version_index:
                    del self._version_index[v.version_id]

            self._stats["total_versions"] -= len(removed)

        # 限制总版本数
        total_versions = sum(len(v) for v in self._versions.values())
        if total_versions > self._max_total_versions:
            # 找到最旧的版本并移除
            all_versions = []
            for mem_id, vers in self._versions.items():
                for v in vers:
                    all_versions.append((mem_id, v))

            all_versions.sort(key=lambda x: x[1].timestamp)

            # 移除最旧的版本
            to_remove = total_versions - self._max_total_versions
            for i in range(min(to_remove, len(all_versions))):
                mem_id, v = all_versions[i]
                if mem_id in self._versions:
                    self._versions[mem_id] = [x for x in self._versions[mem_id] if x.version_id != v.version_id]
                if v.version_id in self._version_index:
                    del self._version_index[v.version_id]
                self._stats["total_versions"] -= 1

    def get_version_history(
        self,
        memory_id: str,
        limit: int = 50,
        version_type: Optional[VersionType] = None,
    ) -> List[MemoryVersion]:
        """获取版本历史

        Args:
            memory_id: 记忆ID
            limit: 返回数量限制
            version_type: 版本类型过滤

        Returns:
            版本列表
        """
        with self._lock:
            versions = self._versions.get(memory_id, [])

            if version_type:
                versions = [v for v in versions if v.version_type == version_type]

            # 按时间排序，最新的在前
            versions.sort(key=lambda v: v.timestamp, reverse=True)

            return versions[:limit]

    def get_version(self, version_id: str) -> Optional[MemoryVersion]:
        """获取特定版本

        Args:
            version_id: 版本ID

        Returns:
            版本对象
        """
        with self._lock:
            return self._version_index.get(version_id)

    def rollback_to_version(self, version_id: str) -> Optional[MemoryVersion]:
        """回滚到特定版本

        Args:
            version_id: 版本ID

        Returns:
            回滚后的版本，如果失败返回None
        """
        with self._lock:
            # 获取目标版本
            target_version = self._version_index.get(version_id)
            if not target_version:
                logger.warning("版本不存在: %s", version_id)
                return None

            # 创建回滚版本
            rollback_version = self.create_snapshot(
                memory_id=target_version.memory_id,
                content=target_version.content,
                metadata={
                    **target_version.metadata,
                    "rollback_from": version_id,
                    "rollback_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                },
                author="system",
                description=f"回滚到版本 {version_id}",
            )

            # 更新版本类型
            rollback_version.version_type = VersionType.ROLLBACK

            # 更新统计
            self._stats["total_rollbacks"] += 1

            logger.info("回滚到版本: %s", version_id)
            return rollback_version

    def compare_versions(self, version_id_1: str, version_id_2: str) -> Optional[VersionDiff]:
        """比较两个版本

        Args:
            version_id_1: 版本1 ID
            version_id_2: 版本2 ID

        Returns:
            版本差异
        """
        with self._lock:
            version_1 = self._version_index.get(version_id_1)
            version_2 = self._version_index.get(version_id_2)

            if not version_1 or not version_2:
                logger.warning("版本不存在")
                return None

            # 简单的内容差异比较
            content_diff = ""
            if version_1.content != version_2.content:
                content_diff = f"内容已更改 (长度: {len(version_1.content)} -> {len(version_2.content)})"

            # 元数据差异
            metadata_diff = {}
            all_keys = set(version_1.metadata.keys()) | set(version_2.metadata.keys())
            for key in all_keys:
                val1 = version_1.metadata.get(key)
                val2 = version_2.metadata.get(key)
                if val1 != val2:
                    metadata_diff[key] = {"from": val1, "to": val2}

            # 时间差异
            timestamp_diff = (version_2.timestamp - version_1.timestamp).total_seconds()

            # 变更摘要
            changes_summary = []
            if content_diff:
                changes_summary.append("内容已修改")
            if metadata_diff:
                changes_summary.append(f"元数据有 {len(metadata_diff)} 处变更")

            return VersionDiff(
                version_id_1=version_id_1,
                version_id_2=version_id_2,
                content_diff=content_diff,
                metadata_diff=metadata_diff,
                timestamp_diff_seconds=timestamp_diff,
                changes_summary=changes_summary,
            )

    def get_latest_version(self, memory_id: str) -> Optional[MemoryVersion]:
        """获取最新版本

        Args:
            memory_id: 记忆ID

        Returns:
            最新版本
        """
        with self._lock:
            versions = self._versions.get(memory_id, [])
            if not versions:
                return None

            # 按时间排序，返回最新的
            versions.sort(key=lambda v: v.timestamp, reverse=True)
            return versions[0]

    def _get_current_version(self, memory_id: str) -> Optional[str]:
        """获取当前版本ID

        Args:
            memory_id: 记忆ID

        Returns:
            版本ID
        """
        latest = self.get_latest_version(memory_id)
        return latest.version_id if latest else None

    def _safe_json_loads(self, json_str: Optional[str]) -> Dict[str, Any]:
        """安全JSON解析

        Args:
            json_str: JSON字符串

        Returns:
            解析后的字典
        """
        if not json_str:
            return {}

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("JSON解析失败: %s", e)
            return {}

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                **self._stats,
                "memories_with_versions": len(self._versions),
            }

    def clear(self) -> None:
        """清空版本历史"""
        with self._lock:
            self._versions.clear()
            self._version_index.clear()

            self._stats = {
                "total_versions": 0,
                "total_snapshots": 0,
                "total_rollbacks": 0,
                "total_merges": 0,
            }

            logger.info("版本历史已清空")


# 全局实例管理
_version_control_instances: Dict[str, MemoryVersionControl] = {}
_version_control_lock = threading.Lock()


def get_version_control(
    storage: Any = None,
    instance_id: str = "default",
) -> MemoryVersionControl:
    """获取版本控制单例

    Args:
        storage: 存储引擎
        instance_id: 实例ID

    Returns:
        版本控制实例
    """
    global _version_control_instances

    with _version_control_lock:
        if instance_id not in _version_control_instances:
            _version_control_instances[instance_id] = MemoryVersionControl(storage=storage)
        return _version_control_instances[instance_id]


def reset_version_control(instance_id: Optional[str] = None) -> None:
    """重置版本控制单例

    Args:
        instance_id: 实例ID，为None时重置所有
    """
    global _version_control_instances

    with _version_control_lock:
        if instance_id is None:
            _version_control_instances.clear()
        elif instance_id in _version_control_instances:
            _version_control_instances[instance_id].clear()
            del _version_control_instances[instance_id]


def reset_all_version_control() -> None:
    """重置所有版本控制单例"""
    reset_version_control(None)
