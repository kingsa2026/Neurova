"""
Neurova 认证系统 - NEU Token

实现 NEU Token 的生成、验证和刷新
符合 FRONTEND_BACKEND_INTEGRATION.md 规范
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
import typing
import uuid
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class NEUTokenManager:
    """
    NEU Token 管理器

    管理访问令牌和刷新令牌的生成、验证、刷新和撤销。
    使用 HMAC-SHA256 签名令牌，支持令牌黑名单机制。
    """

    def __init__(
        self,
        secret_key: Optional[str] = None,
        access_token_ttl: int = 3600,
        refresh_token_ttl: int = 604800,
        issuer: str = "neurova",
    ):
        """
        初始化 NEU Token 管理器

        Args:
            secret_key: HMAC 签名密钥，为 None 时自动生成
            access_token_ttl: 访问令牌有效期（秒），默认 1 小时
            refresh_token_ttl: 刷新令牌有效期（秒），默认 7 天
            issuer: 令牌签发者标识
        """
        self._secret_key = secret_key or os.environ.get(
            "NEU_TOKEN_SECRET", self._generate_secret()
        )
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl
        self._issuer = issuer
        self._lock = threading.RLock()

        # 令牌黑名单: token_jti -> expiry_timestamp
        self._blacklist: Dict[str, float] = {}

        # 刷新令牌存储: refresh_jti -> {user_id, access_jti, created_at, expires_at}
        self._refresh_tokens: Dict[str, Dict[str, Any]] = {}

        self._initialized = False
        self._started = False

    def _generate_secret(self) -> str:
        """生成随机密钥"""
        return base64.urlsafe_b64encode(os.urandom(48)).decode("utf-8")

    def _on_init(self) -> None:
        """初始化回调"""
        self._initialized = True
        logger.info("NEUTokenManager initialized")

    def _on_start(self) -> None:
        """启动回调"""
        self._started = True
        self.cleanup_expired()
        logger.info("NEUTokenManager started")

    def _on_ready(self) -> None:
        """就绪回调"""
        logger.info("NEUTokenManager ready")

    def _on_stop(self) -> None:
        """停止回调"""
        self._started = False
        with self._lock:
            self._blacklist.clear()
            self._refresh_tokens.clear()
        logger.info("NEUTokenManager stopped")

    def _health_check(self) -> Dict[str, Any]:
        """
        健康检查

        Returns:
            健康状态字典
        """
        with self._lock:
            return {
                "initialized": self._initialized,
                "started": self._started,
                "blacklist_size": len(self._blacklist),
                "active_refresh_tokens": len(self._refresh_tokens),
            }

    def generate_tokens(
        self, user_id: str, extra_claims: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        生成访问令牌和刷新令牌

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

        access_token = self._sign_token(access_payload)
        refresh_token = self._sign_token(refresh_payload)

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

        logger.info(f"Generated tokens for user {user_id}")
        return access_token, refresh_token, token_info

    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        验证令牌有效性

        Args:
            token: 要验证的令牌字符串

        Returns:
            令牌 payload 字典，无效则返回 None
        """
        payload = self._verify_token(token)
        if payload is None:
            return None

        # 检查是否在黑名单中
        jti = payload.get("jti")
        if jti and self.is_token_blacklisted(jti):
            logger.debug(f"Token {jti} is blacklisted")
            return None

        # 检查过期时间
        exp = payload.get("exp", 0)
        if time.time() > exp:
            logger.debug(f"Token {jti} has expired")
            return None

        return payload

    def refresh_tokens(
        self, refresh_token: str
    ) -> Optional[Tuple[str, str, Dict[str, Any]]]:
        """
        使用刷新令牌获取新的令牌对

        Args:
            refresh_token: 刷新令牌字符串

        Returns:
            新的 (access_token, refresh_token, token_info) 元组，失败返回 None
        """
        payload = self._verify_token(refresh_token)
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
            logger.warning(f"Refresh token {refresh_jti} is blacklisted")
            return None

        # 查找并移除旧的刷新令牌
        with self._lock:
            refresh_data = self._refresh_tokens.pop(refresh_jti, None)

        if refresh_data is None:
            logger.warning(f"Refresh token {refresh_jti} not found in storage")
            return None

        user_id = refresh_data["user_id"]

        # 撤销旧的访问令牌
        old_access_jti = refresh_data.get("access_jti")
        if old_access_jti:
            self.revoke_token_by_jti(old_access_jti)

        # 生成新的令牌对
        logger.info(f"Refreshed tokens for user {user_id}")
        return self.generate_tokens(user_id)

    def revoke_token(self, token: str) -> bool:
        """
        撤销令牌（加入黑名单）

        Args:
            token: 要撤销的令牌字符串

        Returns:
            是否成功撤销
        """
        payload = self._verify_token(token)
        if payload is None:
            return False

        jti = payload.get("jti")
        if not jti:
            return False

        return self.revoke_token_by_jti(jti, payload.get("exp", 0))

    def revoke_token_by_jti(self, jti: str, expires_at: float = 0) -> bool:
        """
        通过 JTI 撤销令牌

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
            logger.info(f"Token {jti} revoked")
            return True

    def is_token_blacklisted(self, jti: str) -> bool:
        """
        检查令牌是否在黑名单中

        Args:
            jti: 令牌唯一标识

        Returns:
            是否在黑名单中
        """
        with self._lock:
            expiry = self._blacklist.get(jti)
            if expiry is None:
                return False
            # 如果黑名单条目已过期，移除它
            if time.time() > expiry:
                del self._blacklist[jti]
                return False
            return True

    def _sign_token(self, payload: Dict[str, Any]) -> str:
        """
        签名令牌（HMAC-SHA256）

        令牌格式: base64(header).base64(payload).base64(signature)

        Args:
            payload: 令牌 payload 字典

        Returns:
            签名后的令牌字符串
        """
        import hashlib
        import hmac

        header = {"alg": "HS256", "typ": "NEU-JWT"}

        header_b64 = self._base64url_encode(json.dumps(header).encode())
        payload_b64 = self._base64url_encode(json.dumps(payload).encode())

        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self._secret_key.encode(), signing_input.encode(), hashlib.sha256
        ).digest()
        signature_b64 = self._base64url_encode(signature)

        return f"{header_b64}.{payload_b64}.{signature_b64}"

    def _verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        验证令牌签名并解码 payload

        Args:
            token: 令牌字符串

        Returns:
            payload 字典，验证失败返回 None
        """
        import hashlib
        import hmac

        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts

        # 验证签名
        signing_input = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            self._secret_key.encode(), signing_input.encode(), hashlib.sha256
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
            logger.warning(f"Failed to decode token payload: {e}")
            return None

    def cleanup_expired(self) -> int:
        """
        清理过期的黑名单条目和刷新令牌

        Returns:
            清理的条目总数
        """
        now = time.time()
        cleaned = 0

        with self._lock:
            # 清理过期的黑名单条目
            expired_bl = [
                jti for jti, exp in self._blacklist.items() if now > exp
            ]
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
            logger.info(f"Cleaned up {cleaned} expired token entries")

        return cleaned

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


