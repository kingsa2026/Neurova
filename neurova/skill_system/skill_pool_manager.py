"""
Neurova 技能池管理系统

功能:
1. 公共技能池（所有用户可访问）
2. 专属技能池（用户隔离）
3. 技能推送机制（用户→自己的Agent）
4. 技能池隔离和权限控制
"""

from dataclasses import dataclass, field
import datetime
import enum
import json
import logging
from pathlib import Path
import shutil
import time
import typing

from enum import Enum

logger = logging.getLogger(__name__)


class SkillPoolType(str, Enum):
    """技能池类型枚举"""
    PUBLIC = "public"      # 公共技能池
    PRIVATE = "private"    # 专属技能池
    AGENT = "agent"        # Agent技能池


class SkillVisibility(str, Enum):
    """技能可见性枚举"""
    PUBLIC = "public"      # 公开可见
    PRIVATE = "private"    # 私有
    SHARED = "shared"      # 已分享


@dataclass
class SkillMetadata:
    """技能元数据"""
    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    visibility: SkillVisibility = SkillVisibility.PRIVATE
    tags: typing.List[str] = field(default_factory=list)
    enabled: bool = True
    created_at: typing.Optional[float] = None
    updated_at: typing.Optional[float] = None
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = self.created_at
    
    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "visibility": self.visibility.value,
            "tags": self.tags,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "SkillMetadata":
        """从字典创建"""
        visibility = data.get("visibility", "private")
        if isinstance(visibility, str):
            visibility = SkillVisibility(visibility)
        
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            visibility=visibility,
            tags=data.get("tags", []),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata=data.get("metadata", {}),
        )
    
    def touch(self):
        """更新时间戳"""
        self.updated_at = time.time()


