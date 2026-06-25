"""NEU Token Manager - 统一的神经元令牌管理器

合并了两个历史实现:
  1. neurova/auth.py (已删除, 死代码) — HMAC-SHA256签名, refresh token, 黑名单, 线程安全
  2. neurova/security/neu_token_manager.py (本文件) — API Key 管理, 简单令牌

合并后的接口提供:
  - 简单令牌: generate_token / validate_token / revoke_token
  - JWT签名令牌对: generate_tokens / refresh_tokens
  - 黑名单: revoke_token_by_jti / is_token_blacklisted
  - API Key: generate_api_key / validate_api_key / revoke_api_key / list_api_keys
  - 清理: cleanup_expired / cleanup_expired_tokens
  - 线程安全: 所有共享状态操作使用 threading.RLock

向后兼容: NEUTokenManager() 无参构造继续工作 (api/app.py 依赖)。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from neurova.core import config
from neurova.core.logger import get_logger
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


class NEUTokenManager:
    """统一的神经元令牌管理器

    管理两类令牌:
    1. 简单令牌 — secrets.token_urlsafe 生成, 存储在内存字典
    2. JWT签名令牌 — HMAC-SHA256 签名, 支持 access/refresh 双令牌

    以及 API Key 的生成、验证和撤销。
    """

    def __init__(
        self,
        secret_key: Optional[str] = None,
        token_expiry_hours: int = 24,
        access_token_ttl: int = 3600,
        refresh_token_ttl: int = 604800,
        issuer: str = "neurova",
    ):
        """初始化令牌管理器

        Args:
            secret_key: 签名密钥, None 时自动生成
            token_expiry_hours: 简单令牌过期时间 (小时)
            access_token_ttl: JWT访问令牌TTL (秒)
            refresh_token_ttl: JWT刷新令牌TTL (秒)
            issuer: 令牌签发者
        """
        self.secret_key = secret_key or config.get(
            "NEU_TOKEN_SECRET", secrets.token_hex(32)
        )
        self.token_expiry_hours = token_expiry_hours
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl
        self._issuer = issuer
        self._lock = threading.RLock()

        # 简单令牌存储
        self._tokens: Dict[str, Dict[str, Any]] = {}
        # API Key 存储
        self._api_keys: Dict[str, Dict[str, Any]] = {}

        # JWT 黑名单: token_jti -> expiry_timestamp
        self._blacklist: Dict[str, float] = {}
        # JWT 刷新令牌存储: refresh_jti -> {user_id, access_jti, created_at, expires_at}
        self._refresh_tokens: Dict[str, Dict[str, Any]] = {}

        logger.info("NEUTokenManager initialized")

    # ────── 简单令牌 (向后兼容) ──────

    def generate_token(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """生成简单访问令牌

        Args:
            user_id: 用户ID
            metadata: 令牌元数据

        Returns:
            生成的令牌字符串
        """
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=self.token_expiry_hours)

        with self._lock:
            self._tokens[token] = {
                "user_id": user_id,
                "created_at": datetime.now().isoformat(),
                "expires_at": expires_at.isoformat(),
                "metadata": metadata or {},
                "is_active": True,
            }

        logger.info("Generated token for user %s", user_id)
        return token

    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证令牌有效性 (支持简单令牌和JWT令牌)

        Args:
            token: 要验证的令牌

        Returns:
            令牌信息字典, 如果无效则返回 None
        """
        # 先尝试 JWT 令牌验证
        jwt_payload = self._verify_jwt_token(token)
        if jwt_payload is not None:
            # 检查黑名单
            jti = jwt_payload.get("jti")
            if jti and self.is_token_blacklisted(jti):
                logger.debug("JWT token %s is blacklisted", jti)
                return None
            # 检查过期时间
            exp = jwt_payload.get("exp", 0)
            if time.time() > exp:
                logger.debug("JWT token %s has expired", jti)
                return None
            return jwt_payload

        # 回退到简单令牌验证
        with self._lock:
            if token not in self._tokens:
                return None

            token_data = self._tokens[token]

            # 检查是否过期
            expires_at = datetime.fromisoformat(token_data["expires_at"])
            if datetime.now() > expires_at:
                token_data["is_active"] = False
                return None

            # 检查是否激活
            if not token_data["is_active"]:
                return None

            return token_data

    def revoke_token(self, token: str) -> bool:
        """撤销令牌 (支持简单令牌和JWT令牌)

        Args:
            token: 要撤销的令牌

        Returns:
            是否成功撤销
        """
        # 先尝试 JWT 令牌撤销
        jwt_payload = self._verify_jwt_token(token)
        if jwt_payload is not None:
            jti = jwt_payload.get("jti")
            if jti:
                return self.revoke_token_by_jti(jti, jwt_payload.get("exp", 0))
            return False

        # 回退到简单令牌撤销
        with self._lock:
            if token in self._tokens:
                self._tokens[token]["is_active"] = False
                logger.info("Revoked token: %s...", token[:8])
                return True
            return False

    # ────── JWT 签名令牌对 (从 auth.py 合并) ──────

    def generate_tokens(
        self, user_id: str, extra_claims: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str, Dict[str, Any]]:
        """生成 JWT 访问令牌和刷新令牌

        Args:
            user_id: 用户 ID
            extra_claims: 额外的声明信息

        Returns:
            (access_token, refresh_token, token_info) 元组
        """
        now = time.time()
        access_jti = str(uuid.uuid4())
        refresh_jti = str(uuid.uuid4())

        # 构建访问令牌 payload
        access_payload = {
            "sub": user_id,
            "iss": self._issuer,
            "iat": now,
            "exp": now + self._access_token_ttl,
            "jti": access_jti,
            "type": "access",
        }
        if extra_claims:
            access_payload.update(extra_claims)

        # 构建刷新令牌 payload
        refresh_payload = {
            "sub": user_id,
            "iss": self._issuer,
            "iat": now,
            "exp": now + self._refresh_token_ttl,
            "jti": refresh_jti,
            "type": "refresh",
        }

        access_token = self._sign_jwt_token(access_payload)
        refresh_token = self._sign_jwt_token(refresh_payload)

        # 存储刷新令牌映射
        with self._lock:
            self._refresh_tokens[refresh_jti] = {
                "user_id": user_id,
                "access_jti": access_jti,
                "created_at": now,
                "expires_at": now + self._refresh_token_ttl,
            }

        token_info = {
            "user_id": user_id,
            "access_jti": access_jti,
            "refresh_jti": refresh_jti,
            "access_expires_at": now + self._access_token_ttl,
            "refresh_expires_at": now + self._refresh_token_ttl,
            "token_type": "Bearer",
        }

        logger.info("Generated tokens for user %s", user_id)
        return access_token, refresh_token, token_info

    def refresh_tokens(self, refresh_token: str) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """使用刷新令牌获取新的令牌对

        Args:
            refresh_token: 刷新令牌字符串

        Returns:
            新的 (access_token, refresh_token, token_info) 元组, 失败返回 None
        """
        payload = self._verify_jwt_token(refresh_token)
        if payload is None:
            return None

        # 验证是刷新令牌
        if payload.get("type") != "refresh":
            logger.warning("Attempted to refresh with non-refresh token")
            return None

        refresh_jti = payload.get("jti")
        if not refresh_jti:
            return None

        # 检查黑名单
        if self.is_token_blacklisted(refresh_jti):
            logger.warning("Refresh token %s is blacklisted", refresh_jti)
            return None

        # 查找并移除旧的刷新令牌
        with self._lock:
            refresh_data = self._refresh_tokens.pop(refresh_jti, None)

        if refresh_data is None:
            logger.warning("Refresh token %s not found in storage", refresh_jti)
            return None

        user_id = refresh_data["user_id"]

        # 撤销旧的访问令牌
        old_access_jti = refresh_data.get("access_jti")
        if old_access_jti:
            self.revoke_token_by_jti(old_access_jti)

        # 生成新的令牌对
        logger.info("Refreshed tokens for user %s", user_id)
        return self.generate_tokens(user_id)

    def revoke_token_by_jti(self, jti: str, expires_at: float = 0) -> bool:
        """通过 JTI 撤销令牌 (加入黑名单)

        Args:
            jti: 令牌唯一标识
            expires_at: 令牌过期时间戳

        Returns:
            是否成功撤销
        """
        with self._lock:
            if jti in self._blacklist:
                return False
            self._blacklist[jti] = expires_at or (time.time() + self._refresh_token_ttl)
            logger.info("Token %s revoked", jti)
            return True

    def is_token_blacklisted(self, jti: str) -> bool:
        """检查令牌是否在黑名单中

        Args:
            jti: 令牌唯一标识

        Returns:
            是否在黑名单中
        """
        with self._lock:
            expiry = self._blacklist.get(jti)
            if expiry is None:
                return False
            # 如果黑名单条目已过期, 移除它
            if time.time() > expiry:
                del self._blacklist[jti]
                return False
            return True

    # ────── JWT 签名工具 (从 auth.py 合并) ──────

    def _sign_jwt_token(self, payload: Dict[str, Any]) -> str:
        """签名 JWT 令牌 (HMAC-SHA256)

        令牌格式: base64(header).base64(payload).base64(signature)

        Args:
            payload: 令牌 payload 字典

        Returns:
            签名后的令牌字符串
        """
        header = {"alg": "HS256", "typ": "NEU-JWT"}

        header_b64 = self._base64url_encode(json.dumps(header).encode())
        payload_b64 = self._base64url_encode(json.dumps(payload).encode())

        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self.secret_key.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        signature_b64 = self._base64url_encode(signature)

        return f"{header_b64}.{payload_b64}.{signature_b64}"

    def _verify_jwt_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证 JWT 令牌签名并解码 payload

        Args:
            token: 令牌字符串

        Returns:
            payload 字典, 验证失败返回 None
        """
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts

        # 验证签名
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            self.secret_key.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        expected_sig_b64 = self._base64url_encode(expected_sig)

        if not hmac.compare_digest(signature_b64, expected_sig_b64):
            logger.warning("Token signature verification failed")
            return None

        # 解码 payload
        try:
            payload_bytes = self._base64url_decode(payload_b64)
            payload = json.loads(payload_bytes)
            return payload
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to decode token payload: %s", e)
            return None

    @staticmethod
    def _base64url_encode(data: bytes) -> str:
        """Base64url 编码"""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _base64url_decode(s: str) -> bytes:
        """Base64url 解码"""
        padding = 4 - len(s) % 4
        if padding != 4:
            s += "=" * padding
        return base64.urlsafe_b64decode(s)

    # ────── API Key 管理 (向后兼容) ──────

    def generate_api_key(self, user_id: str, name: str, scopes: Optional[List[str]] = None) -> str:
        """生成 API Key

        Args:
            user_id: 用户ID
            name: API Key 名称
            scopes: 权限范围

        Returns:
            生成的 API Key
        """
        api_key = f"neu_{secrets.token_hex(32)}"
        with self._lock:
            self._api_keys[api_key] = {
                "user_id": user_id,
                "name": name,
                "created_at": datetime.now().isoformat(),
                "scopes": scopes or [],
                "is_active": True,
                "last_used": None,
            }

        logger.info("Generated API key '%s' for user %s", name, user_id)
        return api_key

    def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """验证 API Key

        Args:
            api_key: 要验证的 API Key

        Returns:
            API Key 信息字典, 如果无效则返回 None
        """
        with self._lock:
            if api_key not in self._api_keys:
                return None

            key_data = self._api_keys[api_key]

            if not key_data["is_active"]:
                return None

            # 更新最后使用时间
            key_data["last_used"] = datetime.now().isoformat()

            return key_data

    def revoke_api_key(self, api_key: str) -> bool:
        """撤销 API Key

        Args:
            api_key: 要撤销的 API Key

        Returns:
            是否成功撤销
        """
        with self._lock:
            if api_key in self._api_keys:
                self._api_keys[api_key]["is_active"] = False
                logger.info("Revoked API key: %s...", api_key[:12])
                return True
            return False

    def list_api_keys(self, user_id: str) -> List[Dict[str, Any]]:
        """列出用户的 API Keys

        Args:
            user_id: 用户ID

        Returns:
            API Key 信息列表
        """
        with self._lock:
            return [
                {**key_data, "key": api_key[:12] + "..."}
                for api_key, key_data in self._api_keys.items()
                if key_data["user_id"] == user_id
            ]

    # ────── 清理 (合并两者) ──────

    def cleanup_expired_tokens(self) -> int:
        """清理过期的简单令牌

        Returns:
            清理的令牌数量
        """
        now = datetime.now()
        expired_tokens = []

        with self._lock:
            for token, data in self._tokens.items():
                expires_at = datetime.fromisoformat(data["expires_at"])
                if now > expires_at:
                    expired_tokens.append(token)

            for token in expired_tokens:
                del self._tokens[token]

        if expired_tokens:
            logger.info("Cleaned up %s expired tokens", len(expired_tokens))

        return len(expired_tokens)

    def cleanup_expired(self) -> int:
        """清理过期的黑名单条目和刷新令牌

        Returns:
            清理的条目总数
        """
        now = time.time()
        cleaned = 0

        with self._lock:
            # 清理过期的黑名单条目
            expired_bl = [jti for jti, exp in self._blacklist.items() if now > exp]
            for jti in expired_bl:
                del self._blacklist[jti]
                cleaned += 1

            # 清理过期的刷新令牌
            expired_rt = [
                jti
                for jti, data in self._refresh_tokens.items()
                if now > data.get("expires_at", 0)
            ]
            for jti in expired_rt:
                del self._refresh_tokens[jti]
                cleaned += 1

        if cleaned > 0:
            logger.info("Cleaned up %s expired token entries", cleaned)

        return cleaned


# 全局单例
_neu_token_manager: Optional[NEUTokenManager] = None


def get_neu_token_manager() -> NEUTokenManager:
    """获取全局 NEU Token Manager 单例"""
    global _neu_token_manager
    if _neu_token_manager is None:
        _neu_token_manager = NEUTokenManager()
    return _neu_token_manager


def reset_neu_token_manager() -> None:
    """重置全局 NEU Token Manager（用于测试）"""
    global _neu_token_manager
    _neu_token_manager = None
