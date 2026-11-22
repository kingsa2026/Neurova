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
from neurova.core.logger import get_logger
import os
import sqlite3
from typing import Any, Dict, Optional
from neurova.core.data_root import callerPath
from neurova.core.db_migration import apply_domain_steps, register_migration

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# users.db schema 版本域（core/db_migration.py 注册表）。
# users 表的列演进从"散落 ALTER"收口到注册表：auth_oidc（S7 SSO）与 auth_2fa
# （S8 两步验证）各自成域登记，由 _init_db 经 apply_domain_steps 幂等应用
# （两域共享 users.db 的 user_version，故不走 migrate() 的版本记账，见该助手注释）。
# ---------------------------------------------------------------------------

#: S7：OIDC subject 列 + 索引（按 sub 找人是 SSO 供应规则的第一优先级）。
USERS_OIDC_DOMAIN = "auth_oidc"


def _migrateUsersOidcColumn(conn: sqlite3.Connection) -> None:
    """v1（S7）：users 补 oidc_sub TEXT 列 + idx_users_oidc_sub 索引（幂等）。"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "oidc_sub" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN oidc_sub TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_oidc_sub ON users(oidc_sub)"
    )


register_migration(1, _migrateUsersOidcColumn, domain=USERS_OIDC_DOMAIN)


#: S8：TOTP 两步验证三列（secret 暂存、启用位、恢复码哈希 JSON）
USERS_2FA_DOMAIN = "auth_2fa"


def _migrateUsersTwoFactorColumns(conn: sqlite3.Connection) -> None:
    """v1（S8）：users 补 totp_secret / two_factor_enabled / recovery_codes_hash（幂等）。"""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "totp_secret" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
    if "two_factor_enabled" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN two_factor_enabled INTEGER DEFAULT 0")
    if "recovery_codes_hash" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN recovery_codes_hash TEXT")


register_migration(1, _migrateUsersTwoFactorColumns, domain=USERS_2FA_DOMAIN)


class User:
    """User data model - represents a user record"""

    def __init__(
        self,
        id: int = 0,
        username: str = "",
        email: str = "",
        password_hash: str = "",
        role: str = "user",
        status: str = "active",
        created_at: str = "",
        login_count: int = 0,
        failed_attempts: int = 0,
        last_login: str = "",
        locked_until: str = "",
        updated_at: str = "",
        reset_token: str = "",
        oidc_sub: str = "",
        totp_secret: str = "",
        two_factor_enabled: int = 0,
        recovery_codes_hash: str = "",
    ):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.status = status
        self.created_at = created_at
        self.login_count = login_count
        self.failed_attempts = failed_attempts
        # 空串归一 None（NULL=未发生，时间戳语义才成立）
        self.last_login = last_login or None
        self.locked_until = locked_until or None
        self.updated_at = updated_at
        self.reset_token = reset_token or None
        # OIDC subject（S7）：IdP 侧唯一身份键；本地账号与 IdP 身份的绑定锚点
        self.oidc_sub = oidc_sub or None
        # TOTP 2FA（S8）：secret（暂存/启用后同一列）、启用位、恢复码哈希（JSON 数组）
        self.totp_secret = totp_secret or None
        self.two_factor_enabled = bool(two_factor_enabled)
        self.recovery_codes_hash = recovery_codes_hash or None


class UserModel:
    """
    用户数据库模型管理器
    管理用户数据的增删改查操作
    """

    def __init__(self, db_path: str = ""):
        """
        初始化用户模型管理器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = str(callerPath(db_path, "users.db"))
        self._ensure_db_dir()
        self._init_db()
        logger.info("UserModel initialized with db_path=%s", db_path)

    def _ensure_db_dir(self) -> None:
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.debug("Created database directory: %s", db_dir)

    def _get_conn(self):
        """借出池化短连接句柄（P1-4 / ADR 0014）。

        返回 `PooledConnection` 委托句柄：`conn.close()` 被重定向为"归还池"
        （不是真关闭）。这样本文件散落的 19 处 close 与数十个早退/异常分支
        全部自动变成正确归还 —— 池化只改这一行，不改各方法的控制流。
        """
        from neurova.core.pooled_connection import PooledConnection

        return PooledConnection(self.db_path)

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
                    last_login TEXT,
                    locked_until TEXT
                )
            """)

            # 创建登录日志表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS login_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    login_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    ip_address TEXT,
                    user_agent TEXT,
                    success INTEGER DEFAULT 1,
                    message TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            # 存量库幂等列迁移（新建表已含列，旧库补齐）
            existing = {r[1] for r in cursor.execute("PRAGMA table_info(users)").fetchall()}
            if "locked_until" not in existing:
                cursor.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
            existing_logs = {r[1] for r in cursor.execute("PRAGMA table_info(login_logs)").fetchall()}
            if "message" not in existing_logs:
                cursor.execute("ALTER TABLE login_logs ADD COLUMN message TEXT")
            if "username" not in existing_logs:
                cursor.execute("ALTER TABLE login_logs ADD COLUMN username TEXT")
            if "reset_token" not in existing:
                cursor.execute("ALTER TABLE users ADD COLUMN reset_token TEXT")

            # 注册表迁移幂等应用（auth_oidc：oidc_sub；auth_2fa：TOTP 三列。
            # 两域共享 users.db 的 user_version，故经 apply_domain_steps 幂等应用）
            apply_domain_steps(conn, USERS_OIDC_DOMAIN)
            apply_domain_steps(conn, USERS_2FA_DOMAIN)

            conn.commit()
            conn.close()
            logger.debug("Database tables initialized")

        except Exception as e:
            logger.error("Failed to initialize database: %s", e)
            raise

    def create_user(
        self, username: str, password_hash: str, email: str = None, role: str = "user", status: str = "active",
        oidc_sub: str = None,
    ) -> User:
        """
        创建新用户

        Args:
            username: 用户名（唯一）
            password_hash: 密码哈希
            email: 邮箱（可选）
            role: 角色（默认user）
            status: 状态（默认active）
            oidc_sub: OIDC subject（S7 SSO 供应用户时写入；本地注册留空）

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

            # 检查邮箱是否已存在（同 fail-fast 契约）
            if email:
                cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
                if cursor.fetchone():
                    conn.close()
                    raise ValueError(f"Email '{email}' already exists")

            # 插入新用户
            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash, role, status, oidc_sub)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (username, email, password_hash, role, status, oidc_sub),
            )

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
                created_at=datetime.datetime.now().isoformat(),
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
                    id=row["id"],
                    username=row["username"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    role=row["role"],
                    status=row["status"],
                    created_at=row["created_at"],
                    login_count=row["login_count"] if "login_count" in row.keys() else 0,
                    failed_attempts=row["failed_attempts"] if "failed_attempts" in row.keys() else 0,
                    last_login=row["last_login"] if "last_login" in row.keys() else "",
                    locked_until=row["locked_until"] if "locked_until" in row.keys() else "",
                    updated_at=row["updated_at"] if "updated_at" in row.keys() else "",
                    reset_token=row["reset_token"] if "reset_token" in row.keys() else "",
                    oidc_sub=row["oidc_sub"] if "oidc_sub" in row.keys() else "",
                    totp_secret=row["totp_secret"] if "totp_secret" in row.keys() else "",
                    two_factor_enabled=(row["two_factor_enabled"] or 0) if "two_factor_enabled" in row.keys() else 0,
                    recovery_codes_hash=row["recovery_codes_hash"] if "recovery_codes_hash" in row.keys() else "",
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
                    id=row["id"],
                    username=row["username"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    role=row["role"],
                    status=row["status"],
                    created_at=row["created_at"],
                    login_count=row["login_count"] if "login_count" in row.keys() else 0,
                    failed_attempts=row["failed_attempts"] if "failed_attempts" in row.keys() else 0,
                    last_login=row["last_login"] if "last_login" in row.keys() else "",
                    locked_until=row["locked_until"] if "locked_until" in row.keys() else "",
                    updated_at=row["updated_at"] if "updated_at" in row.keys() else "",
                    reset_token=row["reset_token"] if "reset_token" in row.keys() else "",
                    oidc_sub=row["oidc_sub"] if "oidc_sub" in row.keys() else "",
                    totp_secret=row["totp_secret"] if "totp_secret" in row.keys() else "",
                    two_factor_enabled=(row["two_factor_enabled"] or 0) if "two_factor_enabled" in row.keys() else 0,
                    recovery_codes_hash=row["recovery_codes_hash"] if "recovery_codes_hash" in row.keys() else "",
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
                    id=row["id"],
                    username=row["username"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    role=row["role"],
                    status=row["status"],
                    created_at=row["created_at"],
                    login_count=row["login_count"] if "login_count" in row.keys() else 0,
                    failed_attempts=row["failed_attempts"] if "failed_attempts" in row.keys() else 0,
                    last_login=row["last_login"] if "last_login" in row.keys() else "",
                    locked_until=row["locked_until"] if "locked_until" in row.keys() else "",
                    updated_at=row["updated_at"] if "updated_at" in row.keys() else "",
                    reset_token=row["reset_token"] if "reset_token" in row.keys() else "",
                    oidc_sub=row["oidc_sub"] if "oidc_sub" in row.keys() else "",
                    totp_secret=row["totp_secret"] if "totp_secret" in row.keys() else "",
                    two_factor_enabled=(row["two_factor_enabled"] or 0) if "two_factor_enabled" in row.keys() else 0,
                    recovery_codes_hash=row["recovery_codes_hash"] if "recovery_codes_hash" in row.keys() else "",
                )
            return None

        except Exception as e:
            logger.error("Failed to get user by email: %s", e)
            return None

    def get_user_by_oidc_sub(self, oidc_sub: str) -> Optional[User]:
        """
        根据 OIDC subject 获取用户（S7 SSO 供应规则第一优先级）

        Args:
            oidc_sub: IdP 侧唯一身份键

        Returns:
            用户对象，如果不存在则返回None
        """
        if not oidc_sub:
            return None
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM users WHERE oidc_sub = ?", (oidc_sub,))
            row = cursor.fetchone()
            conn.close()

            if row:
                return User(
                    id=row["id"],
                    username=row["username"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    role=row["role"],
                    status=row["status"],
                    created_at=row["created_at"],
                    login_count=row["login_count"] if "login_count" in row.keys() else 0,
                    failed_attempts=row["failed_attempts"] if "failed_attempts" in row.keys() else 0,
                    last_login=row["last_login"] if "last_login" in row.keys() else "",
                    locked_until=row["locked_until"] if "locked_until" in row.keys() else "",
                    updated_at=row["updated_at"] if "updated_at" in row.keys() else "",
                    reset_token=row["reset_token"] if "reset_token" in row.keys() else "",
                    oidc_sub=row["oidc_sub"] if "oidc_sub" in row.keys() else "",
                    totp_secret=row["totp_secret"] if "totp_secret" in row.keys() else "",
                    two_factor_enabled=(row["two_factor_enabled"] or 0) if "two_factor_enabled" in row.keys() else 0,
                    recovery_codes_hash=row["recovery_codes_hash"] if "recovery_codes_hash" in row.keys() else "",
                )
            return None

        except Exception as e:
            logger.error("Failed to get user by oidc_sub: %s", e)
            return None

    def list_users(self, limit: int = 100, offset: int = 0, role: str = None, status: str = None) -> list:
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
                users.append(
                    User(
                        id=row["id"],
                        username=row["username"],
                        email=row["email"],
                        password_hash=row["password_hash"],
                        role=row["role"],
                        status=row["status"],
                        created_at=row["created_at"],
                        login_count=row["login_count"] if "login_count" in row.keys() else 0,
                        failed_attempts=row["failed_attempts"] if "failed_attempts" in row.keys() else 0,
                        last_login=row["last_login"] if "last_login" in row.keys() else "",
                        locked_until=row["locked_until"] if "locked_until" in row.keys() else "",
                        updated_at=row["updated_at"] if "updated_at" in row.keys() else "",
                        reset_token=row["reset_token"] if "reset_token" in row.keys() else "",
                    )
                )

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

            return result["count"] if result else 0

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

            # 构建更新语句（oidc_sub：S7 SSO 绑定；totp_*：S8 两步验证状态）
            allowed_fields = [
                "username", "email", "password_hash", "role", "status",
                "oidc_sub", "totp_secret", "two_factor_enabled", "recovery_codes_hash",
            ]
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

            # 审计 §3.5-6：kwargs 可含 password_hash 等敏感字段，日志只记**字段名**，
            # 不落字段值。
            logger.info("Updated user %d: fields=%s", user_id, sorted(kwargs.keys()))
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

            cursor.execute(
                """
                UPDATE users 
                SET login_count = login_count + 1,
                    last_login = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (user_id,),
            )

            conn.commit()
            conn.close()

            return True

        except Exception as e:
            logger.error("Failed to increment login count: %s", e)
            return False

    def increment_failed_attempts(
        self, user_id: int, max_attempts: int = 5, lock_duration_minutes: int = 15
    ) -> bool:
        """
        增加用户失败尝试次数；达到 max_attempts 后锁定账户。

        暴力破解防护：此前实现只累加计数、无锁定分支（测试描述的安全
        设计从未落地），失败次数无限累积却永不停机。

        Args:
            user_id: 用户ID
            max_attempts: 允许的最大连续失败次数（达到即锁定）
            lock_duration_minutes: 锁定时长（分钟）

        Returns:
            操作是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE users
                SET failed_attempts = failed_attempts + 1
                WHERE id = ?
            """,
                (user_id,),
            )

            failed = cursor.execute(
                "SELECT failed_attempts FROM users WHERE id = ?", (user_id,)
            ).fetchone()[0]

            if failed >= max_attempts:
                locked_until = (
                    datetime.datetime.now()
                    + datetime.timedelta(minutes=lock_duration_minutes)
                ).isoformat()
                cursor.execute(
                    "UPDATE users SET locked_until = ? WHERE id = ?",
                    (locked_until, user_id),
                )

            conn.commit()
            conn.close()

            return True

        except Exception as e:
            logger.error("Failed to increment failed attempts: %s", e)
            return False

    def log_login(
        self,
        user_id: int,
        username: str = None,
        ip_address: str = None,
        success: bool = True,
        message: str = None,
        user_agent: str = None,
    ) -> bool:
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

            cursor.execute(
                """
                INSERT INTO login_logs (user_id, username, ip_address, user_agent, success, message)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    user_id,
                    username,
                    ip_address,
                    user_agent,
                    1 if success else 0,
                    message,
                ),
            )

            conn.commit()
            conn.close()

            return True

        except Exception as e:
            logger.error("Failed to log login: %s", e)
            return False

    def get_login_logs(self, user_id: Optional[int] = None, limit: int = 50) -> list:
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

            # user_id=None → 全量日志（审计查询语义）
            if user_id is None:
                cursor.execute(
                    """
                    SELECT * FROM login_logs
                    ORDER BY login_time DESC
                    LIMIT ?
                """,
                    (limit,),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM login_logs
                    WHERE user_id = ?
                    ORDER BY login_time DESC
                    LIMIT ?
                """,
                    (user_id, limit),
                )

            rows = cursor.fetchall()
            conn.close()

            logs = []
            for row in rows:
                logs.append(
                    {
                        "id": row["id"],
                        "user_id": row["user_id"],
                        "username": row["username"] if "username" in row.keys() else "",
                        "login_time": row["login_time"],
                        "ip_address": row["ip_address"],
                        "user_agent": row["user_agent"],
                        "success": bool(row["success"]),
                        "message": row["message"] if "message" in row.keys() else "",
                    }
                )

            return logs

        except Exception as e:
            logger.error("Failed to get login logs: %s", e)
            return []

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        认证用户

        Args:
            username: 用户名
            password: 密码（明文）

        Returns:
            用户信息字典，如果认证失败返回 None
        """
        try:
            user = self.get_user_by_username(username)
            if not user:
                return None

            # 检查用户状态
            if user.status != "active":
                return None

            # 暴力破解防护：锁定期内拒绝认证（locked_until 未过）
            if user.locked_until:
                try:
                    if datetime.datetime.fromisoformat(user.locked_until) > datetime.datetime.now():
                        logger.warning("用户 %s 处于锁定期（至 %s），拒绝认证", username, user.locked_until)
                        return None
                except ValueError:
                    logger.warning("locked_until 格式非法，忽略锁定检查: %s", user.locked_until)

            # 验证密码
            from neurova.api.auth import verify_password

            if not verify_password(password, user.password_hash):
                return None

            # 认证成功：清零失败计数并清锁定（防锁定到期后首次成功仍残留计数）
            if user.failed_attempts or user.locked_until:
                try:
                    self._clear_lock_state(user.id)
                except Exception as e:
                    logger.warning("清除锁定状态失败: %s", e)

            # 返回用户信息字典（two_factor_enabled：S8 登录链据此决定是否发挑战）
            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "status": user.status,
                "created_at": user.created_at,
                "password_hash": user.password_hash,
                "two_factor_enabled": bool(user.two_factor_enabled),
            }

        except Exception as e:
            logger.error("Failed to authenticate user: %s", e)
            return None

    def _clear_lock_state(self, user_id: int) -> None:
        """认证成功后清零失败计数与锁定时间戳。"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
                (user_id,),
            )
            conn.commit()
        finally:
            conn.close()
