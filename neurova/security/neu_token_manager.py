"""
NEU Token Manager - 神经元令牌管理器

管理 Agent 的令牌认证和授权。
从 .pyc 恢复的骨架文件，需要实现具体功能。
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class NEUTokenManager:
    """
    神经元令牌管理器

    管理 Agent 的 JWT 令牌、API Key 和会话令牌。
    """

    def __init__(self, secret_key: Optional[str] = None, token_expiry_hours: int = 24):
        """
        初始化令牌管理器

        Args:
            secret_key: 令牌签名密钥
            token_expiry_hours: 令牌过期时间（小时）
        """
        self.secret_key = secret_key or secrets.token_hex(32)
        self.token_expiry_hours = token_expiry_hours
        self._tokens: Dict[str, Dict[str, Any]] = {}
        self._api_keys: Dict[str, Dict[str, Any]] = {}

        logger.info("NEUTokenManager initialized")

    def generate_token(self, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        生成访问令牌

        Args:
            user_id: 用户ID
            metadata: 令牌元数据

        Returns:
            生成的令牌字符串
        """
        # TODO: 实现 JWT 令牌生成
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(hours=self.token_expiry_hours)

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
        """
        验证令牌有效性

        Args:
            token: 要验证的令牌

        Returns:
            令牌信息字典，如果无效则返回 None
        """
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
        """
        撤销令牌

        Args:
            token: 要撤销的令牌

        Returns:
            是否成功撤销
        """
        if token in self._tokens:
            self._tokens[token]["is_active"] = False
            logger.info("Revoked token: %s...", token[:8])
            return True
        return False

    def generate_api_key(self, user_id: str, name: str, scopes: Optional[List[str]] = None) -> str:
        """
        生成 API Key

        Args:
            user_id: 用户ID
            name: API Key 名称
            scopes: 权限范围

        Returns:
            生成的 API Key
        """
        api_key = f"neu_{secrets.token_hex(32)}"
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
        """
        验证 API Key

        Args:
            api_key: 要验证的 API Key

        Returns:
            API Key 信息字典，如果无效则返回 None
        """
        if api_key not in self._api_keys:
            return None

        key_data = self._api_keys[api_key]

        if not key_data["is_active"]:
            return None

        # 更新最后使用时间
        key_data["last_used"] = datetime.now().isoformat()

        return key_data

    def revoke_api_key(self, api_key: str) -> bool:
        """
        撤销 API Key

        Args:
            api_key: 要撤销的 API Key

        Returns:
            是否成功撤销
        """
        if api_key in self._api_keys:
            self._api_keys[api_key]["is_active"] = False
            logger.info("Revoked API key: %s...", api_key[:12])
            return True
        return False

    def list_api_keys(self, user_id: str) -> List[Dict[str, Any]]:
        """
        列出用户的 API Keys

        Args:
            user_id: 用户ID

        Returns:
            API Key 信息列表
        """
        return [
            {**key_data, "key": api_key[:12] + "..."}
            for api_key, key_data in self._api_keys.items()
            if key_data["user_id"] == user_id
        ]

    def cleanup_expired_tokens(self) -> int:
        """
        清理过期令牌

        Returns:
            清理的令牌数量
        """
        now = datetime.now()
        expired_tokens = []

        for token, data in self._tokens.items():
            expires_at = datetime.fromisoformat(data["expires_at"])
            if now > expires_at:
                expired_tokens.append(token)

        for token in expired_tokens:
            del self._tokens[token]

        if expired_tokens:
            logger.info("Cleaned up %s expired tokens", len(expired_tokens))

        return len(expired_tokens)


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
