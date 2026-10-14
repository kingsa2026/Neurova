"""
Neurova 认证模块:

整合用户模型、密码加密、Token 管理
提供统一的认证接口
"""

from neurova.auth.enhanced_user_model import EnhancedUserModel

# FastAPI 为可选依赖
try:
    from fastapi import Path as _FastAPIPath
except ImportError:
    _FastAPIPath = None  # type: ignore[assignment]

from neurova.security.rbac import Permission

from neurova.admin.resource_quota_manager import ResourceQuotaManager

from neurova.auth.user_model import User

from neurova.auth.user_group_model import UserGroupManager

__all__ = [
    "EnhancedUserModel",
    "Permission",
    "ResourceQuotaManager",
    "User",
    "UserGroupManager",
]
