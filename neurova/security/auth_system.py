"""
Neurova 认证系统 (Auth System) 2.0

提供用户认证、权限管理、会话管理、API 密钥管理功能。
与现有认证系统（neurova.auth 和 neurova.auth.py）兼容。
"""

from dataclasses import dataclass, field
import datetime
import enum
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import time
import typing
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class UserRole(str, Enum):
    """用户角色"""
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"
    MODERATOR = "moderator"


class UserStatus(str, Enum):
    """用户状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"


class ApprovalMode(str, Enum):
    """审批模式"""
    AUTO = "auto"
    MANUAL = "manual"
    SEMI_AUTO = "semi_auto"


# 简化的密码哈希器（不依赖passlib）
class PasswordHasher:
    """密码哈希器"""
    
    def __init__(self, algorithm: str = "sha256"):
        """
        初始化密码哈希器
        
        Args:
            algorithm: 哈希算法
        """
        self.algorithm = algorithm
    
    def hash(self, password: str) -> str:
        """
        哈希密码
        
        Args:
            password: 原始密码
            
        Returns:
            str: 哈希后的密码
        """
        salt = secrets.token_hex(16)
        hash_obj = hashlib.new(self.algorithm)
        hash_obj.update((salt + password).encode())
        return f"{salt}${hash_obj.hexdigest()}"
    
    def verify(self, password: str, hashed: str) -> bool:
        """
        验证密码
        
        Args:
            password: 原始密码
            hashed: 哈希后的密码
            
        Returns:
            bool: 是否匹配
        """
        try:
            salt, hash_value = hashed.split("$", 1)
            hash_obj = hashlib.new(self.algorithm)
            hash_obj.update((salt + password).encode())
            return hash_obj.hexdigest() == hash_value
        except Exception:
            return False


@dataclass
class User:
    """用户数据类"""
    id: str
    username: str
    email: str
    role: UserRole = UserRole.USER
    status: UserStatus = UserStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_login: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_login": self.last_login,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            username=data.get("username", ""),
            email=data.get("email", ""),
            role=UserRole(data.get("role", "user")),
            status=UserStatus(data.get("status", "active")),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            last_login=data.get("last_login"),
            metadata=data.get("metadata", {})
        )


@dataclass
class Session:
    """会话数据类"""
    id: str
    user_id: str
    token: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    ip_address: str = ""
    user_agent: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """检查会话是否过期"""
        return time.time() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "token": self.token,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "metadata": self.metadata
        }


@dataclass
class APIKey:
    """API 密钥数据类"""
    id: str
    user_id: str
    key: str
    name: str = ""
    description: str = ""
    permissions: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    last_used: Optional[float] = None
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """检查 API 密钥是否过期"""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "permissions": self.permissions,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_used": self.last_used,
            "is_active": self.is_active,
            "metadata": self.metadata
        }


class AuthSystem:
    """
    认证系统
    
    提供用户认证、权限管理、会话管理、API 密钥管理功能。
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        初始化认证系统
        
        Args:
            db_path: 数据库路径
        """
        self._db_path = db_path or str(Path.home() / ".neurova" / "auth.db")
        self._password_hasher = PasswordHasher()
        self._users: Dict[str, User] = {}
        self._sessions: Dict[str, Session] = {}
        self._api_keys: Dict[str, APIKey] = {}
        
        # 确保数据库目录存在
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self._init_db()
        
        logger.info("AuthSystem initialized")
    
    def _init_db(self):
        """初始化数据库"""
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            # 创建用户表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    status TEXT DEFAULT 'active',
                    created_at REAL,
                    updated_at REAL,
                    last_login REAL,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            
            # 创建会话表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at REAL,
                    expires_at REAL,
                    ip_address TEXT,
                    user_agent TEXT,
                    metadata TEXT DEFAULT '{}',
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            # 创建 API 密钥表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    key TEXT UNIQUE NOT NULL,
                    name TEXT,
                    description TEXT,
                    permissions TEXT DEFAULT '[]',
                    created_at REAL,
                    expires_at REAL,
                    last_used REAL,
                    is_active INTEGER DEFAULT 1,
                    metadata TEXT DEFAULT '{}',
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            conn.commit()
            conn.close()
            
            logger.info("Database initialized")
        
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def register_user(self, username: str, email: str, password: str, 
                     role: UserRole = UserRole.USER) -> Optional[User]:
        """
        注册用户
        
        Args:
            username: 用户名
            email: 邮箱
            password: 密码
            role: 角色
            
        Returns:
            Optional[User]: 注册的用户
        """
        try:
            # 检查用户名是否已存在
            if self._get_user_by_username(username):
                logger.error(f"Username already exists: {username}")
                return None
            
            # 检查邮箱是否已存在
            if self._get_user_by_email(email):
                logger.error(f"Email already exists: {email}")
                return None
            
            # 创建用户
            user_id = secrets.token_hex(16)
            password_hash = self._password_hasher.hash(password)
            
            user = User(
                id=user_id,
                username=username,
                email=email,
                role=role,
                status=UserStatus.ACTIVE,
                created_at=time.time(),
                updated_at=time.time()
            )
            
            # 保存到数据库
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO users (id, username, email, password_hash, role, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user.id, user.username, user.email, password_hash, 
                  user.role.value, user.status.value, user.created_at, user.updated_at))
            
            conn.commit()
            conn.close()
            
            # 添加到内存缓存
            self._users[user.id] = user
            
            logger.info(f"Registered user: {username}")
            return user
        
        except Exception as e:
            logger.error(f"Failed to register user: {e}")
            return None
    
    def authenticate(self, username: str, password: str) -> Optional[Session]:
        """
        认证用户
        
        Args:
            username: 用户名
            password: 密码
            
        Returns:
            Optional[Session]: 会话
        """
        try:
            # 获取用户
            user = self._get_user_by_username(username)
            if not user:
                logger.error(f"User not found: {username}")
                return None
            
            # 验证密码
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                logger.error(f"Password hash not found for user: {username}")
                return None
            
            password_hash = result[0]
            if not self._password_hasher.verify(password, password_hash):
                logger.error(f"Invalid password for user: {username}")
                return None
            
            # 创建会话
            session = self._create_session(user)
            
            # 更新最后登录时间
            user.last_login = time.time()
            self._update_user(user)
            
            logger.info(f"Authenticated user: {username}")
            return session
        
        except Exception as e:
            logger.error(f"Failed to authenticate user: {e}")
            return None
    
    def _create_session(self, user: User, 
                       expires_in: int = 3600) -> Session:
        """
        创建会话
        
        Args:
            user: 用户
            expires_in: 过期时间（秒）
            
        Returns:
            Session: 会话
        """
        session_id = secrets.token_hex(16)
        token = secrets.token_hex(32)
        
        session = Session(
            id=session_id,
            user_id=user.id,
            token=token,
            created_at=time.time(),
            expires_at=time.time() + expires_in
        )
        
        # 保存到数据库
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO sessions (id, user_id, token, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
        """, (session.id, session.user_id, session.token, 
              session.created_at, session.expires_at))
        
        conn.commit()
        conn.close()
        
        # 添加到内存缓存
        self._sessions[session.id] = session
        
        return session
    
    def validate_session(self, token: str) -> Optional[User]:
        """
        验证会话
        
        Args:
            token: 会话令牌
            
        Returns:
            Optional[User]: 用户
        """
        try:
            # 从数据库获取会话
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, user_id, token, created_at, expires_at 
                FROM sessions WHERE token = ?
            """, (token,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                logger.error("Session not found")
                return None
            
            session_id, user_id, token, created_at, expires_at = result
            
            # 检查会话是否过期
            if time.time() > expires_at:
                logger.error("Session expired")
                self._delete_session(session_id)
                return None
            
            # 获取用户
            user = self._get_user_by_id(user_id)
            if not user:
                logger.error(f"User not found: {user_id}")
                return None
            
            return user
        
        except Exception as e:
            logger.error(f"Failed to validate session: {e}")
            return None
    
    def logout(self, token: str) -> bool:
        """
        登出
        
        Args:
            token: 会话令牌
            
        Returns:
            bool: 是否成功
        """
        try:
            # 从数据库获取会话
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM sessions WHERE token = ?", (token,))
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                logger.error("Session not found")
                return False
            
            session_id = result[0]
            self._delete_session(session_id)
            
            logger.info("Logged out successfully")
            return True
        
        except Exception as e:
            logger.error(f"Failed to logout: {e}")
            return False
    
    def _delete_session(self, session_id: str):
        """
        删除会话
        
        Args:
            session_id: 会话 ID
        """
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            
            conn.commit()
            conn.close()
            
            # 从内存缓存中删除
            if session_id in self._sessions:
                del self._sessions[session_id]
        
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
    
    def create_api_key(self, user_id: str, name: str, 
                      permissions: List[str] = None,
                      expires_in: Optional[int] = None) -> Optional[APIKey]:
        """
        创建 API 密钥
        
        Args:
            user_id: 用户 ID
            name: 密钥名称
            permissions: 权限列表
            expires_in: 过期时间（秒）
            
        Returns:
            Optional[APIKey]: API 密钥
        """
        try:
            # 检查用户是否存在
            user = self._get_user_by_id(user_id)
            if not user:
                logger.error(f"User not found: {user_id}")
                return None
            
            # 创建 API 密钥
            key_id = secrets.token_hex(16)
            key = secrets.token_hex(32)
            
            api_key = APIKey(
                id=key_id,
                user_id=user_id,
                key=key,
                name=name,
                permissions=permissions or [],
                created_at=time.time(),
                expires_at=time.time() + expires_in if expires_in else None
            )
            
            # 保存到数据库
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO api_keys (id, user_id, key, name, permissions, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (api_key.id, api_key.user_id, api_key.key, api_key.name,
                  json.dumps(api_key.permissions), api_key.created_at, api_key.expires_at))
            
            conn.commit()
            conn.close()
            
            # 添加到内存缓存
            self._api_keys[api_key.id] = api_key
            
            logger.info(f"Created API key: {name}")
            return api_key
        
        except Exception as e:
            logger.error(f"Failed to create API key: {e}")
            return None
    
    def validate_api_key(self, key: str) -> Optional[User]:
        """
        验证 API 密钥
        
        Args:
            key: API 密钥
            
        Returns:
            Optional[User]: 用户
        """
        try:
            # 从数据库获取 API 密钥
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, user_id, key, name, permissions, created_at, expires_at, last_used, is_active
                FROM api_keys WHERE key = ?
            """, (key,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                logger.error("API key not found")
                return None
            
            key_id, user_id, key, name, permissions, created_at, expires_at, last_used, is_active = result
            
            # 检查是否激活
            if not is_active:
                logger.error("API key is inactive")
                return None
            
            # 检查是否过期
            if expires_at and time.time() > expires_at:
                logger.error("API key expired")
                return None
            
            # 更新最后使用时间
            self._update_api_key_last_used(key_id)
            
            # 获取用户
            user = self._get_user_by_id(user_id)
            if not user:
                logger.error(f"User not found: {user_id}")
                return None
            
            return user
        
        except Exception as e:
            logger.error(f"Failed to validate API key: {e}")
            return None
    
    def _update_api_key_last_used(self, key_id: str):
        """
        更新 API 密钥最后使用时间
        
        Args:
            key_id: 密钥 ID
        """
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE api_keys SET last_used = ? WHERE id = ?
            """, (time.time(), key_id))
            
            conn.commit()
            conn.close()
        
        except Exception as e:
            logger.error(f"Failed to update API key last used: {e}")
    
    def _get_user_by_username(self, username: str) -> Optional[User]:
        """
        根据用户名获取用户
        
        Args:
            username: 用户名
            
        Returns:
            Optional[User]: 用户
        """
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, username, email, role, status, created_at, updated_at, last_login, metadata
                FROM users WHERE username = ?
            """, (username,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return None
            
            user_id, username, email, role, status, created_at, updated_at, last_login, metadata = result
            
            return User(
                id=user_id,
                username=username,
                email=email,
                role=UserRole(role),
                status=UserStatus(status),
                created_at=created_at,
                updated_at=updated_at,
                last_login=last_login,
                metadata=json.loads(metadata) if metadata else {}
            )
        
        except Exception as e:
            logger.error(f"Failed to get user by username: {e}")
            return None
    
    def _get_user_by_email(self, email: str) -> Optional[User]:
        """
        根据邮箱获取用户
        
        Args:
            email: 邮箱
            
        Returns:
            Optional[User]: 用户
        """
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, username, email, role, status, created_at, updated_at, last_login, metadata
                FROM users WHERE email = ?
            """, (email,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return None
            
            user_id, username, email, role, status, created_at, updated_at, last_login, metadata = result
            
            return User(
                id=user_id,
                username=username,
                email=email,
                role=UserRole(role),
                status=UserStatus(status),
                created_at=created_at,
                updated_at=updated_at,
                last_login=last_login,
                metadata=json.loads(metadata) if metadata else {}
            )
        
        except Exception as e:
            logger.error(f"Failed to get user by email: {e}")
            return None
    
    def _get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        根据 ID 获取用户
        
        Args:
            user_id: 用户 ID
            
        Returns:
            Optional[User]: 用户
        """
        # 先检查内存缓存
        if user_id in self._users:
            return self._users[user_id]
        
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, username, email, role, status, created_at, updated_at, last_login, metadata
                FROM users WHERE id = ?
            """, (user_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            if not result:
                return None
            
            user_id, username, email, role, status, created_at, updated_at, last_login, metadata = result
            
            user = User(
                id=user_id,
                username=username,
                email=email,
                role=UserRole(role),
                status=UserStatus(status),
                created_at=created_at,
                updated_at=updated_at,
                last_login=last_login,
                metadata=json.loads(metadata) if metadata else {}
            )
            
            # 添加到内存缓存
            self._users[user.id] = user
            
            return user
        
        except Exception as e:
            logger.error(f"Failed to get user by ID: {e}")
            return None
    
    def _update_user(self, user: User):
        """
        更新用户
        
        Args:
            user: 用户
        """
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE users SET 
                    username = ?, email = ?, role = ?, status = ?, 
                    updated_at = ?, last_login = ?, metadata = ?
                WHERE id = ?
            """, (user.username, user.email, user.role.value, user.status.value,
                  user.updated_at, user.last_login, json.dumps(user.metadata), user.id))
            
            conn.commit()
            conn.close()
            
            # 更新内存缓存
            self._users[user.id] = user
        
        except Exception as e:
            logger.error(f"Failed to update user: {e}")
    
    def get_user(self, user_id: str) -> Optional[User]:
        """
        获取用户
        
        Args:
            user_id: 用户 ID
            
        Returns:
            Optional[User]: 用户
        """
        return self._get_user_by_id(user_id)
    
    def list_users(self) -> List[User]:
        """
        列出所有用户
        
        Returns:
            List[User]: 用户列表
        """
        try:
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, username, email, role, status, created_at, updated_at, last_login, metadata
                FROM users
            """)
            
            results = cursor.fetchall()
            conn.close()
            
            users = []
            for result in results:
                user_id, username, email, role, status, created_at, updated_at, last_login, metadata = result
                
                user = User(
                    id=user_id,
                    username=username,
                    email=email,
                    role=UserRole(role),
                    status=UserStatus(status),
                    created_at=created_at,
                    updated_at=updated_at,
                    last_login=last_login,
                    metadata=json.loads(metadata) if metadata else {}
                )
                users.append(user)
            
            return users
        
        except Exception as e:
            logger.error(f"Failed to list users: {e}")
            return []
    
    def delete_user(self, user_id: str) -> bool:
        """
        删除用户
        
        Args:
            user_id: 用户 ID
            
        Returns:
            bool: 是否成功
        """
        try:
            # 删除用户的所有会话
            conn = sqlite3.connect(self._db_path)
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            
            conn.commit()
            conn.close()
            
            # 从内存缓存中删除
            if user_id in self._users:
                del self._users[user_id]
            
            logger.info(f"Deleted user: {user_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete user: {e}")
            return False


# 需要导入 logging
import logging