class SkillPoolManager:
    """
    技能池管理器
    
    管理公共技能池、专属技能池和Agent技能池，
    提供技能的安装、创建、更新、删除、分享和推送功能。
    """
    
    def __init__(self, base_dir: str = None, config: typing.Dict[str, typing.Any] = None):
        """
        初始化技能池管理器
        
        Args:
            base_dir: 基础目录路径
            config: 配置字典
        """
        self._base_dir = Path(base_dir) if base_dir else Path.home() / ".neurova" / "skills"
        self._config = config or {}
        
        # 技能池目录
        self._public_pool_dir = self._base_dir / "public"
        self._private_pool_dir = self._base_dir / "private"
        self._agent_pool_dir = self._base_dir / "agent"
        
        # 元数据存储
        self._metadata_file = self._base_dir / "metadata.json"
        self._metadata: typing.Dict[str, typing.Any] = {
            "public_skills": {},
            "private_skills": {},
            "agent_skills": {},
            "shared_skills": {},
        }
        
        # 初始化
        self._init_dirs()
        self._load_metadata()
    
    def _init_dirs(self) -> None:
        """初始化目录结构"""
        self._public_pool_dir.mkdir(parents=True, exist_ok=True)
        self._private_pool_dir.mkdir(parents=True, exist_ok=True)
        self._agent_pool_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Initialized skill pool directories: {self._base_dir}")
    
    def _load_metadata(self) -> None:
        """加载元数据"""
        if self._metadata_file.exists():
            try:
                with open(self._metadata_file, 'r', encoding='utf-8') as f:
                    self._metadata = json.load(f)
                logger.debug("Loaded skill pool metadata")
            except Exception as e:
                logger.error(f"Failed to load metadata: {e}")
    
    def _save_metadata(self) -> None:
        """保存元数据"""
        try:
            with open(self._metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, indent=2, ensure_ascii=False)
            logger.debug("Saved skill pool metadata")
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
    
    def list_public_skills(self) -> typing.List[SkillMetadata]:
        """
        列出公共技能
        
        Returns:
            公共技能列表
        """
        skills = []
        for skill_name, skill_data in self._metadata.get("public_skills", {}).items():
            try:
                skill = SkillMetadata.from_dict(skill_data)
                skills.append(skill)
            except Exception as e:
                logger.warning(f"Failed to load public skill {skill_name}: {e}")
        return skills
    
    def get_public_skill(self, name: str) -> typing.Optional[SkillMetadata]:
        """
        获取公共技能
        
        Args:
            name: 技能名称
            
        Returns:
            技能元数据或 None
        """
        skill_data = self._metadata.get("public_skills", {}).get(name)
        if skill_data:
            try:
                return SkillMetadata.from_dict(skill_data)
            except Exception as e:
                logger.warning(f"Failed to load public skill {name}: {e}")
        return None
    
    def install_public_skill(self, skill_metadata: SkillMetadata) -> bool:
        """
        安装公共技能
        
        Args:
            skill_metadata: 技能元数据
            
        Returns:
            是否安装成功
        """
        try:
            # 更新元数据
            self._metadata.setdefault("public_skills", {})[skill_metadata.name] = skill_metadata.to_dict()
            self._save_metadata()
            
            # 创建技能目录
            skill_dir = self._public_pool_dir / skill_metadata.name
            skill_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Installed public skill: {skill_metadata.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to install public skill {skill_metadata.name}: {e}")
            return False
    
    def _copy_public_skill_to_private(self, user_id: str, skill_name: str) -> bool:
        """
        将公共技能复制到用户私有池
        
        Args:
            user_id: 用户 ID
            skill_name: 技能名称
            
        Returns:
            是否复制成功
        """
        try:
            src_dir = self._public_pool_dir / skill_name
            dst_dir = self._private_pool_dir / user_id / skill_name
            
            if not src_dir.exists():
                logger.warning(f"Public skill not found: {skill_name}")
                return False
            
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            
            shutil.copytree(src_dir, dst_dir)
            logger.debug(f"Copied public skill {skill_name} to private pool for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to copy public skill {skill_name} to private pool: {e}")
            return False
    
    def list_private_skills(self, user_id: str) -> typing.List[SkillMetadata]:
        """
        列出用户的私有技能
        
        Args:
            user_id: 用户 ID
            
        Returns:
            私有技能列表
        """
        skills = []
        user_skills = self._metadata.get("private_skills", {}).get(user_id, {})
        
        for skill_name, skill_data in user_skills.items():
            try:
                skill = SkillMetadata.from_dict(skill_data)
                skills.append(skill)
            except Exception as e:
                logger.warning(f"Failed to load private skill {skill_name} for user {user_id}: {e}")
        
        return skills
    
    def get_private_skill(self, user_id: str, skill_name: str) -> typing.Optional[SkillMetadata]:
        """
        获取用户的私有技能
        
        Args:
            user_id: 用户 ID
            skill_name: 技能名称
            
        Returns:
            技能元数据或 None
        """
        user_skills = self._metadata.get("private_skills", {}).get(user_id, {})
        skill_data = user_skills.get(skill_name)
        
        if skill_data:
            try:
                return SkillMetadata.from_dict(skill_data)
            except Exception as e:
                logger.warning(f"Failed to load private skill {skill_name} for user {user_id}: {e}")
        
        return None
    
    def create_private_skill(self, user_id: str, skill_metadata: SkillMetadata) -> bool:
        """
        创建私有技能
        
        Args:
            user_id: 用户 ID
            skill_metadata: 技能元数据
            
        Returns:
            是否创建成功
        """
        try:
            # 更新元数据
            self._metadata.setdefault("private_skills", {}).setdefault(user_id, {})[skill_metadata.name] = skill_metadata.to_dict()
            self._save_metadata()
            
            # 创建技能目录
            skill_dir = self._private_pool_dir / user_id / skill_metadata.name
            skill_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Created private skill {skill_metadata.name} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create private skill {skill_metadata.name} for user {user_id}: {e}")
            return False
    
    def update_private_skill(self, user_id: str, skill_metadata: SkillMetadata) -> bool:
        """
        更新私有技能
        
        Args:
            user_id: 用户 ID
            skill_metadata: 技能元数据
            
        Returns:
            是否更新成功
        """
        try:
            # 检查技能是否存在
            if skill_metadata.name not in self._metadata.get("private_skills", {}).get(user_id, {}):
                logger.warning(f"Private skill {skill_metadata.name} not found for user {user_id}")
                return False
            
            # 更新元数据
            skill_metadata.touch()
            self._metadata["private_skills"][user_id][skill_metadata.name] = skill_metadata.to_dict()
            self._save_metadata()
            
            logger.info(f"Updated private skill {skill_metadata.name} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update private skill {skill_metadata.name} for user {user_id}: {e}")
            return False
    
    def delete_private_skill(self, user_id: str, skill_name: str) -> bool:
        """
        删除私有技能
        
        Args:
            user_id: 用户 ID
            skill_name: 技能名称
            
        Returns:
            是否删除成功
        """
        try:
            # 从元数据中删除
            if skill_name in self._metadata.get("private_skills", {}).get(user_id, {}):
                del self._metadata["private_skills"][user_id][skill_name]
                self._save_metadata()
            
            # 删除技能目录
            skill_dir = self._private_pool_dir / user_id / skill_name
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            
            logger.info(f"Deleted private skill {skill_name} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete private skill {skill_name} for user {user_id}: {e}")
            return False
    
    def share_private_skill(self, user_id: str, skill_name: str, target_user_id: str) -> bool:
        """
        分享私有技能给其他用户
        
        Args:
            user_id: 技能所有者用户 ID
            skill_name: 技能名称
            target_user_id: 目标用户 ID
            
        Returns:
            是否分享成功
        """
        try:
            # 获取技能元数据
            skill_metadata = self.get_private_skill(user_id, skill_name)
            if not skill_metadata:
                logger.warning(f"Private skill {skill_name} not found for user {user_id}")
                return False
            
            # 创建分享记录
            share_key = f"{user_id}:{skill_name}"
            self._metadata.setdefault("shared_skills", {})[share_key] = {
                "owner": user_id,
                "skill_name": skill_name,
                "target_user": target_user_id,
                "shared_at": time.time(),
            }
            
            # 将技能复制到目标用户的私有池
            self._copy_public_skill_to_private(target_user_id, skill_name)
            
            # 更新目标用户的技能元数据
            skill_metadata.visibility = SkillVisibility.SHARED
            self._metadata.setdefault("private_skills", {}).setdefault(target_user_id, {})[skill_name] = skill_metadata.to_dict()
            
            self._save_metadata()
            
            logger.info(f"Shared skill {skill_name} from user {user_id} to user {target_user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to share skill {skill_name}: {e}")
            return False
    
    def push_skill_to_agent(self, user_id: str, skill_name: str, agent_id: str) -> bool:
        """
        推送技能到 Agent
        
        Args:
            user_id: 用户 ID
            skill_name: 技能名称
            agent_id: Agent ID
            
        Returns:
            是否推送成功
        """
        try:
            # 获取技能元数据
            skill_metadata = self.get_private_skill(user_id, skill_name)
            if not skill_metadata:
                logger.warning(f"Private skill {skill_name} not found for user {user_id}")
                return False
            
            # 更新 Agent 技能池
            self._metadata.setdefault("agent_skills", {}).setdefault(agent_id, {})[skill_name] = {
                "owner": user_id,
                "skill_name": skill_name,
                "pushed_at": time.time(),
                "metadata": skill_metadata.to_dict(),
            }
            
            self._save_metadata()
            
            logger.info(f"Pushed skill {skill_name} to agent {agent_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to push skill {skill_name} to agent {agent_id}: {e}")
            return False
    
    def unpush_skill_from_agent(self, agent_id: str, skill_name: str) -> bool:
        """
        从 Agent 移除技能
        
        Args:
            agent_id: Agent ID
            skill_name: 技能名称
            
        Returns:
            是否移除成功
        """
        try:
            # 从 Agent 技能池中删除
            if skill_name in self._metadata.get("agent_skills", {}).get(agent_id, {}):
                del self._metadata["agent_skills"][agent_id][skill_name]
                self._save_metadata()
            
            logger.info(f"Unpushed skill {skill_name} from agent {agent_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unpush skill {skill_name} from agent {agent_id}: {e}")
            return False
    
    def get_agent_skills(self, agent_id: str) -> typing.List[SkillMetadata]:
        """
        获取 Agent 的技能列表
        
        Args:
            agent_id: Agent ID
            
        Returns:
            技能元数据列表
        """
        skills = []
        agent_skills = self._metadata.get("agent_skills", {}).get(agent_id, {})
        
        for skill_name, skill_data in agent_skills.items():
            try:
                metadata = skill_data.get("metadata", {})
                skill = SkillMetadata.from_dict(metadata)
                skills.append(skill)
            except Exception as e:
                logger.warning(f"Failed to load agent skill {skill_name}: {e}")
        
        return skills
    
    def admin_list_all_skills(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        管理员列出所有技能
        
        Returns:
            所有技能信息列表
        """
        all_skills = []
        
        # 公共技能
        for skill_name, skill_data in self._metadata.get("public_skills", {}).items():
            all_skills.append({
                "pool": "public",
                "name": skill_name,
                "data": skill_data,
            })
        
        # 私有技能
        for user_id, user_skills in self._metadata.get("private_skills", {}).items():
            for skill_name, skill_data in user_skills.items():
                all_skills.append({
                    "pool": "private",
                    "user_id": user_id,
                    "name": skill_name,
                    "data": skill_data,
                })
        
        # Agent 技能
        for agent_id, agent_skills in self._metadata.get("agent_skills", {}).items():
            for skill_name, skill_data in agent_skills.items():
                all_skills.append({
                    "pool": "agent",
                    "agent_id": agent_id,
                    "name": skill_name,
                    "data": skill_data,
                })
        
        return all_skills
    
    def admin_delete_user_skills(self, user_id: str) -> bool:
        """
        管理员删除用户的所有技能
        
        Args:
            user_id: 用户 ID
            
        Returns:
            是否删除成功
        """
        try:
            # 删除用户的所有私有技能
            if user_id in self._metadata.get("private_skills", {}):
                del self._metadata["private_skills"][user_id]
            
            # 删除用户的技能目录
            user_dir = self._private_pool_dir / user_id
            if user_dir.exists():
                shutil.rmtree(user_dir)
            
            self._save_metadata()
            
            logger.info(f"Deleted all skills for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete skills for user {user_id}: {e}")
            return False
