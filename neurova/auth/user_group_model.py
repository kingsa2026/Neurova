"""
Neurova 用户组和资源配额模型

功能:
1. 用户组定义（UserGroup）
2. 资源配额管理（ResourceQuota）
3. 权限定义（Permission）
4. 用户组-权限关联
"""

import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# core imports

logger = logging.getLogger(__name__)


class Permission(Enum):
    """权限枚举"""

    # 用户管理权限
    USER_READ = "user:read"  # 读取用户信息
    USER_WRITE = "user:write"  # 修改用户信息
    USER_DELETE = "user:delete"  # 删除用户
    USER_LIST = "user:list"  # 列出用户

    # Agent管理权限
    AGENT_READ = "agent:read"  # 读取Agent信息
    AGENT_WRITE = "agent:write"  # 修改Agent配置
    AGENT_DELETE = "agent:delete"  # 删除Agent
    AGENT_CREATE = "agent:create"  # 创建Agent
    AGENT_MANAGE = "agent:manage"  # 管理Agent

    # 记忆管理权限
    MEMORY_READ = "memory:read"  # 读取记忆
    MEMORY_WRITE = "memory:write"  # 写入记忆
    MEMORY_DELETE = "memory:delete"  # 删除记忆

    # 工具管理权限
    TOOL_READ = "tool:read"  # 读取工具信息
    TOOL_WRITE = "tool:write"  # 修改工具配置
    TOOL_DELETE = "tool:delete"  # 删除工具
    TOOL_CREATE = "tool:create"  # 创建工具

    # 系统管理权限
    SYSTEM_ADMIN = "system:admin"  # 系统管理员
    SYSTEM_CONFIG = "system:config"  # 系统配置
    SYSTEM_MONITOR = "system:monitor"  # 系统监控

    # 数据分析权限
    ANALYTICS_READ = "analytics:read"  # 读取分析数据
    ANALYTICS_WRITE = "analytics:write"  # 写入分析数据

    # 协作权限
    COLLAB_READ = "collaboration:read"  # 读取协作信息
    COLLAB_WRITE = "collaboration:write"  # 修改协作信息
    COLLAB_MANAGE = "collaboration:manage"  # 管理协作


