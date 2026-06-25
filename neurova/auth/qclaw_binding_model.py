"""
QClaw 绑定数据模型

负责 qclaw_bindings 表的 CRUD 操作，实现多用户隔离逻辑。
每个用户（neuser_id + user_id）可以绑定一个 QClaw 应用。
"""

import base64
import datetime
import hashlib
import json
from neurova.core.logger import get_logger
import os
import sqlite3

# 可选依赖处理
try:
    import cryptography.fernet
    import cryptography.hazmat.primitives
    import cryptography.hazmat.primitives.kdf.pbkdf2

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

# 日志配置
logger = get_logger(__name__)


class QClawBinding:
    """QClaw绑定数据模型 - 表示一个绑定记录"""

    def __init__(
        self,
        id: int = 0,
        neuser_id: str = "",
        user_id: str = "",
        app_id: str = "",
        app_secret_encrypted: str = "",
        app_name: str = "",
        webhook_url: str = "",
        status: str = "active",
        created_at: str = "",
        updated_at: str = "",
        last_used_at: str = None,
        extra_config: str = "{}",
    ):
        self.id = id
        self.neuser_id = neuser_id
        self.user_id = user_id
        self.app_id = app_id
        self.app_secret_encrypted = app_secret_encrypted
        self.app_name = app_name
        self.webhook_url = webhook_url
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self.last_used_at = last_used_at
        self.extra_config = extra_config


