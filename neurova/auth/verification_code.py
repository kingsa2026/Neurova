from __future__ import annotations

"""
Neurova 验证码模型

用于管理注册验证码、找回密码验证码等
支持:
- 验证码生成与存储
- 验证码有效期管理
- 验证码尝试次数限制
- 注册限流
"""

import hashlib
import logging
import os
import secrets
import sqlite3
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VerificationType(Enum):
    """验证码类型"""

    REGISTER = "register"  # 注册验证码
    RESET_PASSWORD = "reset_password"  # 重置密码验证码
    LOGIN = "login"  # 登录验证码
    CHANGE_EMAIL = "change_email"  # 更改邮箱验证码
    TWO_FACTOR = "two_factor"  # 两步验证


@dataclass
class VerificationCode:
    """验证码数据模型"""

    code_hash: str  # 哈希后的验证码
    code_type: VerificationType
    target: str  # 目标（邮箱、手机号等）
    created_at: float
    expires_at: float
    attempts: int = 0
    max_attempts: int = 3
    is_used: bool = False
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["code_type"] = self.code_type.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationCode":
        """从字典创建"""
        data = data.copy()
        data["code_type"] = VerificationType(data["code_type"])
        return cls(**data)

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        return time.time() > self.expires_at

    @property
    def is_used_up(self) -> bool:
        """是否已用完尝试次数"""
        return self.attempts >= self.max_attempts

    @property
    def is_valid(self) -> bool:
        """是否有效"""
        return not self.is_expired and not self.is_used and not self.is_used_up


