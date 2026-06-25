"""
技能池服务

管理技能的生命周期：注册、查询、启用/禁用、版本管理
"""

from __future__ import annotations

import datetime
from neurova.core.logger import get_logger
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = get_logger(__name__)


class SkillStatus(str, Enum):
    """技能状态"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"
    ERROR = "error"


@dataclass
class SkillEntry:
    """技能池中的技能条目"""

    skill_id: str
    name: str
    version: str
    description: str = ""
    category: str = ""
    status: SkillStatus = SkillStatus.ACTIVE
    tags: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    registered_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    last_used: Optional[datetime.datetime] = None
    usage_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "category": self.category,
            "status": self.status.value,
            "tags": self.tags,
            "capabilities": self.capabilities,
            "registered_at": self.registered_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "usage_count": self.usage_count,
            "metadata": self.metadata,
        }


class SkillPoolService:
    """
    技能池服务

    管理所有可用技能的注册、查询和生命周期。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._skills: Dict[str, SkillEntry] = {}
        self._category_index: Dict[str, Set[str]] = {}
        self._tag_index: Dict[str, Set[str]] = {}
        self._capability_index: Dict[str, Set[str]] = {}

    def register_skill(
        self,
        skill_id: str,
        name: str,
        version: str,
        description: str = "",
        category: str = "",
        tags: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SkillEntry:
        """
        注册技能到池中

        Args:
            skill_id: 技能唯一标识
            name: 技能名称
            version: 版本号
            description: 描述
            category: 分类
            tags: 标签列表
            capabilities: 能力列表
            metadata: 额外元数据

        Returns:
            注册的技能条目
        """
        with self._lock:
            entry = SkillEntry(
                skill_id=skill_id,
                name=name,
                version=version,
                description=description,
                category=category,
                tags=tags or [],
                capabilities=capabilities or [],
                metadata=metadata or {},
            )

            self._skills[skill_id] = entry

            # 更新索引
            if category:
                if category not in self._category_index:
                    self._category_index[category] = set()
                self._category_index[category].add(skill_id)

            for tag in tags or []:
                if tag not in self._tag_index:
                    self._tag_index[tag] = set()
                self._tag_index[tag].add(skill_id)

            for cap in capabilities or []:
                if cap not in self._capability_index:
                    self._capability_index[cap] = set()
                self._capability_index[cap].add(skill_id)

            logger.info("Registered skill '%s' (v%s)", skill_id, version)
            return entry

    def unregister_skill(self, skill_id: str) -> bool:
        """注销技能"""
        with self._lock:
            entry = self._skills.pop(skill_id, None)
            if entry is None:
                return False

            # 清理索引
            if entry.category in self._category_index:
                self._category_index[entry.category].discard(skill_id)

            for tag in entry.tags:
                if tag in self._tag_index:
                    self._tag_index[tag].discard(skill_id)

            for cap in entry.capabilities:
                if cap in self._capability_index:
                    self._capability_index[cap].discard(skill_id)

            logger.info("Unregistered skill '%s'", skill_id)
            return True

    def get_skill(self, skill_id: str) -> Optional[SkillEntry]:
        """获取技能"""
        with self._lock:
            return self._skills.get(skill_id)

    def list_skills(
        self,
        status: Optional[SkillStatus] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        capability: Optional[str] = None,
    ) -> List[SkillEntry]:
        """列出技能"""
        with self._lock:
            if category:
                skill_ids = self._category_index.get(category, set())
                candidates = {sid: self._skills[sid] for sid in skill_ids if sid in self._skills}
            elif capability:
                skill_ids = self._capability_index.get(capability, set())
                candidates = {sid: self._skills[sid] for sid in skill_ids if sid in self._skills}
            elif tags:
                # 取所有标签的交集
                tag_sets = [self._tag_index.get(tag, set()) for tag in tags]
                if tag_sets:
                    skill_ids = tag_sets[0].intersection(*tag_sets[1:])
                else:
                    skill_ids = set()
                candidates = {sid: self._skills[sid] for sid in skill_ids if sid in self._skills}
            else:
                candidates = dict(self._skills)

            # 按状态过滤
            if status:
                candidates = {sid: e for sid, e in candidates.items() if e.status == status}

            return sorted(candidates.values(), key=lambda e: e.name)

    def set_skill_status(self, skill_id: str, status: SkillStatus) -> bool:
        """设置技能状态"""
        with self._lock:
            entry = self._skills.get(skill_id)
            if entry is None:
                return False
            entry.status = status
            logger.info("Skill '%s' status changed to %s", skill_id, status.value)
            return True

    def record_usage(self, skill_id: str) -> bool:
        """记录技能使用"""
        with self._lock:
            entry = self._skills.get(skill_id)
            if entry is None:
                return False
            entry.usage_count += 1
            entry.last_used = datetime.datetime.now(datetime.timezone.utc)
            return True

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        with self._lock:
            return sorted(self._category_index.keys())

    def get_tags(self) -> List[str]:
        """获取所有标签"""
        with self._lock:
            return sorted(self._tag_index.keys())

    def get_capabilities(self) -> List[str]:
        """获取所有能力"""
        with self._lock:
            return sorted(self._capability_index.keys())

    def search_by_capability(self, capability: str) -> List[SkillEntry]:
        """按能力搜索技能"""
        return self.list_skills(capability=capability, status=SkillStatus.ACTIVE)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            status_counts = {}
            for entry in self._skills.values():
                status_counts[entry.status.value] = status_counts.get(entry.status.value, 0) + 1

            return {
                "total_skills": len(self._skills),
                "by_status": status_counts,
                "categories": len(self._category_index),
                "tags": len(self._tag_index),
                "capabilities": len(self._capability_index),
            }


# 全局单例
_pool_service: Optional[SkillPoolService] = None
_service_lock = threading.Lock()


def get_skill_pool_service() -> SkillPoolService:
    """获取全局技能池服务单例"""
    global _pool_service
    if _pool_service is None:
        with _service_lock:
            if _pool_service is None:
                _pool_service = SkillPoolService()
    return _pool_service


def reset_skill_pool_service() -> None:
    """重置全局技能池服务（用于测试）"""
    global _pool_service
    with _service_lock:
        _pool_service = None
