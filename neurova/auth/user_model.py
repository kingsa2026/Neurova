"""
Neurova 用户数据库模型

用户表结构：
- id: 主键
- username: 用户名（唯一）
- email: 邮箱（可选）
- password_hash: bcrypt 加密的密码
- role: 角色（admin/user）
- status: 状态（active/inactive/locked）
- created_at: 创建时间
...
"""

import datetime
import json
import os
from pathlib import Path
import sqlite3
import time
import typing

class User:
    """User data model - represents a user record"""
    def __init__(self, id: int = 0, username: str = "", email: str = "",
                 password_hash: str = "", role: str = "user",
                 status: str = "active", created_at: str = ""):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.status = status
        self.created_at = created_at

class UserModel:
    """
    用户数据库模型管理器
    管理用户数据的增删改查操作
    """
    
    def __init__(self, db_path: str = "data/users.db"):
        """
        初始化用户模型管理器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._ensure_db_dir()
        self._init_db()
        logger.info("UserModel initialized with db_path=%s", db_path)
    
    def _ensure_db_dir(self) -> None:
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.debug("Created database directory: %s", db_dir)
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self) -> None:
        """初始化数据库表"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # 创建用户表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    status TEXT DEFAULT 'active',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    login_count INTEGER DEFAULT 0,
                    failed_attempts INTEGER DEFAULT 0,
                    last_login TEXT
                )
            """)
            
            # 创建登录日志表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS login_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    login_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    ip_address TEXT,
                    user_agent TEXT,
                    success INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            conn.commit()
            conn.close()
            logger.debug("Database tables initialized")
            
        except Exception as e:
            logger.error("Failed to initialize database: %s", e)
            raise
    
    def create_user(self, username: str, password_hash: str, email: str = None, 
                    role: str = "user", status: str = "active") -> User:
        """
        创建新用户
        
        Args:
            username: 用户名（唯一）
            password_hash: 密码哈希
            email: 邮箱（可选）
            role: 角色（默认user）
            status: 状态（默认active）
            
        Returns:
            创建的用户对象
            
        Raises:
            ValueError: 如果用户名已存在
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # 检查用户名是否已存在
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                conn.close()
                raise ValueError(f"Username '{username}' already exists")
            
            # 插入新用户
            cursor.execute("""
                INSERT INTO users (username, email, password_hash, role, status)
                VALUES (?, ?, ?, ?, ?)
            """, (username, email, password_hash, role, status))
            
            user_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            # 返回创建的用户
            return User(
                id=user_id,
                username=username,
                email=email,
                password_hash=password_hash,
                role=role,
                status=status,
                created_at=datetime.datetime.now().isoformat()
            )
            
        except ValueError:
            raise
        except Exception as e:
            logger.error("Failed to create user: %s", e)
            raise
    
    def get_user_by_id(self, user_id: int) -> User:
        """
        根据ID获取用户
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户对象，如果不存在则返回None
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return User(
                    id=row['id'],
                    username=row['username'],
                    email=row['email'],
                    password_hash=row['password_hash'],
                    role=row['role'],
                    status=row['status'],
                    created_at=row['created_at']
                )
            return None
            
        except Exception as e:
            logger.error("Failed to get user by ID: %s", e)
            return None
    
    def get_user_by_username(self, username: str) -> User:
        """
        根据用户名获取用户
        
        Args:
            username: 用户名
            
        Returns:
            用户对象，如果不存在则返回None
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return User(
                    id=row['id'],
                    username=row['username'],
                    email=row['email'],
                    password_hash=row['password_hash'],
                    role=row['role'],
                    status=row['status'],
                    created_at=row['created_at']
                )
            return None
            
        except Exception as e:
            logger.error("Failed to get user by username: %s", e)
            return None
    
    def get_user_by_email(self, email: str) -> User:
        """
        根据邮箱获取用户
        
        Args:
            email: 邮箱
            
        Returns:
            用户对象，如果不存在则返回None
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return User(
                    id=row['id'],
                    username=row['username'],
                    email=row['email'],
                    password_hash=row['password_hash'],
                    role=row['role'],
                    status=row['status'],
                    created_at=row['created_at']
                )
            return None
            
        except Exception as e:
            logger.error("Failed to get user by email: %s", e)
            return None
    
    def list_users(self, limit: int = 100, offset: int = 0, 
                   role: str = None, status: str = None) -> list:
        """
        列出用户
        
        Args:
            limit: 返回数量限制
            offset: 偏移量
            role: 角色过滤
            status: 状态过滤
            
        Returns:
            用户列表
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            query = "SELECT * FROM users"
            params = []
            
            conditions = []
            if role:
                conditions.append("role = ?")
                params.append(role)
            if status:
                conditions.append("status = ?")
                params.append(status)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            users = []
            for row in rows:
                users.append(User(
                    id=row['id'],
                    username=row['username'],
                    email=row['email'],
                    password_hash=row['password_hash'],
                    role=row['role'],
                    status=row['status'],
                    created_at=row['created_at']
                ))
            
            return users
            
        except Exception as e:
            logger.error("Failed to list users: %s", e)
            return []
    
    def count_users(self, role: str = None, status: str = None) -> int:
        """
        统计用户数量
        
        Args:
            role: 角色过滤
            status: 状态过滤
            
        Returns:
            用户数量
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            query = "SELECT COUNT(*) as count FROM users"
            params = []
            
            conditions = []
            if role:
                conditions.append("role = ?")
                params.append(role)
            if status:
                conditions.append("status = ?")
                params.append(status)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            cursor.execute(query, params)
            result = cursor.fetchone()
            conn.close()
            
            return result['count'] if result else 0
            
        except Exception as e:
            logger.error("Failed to count users: %s", e)
            return 0
    
    def update_user(self, user_id: int, **kwargs) -> bool:
        """
        更新用户信息
        
        Args:
            user_id: 用户ID
            **kwargs: 要更新的字段
            
        Returns:
            更新是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # 检查用户是否存在
            cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
            if not cursor.fetchone():
                conn.close()
                return False
            
            # 构建更新语句
            allowed_fields = ['username', 'email', 'password_hash', 'role', 'status']
            update_fields = []
            params = []
            
            for field, value in kwargs.items():
                if field in allowed_fields:
                    update_fields.append(f"{field} = ?")
                    params.append(value)
            
            if not update_fields:
                conn.close()
                return False
            
            # 添加更新时间
            update_fields.append("updated_at = ?")
            params.append(datetime.datetime.now().isoformat())
            
            # 添加用户ID
            params.append(user_id)
            
            query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, params)
            
            conn.commit()
            conn.close()
            
            logger.info("Updated user %d: %s", user_id, kwargs)
            return True
            
        except Exception as e:
            logger.error("Failed to update user: %s", e)
            return False
    
    def delete_user(self, user_id: int) -> bool:
        """
        删除用户
        
        Args:
            user_id: 用户ID
            
        Returns:
            删除是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            # 检查用户是否存在
            cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
            if not cursor.fetchone():
                conn.close()
                return False
            
            # 删除用户的登录日志
            cursor.execute("DELETE FROM login_logs WHERE user_id = ?", (user_id,))
            
            # 删除用户
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            
            conn.commit()
            conn.close()
            
            logger.info("Deleted user %d", user_id)
            return True
            
        except Exception as e:
            logger.error("Failed to delete user: %s", e)
            return False
    
    def increment_login_count(self, user_id: int) -> bool:
        """
        增加用户登录次数
        
        Args:
            user_id: 用户ID
            
        Returns:
            操作是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE users 
                SET login_count = login_count + 1,
                    last_login = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (user_id,))
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            logger.error("Failed to increment login count: %s", e)
            return False
    
    def increment_failed_attempts(self, user_id: int) -> bool:
        """
        增加用户失败尝试次数
        
        Args:
            user_id: 用户ID
            
        Returns:
            操作是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE users 
                SET failed_attempts = failed_attempts + 1
                WHERE id = ?
            """, (user_id,))
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            logger.error("Failed to increment failed attempts: %s", e)
            return False
    
    def log_login(self, user_id: int, ip_address: str = None, 
                  user_agent: str = None, success: bool = True) -> bool:
        """
        记录用户登录日志
        
        Args:
            user_id: 用户ID
            ip_address: IP地址
            user_agent: 用户代理
            success: 是否成功
            
        Returns:
            操作是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO login_logs (user_id, ip_address, user_agent, success)
                VALUES (?, ?, ?, ?)
            """, (user_id, ip_address, user_agent, 1 if success else 0))
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            logger.error("Failed to log login: %s", e)
            return False
    
    def get_login_logs(self, user_id: int, limit: int = 50) -> list:
        """
        获取用户登录日志
        
        Args:
            user_id: 用户ID
            limit: 返回数量限制
            
        Returns:
            登录日志列表
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM login_logs 
                WHERE user_id = ? 
                ORDER BY login_time DESC 
                LIMIT ?
            """, (user_id, limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            logs = []
            for row in rows:
                logs.append({
                    'id': row['id'],
                    'user_id': row['user_id'],
                    'login_time': row['login_time'],
                    'ip_address': row['ip_address'],
                    'user_agent': row['user_agent'],
                    'success': bool(row['success'])
                })
            
            return logs
            
        except Exception as e:
            logger.error("Failed to get login logs: %s", e)
            return []
