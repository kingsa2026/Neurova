"""
记忆共享组管理

提供细粒度的跨 Agent 记忆共享控制：
- 共享组创建/删除
- Agent 加入/退出共享组
- 基于共享组的记忆查询过滤

使用方式：
    # 创建共享组
    manager = ShareGroupManager(storage_path="share_groups.json")
    group = manager.create_group(name="项目组A", agent_ids=["agent_1", "agent_2"])

    # 查询 Agent 所属的共享组
    groups = manager.get_groups_for_agent("agent_1")

    # 查询共享组中的所有 Agent
    agents = manager.get_agents_in_group(group.group_id)
"""

from __future__ import annotations

import json
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = get_logger(__name__)


@dataclass
class ShareGroup:
    """共享组数据模型"""

    group_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    description: str = ""
    agent_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ShareGroup:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ShareGroupManager:
    """共享组管理器

    线程安全的共享组 CRUD 操作，支持 JSON 文件持久化。
    """

    def __init__(self, storage_path: Optional[str] = None):
        """初始化共享组管理器

        Args:
            storage_path: 共享组数据持久化路径，None 则仅内存模式
        """
        self._lock = threading.RLock()
        self._groups: Dict[str, ShareGroup] = {}
        self._storage_path = Path(storage_path) if storage_path else None

        # 反向索引：agent_id -> set of group_ids
        self._agent_index: Dict[str, Set[str]] = {}

        if self._storage_path:
            self._load_from_file()

        logger.info("ShareGroupManager 初始化: %s 个共享组", len(self._groups))

    def _load_from_file(self) -> None:
        """从文件加载共享组"""
        if not self._storage_path or not self._storage_path.exists():
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for group_data in data.get("groups", []):
                group = ShareGroup.from_dict(group_data)
                self._groups[group.group_id] = group
                # 构建反向索引
                for agent_id in group.agent_ids:
                    if agent_id not in self._agent_index:
                        self._agent_index[agent_id] = set()
                    self._agent_index[agent_id].add(group.group_id)

            logger.info("从文件加载 %s 个共享组", len(self._groups))
        except Exception as e:
            logger.error("加载共享组文件失败: %s", e)

    def _save_to_file(self) -> None:
        """保存共享组到文件"""
        if not self._storage_path:
            return

        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "groups": [g.to_dict() for g in self._groups.values()],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("保存共享组文件失败: %s", e)

    def create_group(
        self,
        name: str,
        agent_ids: Optional[List[str]] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ShareGroup:
        """创建共享组

        Args:
            name: 组名称
            agent_ids: 初始 Agent ID 列表
            description: 描述
            metadata: 额外元数据

        Returns:
            创建的共享组
        """
        with self._lock:
            group = ShareGroup(
                name=name,
                description=description,
                agent_ids=list(set(agent_ids or [])),
                metadata=metadata or {},
            )
            self._groups[group.group_id] = group

            # 更新反向索引
            for agent_id in group.agent_ids:
                if agent_id not in self._agent_index:
                    self._agent_index[agent_id] = set()
                self._agent_index[agent_id].add(group.group_id)

            self._save_to_file()
            logger.info("创建共享组: %s (%s), agents=%s", group.group_id, name, group.agent_ids)
            return group

    def get_group(self, group_id: str) -> Optional[ShareGroup]:
        """获取共享组"""
        with self._lock:
            return self._groups.get(group_id)

    def list_groups(self) -> List[ShareGroup]:
        """列出所有共享组"""
        with self._lock:
            return list(self._groups.values())

    def update_group(
        self,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[ShareGroup]:
        """更新共享组信息（不修改 agent_ids）"""
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return None

            if name is not None:
                group.name = name
            if description is not None:
                group.description = description
            if metadata is not None:
                group.metadata = metadata
            group.updated_at = datetime.now(timezone.utc).isoformat()

            self._save_to_file()
            return group

    def delete_group(self, group_id: str) -> bool:
        """删除共享组"""
        with self._lock:
            group = self._groups.pop(group_id, None)
            if not group:
                return False

            # 更新反向索引
            for agent_id in group.agent_ids:
                if agent_id in self._agent_index:
                    self._agent_index[agent_id].discard(group_id)
                    if not self._agent_index[agent_id]:
                        del self._agent_index[agent_id]

            self._save_to_file()
            logger.info("删除共享组: %s", group_id)
            return True

    def add_agent_to_group(self, group_id: str, agent_id: str) -> bool:
        """将 Agent 添加到共享组"""
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return False

            if agent_id not in group.agent_ids:
                group.agent_ids.append(agent_id)
                group.updated_at = datetime.now(timezone.utc).isoformat()

                # 更新反向索引
                if agent_id not in self._agent_index:
                    self._agent_index[agent_id] = set()
                self._agent_index[agent_id].add(group_id)

                self._save_to_file()
                logger.info("Agent %s 加入共享组 %s", agent_id, group_id)

            return True

    def remove_agent_from_group(self, group_id: str, agent_id: str) -> bool:
        """从共享组移除 Agent"""
        with self._lock:
            group = self._groups.get(group_id)
            if not group:
                return False

            if agent_id in group.agent_ids:
                group.agent_ids.remove(agent_id)
                group.updated_at = datetime.now(timezone.utc).isoformat()

                # 更新反向索引
                if agent_id in self._agent_index:
                    self._agent_index[agent_id].discard(group_id)
                    if not self._agent_index[agent_id]:
                        del self._agent_index[agent_id]

                self._save_to_file()
                logger.info("Agent %s 退出共享组 %s", agent_id, group_id)

            return True

    def get_groups_for_agent(self, agent_id: str) -> List[ShareGroup]:
        """获取 Agent 所属的所有共享组"""
        with self._lock:
            group_ids = self._agent_index.get(agent_id, set())
            return [self._groups[gid] for gid in group_ids if gid in self._groups]

    def get_agents_in_group(self, group_id: str) -> List[str]:
        """获取共享组中的所有 Agent ID"""
        with self._lock:
            group = self._groups.get(group_id)
            return list(group.agent_ids) if group else []

    def get_shared_agent_ids(self, agent_id: str) -> Set[str]:
        """获取与指定 Agent 共享记忆的所有 Agent ID 集合

        包括自身和所有同组的 Agent。
        """
        with self._lock:
            result = {agent_id}  # 包括自身
            group_ids = self._agent_index.get(agent_id, set())
            for gid in group_ids:
                group = self._groups.get(gid)
                if group:
                    result.update(group.agent_ids)
            return result

    def are_agents_shared(self, agent_id_1: str, agent_id_2: str) -> bool:
        """检查两个 Agent 是否在同一共享组中"""
        with self._lock:
            groups_1 = self._agent_index.get(agent_id_1, set())
            groups_2 = self._agent_index.get(agent_id_2, set())
            return bool(groups_1 & groups_2)

    def get_group_ids_for_agent(self, agent_id: str) -> List[str]:
        """获取 Agent 所属的所有共享组 ID"""
        with self._lock:
            return list(self._agent_index.get(agent_id, set()))

    def clear(self) -> None:
        """清空所有共享组"""
        with self._lock:
            self._groups.clear()
            self._agent_index.clear()
            self._save_to_file()


# 全局单例
_default_manager: Optional[ShareGroupManager] = None
_manager_lock = threading.Lock()


def get_share_group_manager(storage_path: Optional[str] = None) -> ShareGroupManager:
    """获取全局共享组管理器单例"""
    global _default_manager
    if _default_manager is None:
        with _manager_lock:
            if _default_manager is None:
                _default_manager = ShareGroupManager(storage_path=storage_path)
    return _default_manager


def reset_share_group_manager() -> None:
    """重置全局共享组管理器（用于测试）"""
    global _default_manager
    with _manager_lock:
        _default_manager = None