class QClawBindingModel:
    """
    QClaw绑定数据库模型管理器
    管理QClaw绑定数据的增删改查操作
    """

    def __init__(self, db_path: str = "data/qclaw_bindings.db", encryption_key: str = None):
        """
        初始化QClaw绑定模型管理器

        Args:
            db_path: 数据库文件路径
            encryption_key: 用于加密app_secret的密钥（可选）
        """
        self.db_path = db_path
        self.encryption_key = encryption_key
        self._ensure_db_dir()
        self._init_db()
        logger.info("QClawBindingModel initialized with db_path=%s", db_path)

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

            # 创建QClaw绑定表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS qclaw_bindings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    neuser_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    app_id TEXT NOT NULL,
                    app_secret_encrypted TEXT NOT NULL,
                    app_name TEXT,
                    webhook_url TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TEXT,
                    extra_config TEXT DEFAULT '{}',
                    UNIQUE(neuser_id, user_id, app_id)
                )
            """)

            # 创建索引
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_qclaw_user 
                ON qclaw_bindings(neuser_id, user_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_qclaw_app 
                ON qclaw_bindings(app_id)
            """)

            conn.commit()
            conn.close()
            logger.debug("QClaw bindings table initialized")

        except Exception as e:
            logger.error("Failed to initialize database: %s", e)
            raise

    def create_binding(
        self,
        neuser_id: str,
        user_id: str,
        app_id: str,
        app_secret: str,
        app_name: str = None,
        webhook_url: str = None,
        extra_config: dict = None,
    ) -> QClawBinding:
        """
        创建新的QClaw绑定

        Args:
            neuser_id: Neurova用户ID
            user_id: 平台用户ID
            app_id: QClaw应用ID
            app_secret: QClaw应用密钥（将被加密存储）
            app_name: 应用名称（可选）
            webhook_url: Webhook URL（可选）
            extra_config: 额外配置（可选）

        Returns:
            创建的绑定对象

        Raises:
            ValueError: 如果绑定已存在
        """
        try:
            # 加密app_secret
            encrypted_secret = self._encrypt_secret(app_secret)

            # 序列化extra_config
            config_json = json.dumps(extra_config or {})

            conn = self._get_conn()
            cursor = conn.cursor()

            # 检查是否已存在
            cursor.execute(
                """
                SELECT id FROM qclaw_bindings 
                WHERE neuser_id = ? AND user_id = ? AND app_id = ?
            """,
                (neuser_id, user_id, app_id),
            )

            if cursor.fetchone():
                conn.close()
                raise ValueError(
                    f"Binding already exists for neuser_id={neuser_id}, user_id={user_id}, app_id={app_id}"
                )

            # 插入新绑定
            cursor.execute(
                """
                INSERT INTO qclaw_bindings 
                (neuser_id, user_id, app_id, app_secret_encrypted, app_name, webhook_url, extra_config)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (neuser_id, user_id, app_id, encrypted_secret, app_name, webhook_url, config_json),
            )

            binding_id = cursor.lastrowid
            conn.commit()
            conn.close()

            # 返回创建的绑定
            return QClawBinding(
                id=binding_id,
                neuser_id=neuser_id,
                user_id=user_id,
                app_id=app_id,
                app_secret_encrypted=encrypted_secret,
                app_name=app_name,
                webhook_url=webhook_url,
                status="active",
                created_at=datetime.datetime.now().isoformat(),
                updated_at=datetime.datetime.now().isoformat(),
                extra_config=config_json,
            )

        except ValueError:
            raise
        except Exception as e:
            logger.error("Failed to create binding: %s", e)
            raise

    def get_binding_by_id(self, binding_id: int) -> QClawBinding:
        """
        根据ID获取绑定

        Args:
            binding_id: 绑定ID

        Returns:
            绑定对象，如果不存在则返回None
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM qclaw_bindings WHERE id = ?", (binding_id,))
            row = cursor.fetchone()
            conn.close()

            if row:
                return self._row_to_binding(row)
            return None

        except Exception as e:
            logger.error("Failed to get binding by ID: %s", e)
            return None

    def get_binding_by_user(self, neuser_id: str, user_id: str) -> QClawBinding:
        """
        根据用户信息获取绑定（一个用户只能有一个绑定）

        Args:
            neuser_id: Neurova用户ID
            user_id: 平台用户ID

        Returns:
            绑定对象，如果不存在则返回None
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM qclaw_bindings 
                WHERE neuser_id = ? AND user_id = ? AND status = 'active'
                ORDER BY created_at DESC LIMIT 1
            """,
                (neuser_id, user_id),
            )

            row = cursor.fetchone()
            conn.close()

            if row:
                return self._row_to_binding(row)
            return None

        except Exception as e:
            logger.error("Failed to get binding by user: %s", e)
            return None

    def get_binding_by_app_id(self, app_id: str) -> QClawBinding:
        """
        根据应用ID获取绑定

        Args:
            app_id: QClaw应用ID

        Returns:
            绑定对象，如果不存在则返回None
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM qclaw_bindings 
                WHERE app_id = ? AND status = 'active'
                LIMIT 1
            """,
                (app_id,),
            )

            row = cursor.fetchone()
            conn.close()

            if row:
                return self._row_to_binding(row)
            return None

        except Exception as e:
            logger.error("Failed to get binding by app_id: %s", e)
            return None

    def update_binding(self, binding_id: int, **kwargs) -> bool:
        """
        更新绑定信息

        Args:
            binding_id: 绑定ID
            **kwargs: 要更新的字段

        Returns:
            更新是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # 检查绑定是否存在
            cursor.execute("SELECT id FROM qclaw_bindings WHERE id = ?", (binding_id,))
            if not cursor.fetchone():
                conn.close()
                return False

            # 构建更新语句
            allowed_fields = ["app_name", "webhook_url", "status", "extra_config"]
            update_fields = []
            params = []

            for field, value in kwargs.items():
                if field in allowed_fields:
                    if field == "extra_config" and isinstance(value, dict):
                        value = json.dumps(value)
                    update_fields.append(f"{field} = ?")
                    params.append(value)

            if not update_fields:
                conn.close()
                return False

            # 添加更新时间
            update_fields.append("updated_at = ?")
            params.append(datetime.datetime.now().isoformat())

            # 添加绑定ID
            params.append(binding_id)

            query = f"UPDATE qclaw_bindings SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, params)

            conn.commit()
            conn.close()

            logger.info("Updated binding %d: %s", binding_id, kwargs)
            return True

        except Exception as e:
            logger.error("Failed to update binding: %s", e)
            return False

    def delete_binding(self, binding_id: int) -> bool:
        """
        删除绑定（软删除，设置状态为deleted）

        Args:
            binding_id: 绑定ID

        Returns:
            删除是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # 检查绑定是否存在
            cursor.execute("SELECT id FROM qclaw_bindings WHERE id = ?", (binding_id,))
            if not cursor.fetchone():
                conn.close()
                return False

            # 软删除
            cursor.execute(
                """
                UPDATE qclaw_bindings 
                SET status = 'deleted', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (binding_id,),
            )

            conn.commit()
            conn.close()

            logger.info("Deleted binding %d", binding_id)
            return True

        except Exception as e:
            logger.error("Failed to delete binding: %s", e)
            return False

    def update_last_used(self, binding_id: int) -> bool:
        """
        更新最后使用时间

        Args:
            binding_id: 绑定ID

        Returns:
            更新是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE qclaw_bindings 
                SET last_used_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (binding_id,),
            )

            conn.commit()
            conn.close()

            return True

        except Exception as e:
            logger.error("Failed to update last used: %s", e)
            return False

    def list_user_bindings(self, neuser_id: str, user_id: str = None, status: str = "active", limit: int = 100) -> list:
        """
        列出用户的绑定

        Args:
            neuser_id: Neurova用户ID
            user_id: 平台用户ID（可选）
            status: 状态过滤（可选）
            limit: 返回数量限制

        Returns:
            绑定列表
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            query = "SELECT * FROM qclaw_bindings WHERE neuser_id = ?"
            params = [neuser_id]

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)

            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()

            bindings = []
            for row in rows:
                bindings.append(self._row_to_binding(row))

            return bindings

        except Exception as e:
            logger.error("Failed to list user bindings: %s", e)
            return []

    def _encrypt_secret(self, secret: str) -> str:
        """
        加密app_secret

        Args:
            secret: 原始密钥

        Returns:
            加密后的密钥（Base64编码）
        """
        if not HAS_CRYPTOGRAPHY or not self.encryption_key:
            # 如果没有cryptography库或没有提供密钥，使用简单的Base64编码
            # 注意：这不是安全的加密，只是编码
            logger.warning(
                "Using Base64 encoding instead of encryption (cryptography not available or no key provided)"
            )
            return base64.b64encode(secret.encode()).decode()

        try:
            # 使用Fernet加密
            key = base64.urlsafe_b64encode(hashlib.sha256(self.encryption_key.encode()).digest())
            f = cryptography.fernet.Fernet(key)
            encrypted = f.encrypt(secret.encode())
            return encrypted.decode()

        except Exception as e:
            logger.error("Failed to encrypt secret: %s", e)
            # 回退到Base64编码
            return base64.b64encode(secret.encode()).decode()

    def _decrypt_secret(self, encrypted_secret: str) -> str:
        """
        解密app_secret

        Args:
            encrypted_secret: 加密后的密钥（Base64编码）

        Returns:
            原始密钥
        """
        if not HAS_CRYPTOGRAPHY or not self.encryption_key:
            # 如果没有cryptography库或没有提供密钥，尝试Base64解码
            try:
                return base64.b64decode(encrypted_secret.encode()).decode()
            except Exception:
                # 如果解码失败，可能已经是明文
                return encrypted_secret

        try:
            # 使用Fernet解密
            key = base64.urlsafe_b64encode(hashlib.sha256(self.encryption_key.encode()).digest())
            f = cryptography.fernet.Fernet(key)
            decrypted = f.decrypt(encrypted_secret.encode())
            return decrypted.decode()

        except Exception as e:
            logger.warning("Failed to decrypt secret, trying Base64 decode: %s", e)
            # 尝试Base64解码
            try:
                return base64.b64decode(encrypted_secret.encode()).decode()
            except Exception:
                # 如果解码失败，可能已经是明文
                return encrypted_secret

    def _row_to_binding(self, row: sqlite3.Row) -> QClawBinding:
        """
        将数据库行转换为绑定对象

        Args:
            row: 数据库行

        Returns:
            绑定对象
        """
        return QClawBinding(
            id=row["id"],
            neuser_id=row["neuser_id"],
            user_id=row["user_id"],
            app_id=row["app_id"],
            app_secret_encrypted=row["app_secret_encrypted"],
            app_name=row["app_name"],
            webhook_url=row["webhook_url"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row["last_used_at"],
            extra_config=row["extra_config"],
        )

    def close(self) -> None:
        """关闭数据库连接（如果需要）"""
        # SQLite连接是临时的，不需要显式关闭
