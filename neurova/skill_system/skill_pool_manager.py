"""
Neurova 技能池管理系统 (2.0)

功能:
1. 公共技能池（所有用户可访问）
2. 专属技能池（用户隔离，每用户独立 metadata.json）
3. 技能推送机制（用户→自己的Agent）
4. 技能池隔离和权限控制（所有权检查、重复检测、shared_with/pushed_to_agents 跟踪）

2.0 构造契约:
    mgr = SkillPoolManager({"data_dir": "/path/to/data"})
    mgr._on_init()

目录结构:
    <data_dir>/skills/public/              # 公共技能池
    <data_dir>/skills/private/<user>/      # 用户专属技能池
    <data_dir>/skills/private/<user>/metadata.json  # 用户技能清单
    <data_dir>/skills/private/<user>/<skill_id>/    # 技能文件目录

SkillMetadata 字段 (2.0):
    skill_id, name, description, version, author, pool_type, visibility,
    owner_user_id, shared_with, pushed_to_agents, tags,
    install_count, rating, rating_count, created_at(ISO), updated_at(ISO)
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class SkillPoolType(str, Enum):
    """技能池类型枚举"""

    PUBLIC = "public"
    PRIVATE = "private"
    AGENT = "agent"


class SkillVisibility(str, Enum):
    """技能可见性枚举"""

    PUBLIC = "public"
    PRIVATE = "private"
    SHARED = "shared"


def _now_iso() -> str:
    """当前时间 ISO 字符串 (UTC)"""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SkillMetadata:
    """技能元数据 (2.0)

    包含完整的多用户/多 Agent 协作字段:
    - skill_id: 技能唯一 ID
    - pool_type: 所在池类型
    - owner_user_id: 所有者用户 ID
    - shared_with: 共享目标用户列表
    - pushed_to_agents: 推送目标 Agent 列表
    - install_count/rating/rating_count: 安装和评分统计
    """

    skill_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    pool_type: SkillPoolType = SkillPoolType.PRIVATE
    visibility: SkillVisibility = SkillVisibility.PRIVATE
    owner_user_id: str = ""
    shared_with: List[str] = field(default_factory=list)
    pushed_to_agents: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    install_count: int = 0
    rating: float = 0.0
    rating_count: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        # 兼容 from_dict 传入字符串枚举
        if isinstance(self.pool_type, str):
            try:
                self.pool_type = SkillPoolType(self.pool_type)
            except ValueError:
                self.pool_type = SkillPoolType.PRIVATE
        if isinstance(self.visibility, str):
            try:
                self.visibility = SkillVisibility(self.visibility)
            except ValueError:
                self.visibility = SkillVisibility.PRIVATE

    def touch(self) -> None:
        """更新时间戳"""
        self.updated_at = _now_iso()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "pool_type": self.pool_type.value,
            "visibility": self.visibility.value,
            "owner_user_id": self.owner_user_id,
            "shared_with": list(self.shared_with),
            "pushed_to_agents": list(self.pushed_to_agents),
            "tags": list(self.tags),
            "install_count": self.install_count,
            "rating": self.rating,
            "rating_count": self.rating_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillMetadata":
        """从字典创建"""
        return cls(
            skill_id=data.get("skill_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            pool_type=data.get("pool_type", "private"),
            visibility=data.get("visibility", "private"),
            owner_user_id=data.get("owner_user_id", ""),
            shared_with=list(data.get("shared_with", [])),
            pushed_to_agents=list(data.get("pushed_to_agents", [])),
            tags=list(data.get("tags", [])),
            install_count=int(data.get("install_count", 0)),
            rating=float(data.get("rating", 0.0)),
            rating_count=int(data.get("rating_count", 0)),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )


class SkillPoolManager:
    """技能池管理器 (2.0)

    管理公共技能池、专属技能池和 Agent 技能池，
    提供技能的创建、更新、删除、分享和推送功能。

    构造契约:
        mgr = SkillPoolManager({"data_dir": "/path/to/data"})
        mgr._on_init()

    或无参默认:
        mgr = SkillPoolManager()  # 使用 ~/.neurova/skills
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, base_dir: Optional[str] = None):
        """初始化技能池管理器

        Args:
            config: 配置字典，支持 "data_dir" 键指定数据目录
            base_dir: 兼容旧签名的目录路径 (优先级低于 config["data_dir"])

        Notes:
            - 2.0 构造接受 dict: SkillPoolManager({"data_dir": "..."})
            - 兼容旧签名: SkillPoolManager(base_dir="/path")
            - 无参默认: SkillPoolManager() 使用 ~/.neurova
            - 不会自动创建目录，需显式调用 _on_init()
        """
        # 解析配置
        if config is None:
            config = {}
        self._config = config

        # 解析数据目录 (config["data_dir"] 优先，其次 base_dir，最后默认)
        data_dir = config.get("data_dir") or base_dir or str(Path.home() / ".neurova")
        self._data_dir = Path(data_dir)

        # 技能池目录 (2.0: 在 data_dir 下加 skills/ 中间层)
        self._skills_dir = self._data_dir / "skills"
        self._public_pool_dir = self._skills_dir / "public"
        self._private_pool_dir = self._skills_dir / "private"

        # 公共技能元数据文件 (单一文件)
        self._public_metadata_file = self._public_pool_dir / "metadata.json"

        logger.debug("SkillPoolManager 2.0 initialized with data_dir=%s", self._data_dir)

    # ------------------------------------------------------------------
    # 初始化 (2.0: 显式 _on_init)
    # ------------------------------------------------------------------

    def _on_init(self) -> None:
        """初始化目录结构和元数据文件

        2.0 契约: 构造函数不创建目录，需显式调用 _on_init()。
        """
        self._public_pool_dir.mkdir(parents=True, exist_ok=True)
        self._private_pool_dir.mkdir(parents=True, exist_ok=True)

        # 初始化公共元数据文件
        if not self._public_metadata_file.exists():
            self._save_public_metadata({})

        logger.debug("Initialized skill pool directories: %s", self._skills_dir)

    # ------------------------------------------------------------------
    # 元数据读写
    # ------------------------------------------------------------------

    def _load_public_metadata(self) -> Dict[str, Dict[str, Any]]:
        """加载公共技能元数据 (skill_id -> skill_data)"""
        try:
            if self._public_metadata_file.exists():
                with open(self._public_metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.error("Failed to load public metadata: %s", e)
        return {}

    def _save_public_metadata(self, metadata: Dict[str, Any]) -> None:
        """保存公共技能元数据"""
        try:
            self._public_metadata_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._public_metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save public metadata: %s", e)

    def _user_metadata_file(self, user_id: str) -> Path:
        """获取用户专属元数据文件路径"""
        return self._private_pool_dir / user_id / "metadata.json"

    def _load_user_metadata(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        """加载用户专属技能元数据 (skill_id -> skill_data)"""
        metadata_file = self._user_metadata_file(user_id)
        try:
            if metadata_file.exists():
                with open(metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.error("Failed to load user metadata for %s: %s", user_id, e)
        return {}

    def _save_user_metadata(self, user_id: str, metadata: Dict[str, Any]) -> None:
        """保存用户专属技能元数据"""
        metadata_file = self._user_metadata_file(user_id)
        try:
            metadata_file.parent.mkdir(parents=True, exist_ok=True)
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save user metadata for %s: %s", user_id, e)

    def _skill_dir(self, user_id: str, skill_id: str) -> Path:
        """获取用户技能文件目录"""
        return self._private_pool_dir / user_id / skill_id

    # ------------------------------------------------------------------
    # 公共技能 API
    # ------------------------------------------------------------------

    def list_public_skills(self, user_id: str = "") -> List[SkillMetadata]:
        """列出公共技能池

        Args:
            user_id: 调用者用户 ID (2.0 兼容参数，用于权限过滤；当前实现返回全部)

        Returns:
            SkillMetadata 列表
        """
        metadata = self._load_public_metadata()
        return [SkillMetadata.from_dict(data) for data in metadata.values()]

    def get_public_skill(self, skill_id: str) -> Optional[SkillMetadata]:
        """获取公共技能

        Args:
            skill_id: 技能 ID

        Returns:
            SkillMetadata 或 None
        """
        metadata = self._load_public_metadata()
        data = metadata.get(skill_id)
        return SkillMetadata.from_dict(data) if data else None

    # ------------------------------------------------------------------
    # 专属技能 API
    # ------------------------------------------------------------------

    def create_private_skill(
        self,
        skill_id: str,
        name: str,
        description: str = "",
        user_id: str = "",
        visibility: SkillVisibility = SkillVisibility.PRIVATE,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Optional[SkillMetadata]:
        """创建专属技能

        Args:
            skill_id: 技能 ID
            name: 技能名称
            description: 描述
            user_id: 所有者用户 ID
            visibility: 可见性
            tags: 标签列表

        Returns:
            创建的 SkillMetadata; 若已存在则返回 None
        """
        tags = tags or []
        metadata = self._load_user_metadata(user_id)

        # 重复检测
        if skill_id in metadata:
            logger.warning("Skill already exists: %s for user %s", skill_id, user_id)
            return None

        # 创建技能对象
        skill = SkillMetadata(
            skill_id=skill_id,
            name=name,
            description=description,
            owner_user_id=user_id,
            pool_type=SkillPoolType.PRIVATE,
            visibility=visibility,
            tags=tags,
        )

        # 创建技能文件目录
        skill_dir = self._skill_dir(user_id, skill_id)
        skill_dir.mkdir(parents=True, exist_ok=True)

        # 保存元数据
        metadata[skill_id] = skill.to_dict()
        self._save_user_metadata(user_id, metadata)

        logger.info("Created private skill %s for user %s", skill_id, user_id)
        return skill

    def list_private_skills(
        self,
        user_id: str,
        visibility: Optional[SkillVisibility] = None,
    ) -> List[SkillMetadata]:
        """列出用户的专属技能

        Args:
            user_id: 用户 ID
            visibility: 可选可见性过滤

        Returns:
            SkillMetadata 列表
        """
        metadata = self._load_user_metadata(user_id)
        skills = [SkillMetadata.from_dict(data) for data in metadata.values()]

        if visibility is not None:
            skills = [s for s in skills if s.visibility == visibility]

        return skills

    def get_private_skill(self, skill_name: str, user_id: str) -> Optional[SkillMetadata]:
        """获取用户的专属技能

        Args:
            skill_name: 技能 ID/名称
            user_id: 用户 ID

        Returns:
            SkillMetadata 或 None
        """
        metadata = self._load_user_metadata(user_id)
        data = metadata.get(skill_name)
        return SkillMetadata.from_dict(data) if data else None

    def update_private_skill(
        self,
        skill_id: str,
        user_id: str,
        name: Optional[str] = None,
        visibility: Optional[SkillVisibility] = None,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> bool:
        """更新专属技能

        Args:
            skill_id: 技能 ID
            user_id: 调用者用户 ID (必须为所有者)
            name: 新名称 (None 表示不更新)
            visibility: 新可见性
            tags: 新标签列表

        Returns:
            是否更新成功; 非所有者或不存在返回 False
        """
        metadata = self._load_user_metadata(user_id)
        if skill_id not in metadata:
            return False

        skill_data = metadata[skill_id]

        # 所有权检查
        if skill_data.get("owner_user_id") != user_id:
            return False

        # 更新字段
        if name is not None:
            skill_data["name"] = name
        if visibility is not None:
            skill_data["visibility"] = visibility.value if isinstance(visibility, SkillVisibility) else visibility
        if tags is not None:
            skill_data["tags"] = list(tags)
        skill_data["updated_at"] = _now_iso()

        metadata[skill_id] = skill_data
        self._save_user_metadata(user_id, metadata)
        return True

    def delete_private_skill(self, skill_name: str, user_id: str) -> bool:
        """删除专属技能

        Args:
            skill_name: 技能 ID/名称
            user_id: 调用者用户 ID (必须为所有者)

        Returns:
            是否删除成功; 非所有者或不存在返回 False
        """
        metadata = self._load_user_metadata(user_id)
        if skill_name not in metadata:
            return False

        skill_data = metadata[skill_name]

        # 所有权检查
        if skill_data.get("owner_user_id") != user_id:
            return False

        # 删除技能文件目录
        skill_dir = self._skill_dir(user_id, skill_name)
        if skill_dir.exists():
            shutil.rmtree(skill_dir)

        # 从元数据删除
        del metadata[skill_name]
        self._save_user_metadata(user_id, metadata)

        logger.info("Deleted private skill %s for user %s", skill_name, user_id)
        return True

    def share_private_skill(self, skill_name: str, owner: str, target: str) -> bool:
        """共享专属技能给目标用户

        Args:
            skill_name: 技能 ID/名称
            owner: 所有者用户 ID
            target: 目标用户 ID

        Returns:
            是否共享成功; 非所有者或不存在返回 False
        """
        metadata = self._load_user_metadata(owner)
        if skill_name not in metadata:
            return False

        skill_data = metadata[skill_name]

        # 所有权检查
        if skill_data.get("owner_user_id") != owner:
            return False

        # 更新可见性和 shared_with
        skill_data["visibility"] = SkillVisibility.SHARED.value
        shared_with = list(skill_data.get("shared_with", []))
        if target not in shared_with:
            shared_with.append(target)
        skill_data["shared_with"] = shared_with
        skill_data["updated_at"] = _now_iso()

        metadata[skill_name] = skill_data
        self._save_user_metadata(owner, metadata)
        return True

    # ------------------------------------------------------------------
    # Agent 推送 API
    # ------------------------------------------------------------------

    def push_skill_to_agent(
        self,
        skill_id: str,
        user_id: str,
        agent_id: str,
        is_public: bool = False,
        **kwargs: Any,
    ) -> bool:
        """推送技能给 Agent

        Args:
            skill_id: 技能 ID
            user_id: 调用者用户 ID (必须为所有者)
            agent_id: 目标 Agent ID
            is_public: 是否公共技能 (True 时从公共池查找)

        Returns:
            是否推送成功
        """
        if is_public:
            metadata = self._load_public_metadata()
        else:
            metadata = self._load_user_metadata(user_id)

        if skill_id not in metadata:
            return False

        skill_data = metadata[skill_id]

        # 所有权检查 (公共技能跳过)
        if not is_public and skill_data.get("owner_user_id") != user_id:
            return False

        # 更新 pushed_to_agents
        pushed = list(skill_data.get("pushed_to_agents", []))
        if agent_id not in pushed:
            pushed.append(agent_id)
        skill_data["pushed_to_agents"] = pushed
        skill_data["updated_at"] = _now_iso()

        metadata[skill_id] = skill_data
        if is_public:
            self._save_public_metadata(metadata)
        else:
            self._save_user_metadata(user_id, metadata)
        return True

    def unpush_skill_from_agent(
        self,
        skill_id: str,
        user_id: str,
        agent_id: str,
        is_public: bool = False,
        **kwargs: Any,
    ) -> bool:
        """从 Agent 取消推送技能

        Args:
            skill_id: 技能 ID
            user_id: 调用者用户 ID
            agent_id: 目标 Agent ID
            is_public: 是否公共技能

        Returns:
            是否取消推送成功
        """
        if is_public:
            metadata = self._load_public_metadata()
        else:
            metadata = self._load_user_metadata(user_id)

        if skill_id not in metadata:
            return False

        skill_data = metadata[skill_id]

        # 所有权检查 (公共技能跳过)
        if not is_public and skill_data.get("owner_user_id") != user_id:
            return False

        # 从 pushed_to_agents 移除
        pushed = list(skill_data.get("pushed_to_agents", []))
        if agent_id in pushed:
            pushed.remove(agent_id)
        skill_data["pushed_to_agents"] = pushed
        skill_data["updated_at"] = _now_iso()

        metadata[skill_id] = skill_data
        if is_public:
            self._save_public_metadata(metadata)
        else:
            self._save_user_metadata(user_id, metadata)
        return True

    def get_agent_skills(self, agent_id: str) -> List[SkillMetadata]:
        """获取 Agent 的所有技能

        扫描所有用户的 metadata，返回 pushed_to_agents 包含 agent_id 的技能。

        Args:
            agent_id: Agent ID

        Returns:
            SkillMetadata 列表
        """
        result: List[SkillMetadata] = []

        # 扫描公共池
        public_metadata = self._load_public_metadata()
        for skill_data in public_metadata.values():
            if agent_id in skill_data.get("pushed_to_agents", []):
                result.append(SkillMetadata.from_dict(skill_data))

        # 扫描所有用户私有池
        if self._private_pool_dir.exists():
            for user_dir in self._private_pool_dir.iterdir():
                if not user_dir.is_dir():
                    continue
                user_metadata = self._load_user_metadata(user_dir.name)
                for skill_data in user_metadata.values():
                    if agent_id in skill_data.get("pushed_to_agents", []):
                        result.append(SkillMetadata.from_dict(skill_data))

        return result

    # ------------------------------------------------------------------
    # 管理员 API
    # ------------------------------------------------------------------

    def admin_list_all_skills(self) -> List[SkillMetadata]:
        """管理员列出所有技能

        Returns:
            所有技能的 SkillMetadata 列表 (公共 + 所有用户私有)
        """
        result: List[SkillMetadata] = []

        # 公共池
        public_metadata = self._load_public_metadata()
        result.extend(SkillMetadata.from_dict(data) for data in public_metadata.values())

        # 所有用户私有池
        if self._private_pool_dir.exists():
            for user_dir in self._private_pool_dir.iterdir():
                if not user_dir.is_dir():
                    continue
                user_metadata = self._load_user_metadata(user_dir.name)
                result.extend(SkillMetadata.from_dict(data) for data in user_metadata.values())

        return result

    def admin_delete_user_skills(self, user_id: str) -> int:
        """管理员删除用户的所有专属技能

        Args:
            user_id: 用户 ID

        Returns:
            删除的技能数量
        """
        metadata = self._load_user_metadata(user_id)
        deleted_count = len(metadata)

        # 删除所有技能目录
        for skill_id in list(metadata.keys()):
            skill_dir = self._skill_dir(user_id, skill_id)
            if skill_dir.exists():
                shutil.rmtree(skill_dir)

        # 清空元数据
        self._save_user_metadata(user_id, {})

        logger.info("Admin deleted %d skills for user %s", deleted_count, user_id)
        return deleted_count