@dataclass
class ResourceQuota:
    """资源配额数据模型"""

    max_agents: int = 10  # 最大Agent数量
    max_memory_mb: int = 1024  # 最大内存使用(MB)
    max_storage_mb: int = 10240  # 最大存储空间(MB)
    max_requests_per_minute: int = 60  # 每分钟最大请求数
    max_tokens_per_day: int = 100000  # 每天最大token使用量
    max_concurrent_tasks: int = 5  # 最大并发任务数
    max_file_size_mb: int = 100  # 最大文件大小(MB)
    max_users_per_group: int = 100  # 用户组最大用户数

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResourceQuota":
        """从字典创建"""
        return cls(**data)

    def is_within_quota(self, **kwargs) -> bool:
        """检查是否在配额范围内"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                quota_value = getattr(self, key)
                if value > quota_value:
                    return False
        return True

    def get_usage_percentage(self, **kwargs) -> Dict[str, float]:
        """获取使用百分比"""
        usage = {}
        for key, value in kwargs.items():
            if hasattr(self, key):
                quota_value = getattr(self, key)
                if quota_value > 0:
                    usage[key] = (value / quota_value) * 100
        return usage


class UserGroupType(Enum):
    """用户组类型"""

    SUPER_ADMIN = "super_admin"  # 超级管理员
    ADMIN = "admin"  # 管理员
    DEVELOPER = "developer"  # 开发者
    USER = "user"  # 普通用户
    GUEST = "guest"  # 访客
    CUSTOM = "custom"  # 自定义


@dataclass
class UserGroup:
    """用户组数据模型"""

    group_id: str
    name: str
    description: str
    group_type: UserGroupType
    permissions: List[Permission]
    resource_quota: ResourceQuota
    is_system: bool = False  # 是否系统预设组
    is_active: bool = True
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["group_type"] = self.group_type.value
        result["permissions"] = [p.value for p in self.permissions]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserGroup":
        """从字典创建"""
        data = data.copy()
        data["group_type"] = UserGroupType(data["group_type"])
        data["permissions"] = [Permission(p) for p in data["permissions"]]
        data["resource_quota"] = ResourceQuota.from_dict(data["resource_quota"])
        return cls(**data)

    def has_permission(self, permission: Permission) -> bool:
        """检查是否有指定权限"""
        return permission in self.permissions

    def add_permission(self, permission: Permission):
        """添加权限"""
        if permission not in self.permissions:
            self.permissions.append(permission)
            self.updated_at = time.time()

    def remove_permission(self, permission: Permission):
        """移除权限"""
        if permission in self.permissions:
            self.permissions.remove(permission)
            self.updated_at = time.time()


def create_super_admin_group() -> UserGroup:
    """
    创建超级管理员用户组

    Returns:
        超级管理员用户组
    """
    return UserGroup(
        group_id="super_admin",
        name="超级管理员",
        description="拥有系统所有权限的超级管理员组",
        group_type=UserGroupType.SUPER_ADMIN,
        permissions=list(Permission),  # 所有权限
        resource_quota=ResourceQuota(
            max_agents=100,
            max_memory_mb=10240,
            max_storage_mb=102400,
            max_requests_per_minute=1000,
            max_tokens_per_day=1000000,
            max_concurrent_tasks=50,
            max_file_size_mb=1024,
            max_users_per_group=1000,
        ),
        is_system=True,
        is_active=True,
        metadata={"priority": 1, "color": "#ff4444", "icon": "shield"},
    )


def create_admin_group() -> UserGroup:
    """
    创建管理员用户组

    Returns:
        管理员用户组
    """
    return UserGroup(
        group_id="admin",
        name="管理员",
        description="系统管理员组，拥有大部分管理权限",
        group_type=UserGroupType.ADMIN,
        permissions=[
            Permission.USER_READ,
            Permission.USER_WRITE,
            Permission.USER_LIST,
            Permission.AGENT_READ,
            Permission.AGENT_WRITE,
            Permission.AGENT_CREATE,
            Permission.AGENT_MANAGE,
            Permission.MEMORY_READ,
            Permission.MEMORY_WRITE,
            Permission.TOOL_READ,
            Permission.TOOL_WRITE,
            Permission.TOOL_CREATE,
            Permission.SYSTEM_CONFIG,
            Permission.SYSTEM_MONITOR,
            Permission.ANALYTICS_READ,
            Permission.COLLAB_READ,
            Permission.COLLAB_WRITE,
            Permission.COLLAB_MANAGE,
        ],
        resource_quota=ResourceQuota(
            max_agents=50,
            max_memory_mb=5120,
            max_storage_mb=51200,
            max_requests_per_minute=500,
            max_tokens_per_day=500000,
            max_concurrent_tasks=20,
            max_file_size_mb=512,
            max_users_per_group=500,
        ),
        is_system=True,
        is_active=True,
        metadata={"priority": 2, "color": "#ff8800", "icon": "user-shield"},
    )


def create_developer_group() -> UserGroup:
    """
    创建开发者用户组

    Returns:
        开发者用户组
    """
    return UserGroup(
        group_id="developer",
        name="开发者",
        description="开发者组，拥有开发和调试权限",
        group_type=UserGroupType.DEVELOPER,
        permissions=[
            Permission.USER_READ,
            Permission.AGENT_READ,
            Permission.AGENT_WRITE,
            Permission.AGENT_CREATE,
            Permission.MEMORY_READ,
            Permission.MEMORY_WRITE,
            Permission.TOOL_READ,
            Permission.TOOL_WRITE,
            Permission.TOOL_CREATE,
            Permission.SYSTEM_MONITOR,
            Permission.ANALYTICS_READ,
            Permission.COLLAB_READ,
            Permission.COLLAB_WRITE,
        ],
        resource_quota=ResourceQuota(
            max_agents=20,
            max_memory_mb=2048,
            max_storage_mb=20480,
            max_requests_per_minute=200,
            max_tokens_per_day=200000,
            max_concurrent_tasks=10,
            max_file_size_mb=256,
            max_users_per_group=100,
        ),
        is_system=True,
        is_active=True,
        metadata={"priority": 3, "color": "#00aa00", "icon": "code"},
    )


def create_user_group() -> UserGroup:
    """
    创建普通用户用户组

    Returns:
        普通用户用户组
    """
    return UserGroup(
        group_id="user",
        name="普通用户",
        description="普通用户组，拥有基本使用权限",
        group_type=UserGroupType.USER,
        permissions=[
            Permission.USER_READ,
            Permission.AGENT_READ,
            Permission.AGENT_WRITE,
            Permission.MEMORY_READ,
            Permission.MEMORY_WRITE,
            Permission.TOOL_READ,
            Permission.COLLAB_READ,
        ],
        resource_quota=ResourceQuota(
            max_agents=5,
            max_memory_mb=512,
            max_storage_mb=5120,
            max_requests_per_minute=60,
            max_tokens_per_day=50000,
            max_concurrent_tasks=3,
            max_file_size_mb=100,
            max_users_per_group=10,
        ),
        is_system=True,
        is_active=True,
        metadata={"priority": 4, "color": "#0088ff", "icon": "user"},
    )


def create_guest_group() -> UserGroup:
    """
    创建访客用户组

    Returns:
        访客用户组
    """
    return UserGroup(
        group_id="guest",
        name="访客",
        description="访客组，拥有最小权限",
        group_type=UserGroupType.GUEST,
        permissions=[Permission.USER_READ, Permission.AGENT_READ, Permission.TOOL_READ],
        resource_quota=ResourceQuota(
            max_agents=1,
            max_memory_mb=128,
            max_storage_mb=1024,
            max_requests_per_minute=10,
            max_tokens_per_day=10000,
            max_concurrent_tasks=1,
            max_file_size_mb=10,
            max_users_per_group=5,
        ),
        is_system=True,
        is_active=True,
        metadata={"priority": 5, "color": "#888888", "icon": "user-friends"},
    )


class UserGroupManager:
    """
    用户组管理器
    负责用户组的创建、管理、权限检查和配额管理
    """

    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化用户组管理器

        Args:
            data_dir: 数据目录路径
        """
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent.parent / "data")

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.groups_file = self.data_dir / "user_groups.json"
        self.groups: Dict[str, UserGroup] = {}

        self._init_system_groups()
        self._load_groups()

        logger.info("UserGroupManager initialized with data_dir=%s", data_dir)

    def _init_system_groups(self):
        """初始化系统预设用户组"""
        system_groups = [
            create_super_admin_group(),
            create_admin_group(),
            create_developer_group(),
            create_user_group(),
            create_guest_group(),
        ]

        for group in system_groups:
            if group.group_id not in self.groups:
                self.groups[group.group_id] = group

        logger.info("Initialized %d system user groups", len(system_groups))

    def _load_groups(self):
        """从文件加载用户组"""
        try:
            if self.groups_file.exists():
                with open(self.groups_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for group_data in data.get("groups", []):
                    group = UserGroup.from_dict(group_data)
                    if not group.is_system:  # 系统组不从文件加载
                        self.groups[group.group_id] = group

                logger.info("Loaded %d user groups from file", len(data.get("groups", [])))

        except Exception as e:
            logger.error("Failed to load user groups: %s", e)

    def _save_groups(self):
        """保存用户组到文件"""
        try:
            data = {"groups": [group.to_dict() for group in self.groups.values()], "updated_at": time.time()}

            with open(self.groups_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info("Saved %d user groups to file", len(self.groups))

        except Exception as e:
            logger.error("Failed to save user groups: %s", e)

    def _on_init(self):
        """初始化回调"""
        logger.info("UserGroupManager initialized")

    def _on_start(self):
        """启动回调"""
        logger.info("UserGroupManager started")

    def _on_stop(self):
        """停止回调"""
        self._save_groups()
        logger.info("UserGroupManager stopped")

    def get_group(self, group_id: str) -> Optional[UserGroup]:
        """
        获取用户组

        Args:
            group_id: 用户组ID

        Returns:
            用户组，如果不存在则返回None
        """
        return self.groups.get(group_id)

    def get_group_by_type(self, group_type: UserGroupType) -> Optional[UserGroup]:
        """
        根据类型获取用户组

        Args:
            group_type: 用户组类型

        Returns:
            用户组，如果不存在则返回None
        """
        for group in self.groups.values():
            if group.group_type == group_type:
                return group
        return None

    def list_groups(
        self, include_system: bool = True, include_inactive: bool = False, limit: Optional[int] = None, offset: int = 0
    ) -> List[UserGroup]:
        """
        列出用户组

        Args:
            include_system: 是否包含系统组
            include_inactive: 是否包含非活跃组
            limit: 返回数量限制，None表示不限制
            offset: 偏移量

        Returns:
            用户组列表
        """
        groups = []
        for group in self.groups.values():
            if not include_system and group.is_system:
                continue
            if not include_inactive and not group.is_active:
                continue
            groups.append(group)

        groups = sorted(groups, key=lambda g: g.metadata.get("priority", 100) if g.metadata else 100)

        # 应用分页
        if offset > 0:
            groups = groups[offset:]
        if limit is not None:
            groups = groups[:limit]

        return groups

    def create_group(
        self,
        name: str,
        description: str,
        group_type: UserGroupType = UserGroupType.CUSTOM,
        permissions: Optional[List[Permission]] = None,
        resource_quota: Optional[ResourceQuota] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UserGroup:
        """
        创建用户组

        Args:
            name: 用户组名称
            description: 描述
            group_type: 用户组类型
            permissions: 权限列表
            resource_quota: 资源配额
            metadata: 元数据

        Returns:
            创建的用户组
        """
        try:
            # 生成用户组ID
            group_id = f"group_{secrets.token_hex(8)}"

            # 创建用户组
            group = UserGroup(
                group_id=group_id,
                name=name,
                description=description,
                group_type=group_type,
                permissions=permissions or [],
                resource_quota=resource_quota or ResourceQuota(),
                is_system=False,
                is_active=True,
                metadata=metadata,
            )

            # 保存用户组
            self.groups[group_id] = group
            self._save_groups()

            logger.info("Created user group: %s (%s)", name, group_id)
            return group

        except Exception as e:
            logger.error("Failed to create user group: %s", e)
            raise

    def update_group(self, group_id: str, **kwargs) -> Optional[UserGroup]:
        """
        更新用户组

        Args:
            group_id: 用户组ID
            **kwargs: 要更新的字段

        Returns:
            更新后的用户组，如果不存在则返回None
        """
        group = self.get_group(group_id)
        if group is None:
            logger.warning("User group not found: %s", group_id)
            return None

        if group.is_system:
            logger.warning("Cannot update system group: %s", group_id)
            return None

        try:
            # 更新字段
            for key, value in kwargs.items():
                if hasattr(group, key):
                    setattr(group, key, value)

            group.updated_at = time.time()

            # 保存用户组
            self._save_groups()

            logger.info("Updated user group: %s", group_id)
            return group

        except Exception as e:
            logger.error("Failed to update user group: %s", e)
            return None

    def delete_group(self, group_id: str) -> bool:
        """
        删除用户组

        Args:
            group_id: 用户组ID

        Returns:
            是否成功删除
        """
        group = self.get_group(group_id)
        if group is None:
            logger.warning("User group not found: %s", group_id)
            return False

        if group.is_system:
            logger.warning("Cannot delete system group: %s", group_id)
            return False

        try:
            # 删除用户组
            del self.groups[group_id]

            # 保存用户组
            self._save_groups()

            logger.info("Deleted user group: %s", group_id)
            return True

        except Exception as e:
            logger.error("Failed to delete user group: %s", e)
            return False

    def check_permission(self, group_id: str, permission: Permission) -> bool:
        """
        检查用户组是否有指定权限

        Args:
            group_id: 用户组ID
            permission: 权限

        Returns:
            是否有权限
        """
        group = self.get_group(group_id)
        if group is None:
            logger.warning("User group not found: %s", group_id)
            return False

        return group.has_permission(permission)

    def get_user_quota(self, group_id: str) -> Optional[ResourceQuota]:
        """
        获取用户组的资源配额

        Args:
            group_id: 用户组ID

        Returns:
            资源配额，如果不存在则返回None
        """
        group = self.get_group(group_id)
        if group is None:
            logger.warning("User group not found: %s", group_id)
            return None

        return group.resource_quota

    def check_quota(self, group_id: str, **kwargs) -> Dict[str, Any]:
        """
        检查是否在配额范围内

        Args:
            group_id: 用户组ID
            **kwargs: 要检查的资源使用量

        Returns:
            配额检查结果
        """
        group = self.get_group(group_id)
        if group is None:
            logger.warning("User group not found: %s", group_id)
            return {"group_id": group_id, "is_within_quota": False, "error": "User group not found"}

        is_within_quota = group.resource_quota.is_within_quota(**kwargs)
        usage_percentage = group.resource_quota.get_usage_percentage(**kwargs)

        return {
            "group_id": group_id,
            "is_within_quota": is_within_quota,
            "usage_percentage": usage_percentage,
            "quota": group.resource_quota.to_dict(),
        }

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取用户组统计信息

        Returns:
            统计信息字典
        """
        total_groups = len(self.groups)
        system_groups = sum(1 for g in self.groups.values() if g.is_system)
        custom_groups = total_groups - system_groups
        active_groups = sum(1 for g in self.groups.values() if g.is_active)

        by_type = {}
        for group_type in UserGroupType:
            count = sum(1 for g in self.groups.values() if g.group_type == group_type)
            if count > 0:
                by_type[group_type.value] = count

        return {
            "total_groups": total_groups,
            "system_groups": system_groups,
            "custom_groups": custom_groups,
            "active_groups": active_groups,
            "by_type": by_type,
        }


# 全局实例
_user_group_manager: Optional[UserGroupManager] = None


def get_user_group_manager() -> UserGroupManager:
    """
    获取用户组管理器实例（单例模式）

    Returns:
        UserGroupManager实例
    """
    global _user_group_manager
    if _user_group_manager is None:
        _user_group_manager = UserGroupManager()
    return _user_group_manager


def reset_user_group_manager():
    """
    重置用户组管理器实例（用于测试）
    """
    global _user_group_manager
    if _user_group_manager is not None:
        _user_group_manager._save_groups()
        _user_group_manager = None
