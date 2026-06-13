"""
Auth Protocol - 认证协议抽象

定义认证系统的接口协议。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class AuthProtocol(ABC):
    """认证协议抽象基类"""

    @abstractmethod
    async def authenticate(self, credentials: Dict[str, Any]) -> Optional[str]:
        """认证用户，返回 token"""
        ...

    @abstractmethod
    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证 token"""
        ...

    @abstractmethod
    async def revoke_token(self, token: str) -> bool:
        """撤销 token"""
        ...