class VerificationCodeModel:
    """
    验证码管理模型
    负责验证码的生成、验证、限流和管理
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化验证码管理器

        Args:
            db_path: 数据库文件路径
        """
        if db_path is None:
            # 默认数据库路径
            db_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "verification_codes.db")

        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db_dir()
        self._init_db()

        logger.info("VerificationCodeModel initialized with db_path=%s", db_path)

    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        cursor = conn.cursor()

        # 创建验证码表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_hash TEXT NOT NULL,
                code_type TEXT NOT NULL,
                target TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                is_used BOOLEAN NOT NULL DEFAULT 0,
                metadata TEXT,
                UNIQUE(target, code_type)
            )
        """)

        # 创建注册限流表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS register_rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                attempted_at REAL NOT NULL,
                success BOOLEAN NOT NULL DEFAULT 0
            )
        """)

        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_verification_codes_target_type 
            ON verification_codes (target, code_type)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_verification_codes_expires_at 
            ON verification_codes (expires_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_register_rate_limits_ip 
            ON register_rate_limits (ip_address)
        """)

        conn.commit()
        logger.info("Database initialized successfully")

    def _hash_code(self, code: str) -> str:
        """
        哈希验证码

        Args:
            code: 原始验证码

        Returns:
            哈希后的验证码
        """
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def _generate_code(self, length: int = 6) -> str:
        """
        生成随机验证码

        Args:
            length: 验证码长度

        Returns:
            随机验证码
        """
        # 生成纯数字验证码
        code = "".join(secrets.choice("0123456789") for _ in range(length))
        return code

    def create_code(
        self,
        target: str,
        code_type: VerificationType,
        expires_in: int = 300,  # 5分钟
        max_attempts: int = 3,
        length: int = 6,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        创建验证码

        Args:
            target: 目标（邮箱、手机号等）
            code_type: 验证码类型
            expires_in: 过期时间（秒）
            max_attempts: 最大尝试次数
            length: 验证码长度
            metadata: 元数据

        Returns:
            原始验证码（需要发送给用户）
        """
        try:
            # 删除旧的验证码
            self._delete_old_codes(target, code_type)

            # 生成验证码
            code = self._generate_code(length)
            code_hash = self._hash_code(code)

            # 计算过期时间
            created_at = time.time()
            expires_at = created_at + expires_in

            # 创建验证码对象
            verification_code = VerificationCode(
                code_hash=code_hash,
                code_type=code_type,
                target=target,
                created_at=created_at,
                expires_at=expires_at,
                attempts=0,
                max_attempts=max_attempts,
                is_used=False,
                metadata=metadata,
            )

            # 保存到数据库
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO verification_codes 
                (code_hash, code_type, target, created_at, expires_at, attempts, max_attempts, is_used, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    verification_code.code_hash,
                    verification_code.code_type.value,
                    verification_code.target,
                    verification_code.created_at,
                    verification_code.expires_at,
                    verification_code.attempts,
                    verification_code.max_attempts,
                    verification_code.is_used,
                    str(verification_code.metadata) if verification_code.metadata else None,
                ),
            )

            conn.commit()

            logger.info("Created verification code for %s (type=%s)", target, code_type.value)
            return code

        except Exception as e:
            logger.error("Failed to create verification code: %s", e)
            raise

    def verify_code(self, target: str, code: str, code_type: VerificationType, mark_as_used: bool = True) -> bool:
        """
        验证验证码

        Args:
            target: 目标（邮箱、手机号等）
            code: 验证码
            code_type: 验证码类型
            mark_as_used: 是否标记为已使用

        Returns:
            验证码是否有效
        """
        try:
            # 获取验证码
            verification_code = self.get_code_info(target, code_type)
            if verification_code is None:
                logger.warning("Verification code not found for %s (type=%s)", target, code_type.value)
                return False

            # 检查是否有效
            if not verification_code.is_valid:
                logger.warning(
                    "Verification code is not valid for %s (expired=%s, used=%s, used_up=%s)",
                    target,
                    verification_code.is_expired,
                    verification_code.is_used,
                    verification_code.is_used_up,
                )
                return False

            # 验证验证码
            code_hash = self._hash_code(code)
            if code_hash != verification_code.code_hash:
                # 增加尝试次数
                self._increment_attempts(target, code_type)
                logger.warning("Invalid verification code for %s", target)
                return False

            # 标记为已使用
            if mark_as_used:
                self._mark_as_used(target, code_type)

            logger.info("Verified code for %s (type=%s)", target, code_type.value)
            return True

        except Exception as e:
            logger.error("Failed to verify code: %s", e)
            return False

    def _delete_old_codes(self, target: str, code_type: VerificationType):
        """
        删除旧的验证码

        Args:
            target: 目标
            code_type: 验证码类型
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM verification_codes 
            WHERE target = ? AND code_type = ?
        """,
            (target, code_type.value),
        )

        conn.commit()

    def cleanup_expired_codes(self) -> int:
        """
        清理过期的验证码

        Returns:
            清理的数量
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                DELETE FROM verification_codes 
                WHERE expires_at < ?
            """,
                (time.time(),),
            )

            cleaned = cursor.rowcount
            conn.commit()

            if cleaned > 0:
                logger.info("Cleaned up %d expired verification codes", cleaned)

            return cleaned

        except Exception as e:
            logger.error("Failed to cleanup expired codes: %s", e)
            return 0

    def get_code_info(self, target: str, code_type: VerificationType) -> Optional[VerificationCode]:
        """
        获取验证码信息

        Args:
            target: 目标
            code_type: 验证码类型

        Returns:
            验证码信息，如果不存在则返回None
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM verification_codes 
                WHERE target = ? AND code_type = ?
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (target, code_type.value),
            )

            row = cursor.fetchone()
            if row is None:
                return None

            # 转换为验证码对象
            metadata = None
            if row["metadata"]:
                try:
                    import ast

                    metadata = ast.literal_eval(row["metadata"])
                except:
                    metadata = None

            return VerificationCode(
                code_hash=row["code_hash"],
                code_type=VerificationType(row["code_type"]),
                target=row["target"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                attempts=row["attempts"],
                max_attempts=row["max_attempts"],
                is_used=bool(row["is_used"]),
                metadata=metadata,
            )

        except Exception as e:
            logger.error("Failed to get code info: %s", e)
            return None

    def get_attempts(self, target: str, code_type: VerificationType) -> int:
        """
        获取验证码尝试次数

        Args:
            target: 目标
            code_type: 验证码类型

        Returns:
            尝试次数
        """
        verification_code = self.get_code_info(target, code_type)
        if verification_code is None:
            return 0
        return verification_code.attempts

    def check_register_rate_limit(self, ip_address: str) -> Dict[str, Any]:
        """
        检查注册限流

        Args:
            ip_address: IP地址

        Returns:
            限流信息
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # 获取最近1小时的尝试次数
            one_hour_ago = time.time() - 3600
            cursor.execute(
                """
                SELECT COUNT(*) FROM register_rate_limits 
                WHERE ip_address = ? AND attempted_at > ?
            """,
                (ip_address, one_hour_ago),
            )

            attempts = cursor.fetchone()[0]

            # 获取最近成功的尝试
            cursor.execute(
                """
                SELECT COUNT(*) FROM register_rate_limits 
                WHERE ip_address = ? AND attempted_at > ? AND success = 1
            """,
                (ip_address, one_hour_ago),
            )

            successful = cursor.fetchone()[0]

            # 限流规则
            max_attempts = 10  # 每小时最多10次尝试
            max_successful = 3  # 每小时最多3次成功

            return {
                "ip_address": ip_address,
                "attempts": attempts,
                "successful": successful,
                "max_attempts": max_attempts,
                "max_successful": max_successful,
                "is_limited": attempts >= max_attempts or successful >= max_successful,
                "remaining_attempts": max(0, max_attempts - attempts),
                "remaining_successful": max(0, max_successful - successful),
            }

        except Exception as e:
            logger.error("Failed to check register rate limit: %s", e)
            return {
                "ip_address": ip_address,
                "attempts": 0,
                "successful": 0,
                "max_attempts": 10,
                "max_successful": 3,
                "is_limited": False,
                "remaining_attempts": 10,
                "remaining_successful": 3,
            }

    def record_register_attempt(self, ip_address: str, success: bool = False):
        """
        记录注册尝试

        Args:
            ip_address: IP地址
            success: 是否成功
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO register_rate_limits 
                (ip_address, attempted_at, success)
                VALUES (?, ?, ?)
            """,
                (ip_address, time.time(), success),
            )

            conn.commit()

            logger.info("Recorded register attempt from %s (success=%s)", ip_address, success)

        except Exception as e:
            logger.error("Failed to record register attempt: %s", e)

    def can_send_code(self, target: str, code_type: VerificationType, cooldown: int = 60) -> Dict[str, Any]:
        """
        检查是否可以发送验证码

        Args:
            target: 目标
            code_type: 验证码类型
            cooldown: 冷却时间（秒）

        Returns:
            发送状态信息
        """
        try:
            # 检查是否有未过期的验证码
            verification_code = self.get_code_info(target, code_type)

            if verification_code is not None:
                # 检查是否在冷却期内
                time_since_creation = time.time() - verification_code.created_at
                if time_since_creation < cooldown:
                    return {
                        "can_send": False,
                        "reason": "cooldown",
                        "cooldown_remaining": cooldown - time_since_creation,
                        "message": f"请等待 {int(cooldown - time_since_creation)} 秒后再试",
                    }

            return {"can_send": True, "reason": "ok", "cooldown_remaining": 0, "message": "可以发送验证码"}

        except Exception as e:
            logger.error("Failed to check if can send code: %s", e)
            return {"can_send": True, "reason": "ok", "cooldown_remaining": 0, "message": "可以发送验证码"}

    def _increment_attempts(self, target: str, code_type: VerificationType):
        """
        增加尝试次数

        Args:
            target: 目标
            code_type: 验证码类型
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE verification_codes 
            SET attempts = attempts + 1
            WHERE target = ? AND code_type = ?
        """,
            (target, code_type.value),
        )

        conn.commit()

    def _mark_as_used(self, target: str, code_type: VerificationType):
        """
        标记为已使用

        Args:
            target: 目标
            code_type: 验证码类型
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE verification_codes 
            SET is_used = 1
            WHERE target = ? AND code_type = ?
        """,
            (target, code_type.value),
        )

        conn.commit()

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取验证码统计信息

        Returns:
            统计信息字典
        """
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # 总验证码数
            cursor.execute("SELECT COUNT(*) FROM verification_codes")
            total_codes = cursor.fetchone()[0]

            # 未使用验证码数
            cursor.execute("SELECT COUNT(*) FROM verification_codes WHERE is_used = 0")
            unused_codes = cursor.fetchone()[0]

            # 过期验证码数
            cursor.execute(
                """
                SELECT COUNT(*) FROM verification_codes 
                WHERE expires_at < ?
            """,
                (time.time(),),
            )
            expired_codes = cursor.fetchone()[0]

            # 按类型统计
            cursor.execute("""
                SELECT code_type, COUNT(*) 
                FROM verification_codes 
                GROUP BY code_type
            """)
            by_type = dict(cursor.fetchall())

            # 注册限流统计
            cursor.execute("SELECT COUNT(*) FROM register_rate_limits")
            total_attempts = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM register_rate_limits WHERE success = 1")
            successful_attempts = cursor.fetchone()[0]

            return {
                "total_codes": total_codes,
                "unused_codes": unused_codes,
                "expired_codes": expired_codes,
                "by_type": by_type,
                "register_attempts": {
                    "total": total_attempts,
                    "successful": successful_attempts,
                    "success_rate": successful_attempts / total_attempts if total_attempts > 0 else 0,
                },
            }

        except Exception as e:
            logger.error("Failed to get statistics: %s", e)
            return {}


# 全局实例
_verification_code_model: Optional[VerificationCodeModel] = None


def get_verification_code_model() -> VerificationCodeModel:
    """
    获取验证码管理器实例（单例模式）

    Returns:
        VerificationCodeModel实例
    """
    global _verification_code_model
    if _verification_code_model is None:
        _verification_code_model = VerificationCodeModel()
    return _verification_code_model


def reset_verification_code_model():
    """
    重置验证码管理器实例（用于测试）
    """
    global _verification_code_model
    if _verification_code_model is not None:
        # 关闭数据库连接
        if _verification_code_model._conn:
            verification_code_model._conn.close()
        _verification_code_model = None