# ---------------------------------------------------------------------------
# 全局单例管理
# ---------------------------------------------------------------------------

_token_manager: Optional[NEUTokenManager] = None
_manager_lock = threading.Lock()


def _get_token_manager(
    secret_key: Optional[str] = None,
    access_token_ttl: int = 3600,
    refresh_token_ttl: int = 604800,
) -> NEUTokenManager:
    """
    获取或创建全局 Token 管理器实例

    Args:
        secret_key: 签名密钥（仅首次创建时生效）
        access_token_ttl: 访问令牌有效期
        refresh_token_ttl: 刷新令牌有效期

    Returns:
        全局 NEUTokenManager 实例
    """
    global _token_manager
    if _token_manager is None:
        with _manager_lock:
            if _token_manager is None:
                _token_manager = NEUTokenManager(
                    secret_key=secret_key,
                    access_token_ttl=access_token_ttl,
                    refresh_token_ttl=refresh_token_ttl,
                )
                _token_manager._on_init()
                _token_manager._on_start()
                _token_manager._on_ready()
    return _token_manager


def reset_token_manager() -> None:
    """重置全局 Token 管理器（用于测试）"""
    global _token_manager
    with _manager_lock:
        if _token_manager is not None:
            _token_manager._on_stop()
        _token_manager = None
