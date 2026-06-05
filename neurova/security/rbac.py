from __future__ import annotations

"""
Neurova 权限管理增强模块 (RBAC)

功能:
1. RBAC 角色权限管理
2. 细粒度权限配置
3. 权限变更审批流程
"""

from dataclasses import dataclass, field
import datetime
import json
import logging
import os
from pathlib import Path
import threading
from typing import Dict, Any, List, Optional, Set
from enum import Enum
import sqlite3
import time

logger = logging.getLogger(__name__)


class Permission(str, Enum):
    """权限枚举"""
    SYSTEM_READ = "system:read"
    SYSTEM_WRITE = "system:write"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"
    ROLE_READ = "role:read"
    ROLE_WRITE = "role:write"
    ROLE_DELETE = "role:delete"
    API_KEY_READ = "api_key:read"
    API_KEY_WRITE = "api_key:write"
    API_KEY_DELETE = "api_key:delete"
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    SKILL_READ = "skill:read"
    SKILL_WRITE = "skill:write"
    SKILL_DELETE = "skill:delete"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_WRITE = "workflow:write"
    WORKFLOW_DELETE = "workflow:delete"
    CHANNEL_READ = "channel:read"
    CHANNEL_WRITE = "channel:write"
    CHANNEL_DELETE = "channel:delete"
    COMPLIANCE_READ = "compliance:read"
    COMPLIANCE_WRITE = "compliance:write"


ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "admin": {p.value for p in Permission},
    "operator": {
        Permission.SYSTEM_READ.value, Permission.USER_READ.value, Permission.USER_WRITE.value,
        Permission.API_KEY_READ.value, Permission.API_KEY_WRITE.value, Permission.AUDIT_READ.value,
        Permission.CONFIG_READ.value, Permission.SKILL_READ.value, Permission.SKILL_WRITE.value,
        Permission.WORKFLOW_READ.value, Permission.WORKFLOW_WRITE.value,
        Permission.CHANNEL_READ.value, Permission.CHANNEL_WRITE.value,
    },
    "developer": {
        Permission.SYSTEM_READ.value, Permission.USER_READ.value, Permission.API_KEY_READ.value,
        Permission.CONFIG_READ.value, Permission.SKILL_READ.value, Permission.SKILL_WRITE.value,
        Permission.WORKFLOW_READ.value, Permission.WORKFLOW_WRITE.value, Permission.CHANNEL_READ.value,
    },
    "viewer": {
        Permission.SYSTEM_READ.value, Permission.USER_READ.value, Permission.API_KEY_READ.value,
        Permission.AUDIT_READ.value, Permission.CONFIG_READ.value, Permission.SKILL_READ.value,
        Permission.WORKFLOW_READ.value, Permission.CHANNEL_READ.value, Permission.COMPLIANCE_READ.value,
    },
    "guest": {
        Permission.SYSTEM_READ.value, Permission.SKILL_READ.value,
    },
}


@dataclass
class Role:
    """角色数据类"""
    id: str
    name: str
    description: str = ""
    permissions: Set[str] = field(default_factory=set)
    is_system: bool = False
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    updated_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "permissions": list(self.permissions), "is_system": self.is_system,
            "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class PermissionChangeRequest:
    """权限变更请求数据类"""
    id: int
    requester_id: str
    target_user_id: str
    action: str
    role_id: Optional[str] = None
    permissions: Optional[Set[str]] = None
    reason: str = ""
    status: str = "pending"
    approver_id: Optional[str] = None
    approver_comment: Optional[str] = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    processed_at: Optional[datetime.datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "requester_id": self.requester_id, "target_user_id": self.target_user_id,
            "action": self.action, "role_id": self.role_id,
            "permissions": list(self.permissions) if self.permissions else None,
            "reason": self.reason, "status": self.status, "approver_id": self.approver_id,
            "approver_comment": self.approver_comment,
            "created_at": self.created_at.isoformat(),
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }


class RBACManager:
    """RBAC 管理器（单例）"""

    _instance: Optional['RBACManager'] = None
    _lock = threading.Lock()

    def __new__(cls, db_path: Optional[str] = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if self._initialized:
            return
        self._db_path = db_path or str(Path.home() / ".neurova" / "rbac.db")
        self._ensure_db_dir()
        self._init_db()
        self._init_system_roles()
        self._load_cache()
        self._initialized = True
        logger.info(f"RBACManager initialized: {self._db_path}")

    def _ensure_db_dir(self):
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT,
                permissions TEXT, is_system INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id TEXT NOT NULL, role_id TEXT NOT NULL,
                assigned_by TEXT, assigned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, role_id), FOREIGN KEY (role_id) REFERENCES roles (id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS permission_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, requester_id TEXT NOT NULL,
                target_user_id TEXT NOT NULL, action TEXT NOT NULL, role_id TEXT,
                permissions TEXT, reason TEXT, status TEXT DEFAULT 'pending',
                approver_id TEXT, approver_comment TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_permission_requests_status ON permission_requests(status)")
        conn.commit()
        conn.close()

    def _init_system_roles(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        for role_name, permissions in ROLE_PERMISSIONS.items():
            role_id = role_name.lower().replace(" ", "_")
            cursor.execute("SELECT id FROM roles WHERE id = ?", (role_id,))
            if cursor.fetchone() is None:
                now = datetime.datetime.now().isoformat()
                cursor.execute(
                    "INSERT INTO roles (id, name, description, permissions, is_system, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (role_id, role_name, f"System {role_name} role", json.dumps(list(permissions)), 1, now, now),
                )
        conn.commit()
        conn.close()

    def _load_cache(self):
        self._roles_cache: Dict[str, Role] = {}
        self._user_roles_cache: Dict[str, Set[str]] = {}
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM roles")
        for row in cursor.fetchall():
            role = Role(
                id=row['id'], name=row['name'], description=row['description'] or "",
                permissions=set(json.loads(row['permissions'])) if row['permissions'] else set(),
                is_system=bool(row['is_system']),
                created_at=datetime.datetime.fromisoformat(row['created_at']),
                updated_at=datetime.datetime.fromisoformat(row['updated_at']),
            )
            self._roles_cache[role.id] = role
        cursor.execute("SELECT user_id, role_id FROM user_roles")
        for row in cursor.fetchall():
            self._user_roles_cache.setdefault(row['user_id'], set()).add(row['role_id'])
        conn.close()

    def _invalidate_cache(self):
        self._roles_cache.clear()
        self._user_roles_cache.clear()
        self._load_cache()

    def create_role(self, name: str, description: str = "", permissions: Set[str] = None,
                    is_system: bool = False) -> Optional[Role]:
        role_id = name.lower().replace(" ", "_")
        if role_id in self._roles_cache:
            return None
        for r in self._roles_cache.values():
            if r.name == name:
                return None
        now = datetime.datetime.now()
        role = Role(id=role_id, name=name, description=description,
                    permissions=permissions or set(), is_system=is_system,
                    created_at=now, updated_at=now)
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO roles (id,name,description,permissions,is_system,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (role.id, role.name, role.description, json.dumps(list(role.permissions)),
             1 if role.is_system else 0, role.created_at.isoformat(), role.updated_at.isoformat()),
        )
        conn.commit()
        conn.close()
        self._roles_cache[role.id] = role
        logger.info(f"Created role: {name}")
        return role

    def _get_role(self, role_id: str) -> Optional[Role]:
        return self._roles_cache.get(role_id)

    def get_role(self, role_id: str) -> Optional[Role]:
        return self._get_role(role_id)

    def get_role_by_name(self, name: str) -> Optional[Role]:
        for role in self._roles_cache.values():
            if role.name == name:
                return role
        return None

    def list_roles(self) -> List[Role]:
        return list(self._roles_cache.values())

    def update_role(self, role_id: str, name: Optional[str] = None,
                    description: Optional[str] = None, permissions: Optional[Set[str]] = None) -> Optional[Role]:
        role = self._get_role(role_id)
        if not role or role.is_system:
            return None
        if name is not None:
            for r in self._roles_cache.values():
                if r.id != role_id and r.name == name:
                    return None
            role.name = name
        if description is not None:
            role.description = description
        if permissions is not None:
            role.permissions = permissions
        role.updated_at = datetime.datetime.now()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE roles SET name=?,description=?,permissions=?,updated_at=? WHERE id=?",
                       (role.name, role.description, json.dumps(list(role.permissions)),
                        role.updated_at.isoformat(), role.id))
        conn.commit()
        conn.close()
        self._roles_cache[role.id] = role
        return role

    def delete_role(self, role_id: str) -> bool:
        role = self._get_role(role_id)
        if not role or role.is_system:
            return False
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_roles WHERE role_id=?", (role_id,))
        cursor.execute("DELETE FROM roles WHERE id=?", (role_id,))
        conn.commit()
        conn.close()
        del self._roles_cache[role_id]
        for uid in list(self._user_roles_cache.keys()):
            self._user_roles_cache[uid].discard(role_id)
            if not self._user_roles_cache[uid]:
                del self._user_roles_cache[uid]
        logger.info(f"Deleted role: {role.name}")
        return True

    def has_permission(self, user_id: str, permission: str) -> bool:
        for role_id in self._user_roles_cache.get(user_id, set()):
            role = self._get_role(role_id)
            if role and permission in role.permissions:
                return True
        return False

    def has_any_permission(self, user_id: str, permissions: List[str]) -> bool:
        return any(self.has_permission(user_id, p) for p in permissions)

    def has_all_permissions(self, user_id: str, permissions: List[str]) -> bool:
        return all(self.has_permission(user_id, p) for p in permissions)

    def get_user_permissions(self, user_id: str) -> Set[str]:
        perms: Set[str] = set()
        for role_id in self._user_roles_cache.get(user_id, set()):
            role = self._get_role(role_id)
            if role:
                perms.update(role.permissions)
        return perms

    def assign_role(self, user_id: str, role_id: str, assigned_by: str = "system") -> bool:
        if not self._get_role(role_id):
            return False
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO user_roles (user_id,role_id,assigned_by,assigned_at) VALUES (?,?,?,?)",
                       (user_id, role_id, assigned_by, datetime.datetime.now().isoformat()))
        conn.commit()
        conn.close()
        self._user_roles_cache.setdefault(user_id, set()).add(role_id)
        logger.info(f"Assigned role {role_id} to user {user_id}")
        return True

    def revoke_role(self, user_id: str, role_id: str) -> bool:
        if user_id not in self._user_roles_cache or role_id not in self._user_roles_cache[user_id]:
            return False
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_roles WHERE user_id=? AND role_id=?", (user_id, role_id))
        conn.commit()
        conn.close()
        self._user_roles_cache[user_id].discard(role_id)
        if not self._user_roles_cache[user_id]:
            del self._user_roles_cache[user_id]
        logger.info(f"Revoked role {role_id} from user {user_id}")
        return True

    def get_user_roles(self, user_id: str) -> List[Role]:
        roles = []
        for role_id in self._user_roles_cache.get(user_id, set()):
            role = self._get_role(role_id)
            if role:
                roles.append(role)
        return roles

    def get_role_users(self, role_id: str) -> List[str]:
        return [uid for uid, rids in self._user_roles_cache.items() if role_id in rids]

    def create_permission_request(self, requester_id: str, target_user_id: str, action: str,
                                  reason: str = "", role_id: Optional[str] = None,
                                  permissions: Optional[Set[str]] = None) -> Optional[int]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO permission_requests (requester_id,target_user_id,action,role_id,permissions,reason,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (requester_id, target_user_id, action, role_id,
             json.dumps(list(permissions)) if permissions else None, reason, "pending",
             datetime.datetime.now().isoformat()),
        )
        request_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return request_id

    def get_pending_requests(self) -> List[PermissionChangeRequest]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM permission_requests WHERE status='pending' ORDER BY created_at DESC")
        results = cursor.fetchall()
        conn.close()
        requests = []
        for row in results:
            requests.append(PermissionChangeRequest(
                id=row['id'], requester_id=row['requester_id'],
                target_user_id=row['target_user_id'], action=row['action'],
                role_id=row['role_id'],
                permissions=set(json.loads(row['permissions'])) if row['permissions'] else None,
                reason=row['reason'] or "", status=row['status'],
                approver_id=row['approver_id'], approver_comment=row['approver_comment'],
                created_at=datetime.datetime.fromisoformat(row['created_at']),
                processed_at=datetime.datetime.fromisoformat(row['processed_at']) if row['processed_at'] else None,
            ))
        return requests

    def approve_request(self, request_id: int, approver_id: str, comment: str = "") -> bool:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM permission_requests WHERE id=?", (request_id,))
        row = cursor.fetchone()
        if not row or row['status'] != 'pending':
            conn.close()
            return False
        now = datetime.datetime.now().isoformat()
        cursor.execute("UPDATE permission_requests SET status='approved',approver_id=?,approver_comment=?,processed_at=? WHERE id=?",
                       (approver_id, comment, now, request_id))
        conn.commit()
        conn.close()
        if row['action'] == 'assign_role' and row['role_id']:
            self.assign_role(row['target_user_id'], row['role_id'], assigned_by=approver_id)
        elif row['action'] == 'revoke_role' and row['role_id']:
            self.revoke_role(row['target_user_id'], row['role_id'])
        logger.info(f"Approved request {request_id}")
        return True

    def reject_request(self, request_id: int, approver_id: str, comment: str = "") -> bool:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM permission_requests WHERE id=?", (request_id,))
        row = cursor.fetchone()
        if not row or row['status'] != 'pending':
            conn.close()
            return False
        now = datetime.datetime.now().isoformat()
        cursor.execute("UPDATE permission_requests SET status='rejected',approver_id=?,approver_comment=?,processed_at=? WHERE id=?",
                       (approver_id, comment, now, request_id))
        conn.commit()
        conn.close()
        logger.info(f"Rejected request {request_id}")
        return True

    def get_all_permissions(self) -> List[Dict[str, str]]:
        descriptions = {
            "system:read": "读取系统信息", "system:write": "修改系统配置",
            "user:read": "读取用户信息", "user:write": "修改用户信息", "user:delete": "删除用户",
            "role:read": "读取角色信息", "role:write": "修改角色信息", "role:delete": "删除角色",
            "api_key:read": "读取 API Key", "api_key:write": "创建/修改 API Key", "api_key:delete": "删除 API Key",
            "audit:read": "查看审计日志", "audit:export": "导出审计日志",
            "config:read": "读取配置", "config:write": "修改配置",
            "skill:read": "读取技能", "skill:write": "创建/修改技能", "skill:delete": "删除技能",
            "workflow:read": "读取工作流", "workflow:write": "创建/修改工作流", "workflow:delete": "删除工作流",
            "channel:read": "读取渠道", "channel:write": "创建/修改渠道", "channel:delete": "删除渠道",
            "compliance:read": "查看合规报告", "compliance:write": "修改合规设置",
        }
        return [{"id": p.value, "name": p.name, "description": descriptions.get(p.value, p.value)} for p in Permission]

    def _get_permission_description(self, permission: str) -> str:
        return self.get_all_permissions().get(permission, permission)


_rbac_manager: Optional[RBACManager] = None


def get_rbac_manager(db_path: Optional[str] = None) -> RBACManager:
    global _rbac_manager
    if _rbac_manager is None:
        _rbac_manager = RBACManager(db_path)
    return _rbac_manager
