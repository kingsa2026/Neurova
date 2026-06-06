"""
Neurova 协作模块隔离管理器

功能:
1. 项目隔离（按用户）
2. 文件隔离（按用户）
3. 工作流隔离（按用户）
4. 团队成员管理（用户只能看到自己参与的项目）
5. 资源共享权限控制
"""

from dataclasses import dataclass, field
import datetime
import enum
import json
import logging
from pathlib import Path
import shutil
import time
import threading
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ProjectStatus(str, Enum):
    """项目状态"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"
    SUSPENDED = "suspended"


class ProjectVisibility(str, Enum):
    """项目可见性"""
    PRIVATE = "private"  # 仅成员可见
    TEAM = "team"  # 团队可见
    PUBLIC = "public"  # 公开可见


class MemberRole(str, Enum):
    """成员角色"""
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    GUEST = "guest"


@dataclass
class ProjectMember:
    """项目成员"""
    user_id: str
    role: MemberRole
    joined_at: float = field(default_factory=time.time)
    invited_by: Optional[str] = None
    permissions: Dict[str, bool] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "role": self.role.value,
            "joined_at": self.joined_at,
            "invited_by": self.invited_by,
            "permissions": self.permissions
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectMember':
        """从字典创建"""
        return cls(
            user_id=data["user_id"],
            role=MemberRole(data.get("role", "viewer")),
            joined_at=data.get("joined_at", time.time()),
            invited_by=data.get("invited_by"),
            permissions=data.get("permissions", {})
        )
    
    def has_permission(self, permission: str) -> bool:
        """检查是否有权限"""
        # 所有者和管理员有所有权限
        if self.role in [MemberRole.OWNER, MemberRole.ADMIN]:
            return True
        
        return self.permissions.get(permission, False)
    
    def can_edit(self) -> bool:
        """是否可以编辑"""
        return self.role in [MemberRole.OWNER, MemberRole.ADMIN, MemberRole.EDITOR]
    
    def can_view(self) -> bool:
        """是否可以查看"""
        return self.role != MemberRole.GUEST


@dataclass
class ProjectFile:
    """项目文件"""
    file_id: str = field(default_factory=lambda: f"file_{int(time.time() * 1000)}")
    name: str = ""
    path: str = ""
    file_type: str = ""  # file, folder
    size_bytes: int = 0
    mime_type: str = ""
    created_by: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "file_id": self.file_id,
            "name": self.name,
            "path": self.path,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectFile':
        """从字典创建"""
        return cls(
            file_id=data.get("file_id", f"file_{int(time.time() * 1000)}"),
            name=data.get("name", ""),
            path=data.get("path", ""),
            file_type=data.get("file_type", "file"),
            size_bytes=data.get("size_bytes", 0),
            mime_type=data.get("mime_type", ""),
            created_by=data.get("created_by", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata", {})
        )


@dataclass
class ProjectWorkflow:
    """项目工作流"""
    workflow_id: str = field(default_factory=lambda: f"workflow_{int(time.time() * 1000)}")
    name: str = ""
    description: str = ""
    definition: Dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    is_active: bool = True
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "definition": self.definition,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_active": self.is_active,
            "version": self.version,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectWorkflow':
        """从字典创建"""
        return cls(
            workflow_id=data.get("workflow_id", f"workflow_{int(time.time() * 1000)}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            definition=data.get("definition", {}),
            created_by=data.get("created_by", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            is_active=data.get("is_active", True),
            version=data.get("version", 1),
            metadata=data.get("metadata", {})
        )


@dataclass
class Project:
    """项目"""
    project_id: str = field(default_factory=lambda: f"project_{int(time.time() * 1000)}")
    name: str = ""
    description: str = ""
    owner_id: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    visibility: ProjectVisibility = ProjectVisibility.PRIVATE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    archived_at: Optional[float] = None
    deleted_at: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 成员列表
    members: Dict[str, ProjectMember] = field(default_factory=dict)
    
    # 文件列表
    files: Dict[str, ProjectFile] = field(default_factory=dict)
    
    # 工作流列表
    workflows: Dict[str, ProjectWorkflow] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "status": self.status.value,
            "visibility": self.visibility.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "archived_at": self.archived_at,
            "deleted_at": self.deleted_at,
            "tags": self.tags,
            "metadata": self.metadata,
            "members": {uid: m.to_dict() for uid, m in self.members.items()},
            "files": {fid: f.to_dict() for fid, f in self.files.items()},
            "workflows": {wid: w.to_dict() for wid, w in self.workflows.items()}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        """从字典创建"""
        project = cls(
            project_id=data.get("project_id", f"project_{int(time.time() * 1000)}"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            owner_id=data.get("owner_id", ""),
            status=ProjectStatus(data.get("status", "active")),
            visibility=ProjectVisibility(data.get("visibility", "private")),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            archived_at=data.get("archived_at"),
            deleted_at=data.get("deleted_at"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {})
        )
        
        # 加载成员
        for uid, member_data in data.get("members", {}).items():
            project.members[uid] = ProjectMember.from_dict(member_data)
        
        # 加载文件
        for fid, file_data in data.get("files", {}).items():
            project.files[fid] = ProjectFile.from_dict(file_data)
        
        # 加载工作流
        for wid, workflow_data in data.get("workflows", {}).items():
            project.workflows[wid] = ProjectWorkflow.from_dict(workflow_data)
        
        return project
    
    def is_member(self, user_id: str) -> bool:
        """检查用户是否是成员"""
        return user_id in self.members
    
    def get_member(self, user_id: str) -> Optional[ProjectMember]:
        """获取成员"""
        return self.members.get(user_id)
    
    def add_member(self, user_id: str, role: MemberRole = MemberRole.VIEWER,
                  invited_by: Optional[str] = None) -> ProjectMember:
        """添加成员"""
        member = ProjectMember(
            user_id=user_id,
            role=role,
            invited_by=invited_by
        )
        self.members[user_id] = member
        return member
    
    def remove_member(self, user_id: str) -> bool:
        """移除成员"""
        if user_id in self.members:
            # 不能移除所有者
            if self.members[user_id].role == MemberRole.OWNER:
                return False
            del self.members[user_id]
            return True
        return False
    
    def update_member_role(self, user_id: str, role: MemberRole) -> bool:
        """更新成员角色"""
        if user_id in self.members:
            # 不能更改所有者角色
            if self.members[user_id].role == MemberRole.OWNER:
                return False
            self.members[user_id].role = role
            return True
        return False
    
    def get_file(self, file_id: str) -> Optional[ProjectFile]:
        """获取文件"""
        return self.files.get(file_id)
    
    def add_file(self, file: ProjectFile) -> None:
        """添加文件"""
        self.files[file.file_id] = file
    
    def remove_file(self, file_id: str) -> bool:
        """移除文件"""
        if file_id in self.files:
            del self.files[file_id]
            return True
        return False
    
    def get_workflow(self, workflow_id: str) -> Optional[ProjectWorkflow]:
        """获取工作流"""
        return self.workflows.get(workflow_id)
    
    def add_workflow(self, workflow: ProjectWorkflow) -> None:
        """添加工作流"""
        self.workflows[workflow.workflow_id] = workflow
    
    def remove_workflow(self, workflow_id: str) -> bool:
        """移除工作流"""
        if workflow_id in self.workflows:
            del self.workflows[workflow_id]
            return True
        return False
    
    def archive(self) -> None:
        """归档项目"""
        self.status = ProjectStatus.ARCHIVED
        self.archived_at = time.time()
        self.updated_at = time.time()
    
    def restore(self) -> None:
        """恢复项目"""
        self.status = ProjectStatus.ACTIVE
        self.archived_at = None
        self.updated_at = time.time()
    
    def delete(self) -> None:
        """删除项目（软删除）"""
        self.status = ProjectStatus.DELETED
        self.deleted_at = time.time()
        self.updated_at = time.time()


class CollaborationIsolationManager:
    """
    协作隔离管理器
    
    功能：
    1. 项目隔离（按用户）
    2. 文件隔离（按用户）
    3. 工作流隔离（按用户）
    4. 团队成员管理
    5. 资源共享权限控制
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        """
        初始化协作隔离管理器
        
        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = Path(data_dir) if data_dir else Path("data/collaboration")
        
        # 线程锁
        self._lock = threading.RLock()
        
        # 项目存储: {project_id: Project}
        self._projects: Dict[str, Project] = {}
        
        # 用户项目索引: {user_id: set(project_id)}
        self._user_projects: Dict[str, Set[str]] = {}
        
        # 初始化
        self._on_init()
        
        logger.info("CollaborationIsolationManager initialized")
    
    def _on_init(self) -> None:
        """初始化回调"""
        # 创建数据目录
        self._init_dirs()
        
        # 加载项目
        self._load_projects()
    
    def _on_start(self) -> None:
        """启动回调"""
        logger.info("CollaborationIsolationManager started")
    
    def _init_dirs(self) -> None:
        """初始化目录结构"""
        try:
            # 创建主目录
            self.data_dir.mkdir(parents=True, exist_ok=True)
            
            # 创建子目录
            (self.data_dir / "projects").mkdir(exist_ok=True)
            (self.data_dir / "files").mkdir(exist_ok=True)
            (self.data_dir / "workflows").mkdir(exist_ok=True)
            (self.data_dir / "backups").mkdir(exist_ok=True)
            
            logger.info(f"Initialized collaboration directories: {self.data_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize directories: {e}")
    
    def _load_projects(self) -> None:
        """加载项目"""
        try:
            projects_dir = self.data_dir / "projects"
            if not projects_dir.exists():
                return
            
            for project_file in projects_dir.glob("*.json"):
                try:
                    with open(project_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    project = Project.from_dict(data)
                    self._projects[project.project_id] = project
                    
                    # 更新用户项目索引
                    for user_id in project.members:
                        if user_id not in self._user_projects:
                            self._user_projects[user_id] = set()
                        self._user_projects[user_id].add(project.project_id)
                    
                except Exception as e:
                    logger.warning(f"Failed to load project {project_file}: {e}")
            
            logger.info(f"Loaded {len(self._projects)} projects")
            
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
    
    def _save_project(self, project: Project) -> bool:
        """保存项目"""
        try:
            projects_dir = self.data_dir / "projects"
            project_file = projects_dir / f"{project.project_id}.json"
            
            with open(project_file, 'w', encoding='utf-8') as f:
                json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Saved project: {project.project_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save project {project.project_id}: {e}")
            return False
    
    def create_project(self, name: str, description: str = "",
                      owner_id: str = "",
                      visibility: ProjectVisibility = ProjectVisibility.PRIVATE,
                      tags: Optional[List[str]] = None,
                      metadata: Optional[Dict[str, Any]] = None) -> Optional[Project]:
        """
        创建项目
        
        Args:
            name: 项目名称
            description: 项目描述
            owner_id: 所有者ID
            visibility: 可见性
            tags: 标签
            metadata: 元数据
            
        Returns:
            创建的项目
        """
        with self._lock:
            try:
                # 创建项目
                project = Project(
                    name=name,
                    description=description,
                    owner_id=owner_id,
                    visibility=visibility,
                    tags=tags or [],
                    metadata=metadata or {}
                )
                
                # 添加所有者
                project.add_member(owner_id, MemberRole.OWNER)
                
                # 存储项目
                self._projects[project.project_id] = project
                
                # 更新用户项目索引
                if owner_id not in self._user_projects:
                    self._user_projects[owner_id] = set()
                self._user_projects[owner_id].add(project.project_id)
                
                # 保存到文件
                self._save_project(project)
                
                logger.info(f"Created project: {project.project_id} by {owner_id}")
                return project
                
            except Exception as e:
                logger.error(f"Failed to create project: {e}")
                return None
    
    def get_project(self, project_id: str, 
                   user_id: Optional[str] = None) -> Optional[Project]:
        """
        获取项目
        
        Args:
            project_id: 项目ID
            user_id: 用户ID（用于权限检查）
            
        Returns:
            项目对象
        """
        project = self._projects.get(project_id)
        if not project:
            return None
        
        # 检查权限
        if user_id and not self._can_access_project(project, user_id):
            return None
        
        return project
    
    def list_user_projects(self, user_id: str, 
                          include_archived: bool = False,
                          include_deleted: bool = False) -> List[Project]:
        """
        列出用户的项目
        
        Args:
            user_id: 用户ID
            include_archived: 是否包含归档项目
            include_deleted: 是否包含删除项目
            
        Returns:
            项目列表
        """
        projects = []
        
        with self._lock:
            # 获取用户参与的项目
            project_ids = self._user_projects.get(user_id, set())
            
            for project_id in project_ids:
                project = self._projects.get(project_id)
                if not project:
                    continue
                
                # 过滤状态
                if not include_archived and project.status == ProjectStatus.ARCHIVED:
                    continue
                
                if not include_deleted and project.status == ProjectStatus.DELETED:
                    continue
                
                # 检查可见性
                if self._can_view_project(project, user_id):
                    projects.append(project)
        
        # 按更新时间排序
        projects.sort(key=lambda p: p.updated_at, reverse=True)
        
        return projects
    
    def update_project(self, project_id: str, user_id: str,
                      updates: Dict[str, Any]) -> Optional[Project]:
        """
        更新项目
        
        Args:
            project_id: 项目ID
            user_id: 用户ID
            updates: 更新内容
            
        Returns:
            更新后的项目
        """
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return None
            
            # 检查权限
            member = project.get_member(user_id)
            if not member or not member.can_edit():
                return None
            
            # 应用更新
            if "name" in updates:
                project.name = updates["name"]
            if "description" in updates:
                project.description = updates["description"]
            if "visibility" in updates:
                project.visibility = ProjectVisibility(updates["visibility"])
            if "tags" in updates:
                project.tags = updates["tags"]
            if "metadata" in updates:
                project.metadata.update(updates["metadata"])
            
            project.updated_at = time.time()
            
            # 保存
            self._save_project(project)
            
            logger.info(f"Updated project: {project_id} by {user_id}")
            return project
    
    def delete_project(self, project_id: str, user_id: str) -> bool:
        """
        删除项目（软删除）
        
        Args:
            project_id: 项目ID
            user_id: 用户ID
            
        Returns:
            是否删除成功
        """
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return False
            
            # 检查权限（只有所有者可以删除）
            member = project.get_member(user_id)
            if not member or member.role != MemberRole.OWNER:
                return False
            
            # 软删除
            project.delete()
            
            # 保存
            self._save_project(project)
            
            logger.info(f"Deleted project: {project_id} by {user_id}")
            return True
    
    def hard_delete_project(self, project_id: str, user_id: str) -> bool:
        """
        硬删除项目
        
        Args:
            project_id: 项目ID
            user_id: 用户ID
            
        Returns:
            是否删除成功
        """
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return False
            
            # 检查权限（只有所有者可以硬删除）
            member = project.get_member(user_id)
            if not member or member.role != MemberRole.OWNER:
                return False
            
            # 删除项目文件
            try:
                project_dir = self.data_dir / "projects"
                project_file = project_dir / f"{project_id}.json"
                if project_file.exists():
                    project_file.unlink()
                
                # 删除项目文件目录
                files_dir = self.data_dir / "files" / project_id
                if files_dir.exists():
                    shutil.rmtree(files_dir)
                
                # 删除工作流目录
                workflows_dir = self.data_dir / "workflows" / project_id
                if workflows_dir.exists():
                    shutil.rmtree(workflows_dir)
                
            except Exception as e:
                logger.error(f"Failed to delete project files: {e}")
            
            # 从索引中移除
            for user_id in project.members:
                if user_id in self._user_projects:
                    self._user_projects[user_id].discard(project_id)
            
            # 从存储中移除
            del self._projects[project_id]
            
            logger.info(f"Hard deleted project: {project_id} by {user_id}")
            return True
    
    def add_project_member(self, project_id: str, inviter_id: str,
                          user_id: str, 
                          role: MemberRole = MemberRole.VIEWER) -> bool:
        """
        添加项目成员
        
        Args:
            project_id: 项目ID
            inviter_id: 邀请者ID
            user_id: 用户ID
            role: 角色
            
        Returns:
            是否添加成功
        """
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return False
            
            # 检查邀请者权限
            inviter = project.get_member(inviter_id)
            if not inviter or not inviter.can_edit():
                return False
            
            # 检查用户是否已是成员
            if project.is_member(user_id):
                return False
            
            # 添加成员
            project.add_member(user_id, role, invited_by=inviter_id)
            
            # 更新用户项目索引
            if user_id not in self._user_projects:
                self._user_projects[user_id] = set()
            self._user_projects[user_id].add(project_id)
            
            # 保存
            self._save_project(project)
            
            logger.info(f"Added member {user_id} to project {project_id} by {inviter_id}")
            return True
    
    def remove_project_member(self, project_id: str, remover_id: str,
                             user_id: str) -> bool:
        """
        移除项目成员
        
        Args:
            project_id: 项目ID
            remover_id: 移除者ID
            user_id: 用户ID
            
        Returns:
            是否移除成功
        """
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return False
            
            # 检查移除者权限
            remover = project.get_member(remover_id)
            if not remover or not remover.can_edit():
                return False
            
            # 不能移除自己
            if remover_id == user_id:
                return False
            
            # 移除成员
            if not project.remove_member(user_id):
                return False
            
            # 更新用户项目索引
            if user_id in self._user_projects:
                self._user_projects[user_id].discard(project_id)
            
            # 保存
            self._save_project(project)
            
            logger.info(f"Removed member {user_id} from project {project_id} by {remover_id}")
            return True
    
    def update_member_role(self, project_id: str, updater_id: str,
                          user_id: str, role: MemberRole) -> bool:
        """
        更新成员角色
        
        Args:
            project_id: 项目ID
            updater_id: 更新者ID
            user_id: 用户ID
            role: 新角色
            
        Returns:
            是否更新成功
        """
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return False
            
            # 检查更新者权限
            updater = project.get_member(updater_id)
            if not updater or updater.role != MemberRole.OWNER:
                return False
            
            # 更新角色
            if not project.update_member_role(user_id, role):
                return False
            
            # 保存
            self._save_project(project)
            
            logger.info(f"Updated role of {user_id} in project {project_id} to {role.value}")
            return True
    
    def get_project_file_path(self, project_id: str, file_id: str) -> Optional[Path]:
        """获取项目文件路径"""
        project = self._projects.get(project_id)
        if not project:
            return None
        
        file_obj = project.get_file(file_id)
        if not file_obj:
            return None
        
        return self.data_dir / "files" / project_id / file_obj.path
    
    def list_project_files(self, project_id: str, 
                          user_id: Optional[str] = None) -> List[ProjectFile]:
        """
        列出项目文件
        
        Args:
            project_id: 项目ID
            user_id: 用户ID（用于权限检查）
            
        Returns:
            文件列表
        """
        project = self._projects.get(project_id)
        if not project:
            return []
        
        # 检查权限
        if user_id and not self._can_access_project(project, user_id):
            return []
        
        return list(project.files.values())
    
    def add_project_file(self, project_id: str, user_id: str,
                        file: ProjectFile) -> bool:
        """
        添加项目文件
        
        Args:
            project_id: 项目ID
            user_id: 用户ID
            file: 文件对象
            
        Returns:
            是否添加成功
        """
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return False
            
            # 检查权限
            member = project.get_member(user_id)
            if not member or not member.can_edit():
                return False
            
            # 设置文件信息
            file.created_by = user_id
            file.created_at = time.time()
            file.updated_at = time.time()
            
            # 添加文件
            project.add_file(file)
            
            # 保存
            self._save_project(project)
            
            logger.info(f"Added file {file.file_id} to project {project_id}")
            return True
    
    def get_project_workflow_path(self, project_id: str, 
                                 workflow_id: str) -> Optional[Path]:
        """获取项目工作流路径"""
        project = self._projects.get(project_id)
        if not project:
            return None
        
        workflow = project.get_workflow(workflow_id)
        if not workflow:
            return None
        
        return self.data_dir / "workflows" / project_id / f"{workflow_id}.json"
    
    def list_project_workflows(self, project_id: str,
                              user_id: Optional[str] = None) -> List[ProjectWorkflow]:
        """
        列出项目工作流
        
        Args:
            project_id: 项目ID
            user_id: 用户ID（用于权限检查）
            
        Returns:
            工作流列表
        """
        project = self._projects.get(project_id)
        if not project:
            return []
        
        # 检查权限
        if user_id and not self._can_access_project(project, user_id):
            return []
        
        return list(project.workflows.values())
    
    def add_project_workflow(self, project_id: str, user_id: str,
                            workflow: ProjectWorkflow) -> bool:
        """
        添加项目工作流
        
        Args:
            project_id: 项目ID
            user_id: 用户ID
            workflow: 工作流对象
            
        Returns:
            是否添加成功
        """
        with self._lock:
            project = self._projects.get(project_id)
            if not project:
                return False
            
            # 检查权限
            member = project.get_member(user_id)
            if not member or not member.can_edit():
                return False
            
            # 设置工作流信息
            workflow.created_by = user_id
            workflow.created_at = time.time()
            workflow.updated_at = time.time()
            
            # 添加工作流
            project.add_workflow(workflow)
            
            # 保存
            self._save_project(project)
            
            logger.info(f"Added workflow {workflow.workflow_id} to project {project_id}")
            return True
    
    def admin_list_all_projects(self, admin_id: str,
                               include_deleted: bool = False) -> List[Project]:
        """
        管理员列出所有项目
        
        Args:
            admin_id: 管理员ID
            include_deleted: 是否包含删除项目
            
        Returns:
            项目列表
        """
        # 这里简化处理，实际应用中应该检查管理员权限
        projects = []
        
        with self._lock:
            for project in self._projects.values():
                if not include_deleted and project.status == ProjectStatus.DELETED:
                    continue
                projects.append(project)
        
        # 按创建时间排序
        projects.sort(key=lambda p: p.created_at, reverse=True)
        
        return projects
    
    def admin_delete_user_projects(self, admin_id: str, user_id: str) -> int:
        """
        管理员删除用户的所有项目
        
        Args:
            admin_id: 管理员ID
            user_id: 用户ID
            
        Returns:
            删除的项目数量
        """
        # 这里简化处理，实际应用中应该检查管理员权限
        deleted_count = 0
        
        with self._lock:
            # 获取用户的项目
            project_ids = self._user_projects.get(user_id, set()).copy()
            
            for project_id in project_ids:
                project = self._projects.get(project_id)
                if not project:
                    continue
                
                # 如果用户是所有者，删除项目
                if project.owner_id == user_id:
                    if self.hard_delete_project(project_id, admin_id):
                        deleted_count += 1
        
        logger.info(f"Admin {admin_id} deleted {deleted_count} projects of user {user_id}")
        return deleted_count
    
    def _can_access_project(self, project: Project, user_id: str) -> bool:
        """检查用户是否可以访问项目"""
        # 如果是成员，可以访问
        if project.is_member(user_id):
            return True
        
        # 检查可见性
        return self._can_view_project(project, user_id)
    
    def _can_view_project(self, project: Project, user_id: str) -> bool:
        """检查用户是否可以查看项目"""
        # 如果是成员，可以查看
        if project.is_member(user_id):
            return True
        
        # 检查可见性
        if project.visibility == ProjectVisibility.PUBLIC:
            return True
        
        # 团队可见性需要额外检查（这里简化处理）
        if project.visibility == ProjectVisibility.TEAM:
            # 实际应用中应该检查用户是否在同一团队
            return False
        
        return False


# 全局实例
_collaboration_manager: Optional[CollaborationIsolationManager] = None


def get_collaboration_manager() -> CollaborationIsolationManager:
    """获取全局协作管理器实例"""
    global _collaboration_manager
    if _collaboration_manager is None:
        _collaboration_manager = CollaborationIsolationManager()
    return _collaboration_manager


def reset_collaboration_manager() -> None:
    """重置全局协作管理器实例（用于测试）"""
    global _collaboration_manager
    _collaboration_manager = None